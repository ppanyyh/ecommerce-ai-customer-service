"""V3.0 三种检索方式对比评测（留出测试集；不调用 DeepSeek，不接入 /api/chat）。

在同一份留出集（hybrid_holdout_eval_cases.json，30条=24可回答+6不可回答）上分别运行：
1. keyword_only  — keyword_retriever_v3.keyword_search(top_k=5)
2. vector_only   — vector_retriever.vector_search(top_k=5)
3. hybrid_rrf    — hybrid_retriever.hybrid_search(top_k=5)

指标（24条可回答）：Answer Hit@1 / Answer Recall@3 / MRR / Rule Recall@3
                    + 分类指标（product / faq / rule / multi）。
不可回答（6条）：记录各模式 Top-1 结果与分数，并按启发式标记"明显错误命中"
                 （keyword: 完整短语关键词命中；vector: similarity>=0.55；
                  hybrid: 二者其一）。不设置自动拒答阈值。
延迟：各模式首次冷启动时间 + 预热后30次单query检索的 P50 / P95。

成功判断（不以100%为强制目标）：
1. hybrid Hit@1 >= vector；2. hybrid Recall@3 >= vector；3. Rule Recall@3 >= vector；
4. 编号查询（H-024）不低于 keyword；5. 无新增严重错误匹配（hybrid错误命中数<=vector）；
6. 预热后 P95 <= 500ms（本地演示可接受）。

输出：backend/data/retrieval_mode_comparison.json（逐条Top-3、汇总、分类、失败案例、
不可回答案例、延迟、全部哈希、是否建议接入 /api/chat）。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\evaluate_retrieval_modes.py
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
HOLDOUT_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_holdout_eval_cases.json")
FREEZE_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_code_freeze_manifest.json")
OUT_PATH = os.path.join(BACKEND_DIR, "data", "retrieval_mode_comparison.json")

sys.path.insert(0, BACKEND_DIR)
from keyword_retriever_v3 import keyword_search  # noqa: E402
from vector_retriever import vector_search  # noqa: E402
from hybrid_retriever import hybrid_search  # noqa: E402

TOP_K = 5
VECTOR_ERROR_SIM = 0.55
WARM_P95_BUDGET_MS = 500.0
HOLDOUT_SHA256_EXPECTED = "26ee720d21c486a5d9829a3fd390db9b173360f251a41a6f1523c74759616948"


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def top3_records(results, score_key):
    return [
        {"rank": r["final_rank"] if "final_rank" in r else r["rank"],
         "chunk_id": r["chunk_id"], "doc_type": r["doc_type"],
         "score": r[score_key], "source": r["source"]}
        for r in results[:3]
    ]


def mode_search(mode, query):
    if mode == "keyword_only":
        return keyword_search(query, top_k=TOP_K), "keyword_score"
    if mode == "vector_only":
        return vector_search(query, top_k=TOP_K), "similarity"
    return hybrid_search(query, top_k=TOP_K), "rrf_score"


def evaluate_mode(mode, cases):
    answerable = [c for c in cases if c["is_answerable"]]
    irrelevant = [c for c in cases if not c["is_answerable"]]

    per_case = []
    hit1_cnt = recall3_cnt = 0
    rr_sum = 0.0
    rule_total = rule_ok_cnt = 0
    by_cat = {}
    failures = []
    irr_records = []

    for case in cases:
        results, score_key = mode_search(mode, case["query"])
        top_ids = [r["chunk_id"] for r in results]
        entry = {
            "case_id": case["case_id"], "category": case["category"],
            "query": case["query"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "required_rule_ids": case["required_rule_ids"],
            "is_answerable": case["is_answerable"],
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
                    "query": case["query"],
                    "problem": ("hit1_miss" if not hit1 else "") +
                               (" recall3_miss" if not recall3 else "") +
                               (" rule_miss" if required and not rule_ok else ""),
                    "top3": [t["chunk_id"] for t in entry["top3"]],
                    "relevant": case["relevant_chunk_ids"],
                    "required_rule_ids": required,
                })
        else:
            top1 = results[0] if results else None
            score = top1[score_key] if top1 else None
            kw_top1_score = top1.get("keyword_score") if top1 and "keyword_score" in top1 else None
            vec_top1_sim = top1.get("similarity") if top1 and "similarity" in top1 else None
            error_hit = (
                (kw_top1_score is not None and kw_top1_score >= 6.0)
                or (vec_top1_sim is not None and vec_top1_sim >= VECTOR_ERROR_SIM)
            ) if top1 else False
            entry.update({
                "top1_chunk_id": top1["chunk_id"] if top1 else None,
                "top1_score": score, "error_hit_flag": error_hit,
            })
            irr_records.append(entry)
        per_case.append(entry)

    n = len(answerable)
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
    return {
        "metrics": metrics, "category_metrics": category_metrics,
        "failures": failures, "irrelevant_records": irr_records,
        "per_case": per_case,
    }


def measure_latency(mode, queries):
    # 冷启动：该模式首次调用（keyword为首次构建索引；vector为首次加载模型；hybrid复用已预热组件）
    t0 = time.perf_counter()
    mode_search(mode, queries[0])
    cold_ms = (time.perf_counter() - t0) * 1000.0
    samples = []
    for q in queries:
        t0 = time.perf_counter()
        mode_search(mode, q)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()

    def pct(p):
        k = max(0, min(len(samples) - 1, int(round(p / 100.0 * len(samples) + 0.5)) - 1))
        return round(samples[k], 2)

    return {"cold_start_ms": round(cold_ms, 2),
            "warm_p50_ms": pct(50), "warm_p95_ms": pct(95),
            "n_samples": len(samples)}


def main():
    cases = json.load(open(HOLDOUT_PATH, encoding="utf-8"))["cases"]
    queries = [c["query"] for c in cases]
    print(f"留出集: {len(cases)} 条（answerable={sum(c['is_answerable'] for c in cases)}）")

    modes = ["keyword_only", "vector_only", "hybrid_rrf"]
    results = {}
    for mode in modes:
        print(f"\n===== {mode} =====")
        results[mode] = evaluate_mode(mode, cases)
        m = results[mode]["metrics"]
        print(f"Hit@1={m['hit1_correct']} Recall@3={m['recall3_correct']} "
              f"MRR={m['mrr']} Rule@3={m['rule_ok']}/{m['rule_cases']}")
        for cat, st in results[mode]["category_metrics"].items():
            print(f"  {cat}: n={st['n']} Hit@1={st['hit_at_1']:.0%} Recall@3={st['recall_at_3']:.0%}")
        for f in results[mode]["failures"]:
            print(f"  FAIL {f['case_id']}[{f['problem'].strip()}] top3={f['top3']}")
        err = sum(1 for r in results[mode]["irrelevant_records"] if r["error_hit_flag"])
        print(f"  不可回答错误命中标记: {err}/6")

    print("\n===== 延迟 =====")
    latency = {}
    for mode in modes:
        latency[mode] = measure_latency(mode, queries)
        print(f"{mode}: cold={latency[mode]['cold_start_ms']}ms "
              f"P50={latency[mode]['warm_p50_ms']}ms P95={latency[mode]['warm_p95_ms']}ms")

    # ---------- 成功判断 ----------
    mv, mh = results["vector_only"]["metrics"], results["hybrid_rrf"]["metrics"]
    mk = results["keyword_only"]["metrics"]
    id_case = next(c for c in results["hybrid_rrf"]["per_case"] if c["case_id"] == "H-024")
    id_case_kw = next(c for c in results["keyword_only"]["per_case"] if c["case_id"] == "H-024")
    err_v = sum(1 for r in results["vector_only"]["irrelevant_records"] if r["error_hit_flag"])
    err_h = sum(1 for r in results["hybrid_rrf"]["irrelevant_records"] if r["error_hit_flag"])
    criteria = {
        "1_hybrid_hit1_ge_vector": mh["answer_hit_at_1"] >= mv["answer_hit_at_1"],
        "2_hybrid_recall3_ge_vector": mh["answer_recall_at_3"] >= mv["answer_recall_at_3"],
        "3_hybrid_rule_recall3_ge_vector": (mh["rule_recall_at_3"] or 0) >= (mv["rule_recall_at_3"] or 0),
        "4_id_query_not_worse_than_keyword":
            (id_case["hit1"], id_case["recall3"]) >= (id_case_kw["hit1"], id_case_kw["recall3"]),
        "5_no_new_severe_mismatch": err_h <= err_v,
        "6_latency_p95_acceptable": latency["hybrid_rrf"]["warm_p95_ms"] <= WARM_P95_BUDGET_MS,
    }
    recommend = all(criteria.values())
    print("\n===== 成功判断 =====")
    for k, v in criteria.items():
        print(f"[{'PASS' if v else 'FAIL'}] {k}")

    # ---------- 哈希核验（防泄漏 3/4） ----------
    freeze = json.load(open(FREEZE_PATH, encoding="utf-8"))
    freeze_now = {f: sha256(os.path.join(BACKEND_DIR, f)) for f in freeze["files_sha256"]}
    freeze_ok = freeze_now == freeze["files_sha256"]
    holdout_now = sha256(HOLDOUT_PATH)
    holdout_ok = holdout_now == HOLDOUT_SHA256_EXPECTED
    print(f"\n冻结哈希保持: {freeze_ok} | 留出集哈希保持: {holdout_ok}")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "holdout_file": "hybrid_holdout_eval_cases.json",
        "holdout_sha256": holdout_now,
        "holdout_sha256_expected": HOLDOUT_SHA256_EXPECTED,
        "holdout_unchanged": holdout_ok,
        "freeze_manifest": freeze,
        "freeze_hashes_verified_after_eval": freeze_ok,
        "freeze_hashes_now": freeze_now,
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
        "success_criteria": criteria,
        "recommendation": {
            "integrate_into_api_chat": recommend,
            "statement": ("hybrid 在 Hit@1 / Recall@3 / Rule Recall@3 上不低于 vector_only，"
                          "编号查询不低于 keyword_only，无新增严重错误匹配，延迟可接受——"
                          "满足进入下一阶段条件" if recommend else
                          "hybrid 未全面优于/持平 vector_only——如实报告，不建议本阶段接入 /api/chat"),
        },
        "notes": "本评测为留出集单次运行；开发集100%结果不作为泛化结论；未设置自动拒答阈值；未调用DeepSeek。",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入: {OUT_PATH}")
    print("建议接入 /api/chat:", "是" if recommend else "否")


if __name__ == "__main__":
    main()
