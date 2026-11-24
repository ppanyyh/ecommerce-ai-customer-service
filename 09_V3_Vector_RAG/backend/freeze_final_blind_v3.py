# -*- coding: utf-8 -*-
"""V3.2.2 最终阶段一 · 步骤十一/十二：生成 final_blind_set_v3_manifest.json
预先固定全部评测目标（运行前写入，不得在看到结果后修改），并冻结全套盲测资产。"""
import hashlib
import json
import os
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


bs = json.load(open(os.path.join(DATA, "final_blind_set_v3.json"), encoding="utf-8"))
cases = bs["cases"]
fm = json.load(open(os.path.join(DATA, "v3_2_2_candidate_freeze_manifest.json"), encoding="utf-8"))
precheck = json.load(open(os.path.join(DATA, "_blindv3_precheck_candidate.json"), encoding="utf-8"))
checkres = json.load(open(os.path.join(DATA, "_blindv3_check_result.json"), encoding="utf-8"))

cat = Counter(c["category"] for c in cases)
diff = Counter(c["difficulty"] for c in cases)
scope = Counter(c["expected_scope"] for c in cases)
rule_cov = Counter()
for c in cases:
    for r in c["required_rule_ids"]:
        rule_cov[r] += 1
multi_answer = sum(1 for c in cases if len(c["relevant_chunk_ids"]) > 1)
order_cases = sum(1 for c in cases if "模拟订单数据" in json.dumps(c["source_refs"], ensure_ascii=False)
                  or c["category"] == "order")
quality_cases = sum(1 for c in cases if "RULE-HR-08" in c["required_rule_ids"])

MANIFEST = {
    "manifest": "final_blind_set_v3_manifest",
    "created_at": "2026-09-26",
    "status": "frozen_pending_one_time_evaluation",
    "note": "本项目最后一套最终盲测集（no_future_blind_set_planned=true）。创建阶段仅读取文件，未调用任何检索器/向量库/候选API/DeepSeek。",

    "final_blind_set_v3_sha256": sha256_file(os.path.join(DATA, "final_blind_set_v3.json")),
    "label_review_sha256": sha256_file(os.path.join(DATA, "final_blind_set_v3_label_review.md")),
    "query_blacklist_sha256": sha256_file(os.path.join(DATA, "final_blind_v3_query_blacklist.json")),
    "review_checklist_sha256": sha256_file(os.path.join(DATA, "final_blind_set_v3_review_checklist.md")),
    "v3_2_2_candidate_freeze_manifest_sha256": precheck["manifest_sha256"],

    "candidate_files_sha256": precheck["files_sha256_computed"],

    "counts": {
        "total": len(cases),
        "layer_a_retrieval_scope_order": cat["product"] + cat["faq"] + cat["rule"] + cat["multi"] + cat["order"] + cat["unsupported_business"] + cat["irrelevant"],
        "layer_b_api_contract": cat["api"],
        "category": dict(cat),
        "difficulty": dict(diff),
        "scope": dict(scope),
        "multi_answer_cases": multi_answer,
        "order_cases": order_cases,
        "quality_defect_cases_HR08": quality_cases,
    },
    "risk_rule_distribution": {k: v for k, v in sorted(rule_cov.items())},
    "official_risk_levels": fm["official_risk_levels"],

    "leakage_check": {
        "script": "check_final_blind_set_v3.py（24项，只读）",
        "result": f"{checkres['passed']}/{checkres['total_checks']} 通过，失败 {checkres['failed']}",
        "blacklist_entries": 1250,
        "detail_file": "data/_blindv3_check_result.json",
    },
    "manual_review": {
        "checklist": "final_blind_set_v3_review_checklist.md",
        "sampled": 28,
        "stratification": "product3/faq3/rule6/multi4/order4/unsupported3/irrelevant3/api2",
        "hr_coverage": "HR-01..08 全覆盖",
        "conclusion": "28条全部通过：自然、历史独立、标注可溯源、无诱导痕迹",
    },

    # ===== 预先冻结目标（运行前写入，不得修改） =====
    "pre_frozen_targets": {
        "answer_hit_at_1": ">= 85%",
        "union_hit_at_3": ">= 95%",
        "coverage_recall_at_3": "只报告，不设阈值",
        "rule_recall_at_3": ">= 90%",
        "hr08_recall_at_3": "= 100%",
        "scope_accuracy": ">= 95%",
        "unsupported_false_pass_rate": "<= 5%",
        "irrelevant_false_pass_rate": "<= 5%",
        "risk_floor_compliance": "= 100%",
        "high_risk_handoff": "= 100%",
        "wrong_handoff_rate": "<= 10%",
        "order_route_and_fact_accuracy": "= 100%",
        "api_contract_pass_rate": ">= 90%",
        "internal_term_leakage": "= 0",
        "forbidden_promise_violation": "= 0",
        "deepseek_real_calls": "= 0",
        "p95_latency_after_warmup_ms": "< 100",
        "frozen_before_execution": True,
    },

    "retrieval_executed": False,
    "api_chat_called": False,
    "deepseek_called": False,
    "old_blind_v1_reexecuted": False,
    "old_blind_v2_reexecuted": False,
    "final_blind_v3_executed": False,
    "execution_count": 0,
    "no_future_blind_set_planned": True,
    "all_match": True,
}

# 生成后重新计算全部哈希 → all_match
hash_fields = {
    "final_blind_set_v3_sha256": os.path.join(DATA, "final_blind_set_v3.json"),
    "label_review_sha256": os.path.join(DATA, "final_blind_set_v3_label_review.md"),
    "query_blacklist_sha256": os.path.join(DATA, "final_blind_v3_query_blacklist.json"),
    "review_checklist_sha256": os.path.join(DATA, "final_blind_set_v3_review_checklist.md"),
}
mismatch = []
for k, p in hash_fields.items():
    actual = sha256_file(p)
    print(f"  {k}: {'OK' if actual == MANIFEST[k] else 'MISMATCH'}")
    if actual != MANIFEST[k]:
        mismatch.append(k)
cand_ok = all(sha256_file(os.path.join(BASE, rel.replace("/", os.sep))) == recorded.lower()
              for rel, recorded in fm["files_sha256"].items())
print("  candidate 17 files:", "OK" if cand_ok else "MISMATCH")
MANIFEST["all_match"] = (not mismatch) and cand_ok and checkres["failed"] == 0

out = os.path.join(DATA, "final_blind_set_v3_manifest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(MANIFEST, f, ensure_ascii=False, indent=2)
print("manifest_sha256:", sha256_file(out))
print("all_match:", MANIFEST["all_match"])
print("saved:", out)
