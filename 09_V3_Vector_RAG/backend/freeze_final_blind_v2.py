# -*- coding: utf-8 -*-
"""V3.1 第四阶段：生成 final_blind_set_v2_manifest.json（盲测数据冻结清单），
生成后重新计算全部相关文件哈希并复核 all_match。纯数据操作，不运行任何检索/API/模型。
"""

import hashlib
import json
import os
from collections import Counter
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    bs_path = os.path.join(DATA, "final_blind_set_v2.json")
    review_path = os.path.join(DATA, "final_blind_set_v2_label_review.md")
    bl_path = os.path.join(DATA, "final_blind_v2_query_blacklist.json")
    checklist_path = os.path.join(DATA, "final_blind_set_v2_review_checklist.md")
    rt_manifest_path = os.path.join(DATA, "v3_1_runtime_freeze_manifest.json")

    bs = json.load(open(bs_path, encoding="utf-8"))
    bl = json.load(open(bl_path, encoding="utf-8"))
    cases = bs["cases"]

    cat = Counter(c["category"] for c in cases
                  if c["evaluation_layer"] == "retrieval_scope_order")
    diff = Counter(c["difficulty"] for c in cases)
    scope = Counter(c["expected_scope"] for c in cases)
    layer = Counter(c["evaluation_layer"] for c in cases)
    multi_ans = sum(1 for c in cases if len(c["relevant_chunk_ids"]) >= 2)
    risk = sum(1 for c in cases if c["required_rule_ids"])
    defect = sum(1 for c in cases if "RULE-HR-08" in c["required_rule_ids"])
    order = cat.get("order", 0)

    rt = json.load(open(rt_manifest_path, encoding="utf-8"))
    runtime_files = {f: sha256_file(os.path.join(BACKEND, f))
                     for f in rt["files_sha256"]}

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "name": "final blind set v2 冻结清单（候选冻结，等待一次性评测指令）",
        "status": "frozen_pending_one_time_evaluation",
        "files_sha256": {
            "data/final_blind_set_v2.json": sha256_file(bs_path),
            "data/final_blind_set_v2_label_review.md": sha256_file(review_path),
            "data/final_blind_v2_query_blacklist.json": sha256_file(bl_path),
            "data/final_blind_set_v2_review_checklist.md": sha256_file(checklist_path),
        },
        "v3_1_runtime_freeze_manifest_sha256": sha256_file(rt_manifest_path),
        "runtime_candidate_files_sha256": runtime_files,
        "runtime_candidate_files_match_baseline": all(
            h == rt["files_sha256"][f] for f, h in runtime_files.items()),
        "counts": {
            "total": len(cases),
            "by_layer": dict(layer),
            "by_category_A": dict(cat),
            "by_difficulty": dict(diff),
            "by_scope": dict(scope),
            "multi_answer_cases": multi_ans,
            "risk_rule_cases": risk,
            "quality_defect_cases": defect,
            "order_cases": order,
        },
        "leakage_check": {
            "script": "backend/check_final_blind_set_v2.py",
            "result": "16/16 通过",
            "blacklist_unique_queries": bl["meta"]["total_unique"],
            "exact_duplicates": 0,
            "near_duplicates": 0,
        },
        "manual_review": {
            "checklist": "backend/data/final_blind_set_v2_review_checklist.md",
            "sampled": 23,
            "required": 20,
            "conclusion": "23条抽查全部通过（自然度/独立性/资料可支持性/scope/风险要求），无回改条目",
        },
        "retrieval_executed": False,
        "api_chat_called": False,
        "deepseek_called": False,
        "old_final_blind_reexecuted": False,
        "final_blind_v2_executed": False,
        "execution_count": 0,
    }

    out_path = os.path.join(DATA, "final_blind_set_v2_manifest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 生成后重新计算全部相关文件哈希并确认一致
    ok = True
    for f, h in manifest["files_sha256"].items():
        now = sha256_file(os.path.join(BACKEND, f))
        same = now == h
        ok = ok and same
        print(("OK  " if same else "DIFF"), f)
    print("runtime_candidate_files_match_baseline:",
          manifest["runtime_candidate_files_match_baseline"])
    print("all_match =", ok)
    print("saved:", out_path)
    print("blind_set_sha256:", manifest["files_sha256"]["data/final_blind_set_v2.json"])


if __name__ == "__main__":
    main()
