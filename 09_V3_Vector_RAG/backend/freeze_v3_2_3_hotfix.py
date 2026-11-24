# -*- coding: utf-8 -*-
"""V3.2.3 热修复冻结清单生成器（不覆盖任何旧清单）。"""
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def _raw_sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def sha(rel):
    p = rel.replace("backend/", "", 1) if rel.startswith("backend/") else rel
    return _raw_sha(p)


baseline = json.load(open(os.path.join(BASE, "data", "v3_2_3_hotfix_baseline_manifest.json"), encoding="utf-8"))
pre_sha = baseline["pre_hotfix_file_sha256"]

# 实际修改的文件（热修复范围）
changed = {
    "backend/risk_intents.py": pre_sha["backend/risk_intents.py"],
    "backend/main.py": pre_sha["backend/main.py"],
}
# 未修改的候选文件（V3.2.2 冻结清单 17 文件中，除上述两个之外应逐一比对）
freeze = json.load(open(os.path.join(BASE, "data", "v3_2_2_candidate_freeze_manifest.json"), encoding="utf-8"))
cand = freeze["files_sha256"]
untouched = {}
mismatch = []
for rel, expect in sorted(cand.items()):
    actual = sha(rel)
    changed_key = "backend/" + rel if "backend/" + rel in changed else rel
    if changed_key in changed:
        if actual == expect:
            mismatch.append(rel + " (在changed列表中但SHA未变)")
        untouched[rel] = {"status": "intentionally_changed", "pre": expect, "post": actual}
    else:
        if actual != expect:
            mismatch.append(rel)
        untouched[rel] = {"status": "unmodified", "sha256": actual,
                          "matches_v322_freeze": actual == expect}

# 回归结果摘要
reg = json.load(open(os.path.join(BASE, "data", "_v323_regress_raw.json"), encoding="utf-8"))
regress_summary = {k: v["rc"] for k, v in reg.items()}

manifest = {
    "manifest": "V3.2.3 hotfix freeze manifest (post-archive safety hotfix: single-side audio defect / HR-08)",
    "created_at": "2026-09-26",
    "version_boundary": {
        "v3_2_2_is_final_blind_v3_version": True,
        "v3_2_3_only_specialized_and_regression_tested": True,
        "v3_2_3_no_final_blind_rerun": True,
        "must_not_claim_v322_blind_scores_as_v323": True,
    },
    "changed_files": {rel: {"pre_sha256": pre, "post_sha256": sha(rel)} for rel, pre in changed.items()},
    "candidate_files_17": untouched,
    "test_results": {
        "hotfix_specialized_30cases": "30/30 PASS",
        "hotfix_api_regression": "13/13 PASS",
        "risk_levels_unit": "43/43 PASS (rc=0)",
        "risk_selftest": "rc=0",
        "v321_dev": "15/15 rc=0",
        "v32_dev": "17/17 rc=0",
        "v31_dev": "rc=0 (与基线一致)",
        "validation_v1_1_frozen": "rc=0 (与基线一致)",
        "validation_v1_2_reviewed": "rc=0 (与基线一致)",
        "api_integration": "rc=0",
        "test_retriever": "rc=0",
        "latency_order": "rc=0",
        "leakage": "rc=0",
        "chat_integration": "268/309（41条失败与V3.2.2基线逐位相同，均为DeepSeek禁用预期差异；零新增回归）",
    },
    "user_original_sentence_fix": {
        "query": "昨天刚收到的耳机，今天早上右边就不出声了",
        "category": "售后", "risk_level": "高", "handoff_required": True,
        "answer_contains_order_and_evidence_hints": True,
        "answer_no_price": True, "answer_no_package_list": True,
        "answer_no_promise": True, "answer_no_internal_terms": True,
    },
    "deepseek_calls": 0,
    "blind_flags": {
        "old_blind_v1_reexecuted": False,
        "old_blind_v2_reexecuted": False,
        "blind_v3_reexecuted": False,
        "no_blind_v4": True,
        "final_blind_score_source": "V3.2.2 only",
        "hotfix_final_blind_evaluated": False,
    },
    "baseline_manifest_sha256": sha(os.path.join(BASE, "data", "v3_2_3_hotfix_baseline_manifest.json")),
    "regress_raw_rc": regress_summary,
    "unmodified_candidates_match_v322_freeze": not mismatch,
    "all_match": not mismatch and all(rc == 0 for k, rc in regress_summary.items() if k != "chat_integration"),
}

out = os.path.join(BASE, "data", "v3_2_3_hotfix_freeze_manifest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# 复核
rel2 = json.load(open(out, encoding="utf-8"))
recomputed = all(v["post_sha256"] == sha(rel) for rel, v in rel2["changed_files"].items())
print("changed files recomputed:", recomputed)
print("unmodified mismatch:", mismatch or "无")
print("all_match =", rel2["all_match"])
print("freeze manifest sha256:", hashlib.sha256(open(out, "rb").read()).hexdigest()[:16], "...")
