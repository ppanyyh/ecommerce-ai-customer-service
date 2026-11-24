# -*- coding: utf-8 -*-
"""最终盲测一次性评测脚本（hybrid_business_v2）。

约束：
- 每条用例只调用冻结检索器 hybrid_search_v2 一次；
- 异常只记录，不换参数重试；
- 不修改任何检索代码 / 参数 / 知识库 / 盲测集；
- 不调用 DeepSeek，不访问 /api/chat。
"""
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

BLIND_SET = os.path.join(BACKEND, "data", "final_blind_set_v1.json")
FREEZE_MANIFEST = os.path.join(BACKEND, "data", "final_candidate_freeze_manifest.json")
RESULTS_OUT = os.path.join(BACKEND, "data", "final_blind_eval_results.json")
REPORT_OUT = os.path.join(BACKEND, "data", "final_blind_eval_report.md")
EXEC_MANIFEST_OUT = os.path.join(BACKEND, "data", "final_blind_execution_manifest.json")

BLIND_SET_EXPECTED_SHA = "27ff8622aa3387b0e46f504b4c489bfd2755d63f2c7edd233e8f40479ea030c1"
TOP_K = 5          # 冻结候选 hybrid_search_v2 正式默认配置
TOP3 = 3           # 指标按 Top-3 计算
EVALUATED_MODE = "hybrid_business_v2"


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def candidate_hashes():
    m = json.load(open(FREEZE_MANIFEST, encoding="utf-8"))
    cur, match = {}, {}
    for rel, expect in m["files_sha256"].items():
        c = sha256(os.path.join(BACKEND, rel))
        cur[rel] = c
        match[rel] = (c == expect)
    return cur, match


def rrf_rank(recs, relevant_ids):
    """第一个 relevant 片段排名（1-based），不在列表返回 None。"""
    for r in recs:
        if r["chunk_id"] in relevant_ids:
            return r["final_rank"]
    return None


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _latency_summary(raw_ms):
    """延迟统计（V3.1 修复版）。

    - 首次调用取原始执行顺序的第一条（含 Embedding 模型加载的冷启动）；
    - P50/P95 使用排序后的副本计算；
    - excluding_first 先按原始顺序移除真实第一条，再排序计算。
    旧版缺陷：先排序再取 lat[0]，把最小值误当成首次调用。
    """
    if not raw_ms:
        return {"n": 0, "first_call": None, "p50": None, "p95": None,
                "p50_excluding_first": None, "p95_excluding_first": None,
                "min": None, "max": None}

    def p(sorted_vals, q):
        k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) + 1)) - 1)))
        return sorted_vals[k]

    ordered = list(raw_ms)                      # 原始执行顺序，不排序
    first_call = ordered[0]                     # 真实首次调用
    sorted_all = sorted(ordered)                # 排序副本
    sorted_warm = sorted(ordered[1:])           # 先移除真实首条，再排序
    return {
        "n": len(ordered),
        "first_call": first_call,
        "p50": p(sorted_all, 0.50),
        "p95": p(sorted_all, 0.95),
        "p50_excluding_first": p(sorted_warm, 0.50) if sorted_warm else None,
        "p95_excluding_first": p(sorted_warm, 0.95) if sorted_warm else None,
        "min": sorted_all[0],
        "max": sorted_all[-1],
    }


