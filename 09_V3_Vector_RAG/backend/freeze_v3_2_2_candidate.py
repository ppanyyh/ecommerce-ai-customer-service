# -*- coding: utf-8 -*-
"""V3.2.2 候选冻结清单生成（一次性，不覆盖任何旧清单）。
- 冻结原 16 个候选文件 + 新增 risk_levels.py（共 17 个）；
- 记录 V3.2.1 冻结清单比对（修改前后 SHA）；
- all_match 必须为 true。"""
import hashlib
import json
import platform
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent

FILES = [
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
    "risk_levels.py",  # V3.2.2 新增
]

# V3.2.1 → V3.2.2 允许修改的文件（其余必须与 V3.2.1 冻结值一致）
ALLOWED_MODIFIED = {
    "main.py",
    "v3_retrieval_adapter.py",
    "risk_intents.py",
    "risk_levels.py",  # 新增
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


prev = json.loads((ROOT / "data" / "v3_2_1_candidate_freeze_manifest.json").read_text(encoding="utf-8"))
prev_sha = prev["files_sha256"]

files_sha, verification = {}, {}
intentional = []
for rel in FILES:
    digest = sha256(ROOT / rel)
    files_sha[rel] = digest
    if rel in ALLOWED_MODIFIED:
        verification[rel] = True
        intentional.append({
            "file": rel,
            "pre_sha256": prev_sha.get(rel, "(new in V3.2.2)"),
            "post_sha256": digest,
            "changed": prev_sha.get(rel) != digest,
        })
    else:
        verification[rel] = (prev_sha.get(rel) == digest)

all_match = all(verification.values())

manifest = {
    "manifest": "v3_2_2_candidate_freeze_manifest",
    "created_at": "2026-09-26",
    "phase": "V3.2.2 最终盲测前 P0 修复（风险等级排序统一 + 版本标识更新 + HR-07 规则等级如实传播）",
    "frozen": True,
    "files_sha256": files_sha,
    "v3_2_1_candidate_freeze_manifest_sha256": sha256(ROOT / "data" / "v3_2_1_candidate_freeze_manifest.json"),
    "v3_2_2_baseline_source": "v3_2_1_candidate_freeze_manifest.json（16 文件）+ risk_levels.py（新增）",
    "environment": {"python": "3.12.0", "platform": platform.platform()},
    "embedding": {
        "model": "BAAI/bge-small-zh-v1.5", "dim": 512,
        "collection": "ecommerce_kb_v1", "data_version": "1.2",
    },
    "retrieval_params": {
        "RRF_K": 60, "top_k": 5, "EPSILON": 0.0003, "ALIAS_BOOST": 0.0002,
        "RULE_NET_VEC_SIM": 0.42,
        "note": "本阶段禁止调整，未修改",
    },
    "official_risk_levels": {
        "HR-01": "高", "HR-02": "高", "HR-03": "中", "HR-04": "中",
        "HR-05": "高", "HR-06": "高", "HR-07": "高", "HR-08": "高",
        "source": "knowledge_chunks.jsonl 原始规则 / knowledge_base.json retriever.RULES，未降低任何等级",
        "unified_definition": "risk_levels.py RISK_SCORE（低=0 中=1 高=2），main.py 与 v3_retrieval_adapter.py 统一调用",
    },
    "intentional_changes": intentional,
    "dev_and_regress_summary": {
        "risk_levels_unit": "43/43 PASS（test_v3_2_2_risk_levels.py，全新问题）",
        "risk_intents_selftest": "PASS（over_promise guard 24/24）",
        "check_v3_2_dev": "16/16",
        "check_v3_2_1_dev": "17/17",
        "v3_2_1_dev_eval": "15/15 目标达标；risk floor 符合率 80/80=100%；HR-07 正例 12/12 全高；否定反例 12/12 不触发；handoff 100%",
        "v3_2_dev_eval": "17/17 目标达标",
        "v3_1_dev_eval": "与既有基线一致（hit1 34/40，无新增回归）",
        "validation_v1_1_frozen": "hybrid Hit@1=22/24 MRR=0.9375 Rule 8/8，与冻结基线一致（H-013 既有）",
        "validation_v1_2_reviewed": "hybrid Hit@1=23/24 MRR=0.9583 Rule 8/8，与冻结基线一致",
        "api_integration": "169/169 PASS（rc=0）",
        "chat_integration": "268/309，失败 41 条与 V3.2.1 逐位一致（DeepSeek 禁用+V3 设计变更预期差异，零新增回归；V3.2.1 报告中 269 为笔误）",
        "order_tests": "test_retriever 订单 TC 全过 + v32_dev 订单 5/5 + v321_dev 订单 10/10",
        "local_fallback": "v32_dev fallback 概念覆盖 100% + v321_dev 97.62%",
        "leakage": "check_leakage 全过",
        "latency_order": "9/9",
        "service_test": "11/11 OK（data/_v322_servicetest.txt）；health version=3.2.2 mode=hybrid_rag_with_structured_orders；ready 正常",
    },
    "annotation_revision_disclosure": [
        "v3_2_1_dev_cases.json E 类 DV321-073（HR-03）/DV321-074（HR-04）expected_risk_floor 由'高'修正为'中'："
        "原生成器对 E 类一刀切标'高'，与指令二的正式规则等级映射（HR-03/04=中）直接冲突，属标注错误纠正而非放宽；"
        "HR-07 正例 12 条标注'高'未动（修复后 12/12 实际为高）；生成器 build_v3_2_1_dev_cases.py 已同步按 risk_levels.RULE_RISK_LEVELS 取值",
    ],
    "known_residues": [
        "chat_integration 41 条失败（与 V3.2.1 相同集合）：DeepSeek 禁用 + V2 时代断言的预期差异",
        "本地组稿 supported 回答复用 FAQ 原句文本（如'符合示例售后规则'），个别语句拼接略显生硬（既有组稿行为，非本轮引入）",
        "极少数物流表述（如'卡了六天没有任何更新'）会额外召回 HR-08 安全网证据，风险保守侧升为高（风险不得降低原则下的如实传播，V3.2.1 开发集/服务实测 HR-04 句型无回归）",
        "V3.1 开发集 DV-007/025/029/032 hit1、V3.2 DV3-010/079/089/080/090 等既有残留不变",
    ],
    "deepseek_calls_total": 0,
    "old_blind_v1_reexecuted": False,
    "old_blind_v2_reexecuted": False,
    "final_blind_v3_created": False,
    "final_blind_v3_executed": False,
    "all_match": all_match,
    "verification": verification,
}

out = ROOT / "data" / "v3_2_2_candidate_freeze_manifest.json"
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("written:", out.name)
print("all_match:", all_match)
for it in intentional:
    print(" changed:", it["file"], it["changed"])
print(" unchanged verified:", sum(1 for k, v in verification.items() if k not in ALLOWED_MODIFIED and v))
readback = json.loads(out.read_text(encoding="utf-8"))
print("readback recheck:", all(sha256(ROOT / rel) == readback["files_sha256"][rel] for rel in FILES))
