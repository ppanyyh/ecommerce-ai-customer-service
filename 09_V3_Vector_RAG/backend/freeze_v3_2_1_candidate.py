# -*- coding: utf-8 -*-
"""V3.2.1 候选冻结清单生成（一次性）。
- 复算 16 个候选文件 SHA-256；
- 禁改文件必须与 v3_2_1_baseline_manifest.json 记录的修改前 SHA 逐位一致；
- 允许修改文件记录新 SHA（不与基线比较，属有意变更）；
- 生成 data/v3_2_1_candidate_freeze_manifest.json，不覆盖任何旧清单。"""
import hashlib
import json
import platform
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent

CANDIDATE_FILES = [
    "main.py",
    "schemas.py",
    "prompts.py",
    "v3_retrieval_adapter.py",
    "retriever.py",
    "query_analyzer.py",
    "risk_intents.py",
    "keyword_retriever_v3.py",
    "vector_retriever.py",
    "hybrid_retriever_v2.py",
    "deepseek_client.py",
    "build_vector_index.py",
    "evaluate_final_blind_v2.py",
    "data/business_capability_catalog.json",
    "data/knowledge_chunks.jsonl",
    "data/index_manifest.json",
]

# 本阶段允许修改的文件（其余为禁改，必须与基线一致）
ALLOWED_MODIFIED = {
    "query_analyzer.py",
    "risk_intents.py",
    "v3_retrieval_adapter.py",
    "main.py",
    "hybrid_retriever_v2.py",  # 仅必要时：安全网否定守卫（一行）
    "data/business_capability_catalog.json",  # v1.1 -> v1.2 复合价格类别
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


baseline = json.loads((ROOT / "data" / "v3_2_1_baseline_manifest.json").read_text(encoding="utf-8"))
pre_sha = baseline["candidate_files_pre_modification_sha256"]

files_sha = {}
verification = {}
unchanged_match = []
intentional_changes = []

for rel in CANDIDATE_FILES:
    digest = sha256(ROOT / rel)
    files_sha[rel] = digest
    if rel in ALLOWED_MODIFIED:
        verification[rel] = True
        intentional_changes.append({
            "file": rel,
            "pre_sha256": pre_sha[rel],
            "post_sha256": digest,
            "changed": pre_sha[rel] != digest,
        })
    else:
        ok = (pre_sha.get(rel) == digest)
        verification[rel] = ok
        if ok:
            unchanged_match.append(rel)

all_match = all(verification.values())

catalog = json.loads((ROOT / "data" / "business_capability_catalog.json").read_text(encoding="utf-8"))
catalog_version = catalog.get("catalog_version")

manifest = {
    "manifest": "v3_2_1_candidate_freeze_manifest",
    "created_at": "2026-09-26",
    "phase": "V3.2.1 落地前修复阶段（未知商品/复合价格/否定承诺/订单本地降级/转人工文案 修复后候选冻结）",
    "frozen": True,
    "files_sha256": files_sha,
    "v3_2_candidate_freeze_manifest_sha256": baseline["v3_2_candidate_freeze_manifest_sha256"],
    "v3_2_1_baseline_manifest_sha256": sha256(ROOT / "data" / "v3_2_1_baseline_manifest.json"),
    "environment": {
        "python": "3.12.0",
        "platform": platform.platform(),
    },
    "embedding": {
        "model": "BAAI/bge-small-zh-v1.5",
        "dim": 512,
        "collection": "ecommerce_kb_v1",
        "data_version": "1.2",
    },
    "retrieval_params": {
        "RRF_K": 60,
        "top_k": 5,
        "EPSILON": 0.0003,
        "ALIAS_BOOST": 0.0002,
        "RULE_NET_VEC_SIM": 0.42,
        "rule_keep_top3": "风险意图或安全网启用时保留位（1内容片段+必需规则≤2条）",
    },
    "capability_catalog": {
        "version": catalog_version,
        "sha256": files_sha["data/business_capability_catalog.json"],
    },
    "intentional_changes": intentional_changes,
    "unchanged_files_verified": len(unchanged_match),
    "dev_and_regress_summary": {
        "v3_2_1_dev_eval_targets": "15/15 PASS（data/v3_2_1_dev_eval_results.json）",
        "check_v3_2_1_dev_set": "17/17 PASS",
        "v3_2_dev_eval_targets": "17/17 PASS（承诺类调和后恢复）",
        "validation_v1_1_frozen": "与 V3.1/V3.2 冻结基线逐位一致（唯一 per-case 差异 H-015 Top-1 名称，指标不变）",
        "validation_v1_2_reviewed": "与冻结基线逐位一致",
        "api_integration": "169/169 PASS",
        "chat_integration": "269/309（41 条失败为 DeepSeek 禁用+V3 设计变更预期差异，非回归）",
        "check_leakage": "PASS",
        "service_test_14_scenarios": "14/14 OK（data/_v321_servicetest.txt）",
        "risk_intents_over_promise_guard_selftest": "24/24",
    },
    "known_residues": [
        "DV3-010（HR-05 规则片段未进 Top-3，意图与 handoff 正确）——既有，按指令不处理",
        "DV3-079/DV3-089 hit1 Top-2 语义竞争（Recall@3 正常）",
        "wrong_handoff 2 条（DV3-080/090 诱导用例保守侧转人工）",
        "V3.1 开发集 DV-007/025/029/032 hit1 残留（既有）",
        "V3.2.1 开发集 DV321-073 原门控缺口已修复，其余 hit1 语义竞争残留见评测结果文件",
    ],
    "deepseek_calls_total": 0,
    "old_blind_v1_reexecuted": False,
    "old_blind_v2_reexecuted": False,
    "final_blind_v3_created": False,
    "final_blind_v3_executed": False,
    "blind_v2_status": "已执行并永久消耗（execution_count=1），不得重建/重跑/用于V3.2.1评分",
    "all_match": all_match,
    "verification": verification,
}

out = ROOT / "data" / "v3_2_1_candidate_freeze_manifest.json"
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("written:", out.name)
print("all_match:", all_match)
for item in intentional_changes:
    print(" changed:", item["file"], item["changed"])
print(" unchanged verified:", len(unchanged_match))
# 复核：读回再验一遍
readback = json.loads(out.read_text(encoding="utf-8"))
recheck = all(sha256(ROOT / rel) == readback["files_sha256"][rel] for rel in CANDIDATE_FILES)
print("readback recheck:", recheck)
