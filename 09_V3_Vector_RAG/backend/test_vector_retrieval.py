"""V3.0 向量检索评测脚本（仅本地检索，不调用 DeepSeek，不接入 /api/chat）。

评测内容（20条用例：5商品改写 + 5FAQ口语 + 4规则 + 3混淆 + 3无关），
区分两类检索目标：
- answer_relevance：可用于回答的商品/FAQ/规则片段（relevant_chunk_ids）；
- rule_coverage：风险问题必须召回的转人工规则（required_rule_ids）。

指标：
1. Answer Hit@1：Top-1 是否在 relevant_chunk_ids 中；
2. Answer Recall@3：Top-3 是否至少命中一个 relevant_chunk_id；
3. MRR：第一个 relevant_chunk_id 排名的倒数（仅可回答问题取平均）；
4. Rule Recall@3：required_rule_ids 非空的用例，其必需规则是否进入 Top-3
   （本项目每条用例只有一个必需规则，故要求该规则进入 Top-3）；
5. 各 doc_type 指标；
6. 无关问题最高相似度（拒答阈值参考，不设固定阈值）。

目标参考：Answer Hit@1 >= 80%，Answer Recall@3 >= 90%，Rule Recall@3 = 100%，
商品与FAQ不回归（与 vector_eval_baseline.json 自动对比）。
约定：不为达标修改预期答案；不把测试语句加入知识片段（无数据泄漏）。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\test_vector_retrieval.py
"""

import json
import os
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
EVAL_PATH = os.path.join(BACKEND_DIR, "data", "vector_eval_cases.json")
BASELINE_PATH = os.path.join(BACKEND_DIR, "data", "vector_eval_baseline.json")
AFTER_PATH = os.path.join(BACKEND_DIR, "data", "vector_eval_after_rule_optimization.json")

sys.path.insert(0, BACKEND_DIR)
from vector_retriever import vector_search  # noqa: E402

TOP_K = 5
TARGET_HIT1 = 0.80
TARGET_RECALL3 = 0.90
TARGET_RULE_RECALL3 = 1.00


def top3_records(results):
    return [
        {"rank": r["rank"], "chunk_id": r["chunk_id"], "doc_type": r["doc_type"],
         "similarity": r["similarity"], "source": r["source"]}
        for r in results[:3]
    ]


def evaluate_case(case, results):
    relevant = set(case.get("relevant_chunk_ids") or [])
    required_rules = case.get("required_rule_ids") or []
    top_ids = [r["chunk_id"] for r in results]
    top3 = top_ids[:3]

    hit1 = bool(top3) and top3[0] in relevant
    recall3 = any(cid in relevant for cid in top3)
    mrr_rank = next((i + 1 for i, cid in enumerate(top_ids) if cid in relevant), None)
    rule_ok = all(rid in top3 for rid in required_rules) if required_rules else None
    return hit1, recall3, mrr_rank, rule_ok


