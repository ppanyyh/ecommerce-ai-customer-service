"""V3.0 四种检索模式对比评测（validation_set_v1；不调用 DeepSeek，不接入 /api/chat）。

模式：
1. keyword_only        — keyword_retriever_v3.keyword_search（v1 口径，未改）
2. vector_only         — vector_retriever.vector_search（未改）
3. hybrid_rrf_v1       — hybrid_retriever.hybrid_search（原 v1，保留未改）
4. hybrid_business_v2  — hybrid_retriever_v2.hybrid_search_v2（本轮新增）

测试集：backend/data/hybrid_holdout_eval_cases.json（已标记 validation_set_v1，v1.1）。
v1.1 变更：H-009 相关性人工复核扩展（+PRODUCT-P004，见 meta.annotation_revision）。
v1 结果（retrieval_mode_comparison.json）保留不动；本脚本在修订后标注上重算全部四模式。

指标（24条可回答）：Answer Hit@1 / Recall@3 / MRR / Rule Recall@3 / 分类指标。
不可回答（6条）：Top-1、分数、门控情况；沿用 v1 启发式标记（keyword>=6.0 或 vector>=0.55）。
延迟：各模式预热后 30 次检索 P50/P95。

成功条件（validation_set_v1 上）：
1. v2 Hit@1 >= vector_only；2. Recall@3 = 100%；3. Rule Recall@3 = 100%；
4. 多意图 Hit@1 = 100%；5. H-025 类不再误命中（门控拦截）；
6. 相比 v1 无回归（逐条 hit1/recall3 不变差）；7. 风险意图 H-016/017/018 被 analyzer 正确识别；
8. 预热 P95 <= 500ms。

防过拟合自检：检索/分析源码中不得出现任何 validation 完整 query 或按 case_id 的条件分支。

输出：backend/data/hybrid_v2_validation_results.json

运行（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\evaluate_hybrid_v2.py
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
CASES_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_holdout_eval_cases.json")
FREEZE_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_code_freeze_manifest.json")
V1_COMPARISON_PATH = os.path.join(BACKEND_DIR, "data", "retrieval_mode_comparison.json")
OUT_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_v2_validation_results.json")

sys.path.insert(0, BACKEND_DIR)
from keyword_retriever_v3 import keyword_search  # noqa: E402
from vector_retriever import vector_search  # noqa: E402
from hybrid_retriever import hybrid_search  # noqa: E402
from hybrid_retriever_v2 import hybrid_search_v2  # noqa: E402
from query_analyzer import analyze  # noqa: E402

TOP_K = 5
VECTOR_ERROR_SIM = 0.55
KEYWORD_ERROR_SCORE = 6.0
WARM_P95_BUDGET_MS = 500.0
VALIDATION_OLD_SHA256 = "26ee720d21c486a5d9829a3fd390db9b173360f251a41a6f1523c74759616948"
KEY_CASES = ["H-004", "H-007", "H-009", "H-016", "H-017", "H-018", "H-021", "H-022", "H-025"]
RISK_LEAK_CASES = ["H-016", "H-017", "H-018"]


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def mode_search(mode, query):
    """统一检索入口。返回 (results, score_key, gated)。"""
    if mode == "keyword_only":
        return keyword_search(query, top_k=TOP_K), "keyword_score", False
    if mode == "vector_only":
        return vector_search(query, top_k=TOP_K), "similarity", False
    if mode == "hybrid_rrf_v1":
        return hybrid_search(query, top_k=TOP_K), "rrf_score", False
    out = hybrid_search_v2(query, top_k=TOP_K)
    return out["results"], "rrf_score", (not out["supported"])


def top3_records(results, score_key):
    return [
        {"rank": r.get("final_rank", r.get("rank")), "chunk_id": r["chunk_id"],
         "doc_type": r["doc_type"], "score": r[score_key], "source": r["source"]}
        for r in results[:3]
    ]


def evaluate_mode(mode, cases):
    per_case, failures = [], []
    hit1_cnt = recall3_cnt = 0
    rr_sum = 0.0
    rule_total = rule_ok_cnt = 0
    by_cat = {}
    irr_records = []

    for case in cases:
        results, score_key, gated = mode_search(mode, case["query"])
        top_ids = [r["chunk_id"] for r in results]
        entry = {
            "case_id": case["case_id"], "category": case["category"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "required_rule_ids": case["required_rule_ids"],
            "gated": gated,
            "top3": top3_records(results, score_key),
        }
        if case["is_answerable"]:
            relevant = set(case["relevant_chunk_ids"])
            required = case["required_rule_ids"]
            top3 = top_ids[:3]
            hit1 = bool(top3) and top3[0] in relevant
            recall3 = any(cid in relevant for cid in top3)
            first_rank = next((i + 1 for i, cid in enumerate(top_ids) if cid in relevant), None)
            rule_ok = all(rid in top3 for rid in required) if required else None
            hit1_cnt += hit1
            recall3_cnt += recall3
            rr_sum += (1.0 / first_rank) if first_rank else 0.0
            if required:
                rule_total += 1
                rule_ok_cnt += int(bool(rule_ok))
            st = by_cat.setdefault(case["category"], {"n": 0, "hit1": 0, "recall3": 0})
            st["n"] += 1
            st["hit1"] += int(hit1)
            st["recall3"] += int(recall3)
            entry.update({"hit1": hit1, "recall3": recall3,
                          "first_relevant_rank": first_rank, "rule_recall3": rule_ok})
            if not (hit1 and recall3) or (required and not rule_ok):
                failures.append({
                    "case_id": case["case_id"], "category": case["category"],
                    "problem": ("hit1_miss" if not hit1 else "") +
                               (" recall3_miss" if not recall3 else "") +
                               (" rule_miss" if required and not rule_ok else "").strip(),
                    "top3": top3,
                })
        else:
            top1 = results[0] if results else None
            if gated or top1 is None:
                error_hit = False
            else:
                kw_s = top1.get("keyword_score")
                vec_s = top1.get("similarity") or top1.get("vector_similarity")
                error_hit = ((kw_s is not None and kw_s >= KEYWORD_ERROR_SCORE) or
                             (vec_s is not None and vec_s >= VECTOR_ERROR_SIM))
            entry.update({
                "top1_chunk_id": top1["chunk_id"] if top1 else None,
                "top1_score": top1[score_key] if top1 else None,
                "error_hit_flag": error_hit,
            })
            irr_records.append(entry)
        per_case.append(entry)

    n = sum(1 for c in cases if c["is_answerable"])
    metrics = {
        "answer_hit_at_1": round(hit1_cnt / n, 4) if n else 0.0,
        "answer_recall_at_3": round(recall3_cnt / n, 4) if n else 0.0,
        "mrr": round(rr_sum / n, 4) if n else 0.0,
        "rule_recall_at_3": round(rule_ok_cnt / rule_total, 4) if rule_total else None,
        "hit1_correct": hit1_cnt, "recall3_correct": recall3_cnt,
        "rule_cases": rule_total, "rule_ok": rule_ok_cnt,
    }
    category_metrics = {
        cat: {"n": st["n"], "hit_at_1": round(st["hit1"] / st["n"], 4),
              "recall_at_3": round(st["recall3"] / st["n"], 4)}
        for cat, st in sorted(by_cat.items())
    }
    return {"metrics": metrics, "category_metrics": category_metrics,
            "failures": failures, "irrelevant_records": irr_records, "per_case": per_case}


def measure_latency(mode, queries, warm_query):
    mode_search(mode, warm_query)  # 预热
    samples = []
    for q in queries:
        t0 = time.perf_counter()
        mode_search(mode, q)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()

    def pct(p):
        k = max(0, min(len(samples) - 1, int(round(p / 100.0 * len(samples) + 0.5)) - 1))
        return round(samples[k], 2)

    return {"warm_p50_ms": pct(50), "warm_p95_ms": pct(95), "n_samples": len(samples)}


def anti_overfit_check():
    """源码中不得出现 validation 完整 query 或按 case_id 的条件分支。"""
    src_files = ["query_analyzer.py", "hybrid_retriever_v2.py"]
    src = "\n".join(open(os.path.join(BACKEND_DIR, f), encoding="utf-8").read()
                    for f in src_files)
    cases = json.load(open(CASES_PATH, encoding="utf-8"))["cases"]
    leaked_queries = [c["case_id"] for c in cases if c["query"].strip() and c["query"] in src]
    case_id_branches = [c["case_id"] for c in cases
                        if re.search(r"[\"']" + re.escape(c["case_id"]) + r"[\"']", src)]
    return {"full_query_in_code": leaked_queries, "case_id_branch_in_code": case_id_branches,
            "passed": not leaked_queries and not case_id_branches}


def main():
    global CASES_PATH, OUT_PATH
    # V3.1 Phase 2：validation 双口径评测（--cases 选择用例文件，--out 指定输出）
    import argparse
    ap = argparse.ArgumentParser(description="validation_set_v1 四模式评测（双口径）")
    ap.add_argument("--cases", default="hybrid_holdout_eval_cases_v1_2_reviewed.json",
                    help="validation 用例文件名（data/ 目录下）：v1_1_frozen 或 v1_2_reviewed")
    ap.add_argument("--out", default=None, help="结果输出文件名（data/ 目录下），默认 hybrid_v2_validation_results.json")
    args = ap.parse_args()
    CASES_PATH = os.path.join(BACKEND_DIR, "data", args.cases)
    if args.out:
        OUT_PATH = os.path.join(BACKEND_DIR, "data", args.out)
    data = json.load(open(CASES_PATH, encoding="utf-8"))
    cases = data["cases"]
    validation_sha = sha256(CASES_PATH)
    print(f"validation_set_v1: {len(cases)} 条 "
          f"(answerable={sum(c['is_answerable'] for c in cases)}) v{data['meta'].get('version')}")
    print(f"validation SHA-256: {validation_sha}")

    modes = ["keyword_only", "vector_only", "hybrid_rrf_v1", "hybrid_business_v2"]
    results = {}
    for mode in modes:
        print(f"\n===== {mode} =====")
        results[mode] = evaluate_mode(mode, cases)
        m = results[mode]["metrics"]
        print(f"Hit@1={m['hit1_correct']}/24 Recall@3={m['recall3_correct']}/24 "
              f"MRR={m['mrr']} Rule@3={m['rule_ok']}/{m['rule_cases']}")
        for cat, st in results[mode]["category_metrics"].items():
            print(f"  {cat}: n={st['n']} Hit@1={st['hit_at_1']:.0%} Recall@3={st['recall_at_3']:.0%}")
        for f in results[mode]["failures"]:
            print(f"  FAIL {f['case_id']}[{f['problem']}] top3={f['top3']}")
        err = sum(1 for r in results[mode]["irrelevant_records"] if r["error_hit_flag"])
        gated = sum(1 for r in results[mode]["irrelevant_records"] if r.get("gated"))
        print(f"  不可回答: 错误命中标记={err}/6 门控={gated}")

    # 延迟（全部预热后测量）
    warm_q = "退款什么时候到账"
    latency = {}
    print("\n===== 延迟（预热后） =====")
    for mode in modes:
        latency[mode] = measure_latency(mode, [c["query"] for c in cases], warm_q)
        print(f"{mode}: P50={latency[mode]['warm_p50_ms']}ms P95={latency[mode]['warm_p95_ms']}ms")

    # 重点案例排名变化（v1 -> v2）
    key_case_changes = {}
    for cid in KEY_CASES:
        row = {"case_id": cid}
        for mode in modes:
            pc = next(c for c in results[mode]["per_case"] if c["case_id"] == cid)
            row[mode] = {
                "top3": [t["chunk_id"] for t in pc["top3"]],
                "hit1": pc.get("hit1"), "recall3": pc.get("recall3"),
                "rule_recall3": pc.get("rule_recall3"),
                "gated": pc.get("gated", False),
            }
        key_case_changes[cid] = row

    # 风险意图识别（H-016/017/018 + 附加漏检案例复验）
    risk_intent_check = {}
    for case in cases:
        if case["case_id"] in RISK_LEAK_CASES or case["case_id"] in ("H-014", "H-015", "H-019", "H-021", "H-022"):
            a = analyze(case["query"])
            risk_intent_check[case["case_id"]] = {
                "intents": a["intents"],
                "required_rule_ids_analyzer": a["required_rule_ids"],
                "required_rule_ids_expected": case["required_rule_ids"],
                "identified": all(r in a["required_rule_ids"] for r in case["required_rule_ids"]),
            }

    # 回归检查：v2 vs v1 逐条（可回答用例指标不变差；不可回答用例无新增错误命中）
    regressions = []
    for pc1 in results["hybrid_rrf_v1"]["per_case"]:
        pc2 = next(c for c in results["hybrid_business_v2"]["per_case"] if c["case_id"] == pc1["case_id"])
        case = next(c for c in cases if c["case_id"] == pc1["case_id"])
        if case["is_answerable"]:
            worse = []
            if pc1["hit1"] and not pc2["hit1"]:
                worse.append("hit1")
            if pc1["recall3"] and not pc2["recall3"]:
                worse.append("recall3")
            if pc1.get("rule_recall3") and not pc2.get("rule_recall3"):
                worse.append("rule_recall3")
            if worse:
                regressions.append({"case_id": pc1["case_id"], "worse_in": worse,
                                    "v1_top3": [t["chunk_id"] for t in pc1["top3"]],
                                    "v2_top3": [t["chunk_id"] for t in pc2["top3"]]})
    # 不可回答用例：v2 新增错误命中
    for r1, r2 in zip(results["hybrid_rrf_v1"]["irrelevant_records"],
                      results["hybrid_business_v2"]["irrelevant_records"]):
        if not r1["error_hit_flag"] and r2["error_hit_flag"]:
            regressions.append({"case_id": r1["case_id"], "worse_in": ["new_error_hit"],
                                "v2_top1": r2["top1_chunk_id"]})

    # 成功条件
    mv = results["vector_only"]["metrics"]
    m1 = results["hybrid_rrf_v1"]["metrics"]
    m2 = results["hybrid_business_v2"]["metrics"]
    irr2 = results["hybrid_business_v2"]["irrelevant_records"]
    h025 = next(r for r in irr2 if r["case_id"] == "H-025")
    multi_v1 = results["hybrid_rrf_v1"]["category_metrics"].get("multi", {}).get("hit_at_1", 0)
    multi_v2 = results["hybrid_business_v2"]["category_metrics"].get("multi", {}).get("hit_at_1", 0)
    criteria = {
        "1_v2_hit1_ge_vector": m2["answer_hit_at_1"] >= mv["answer_hit_at_1"],
        "2_v2_recall3_100pct": m2["answer_recall_at_3"] == 1.0,
        "3_v2_rule_recall3_100pct": m2["rule_recall_at_3"] == 1.0,
        "4_v2_multi_hit1_100pct": multi_v2 == 1.0,
        "5_H025_no_mis_hit": (h025["gated"] or not h025["error_hit_flag"]),
        "6_no_regression_vs_v1": not regressions,
        "7_risk_intents_identified": all(v["identified"] for k, v in risk_intent_check.items()
                                         if k in RISK_LEAK_CASES),
        "8_latency_p95_ok": latency["hybrid_business_v2"]["warm_p95_ms"] <= WARM_P95_BUDGET_MS,
    }

    # 冻结哈希核验
    freeze = json.load(open(FREEZE_PATH, encoding="utf-8"))
    freeze_now = {f: sha256(os.path.join(BACKEND_DIR, f)) for f in freeze["files_sha256"]}
    freeze_ok = freeze_now == freeze["files_sha256"]

    # 防过拟合自检
    overfit = anti_overfit_check()

    # final blind set 条件
    all_pass = all(criteria.values())
    blind_set_ready = all_pass and freeze_ok and overfit["passed"]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "validation_set": {
            "file": os.path.basename(CASES_PATH),
            "label": data["meta"].get("validation_set_label"),
            "version": data["meta"].get("version"),
            "sha256_old": VALIDATION_OLD_SHA256,
            "sha256_now": validation_sha,
            "v1_1_change": "H-009 relevant_chunk_ids 人工复核扩展（+PRODUCT-P004），见 meta.annotation_revision",
        },
        "modes": {
            mode: {
                "metrics": results[mode]["metrics"],
                "category_metrics": results[mode]["category_metrics"],
                "failures": results[mode]["failures"],
                "irrelevant_records": results[mode]["irrelevant_records"],
                "latency": latency[mode],
                "per_case_top3": results[mode]["per_case"],
            } for mode in modes
        },
        "key_case_changes_v1_to_v2": key_case_changes,
        "risk_intent_check": risk_intent_check,
        "regressions_vs_v1": regressions,
        "success_criteria": criteria,
        "final_blind_set_ready": blind_set_ready,
        "anti_overfit_check": overfit,
        "freeze_hashes_verified": freeze_ok,
        "freeze_hashes_now": freeze_now,
        "config": {
            "EPSILON": 0.0003, "ALIAS_BOOST": 0.0002,
            "GENERIC_WEAK_WORDS": sorted(["商品", "购物", "问题", "怎么样", "质量", "订单", "处理"]),
            "WEAK_WORD_CAP": 0.5, "HAN_CHAR_SCORE": 0.15, "HAN_OVERLAP_CAP": 0.8,
            "RRF_K": 60, "KEYWORD_WEIGHT": 1.0, "VECTOR_WEIGHT": 1.0,
            "extended_synonyms": {"书包": "P004"},
        },
        "notes": ("四种模式均在 validation_set_v1（v1.1 标注）上单次运行；"
                  "keyword_only/vector_only/hybrid_rrf_v1 代码未改，其指标变化仅来自 H-009 标注修订；"
                  "未设置向量拒答阈值；未调用 DeepSeek；未接入 /api/chat。"),
    }
    json.dump(report, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n结果已写入: {OUT_PATH}")
    print("===== 成功条件 =====")
    for k, v in criteria.items():
        print(f"[{'PASS' if v else 'FAIL'}] {k}")
    print("final blind set 就绪:", blind_set_ready)


if __name__ == "__main__":
    main()