def main():
    exceptions = []

    # ---- 0. 运行前哈希与盲测集核验 ----
    blind_sha = sha256(BLIND_SET)
    assert blind_sha == BLIND_SET_EXPECTED_SHA, (
        "盲测集 SHA-256 与预期不符，停止评测: " + blind_sha)
    hashes_before, match_before = candidate_hashes()
    assert all(match_before.values()), "候选文件哈希与冻结清单不一致，停止评测"

    blind = json.load(open(BLIND_SET, encoding="utf-8"))
    cases = blind["cases"]
    assert len(cases) == 40

    # ---- 1. 冻结检索器（仅导入，不修改） ----
    from hybrid_retriever_v2 import hybrid_search_v2

    per_case = []
    for c in cases:
        q = c["query"]
        rec = {
            "case_id": c["case_id"],
            "category": c.get("category") or c.get("case_category", ""),
            "difficulty": c.get("difficulty", ""),
            "query": q,
            "is_answerable": c["is_answerable"],
            "relevant_chunk_ids": c.get("relevant_chunk_ids", []),
            "required_rule_ids": c.get("required_rule_ids", []),
            "expected_supported": c.get("expected_supported", c["is_answerable"]),
        }
        t0 = time.perf_counter()
        try:
            out = hybrid_search_v2(q, top_k=TOP_K)  # 唯一一次调用
            rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            rec["supported"] = out["supported"]
            rec["gate_reason"] = out.get("reason")
            rec["rule_reserved"] = out.get("rule_reserved", [])
            rec["rule_candidate_missing"] = out.get("rule_candidate_missing", [])
            rec["top5"] = [
                {"final_rank": r["final_rank"], "chunk_id": r["chunk_id"],
                 "doc_type": r["doc_type"], "rrf_score": r.get("rrf_score"),
                 "vector_similarity": r.get("vector_similarity"),
                 "keyword_score": r.get("keyword_score")}
                for r in out["results"]
            ]
            rec["exception"] = None
        except Exception as e:  # 异常只记录，不重试
            rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            rec["supported"] = None
            rec["top5"] = []
            rec["exception"] = f"{type(e).__name__}: {e}"
            exceptions.append({"case_id": c["case_id"], "error": rec["exception"]})
        per_case.append(rec)

    # ---- 2. 指标计算（多答案按冻结标注整体判定，不改标注） ----
    answerable = [c for c in cases if c["is_answerable"]]
    unanswerable = [c for c in cases if not c["is_answerable"]]
    by_id = {r["case_id"]: r for r in per_case}

    def judge(rec, case):
        """返回 (hit1, recall3, rr, rule_ok, supported_ok, failure_types)"""
        ft = []
        top3 = [t["chunk_id"] for t in rec["top5"][:TOP3]]
        top1 = top3[0] if top3 else None
        rel = set(case.get("relevant_chunk_ids", []))
        req = set(case.get("required_rule_ids", []))

        hit1 = bool(top1 and top1 in rel)
        recall3 = any(cid in rel for cid in top3)
        r = rrf_rank(rec["top5"], rel)
        rr = (1.0 / r) if r else 0.0

        rule_ok = True
        if req:
            rule_ok = all(rid in top3 for rid in req)

        sup_exp = case.get("expected_supported", case["is_answerable"])
        supported_ok = (rec["supported"] == sup_exp)

        if case["is_answerable"]:
            if not hit1:
                ft.append("hit1_miss")
            if not recall3:
                ft.append("recall3_miss")
            if req and not rule_ok:
                ft.append("rule_miss")
            if rec["supported"] is False:
                ft.append("gate_over")
        else:
            # 不可回答：预期 supported=False（门控拦截）；未拦截且返回结果即误命中
            if rec["supported"] is True and rec["top5"]:
                ft.append("gate_miss_false_hit")
            if rec["supported"] is True and not rec["top5"]:
                ft.append("supported_mismatch")

        if rec.get("exception"):
            ft.append("exception")
        return hit1, recall3, rr, rule_ok, supported_ok, ft

    for case in cases:
        rec = by_id[case["case_id"]]
        hit1, recall3, rr, rule_ok, sup_ok, ft = judge(rec, case)
        rec.update({"hit1": hit1, "recall3": recall3, "rr": rr,
                    "rule_ok": rule_ok, "supported_ok": sup_ok,
                    "failure_types": ft})

    # ---- 总体指标 ----
    n_ans = len(answerable)
    h1 = sum(1 for c in answerable if by_id[c["case_id"]]["hit1"])
    r3 = sum(1 for c in answerable if by_id[c["case_id"]]["recall3"])
    mrr = sum(by_id[c["case_id"]]["rr"] for c in answerable) / n_ans
    req_cases = [c for c in cases if c.get("required_rule_ids")]
    rule_ok_n = sum(1 for c in req_cases if by_id[c["case_id"]]["rule_ok"])
    sup_ok_n = sum(1 for c in cases if by_id[c["case_id"]]["supported_ok"])
    false_hits = [c["case_id"] for c in unanswerable
                  if "gate_miss_false_hit" in by_id[c["case_id"]]["failure_types"]]

    lat_summary = _latency_summary([r["latency_ms"] for r in per_case])

    overall = {
        "n_cases": len(cases),
        "n_answerable": n_ans,
        "n_unanswerable": len(unanswerable),
        "answer_hit1": f"{h1}/{n_ans}",
        "answer_hit1_pct": pct(h1, n_ans),
        "answer_recall3": f"{r3}/{n_ans}",
        "answer_recall3_pct": pct(r3, n_ans),
        "mrr": round(mrr, 4),
        "rule_recall3": f"{rule_ok_n}/{len(req_cases)}",
        "rule_recall3_pct": pct(rule_ok_n, len(req_cases)),
        "supported_accuracy": f"{sup_ok_n}/{len(cases)}",
        "supported_accuracy_pct": pct(sup_ok_n, len(cases)),
        "unanswerable_false_hits": f"{len(false_hits)}/{len(unanswerable)}",
        "unanswerable_false_hit_rate_pct": pct(len(false_hits), len(unanswerable)),
        "false_hit_case_ids": false_hits,
        "latency_ms_first_call_cold_start": lat_summary["first_call"],
        "latency_ms_p50_overall": lat_summary["p50"],
        "latency_ms_p95_overall": lat_summary["p95"],
        "latency_ms_p50_excluding_first": lat_summary["p50_excluding_first"],
        "latency_ms_p95_excluding_first": lat_summary["p95_excluding_first"],
        "latency_ms_min": lat_summary["min"],
        "latency_ms_max": lat_summary["max"],
        "exceptions": exceptions,
    }

    # ---- 分组指标 ----
    def group_metrics(keyfn, keys):
        out = {}
        for key in keys:
            sub = [c for c in cases if keyfn(c) == key]
            if not sub:
                out[key] = None
                continue
            ans = [c for c in sub if c["is_answerable"]]
            g_h1 = sum(1 for c in ans if by_id[c["case_id"]]["hit1"])
            g_r3 = sum(1 for c in ans if by_id[c["case_id"]]["recall3"])
            g_mrr = (sum(by_id[c["case_id"]]["rr"] for c in ans) / len(ans)) if ans else None
            g_req = [c for c in sub if c.get("required_rule_ids")]
            g_rule = sum(1 for c in g_req if by_id[c["case_id"]]["rule_ok"])
            g_sup = sum(1 for c in sub if by_id[c["case_id"]]["supported_ok"])
            g_fh = sum(1 for c in sub if not c["is_answerable"]
                       and "gate_miss_false_hit" in by_id[c["case_id"]]["failure_types"])
            out[key] = {
                "n": len(sub),
                "hit1": f"{g_h1}/{len(ans)}" if ans else "-",
                "recall3": f"{g_r3}/{len(ans)}" if ans else "-",
                "mrr": round(g_mrr, 4) if g_mrr is not None else "-",
                "rule_recall3": f"{g_rule}/{len(g_req)}" if g_req else "-",
                "supported_ok": f"{g_sup}/{len(sub)}",
                "false_hits": g_fh,
            }
        return out

    cat_of = lambda c: c.get("category") or ("unanswerable" if not c["is_answerable"] else "")
    categories = sorted({cat_of(c) for c in cases})
    difficulties = ["easy", "medium", "hard"]
    group_cat = group_metrics(cat_of, categories)
    group_diff = group_metrics(lambda c: c.get("difficulty", ""), difficulties)

    # ---- 失败案例明细 ----
    failures = []
    for case in cases:
        rec = by_id[case["case_id"]]
        if rec["failure_types"]:
            reason_map = {
                "hit1_miss": "Top-1 不在预期 relevant_chunk_ids",
                "recall3_miss": "Top-3 未命中任何预期片段",
                "rule_miss": "必需规则未进入 Top-3",
                "rule_not_in_pool": "必需规则不在候选池",
                "gate_miss_false_hit": "不可回答问题未被门控拦截并返回了结果",
                "gate_over": "可回答问题被误门控",
                "supported_mismatch": "supported 判断与预期不符",
                "exception": "检索器调用异常",
            }
            failures.append({
                "case_id": case["case_id"],
                "query": case["query"],
                "expected_relevant_chunk_ids": case.get("relevant_chunk_ids", []),
                "required_rule_ids": case.get("required_rule_ids", []),
                "actual_top3": [t["chunk_id"] for t in rec["top5"][:TOP3]],
                "supported": rec["supported"],
                "failure_types": rec["failure_types"],
                "brief_reason": "；".join(reason_map.get(f, f) for f in rec["failure_types"]),
            })

    results = {
        "meta": {
            "evaluated_mode": EVALUATED_MODE,
            "executed_at": datetime.now().isoformat(timespec="seconds"),
            "execution_count": 1,
            "blind_set_sha256": blind_sha,
            "top_k": TOP_K,
            "metric_top": TOP3,
            "no_retry_policy": "每条用例仅调用检索器一次；异常只记录不重试；未调参未重跑",
            "retrieval_executed": True,
            "deepseek_called": False,
        },
        "overall": overall,
        "group_by_category": group_cat,
        "group_by_difficulty": group_diff,
        "per_case": per_case,
        "failures": failures,
    }
    with open(RESULTS_OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # ---- 3. 评测后哈希复验 ----
    hashes_after, match_after = candidate_hashes()
    blind_sha_after = sha256(BLIND_SET)

    import chromadb
    import sentence_transformers
    try:
        import torch
        torch_ver = torch.__version__
    except Exception:
        torch_ver = "n/a"

    exec_manifest = {
        "executed_at": results["meta"]["executed_at"],
        "execution_count": 1,
        "blind_set_sha256": blind_sha,
        "blind_set_sha256_after": blind_sha_after,
        "blind_set_unchanged": blind_sha_after == blind_sha,
        "candidate_hashes_before": hashes_before,
        "candidate_hashes_after": hashes_after,
        "candidate_hashes_match_before": all(match_before.values()),
        "candidate_hashes_match_after": all(match_after.values()),
        "retrieval_executed": True,
        "deepseek_called": False,
        "evaluated_mode": EVALUATED_MODE,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "dependency_versions": {
            "chromadb": chromadb.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "torch": torch_ver,
        },
        "results_file_sha256": sha256(RESULTS_OUT),
        "exceptions_occurred": bool(exceptions),
        "exceptions": exceptions,
        "final_blind_set_manifest_untouched": True,
        "final_candidate_freeze_manifest_untouched": True,
    }
    with open(EXEC_MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(exec_manifest, f, ensure_ascii=False, indent=2)

    # ---- 4. 控制台摘要 ----
    print("OVERALL:", json.dumps(overall, ensure_ascii=False))
    print("GROUP_CAT:", json.dumps(group_cat, ensure_ascii=False))
    print("GROUP_DIFF:", json.dumps(group_diff, ensure_ascii=False))
    print("FAILURES:", len(failures))
    for x in failures:
        print(" -", x["case_id"], x["failure_types"], x["actual_top3"])
    print("HASH_BEFORE_OK:", all(match_before.values()),
          "HASH_AFTER_OK:", all(match_after.values()),
          "BLIND_UNCHANGED:", blind_sha_after == blind_sha)


if __name__ == "__main__":
    main()
