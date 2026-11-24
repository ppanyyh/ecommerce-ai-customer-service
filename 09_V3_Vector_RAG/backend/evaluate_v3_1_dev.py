# -*- coding: utf-8 -*-
"""V3.1 开发集评测：门控三分类混淆矩阵 + 检索指标 + 缺陷 HR-08 检查。

仅使用 v3_1_dev_cases.json（本阶段新开发集），不触碰旧 final blind set。
每条用例只调用一次 hybrid_search_v2；阈值如需调整只能依据本开发集结果。
"""
import json
import os
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

from hybrid_retriever_v2 import hybrid_search_v2
from evaluate_final_blind_set import _latency_summary

DEV_SET = os.path.join(BACKEND, "data", "v3_1_dev_cases.json")
OUT = os.path.join(BACKEND, "data", "v3_1_dev_eval_results.json")
TOP_K = 5


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def main():
    blind = json.load(open(DEV_SET, encoding="utf-8"))
    cases = blind["cases"]

    per_case = []
    for c in cases:
        rec = dict(c)
        rec["top5"] = []
        t0 = time.perf_counter()
        try:
            out = hybrid_search_v2(c["query"], top_k=TOP_K)
            rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            rec["supported"] = out["supported"]
            rec["gate_reason"] = out.get("reason")
            rec["top5"] = [
                {"final_rank": r["final_rank"], "chunk_id": r["chunk_id"], "doc_type": r["doc_type"]}
                for r in out["results"]
            ]
            analysis = out.get("analysis", {})
            if out["supported"]:
                pred_scope = "supported"
            else:
                pred_scope = analysis.get("scope")
                if pred_scope not in ("unsupported_business", "irrelevant"):
                    pred_scope = (out.get("gate_evidence") or {}).get("final_scope", "unknown")
            rec["predicted_scope"] = pred_scope
            rec["required_rule_ids_detected"] = analysis.get("required_rule_ids", [])
            rec["exception"] = None
        except Exception as e:
            rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            rec["supported"] = None
            rec["predicted_scope"] = "error"
            rec["exception"] = f"{type(e).__name__}: {e}"
        per_case.append(rec)

    top3 = lambda r: [t["chunk_id"] for t in r["top5"][:3]]

    def judge(c, r):
        rel = set(c["relevant_chunk_ids"])
        req = set(c["required_rule_ids"])
        t3 = top3(r)
        hit1 = bool(t3 and t3[0] in rel)
        recall3 = any(x in rel for x in t3)
        rr = 0.0
        for t in r["top5"]:
            if t["chunk_id"] in rel:
                rr = 1.0 / t["final_rank"]
                break
        rule_ok = all(x in t3 for x in req) if req else True
        return hit1, recall3, rr, rule_ok

    for c, r in zip(cases, per_case):
        if c["is_answerable"]:
            h1, r3, rr, rok = judge(c, r)
            r.update({"hit1": h1, "recall3": r3, "rr": rr, "rule_ok": rok})

    answerable = [c for c in cases if c["is_answerable"]]
    unans = [c for c in cases if not c["is_answerable"]]
    a_by = {c["case_id"]: r for c, r in zip(cases, per_case) if c["is_answerable"]}

    n = len(answerable)
    h1n = sum(1 for c in answerable if a_by[c["case_id"]]["hit1"])
    r3n = sum(1 for c in answerable if a_by[c["case_id"]]["recall3"])
    mrr = sum(a_by[c["case_id"]]["rr"] for c in answerable) / n
    req_cases = [c for c in answerable if c["required_rule_ids"]]
    rok_n = sum(1 for c in req_cases if a_by[c["case_id"]]["rule_ok"])

    # supported / scope
    sup_ok = sum(1 for c, r in zip(cases, per_case) if r["supported"] == c["expected_supported"])
    scope_ok = sum(1 for c, r in zip(cases, per_case) if r["predicted_scope"] == c["expected_scope"])
    false_pass = [c["case_id"] for c, r in zip(cases, per_case)
                  if not c["is_answerable"] and r["supported"] is True]
    false_gate = [c["case_id"] for c, r in zip(cases, per_case)
                  if c["is_answerable"] and r["supported"] is False]

    # 混淆矩阵（expected_scope x predicted_scope）
    labels = ["supported", "unsupported_business", "irrelevant"]
    confusion = {e: {p: 0 for p in labels} for e in labels}
    for c, r in zip(cases, per_case):
        e, p = c["expected_scope"], r["predicted_scope"]
        confusion.setdefault(e, {}).setdefault(p, 0)
        confusion[e][p] = confusion[e].get(p, 0) + 1

    # 分类分组指标
    groups = {}
    for cat in sorted({c["category"] for c in cases}):
        sub = [c for c in cases if c["category"] == cat]
        ans = [c for c in sub if c["is_answerable"]]
        g = {"n": len(sub)}
        if ans:
            g["hit1"] = f"{sum(1 for c in ans if a_by[c['case_id']]['hit1'])}/{len(ans)}"
            g["recall3"] = f"{sum(1 for c in ans if a_by[c['case_id']]['recall3'])}/{len(ans)}"
        greq = [c for c in sub if c["required_rule_ids"]]
        if greq:
            g["rule_recall3"] = f"{sum(1 for c in greq if a_by[c['case_id']]['rule_ok'])}/{len(greq)}"
        g["scope_ok"] = f"{sum(1 for c in sub if next(r for r in per_case if r['case_id']==c['case_id'])['predicted_scope']==c['expected_scope'])}/{len(sub)}"
        groups[cat] = g

    # 缺陷 HR-08 检查
    defect_cases = [c for c in cases if "RULE-HR-08" in c.get("required_rule_ids", [])]
    defect_ok = sum(1 for c in defect_cases
                    if "RULE-HR-08" in top3(next(r for r in per_case if r["case_id"] == c["case_id"])))

    lat_summary = _latency_summary([r["latency_ms"] for r in per_case])

    overall = {
        "n_cases": len(cases),
        "n_answerable": n,
        "n_unanswerable": len(unans),
        "answer_hit1": f"{h1n}/{n}",
        "answer_hit1_pct": pct(h1n, n),
        "answer_recall3": f"{r3n}/{n}",
        "answer_recall3_pct": pct(r3n, n),
        "mrr": round(mrr, 4),
        "rule_recall3": f"{rok_n}/{len(req_cases)}",
        "rule_recall3_pct": pct(rok_n, len(req_cases)),
        "supported_accuracy": f"{sup_ok}/{len(cases)}",
        "supported_accuracy_pct": pct(sup_ok, len(cases)),
        "scope_classification_accuracy_pct": pct(scope_ok, len(cases)),
        "unanswerable_false_pass": f"{len(false_pass)}/{len(unans)}",
        "unanswerable_false_pass_rate_pct": pct(len(false_pass), len(unans)),
        "false_pass_case_ids": false_pass,
        "answerable_false_gate_case_ids": false_gate,
        "defect_hr08_top3": f"{defect_ok}/{len(defect_cases)}",
        "latency": lat_summary,
        "exceptions": [r["exception"] for r in per_case if r.get("exception")],
    }

    results = {
        "meta": {"evaluated_at": datetime.now().isoformat(timespec="seconds"),
                 "mode": "hybrid_business_v2 (V3.1)", "top_k": TOP_K, "dev_set": "v3_1_dev_cases.json"},
        "overall": overall,
        "confusion_matrix": confusion,
        "groups": groups,
        "per_case": per_case,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("OVERALL:", json.dumps(overall, ensure_ascii=False))
    print("CONFUSION:", json.dumps(confusion, ensure_ascii=False))
    print("GROUPS:", json.dumps(groups, ensure_ascii=False))
    print("FAIL/HIT-DETAIL:")
    for c, r in zip(cases, per_case):
        if c["is_answerable"] and (not r["hit1"] or not r["recall3"] or not r["rule_ok"]):
            print(" -", c["case_id"], "hit1" if r["hit1"] else "H1X", "r3" if r["recall3"] else "R3X",
                  "rule" if r["rule_ok"] else "RULEX", top3(r), "|", c["query"][:30])


if __name__ == "__main__":
    main()