def main():
    with open(EVAL_PATH, encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    baseline = None
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, encoding="utf-8") as f:
            baseline = json.load(f)
    base_by_id = {e["case_id"]: e for e in baseline["cases"]} if baseline else {}

    answerable = [c for c in cases if c["is_answerable"]]
    irrelevant = [c for c in cases if not c["is_answerable"]]

    print("=" * 68)
    print(f"V3.0 向量检索评测（{len(cases)} 条用例，top_k={TOP_K}，规则retrieval_text优化后）")
    print("=" * 68)

    hit1_cnt = recall3_cnt = 0
    rr_sum = 0.0
    rule_cases_total = rule_cases_ok = 0
    failures = []
    by_type = {}
    case_results = []
    irr_scores = []

    for case in cases:
        results = vector_search(case["query"], top_k=TOP_K)
        top_ids = [r["chunk_id"] for r in results]

        entry = {
            "case_id": case["case_id"],
            "query": case["query"],
            "relevant_chunk_ids": case.get("relevant_chunk_ids", []),
            "required_rule_ids": case.get("required_rule_ids", []),
            "is_answerable": case["is_answerable"],
            "note": case.get("note", ""),
            "annotation_note": case.get("annotation_note", ""),
            "top3": top3_records(results),
        }

        if case["is_answerable"]:
            hit1, recall3, mrr_rank, rule_ok = evaluate_case(case, results)
            hit1_cnt += hit1
            recall3_cnt += recall3
            rr_sum += (1.0 / mrr_rank) if mrr_rank else 0.0
            entry.update({"hit1": hit1, "recall3": recall3,
                          "mrr_rank": mrr_rank, "rule_recall3": rule_ok})

            dt = case.get("expected_doc_type") or "unknown"
            st = by_type.setdefault(dt, {"hit1": 0, "recall3": 0, "rr_sum": 0.0, "n": 0})
            st["hit1"] += int(hit1)
            st["recall3"] += int(recall3)
            st["rr_sum"] += (1.0 / mrr_rank) if mrr_rank else 0.0
            st["n"] += 1

            if case["required_rule_ids"]:
                rule_cases_total += 1
                rule_cases_ok += int(bool(rule_ok))

            status = "PASS" if (hit1 and recall3) else ("PART" if recall3 else "FAIL")
            if not (hit1 and recall3):
                failures.append(f"{case['case_id']}({status},top1={top_ids[:1]})")
            if case["required_rule_ids"] and not rule_ok:
                failures.append(f"{case['case_id']}(RULE_MISS,required={case['required_rule_ids']})")

            note = f" | {case['note']}" if case.get("note") else ""
            anno = f" | {case['annotation_note']}" if case.get("annotation_note") else ""
            rule_txt = f" rule_recall3={rule_ok}" if rule_ok is not None else ""
            print(f"[{case['case_id']}] {status} hit1={hit1} recall3={recall3} "
                  f"mrr_rank={mrr_rank or '-'}{rule_txt}")
            print(f"    Q: {case['query']}{note}{anno}")
            print(f"    Top3: " + " | ".join(
                f"{t['rank']}.{t['chunk_id']}({t['doc_type']},sim={t['similarity']:.4f})"
                for t in entry["top3"]) or "（无结果）")

            # 与基线对比：relevant 集内第一个命中的排名变化
            b = base_by_id.get(case["case_id"])
            if b:
                entry["baseline_first_expected_rank"] = b.get("first_expected_rank")
        else:
            top1_sim = results[0]["similarity"] if results else 0.0
            irr_scores.append({"case_id": case["case_id"], "query": case["query"],
                               "top1_chunk_id": top_ids[0] if top_ids else None,
                               "top1_similarity": top1_sim})
            entry["top1_similarity"] = top1_sim
            print(f"[{case['case_id']}] 无关问题 Top1: "
                  f"{results[0]['chunk_id']} sim={top1_sim:.4f}" if results
                  else f"[{case['case_id']}] 无关问题 无结果")

        case_results.append(entry)

    n_ans = len(answerable)
    hit1_rate = hit1_cnt / n_ans if n_ans else 0.0
    recall3_rate = recall3_cnt / n_ans if n_ans else 0.0
    mrr = rr_sum / n_ans if n_ans else 0.0
    rule_recall3 = rule_cases_ok / rule_cases_total if rule_cases_total else None

    print("\n----- 总体指标（仅可回答问题，n=%d）-----" % n_ans)
    print(f"Answer Hit@1   : {hit1_cnt}/{n_ans} = {hit1_rate:.1%}  "
          f"(目标>=80% {'PASS' if hit1_rate >= TARGET_HIT1 else 'FAIL'})")
    print(f"Answer Recall@3: {recall3_cnt}/{n_ans} = {recall3_rate:.1%}  "
          f"(目标>=90% {'PASS' if recall3_rate >= TARGET_RECALL3 else 'FAIL'})")
    print(f"MRR            : {mrr:.4f}")
    if rule_recall3 is not None:
        print(f"Rule Recall@3  : {rule_cases_ok}/{rule_cases_total} = {rule_recall3:.0%}  "
              f"(目标=100% {'PASS' if rule_recall3 >= TARGET_RULE_RECALL3 else 'FAIL'})")

    print("\n----- 按 doc_type -----")
    for dt, st in sorted(by_type.items()):
        n = st["n"]
        print(f"{dt:8s}: n={n} Hit@1={st['hit1']}/{n}={st['hit1']/n:.0%} "
              f"Recall@3={st['recall3']}/{n}={st['recall3']/n:.0%} MRR={st['rr_sum']/n:.4f}")

    print("\n----- 无关问题最高相似度（拒答阈值依据，不设固定阈值）-----")
    for s in irr_scores:
        print(f"[{s['case_id']}] {s['query']} -> Top1 sim={s['top1_similarity']:.4f}")
    irr_max = max((s["top1_similarity"] for s in irr_scores), default=0.0)
    print(f"无关问题最高相似度: max={irr_max:.4f} "
          f"avg={sum(s['top1_similarity'] for s in irr_scores)/len(irr_scores):.4f}")

    # ---------- 与基线对比 ----------
    comparison = None
    if baseline:
        bm = baseline["metrics"]
        comparison = {
            "metrics_before": bm,
            "metrics_after": {
                "hit_at_1": round(hit1_rate, 4), "hit1_correct": hit1_cnt,
                "recall_at_3": round(recall3_rate, 4), "recall3_correct": recall3_cnt,
                "mrr": round(mrr, 4),
                "rule_recall_at_3": round(rule_recall3, 4) if rule_recall3 is not None else None,
            },
            "per_doc_type_before": baseline.get("per_doc_type", {}),
            "per_doc_type_after": {
                dt: {"n": st["n"], "hit_at_1": round(st["hit1"] / st["n"], 4),
                     "recall_at_3": round(st["recall3"] / st["n"], 4),
                     "mrr": round(st["rr_sum"] / st["n"], 4)}
                for dt, st in sorted(by_type.items())
            },
            "irrelevant_max_similarity_before": baseline.get("irrelevant_max_similarity"),
            "irrelevant_max_similarity_after": round(irr_max, 4),
            "rule_case_rank_changes": [],
        }
        for e in case_results:
            if e["required_rule_ids"] and e.get("baseline_first_expected_rank") is not None:
                comparison["rule_case_rank_changes"].append({
                    "case_id": e["case_id"],
                    "baseline_single_expected_rank": e["baseline_first_expected_rank"],
                    "after_first_relevant_rank": e.get("mrr_rank"),
                    "after_required_rule_in_top3": e.get("rule_recall3"),
                    "after_top3": [t["chunk_id"] for t in e["top3"]],
                })
        # 商品/FAQ 回归检查
        reg = []
        for dt in ("product", "faq"):
            b = comparison["per_doc_type_before"].get(dt, {})
            a = comparison["per_doc_type_after"].get(dt, {})
            regression = (a.get("hit_at_1", 0) < b.get("hit_at_1", 0)
                          or a.get("recall_at_3", 0) < b.get("recall_at_3", 0))
            reg.append({"doc_type": dt, "before": b, "after": a, "regression": regression})
        comparison["product_faq_regression"] = reg

        print("\n----- 优化前后对比 -----")
        print(f"Hit@1   : {bm['hit_at_1']:.1%} -> {hit1_rate:.1%}")
        print(f"Recall@3: {bm['recall_at_3']:.1%} -> {recall3_rate:.1%}")
        print(f"MRR     : {bm['mrr']:.4f} -> {mrr:.4f}")
        print(f"Rule Recall@3（必需规则进Top-3）: -> "
              f"{rule_recall3:.0%}" if rule_recall3 is not None else "")
        for r in comparison["rule_case_rank_changes"]:
            print(f"  {r['case_id']}: 基线单预期rank={r['baseline_single_expected_rank']} -> "
                  f"本次首个relevant rank={r['after_first_relevant_rank']} | "
                  f"必需规则进Top3={r['after_required_rule_in_top3']} | "
                  f"Top3={r['after_top3']}")
        for r in reg:
            print(f"  {r['doc_type']} 回归检查: before Hit@1={r['before'].get('hit_at_1')} "
                  f"Recall@3={r['before'].get('recall_at_3')} -> "
                  f"after Hit@1={r['after'].get('hit_at_1')} "
                  f"Recall@3={r['after'].get('recall_at_3')} | 回归={r['regression']}")
        print(f"  无关问题最高相似度: {baseline.get('irrelevant_max_similarity'):.4f} -> {irr_max:.4f}")

    # ---------- 写 after 结果文件 ----------
    after = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "description": "规则片段 retrieval_text 优化后的评测结果（含每条用例Top-3与最终指标，"
                       "对比基线见 vector_eval_baseline.json）",
        "annotation_revision_applied": True,
        "total_cases": len(cases),
        "answerable_cases": n_ans,
        "metrics": comparison["metrics_after"] if comparison else {
            "hit_at_1": round(hit1_rate, 4), "recall_at_3": round(recall3_rate, 4),
            "mrr": round(mrr, 4),
            "rule_recall_at_3": round(rule_recall3, 4) if rule_recall3 is not None else None,
        },
        "per_doc_type": comparison["per_doc_type_after"] if comparison else {},
        "comparison_with_baseline": comparison,
        "irrelevant_scores": irr_scores,
        "irrelevant_max_similarity": round(irr_max, 4),
        "cases": case_results,
    }
    with open(AFTER_PATH, "w", encoding="utf-8") as f:
        json.dump(after, f, ensure_ascii=False, indent=2)
    print(f"\nafter 结果已写入: {AFTER_PATH}")

    ok = (hit1_rate >= TARGET_HIT1 and recall3_rate >= TARGET_RECALL3
          and (rule_recall3 is None or rule_recall3 >= TARGET_RULE_RECALL3))
    print("评测结论:", "达到目标参考线" if ok else "未达目标——仅报告失败原因，不调参不泄漏")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
