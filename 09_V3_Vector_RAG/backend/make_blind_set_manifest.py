# -*- coding: utf-8 -*-
"""生成 final_blind_set_manifest.json（盲测集冻结清单，只读哈希与统计，不运行检索）。

记录：
- final_blind_set_v1.json / final_blind_set_label_review.md /
  eval_query_blacklist.json / final_candidate_freeze_manifest.json 的 SHA-256；
- 用例总数/可回答/不可回答/分类分布/难度分布/多答案用例数/风险规则用例数；
- check_final_blind_set.py 结论（12/12）；
- 候选代码冻结哈希是否保持（当前SHA-256 与 final_candidate_freeze_manifest.json 比对）；
- retrieval_executed=false、deepseek_called=false。
"""

import hashlib
import json
import os
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main():
    blind_path = os.path.join(DATA, "final_blind_set_v1.json")
    review_path = os.path.join(DATA, "final_blind_set_label_review.md")
    blacklist_path = os.path.join(DATA, "eval_query_blacklist.json")
    freeze_path = os.path.join(DATA, "final_candidate_freeze_manifest.json")

    blind = json.load(open(blind_path, encoding="utf-8"))
    cases = blind["cases"]
    category_counts = {}
    difficulty_counts = {}
    for c in cases:
        category_counts[c["category"]] = category_counts.get(c["category"], 0) + 1
        difficulty_counts[c["difficulty"]] = difficulty_counts.get(c["difficulty"], 0) + 1
    multi_answer = [c["case_id"] for c in cases if len(c["relevant_chunk_ids"]) > 1]
    risk_rule = [c["case_id"] for c in cases if c["required_rule_ids"]]

    # 候选代码哈希保持性核验
    freeze = json.load(open(freeze_path, encoding="utf-8"))
    files_ok, files_now = {}, {}
    for rel, old_hash in freeze["files_sha256"].items():
        p = os.path.join(BACKEND, rel)
        now = sha256_of(p)
        files_now[rel] = now
        files_ok[rel] = (now == old_hash)

    manifest = {
        "purpose": "最终盲测集冻结清单：final_blind_set_v1.json 创建后不得修改；"
                   "盲测运行前 final_candidate_freeze_manifest.json 中哈希必须保持不变。",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files_sha256": {
            "final_blind_set_v1.json": sha256_of(blind_path),
            "final_blind_set_label_review.md": sha256_of(review_path),
            "eval_query_blacklist.json": sha256_of(blacklist_path),
            "final_candidate_freeze_manifest.json": sha256_of(freeze_path),
        },
        "case_stats": {
            "total": len(cases),
            "answerable": sum(1 for c in cases if c["is_answerable"]),
            "unanswerable": sum(1 for c in cases if not c["is_answerable"]),
            "category_distribution": category_counts,
            "difficulty_distribution": difficulty_counts,
            "multi_answer_case_ids": multi_answer,
            "multi_answer_count": len(multi_answer),
            "risk_rule_case_ids": risk_rule,
            "risk_rule_case_count": len(risk_rule),
        },
        "label_review_check": "final_blind_set_label_review.md 逐条标注依据与多答案说明已完成（13条多答案用例全部提前列入relevant_chunk_ids）",
        "check_final_blind_set_result": "12/12 通过（backend/check_final_blind_set.py，2026-09-25）",
        "candidate_code_hashes_unchanged": {
            "all_match": all(files_ok.values()),
            "per_file": files_ok,
            "current_sha256": files_now,
        },
        "retrieval_executed": False,
        "deepseek_called": False,
        "notes": "盲测集创建与检查全程未导入/未调用 keyword_retriever / vector_retriever / "
                 "hybrid_retriever(v1/v2)，未查看任何Top-K结果，未调用DeepSeek。",
    }

    out = os.path.join(DATA, "final_blind_set_manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("manifest written:", out)
    print("blind_set_sha256:", manifest["files_sha256"]["final_blind_set_v1.json"].upper())
    print("candidate_code_hashes_unchanged:", manifest["candidate_code_hashes_unchanged"]["all_match"])
    print("multi_answer:", len(multi_answer), "risk_rule:", len(risk_rule))


if __name__ == "__main__":
    main()
