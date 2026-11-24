# -*- coding: utf-8 -*-
"""V3.2 候选冻结清单生成（阶段八）。生成后复算全部哈希，必须 all_match=true。
只读采集候选文件；不修改任何代码/知识库/目录。"""
import sys, io, json, hashlib, os, platform
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

FREEZE_FILES = [
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

missing = [f for f in FREEZE_FILES if not os.path.exists(f)]
if missing:
    print("MISSING FILES:", missing)
    sys.exit(1)

files_sha256 = {f: sha(f) for f in FREEZE_FILES}

# V3.1 runtime freeze manifest SHA 与 v3_2 baseline manifest SHA
v31_manifest_sha = sha("data/v3_1_runtime_freeze_manifest.json")
v32_baseline_sha = sha("data/v3_2_baseline_manifest.json")

# 运行环境
import chromadb
import sentence_transformers
import fastapi
import uvicorn
env = {
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "chromadb": getattr(chromadb, "__version__", "?"),
    "sentence_transformers": getattr(sentence_transformers, "__version__", "?"),
    "fastapi": getattr(fastapi, "__version__", "?"),
    "uvicorn": getattr(uvicorn, "__version__", "?"),
}

# 索引信息
im = json.load(open("data/index_manifest.json", encoding="utf-8"))
embedding_info = {
    "model": im.get("embedding_model") or "BAAI/bge-small-zh-v1.5",
    "dim": im.get("dim") or 512,
    "collection": im.get("collection") or im.get("collection_name") or "ecommerce_kb_v1",
    "data_version": im.get("data_version"),
}

# 检索与安全网参数
import hybrid_retriever_v2 as h2
params = {
    "RRF_K": h2.RRF_K,
    "double_weight": getattr(h2, "DOUBLE_WEIGHT", None) or [getattr(h2, "KW_WEIGHT", None), getattr(h2, "VEC_WEIGHT", None)],
    "top_k": getattr(h2, "TOP_K", getattr(h2, "DEFAULT_TOP_K", 5)),
    "EPSILON": h2.EPSILON,
    "ALIAS_BOOST": getattr(h2, "ALIAS_BOOST", None),
    "RULE_NET_VEC_SIM": h2.RULE_NET_VEC_SIM,
    "rule_keep_top3": "风险意图或安全网启用时保留位（1内容片段+必需规则≤2条）",
}

catalog = json.load(open("data/business_capability_catalog.json", encoding="utf-8"))

manifest = {
    "manifest": "v3_2_candidate_freeze_manifest",
    "created_at": "2026-09-26",
    "phase": "V3.2 第二阶段（标注批准落档、全量回归复核、候选版本冻结）",
    "frozen": True,
    "files_sha256": files_sha256,
    "v3_1_runtime_freeze_manifest_sha256": v31_manifest_sha,
    "v3_2_baseline_manifest_sha256": v32_baseline_sha,
    "environment": env,
    "embedding": embedding_info,
    "retrieval_params": params,
    "capability_catalog": {
        "version": catalog.get("catalog_version"),
        "sha256": files_sha256["data/business_capability_catalog.json"],
    },
    "rule_id_normalization": "risk_intents/INTENT_RULE_MAP 输出 RULE-HR-xx 带前缀格式；adapter._risk_floor 仅去除 'RULE-' 前缀（rid[5:]），不改变 HR 编号；retriever.RULES 与 knowledge_chunks(RULE-HR-xx/ref_id=HR-xx) 编号一致，8/8 映射核验通过",
    "dev_and_regress_summary": {
        "v3_2_dev_eval_targets": "17/17 PASS（详见 data/v3_2_dev_eval_results.json）",
        "risk_intents_selftest": "19/19",
        "evaluator_unit_tests": "52/52",
        "check_v3_2_dev_set": "16/16",
        "validation_v1_1_frozen": "见 phase2 报告第12节",
        "validation_v1_2_reviewed": "见 phase2 报告第12节",
        "v3_1_dev_eval": "见 phase2 报告第12节",
        "api_integration": "见 phase2 报告第12节",
        "chat_integration": "见 phase2 报告第12节（V2 时代基线的预期差异）",
        "latency_order": "见 phase2 报告第12节",
        "check_leakage": "PASS",
        "service_test_14_scenarios": "见 phase2 报告第13节",
    },
    "known_residues": [
        "DV3-010（HR-05 规则片段未进 Top-3，意图识别与 handoff 均正确）——开发集已知残留，按第二阶段指令不修改算法",
        "DV3-079/DV3-089 hit1 Top-2 语义竞争（Recall@3 正常）",
        "wrong_handoff 2 条（DV3-080/090 诱导用例保守侧转人工）",
        "detect_over_promise 无否定守卫（'我不要求你保证退款'类否定表达会保守侧误触发）——静态审核发现，非 P0，按指令只报告",
        "V3.1 开发集 DV-007/025/029/032 hit1 残留（既有）",
        "服务实测：未收录商品句式'你们的XX有XX功能吗'（行车记录仪）未被未知商品检测拦截，检索返回 P005 事实（功率10W）——答非所问但无编造无泄漏，属未知商品检测泛化缺口（开发集 B 层 7 条未收录用例全部正确拦截）",
        "服务实测：已知商品+未覆盖业务'二手回收价格'因含'价格'子串命中价格属性词条而放行，回答仅给售价事实+人工提示，未编造回收价",
        "DeepSeek 禁用环境既定行为：handoff 用例 answer 为通用繁忙文案（handoff 分支不组稿，一阶段设计）；有效订单号 answer 为通用降级文案（v2_order_structured 路径不走 compose_local_answer），路由/来源/风险字段均正确",
    ],
    "deepseek_calls_total": 0,
    "old_blind_v1_reexecuted": False,
    "old_blind_v2_reexecuted": False,
    "final_blind_v3_created": False,
    "final_blind_v3_executed": False,
    "blind_v2_status": "已执行并永久消耗（execution_count=1），不得重建/重跑/用于V3.2评分",
}

# ---- 生成后复算 ----
ok = all(sha(f) == s for f, s in files_sha256.items())
manifest["all_match"] = ok
manifest["verification"] = {f: (sha(f) == s) for f, s in files_sha256.items()}

with open("data/v3_2_candidate_freeze_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print("frozen files:", len(files_sha256), "all_match =", ok)
for f, s in files_sha256.items():
    print(" ", s[:12], f)
print("v3_1_manifest_sha =", v31_manifest_sha[:12])
print("v3_2_baseline_sha =", v32_baseline_sha[:12])
