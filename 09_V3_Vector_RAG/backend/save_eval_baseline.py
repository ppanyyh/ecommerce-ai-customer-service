"""保存 V3.0 规则片段优化前的基线评测结果（只读当前索引与当前评测集，不做任何修改）。

输出：backend/data/vector_eval_baseline.json
- 每条用例的 Top-3（chunk_id/doc_type/similarity/source）与排名；
- 总体 Hit@1 / Recall@3 / MRR（仅可回答问题，answerable=17）；
- 各 doc_type 指标；
- 失败/混淆用例清单（含 Top-3）；
- 3 条无关问题的 Top-1 相似度。

约定：本脚本在规则 retrieval_text 优化之前运行一次，结果作为不可覆盖的基线；
      优化后的对比结果由 test_vector_retrieval.py 写入
      vector_eval_after_rule_optimization.json，不修改本文件。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\save_eval_baseline.py
"""

import json
import os
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
EVAL_PATH = os.path.join(BACKEND_DIR, "data", "vector_eval_cases.json")
OUT_PATH = os.path.join(BACKEND_DIR, "data", "vector_eval_baseline.json")

sys.path.insert(0, BACKEND_DIR)
from vector_retriever import vector_search  # noqa: E402

TOP_K = 5


def main():
    with open(EVAL_PATH, encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    case_results = []
    answerable = [c for c in cases if c["is_answerable"]]
    irrelevant = [c for c in cases if not c["is_answerable"]]

    hit1_cnt = recall3_cnt = 0
    rr_sum = 0.0
    by_type = {}
    failed_or_confused = []
    irr_scores = []

    for case in cases:
        results = vector_search(case["query"], top_k=TOP_K)
        expected = set(case.get("expected_chunk_ids") or [])
        top_ids = [r["chunk_id"] for r in results]
        top3 = top_ids[:3]

        entry = {
            "case_id": case["case_id"],
            "query": case["query"],
            "expected_chunk_ids": case.get("expected_chunk_ids", []),
            "is_answerable": case["is_answerable"],
            "note": case.get("note", ""),
            "top3": [
                {
                    "rank": r["rank"],
                    "chunk_id": r["chunk_id"],
                    "doc_type": r["doc_type"],
                    "similarity": r["similarity"],
                    "source": r["source"],
                }
                for r in results[:3]
            ],
            "first_expected_rank": next(
                (i + 1 for i, cid in enumerate(top_ids) if cid in expected), None
            ),
        }

        if case["is_answerable"]:
            hit1 = bool(top3) and top3[0] in expected
            recall3 = any(cid in expected for cid in top3)
            mrr_rank = entry["first_expected_rank"]
            hit1_cnt += hit1
            recall3_cnt += recall3
            rr_sum += (1.0 / mrr_rank) if mrr_rank else 0.0

            dt = case.get("expected_doc_type") or "unknown"
            st = by_type.setdefault(dt, {"hit1": 0, "recall3": 0, "rr_sum": 0.0, "n": 0})
            st["hit1"] += int(hit1)
            st["recall3"] += int(recall3)
            st["rr_sum"] += (1.0 / mrr_rank) if mrr_rank else 0.0
            st["n"] += 1

            entry["hit1"] = hit1
            entry["recall3"] = recall3
            entry["mrr_rank"] = mrr_rank
            if not (hit1 and recall3):
                failed_or_confused.append(entry)
        else:
            top1_sim = results[0]["similarity"] if results else 0.0
            irr_scores.append({"case_id": case["case_id"], "query": case["query"],
                               "top1_chunk_id": top_ids[0] if top_ids else None,
                               "top1_similarity": top1_sim})
            entry["top1_similarity"] = top1_sim

        case_results.append(entry)

    n_ans = len(answerable)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "description": "规则片段 retrieval_text 优化前的基线评测（优化前口径：expected_chunk_ids 为单一预期）",
        "total_cases": len(cases),
        "answerable_cases": n_ans,
        "metrics": {
            "hit_at_1": round(hit1_cnt / n_ans, 4),
            "hit1_correct": hit1_cnt,
            "recall_at_3": round(recall3_cnt / n_ans, 4),
            "recall3_correct": recall3_cnt,
            "mrr": round(rr_sum / n_ans, 4),
        },
        "per_doc_type": {
            dt: {
                "n": st["n"],
                "hit_at_1": round(st["hit1"] / st["n"], 4),
                "recall_at_3": round(st["recall3"] / st["n"], 4),
                "mrr": round(st["rr_sum"] / st["n"], 4),
            }
            for dt, st in sorted(by_type.items())
        },
        "failed_or_confused_cases": [e["case_id"] for e in failed_or_confused],
        "irrelevant_scores": irr_scores,
        "irrelevant_max_similarity": max(s["top1_similarity"] for s in irr_scores) if irr_scores else 0.0,
        "cases": case_results,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    m = summary["metrics"]
    print(f"baseline saved: {OUT_PATH}")
    print(f"Hit@1={m['hit1_correct']}/{n_ans}={m['hit_at_1']:.1%} "
          f"Recall@3={m['recall3_correct']}/{n_ans}={m['recall_at_3']:.1%} MRR={m['mrr']}")
    print("failed/confused:", ", ".join(summary["failed_or_confused_cases"]))
    for e in case_results:
        if e["case_id"] in ("VE-011", "VE-012", "VE-013", "VE-014"):
            ranks = [(t["rank"], t["chunk_id"]) for t in e["top3"]]
            print(f"{e['case_id']}: expected={e['expected_chunk_ids']} first_rank={e['first_expected_rank']} top3={ranks}")


if __name__ == "__main__":
    main()
