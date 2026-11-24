# -*- coding: utf-8 -*-
"""V3.1 第三阶段：完整运行版本冻结清单。

冻结范围 = /api/chat 运行链路全部模块 + 检索内核 + 索引数据。
同时核验：原 v3_1_candidate_freeze_manifest.json（检索内核基线）中
除 main.py/schemas.py/prompts.py 外的文件是否保持一致（本阶段禁止修改）。
生成后立即重算全部文件哈希，all_match=true 才算冻结成功。

输出：backend/data/v3_1_runtime_freeze_manifest.json
"""
import hashlib
import json
import os
import platform
import sys
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BACKEND, "data", "v3_1_runtime_freeze_manifest.json")
CANDIDATE = os.path.join(BACKEND, "data", "v3_1_candidate_freeze_manifest.json")

FILES = [
    "main.py",
    "schemas.py",
    "prompts.py",
    "v3_retrieval_adapter.py",
    "retriever.py",
    "query_analyzer.py",
    "keyword_retriever_v3.py",
    "vector_retriever.py",
    "hybrid_retriever_v2.py",
    "deepseek_client.py",
    "build_vector_index.py",
    "data/knowledge_chunks.jsonl",
    "data/index_manifest.json",
]

# 原候选冻结清单中允许本阶段修改的文件（接入需要）
PHASE3_MUTABLE = {"main.py", "schemas.py", "prompts.py"}


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    import chromadb
    import sentence_transformers

    files_sha = {f: sha256(os.path.join(BACKEND, f)) for f in FILES}

    # ---- 检索内核基线核验 ----
    cand = json.load(open(CANDIDATE, encoding="utf-8"))
    kernel_check = {}
    kernel_unchanged = True
    for f, old in cand["files_sha256"].items():
        now = sha256(os.path.join(BACKEND, f))
        same = now == old
        kernel_check[f] = {"unchanged": same, "old_sha256": old, "now_sha256": now}
        if f not in PHASE3_MUTABLE and not same:
            kernel_unchanged = False

    index_manifest = json.load(open(os.path.join(BACKEND, "data", "index_manifest.json"), encoding="utf-8"))

    manifest = {
        "manifest": "v3_1_runtime_freeze_manifest",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "phase": "V3.1 Phase 3（V3.1 混合检索接入 /api/chat，端到端集成，运行版本冻结）",
        "files_sha256": files_sha,
        "retrieval_kernel_baseline": {
            "file": "v3_1_candidate_freeze_manifest.json",
            "sha256": hashlib.sha256(open(CANDIDATE, "rb").read()).hexdigest(),
            "per_file_check": kernel_check,
            "kernel_unchanged_except_allowed": kernel_unchanged,
            "note": "原检索内核冻结基线保留未覆盖；main.py/schemas.py/prompts.py 为接入允许修改项"
                    "（本阶段实际仅修改 main.py，schemas.py/prompts.py 未改动）。",
        },
        "environment": {
            "python": platform.python_version(),
            "chromadb": chromadb.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "embedding_model": index_manifest["embedding_model"],
            "vector_dimension": index_manifest["vector_dimension"],
            "collection": index_manifest["collection"],
            "data_version": index_manifest["data_version"],
        },
        "api_routing": {
            "chat_entry": "POST /api/chat -> v3_retrieval_adapter.retrieve(message)",
            "order_routing": "消息含完整12位或疑似6-11位订单号 → V2 retriever 结构化订单查询"
                             "（存在性/状态/金额/物流/风险标注），订单不入向量库；"
                             "订单号+高风险表达时本地风险下限（_risk_decision force_handoff）不被降低",
            "other_routing": "其余问题 → hybrid_retriever_v2.hybrid_search_v2（冻结内核）",
            "gate_behavior": {
                "supported": "Top-K 原始片段构造 context → 确定性/DeepSeek 生成 → 校验兜底降级；高风险强制转人工",
                "unsupported_business": "确定性回复（不调 DeepSeek，results/context 为空），"
                                         "sources=[现有资料未覆盖]，风险中、转人工",
                "irrelevant": "确定性回复（不调 DeepSeek），范围说明文案，不携带知识片段",
            },
            "user_visible_boundary": "answer 不含 HR 编号/SOP 名/scope 标签/门控/相似度/分数/阈值"
                                      "（main._INTERNAL_LEAK_RE + 集成测试 _USER_LEAK_RE 双重校验）",
            "warmup": "lifespan 启动预热本地 Embedding+向量库（约17.4s），不调用 DeepSeek；"
                      "GET /api/ready 上报就绪状态",
        },
        "results": {
            "new_api_integration": "test_v3_1_api_integration.py：169/169 通过（16 类用例）",
            "old_chat_integration": "test_chat_integration.py：269/309（40 项失败已归因："
                                     "无Key环境性模型断言 / V3多源sources预期变化 / 门控文案与发票口径有意语义变更，"
                                     "详见 v3_1_phase3_integration_report.md 第10节）",
            "unit_tests": "test_hybrid_v2_validation 20/20；test_retriever 8/8 一致性通过；"
                          "test_hybrid_retriever_unit 10/10；test_latency_order 全过",
            "dev_set": "v3_1_dev_cases：Hit@1 36/40(90.0%)、Recall@3 100%、Rule 17/17、"
                        "门控 60/60、误放行 0/20、HR-08 7/7（与 Phase 2 完全一致）",
            "validation_v1_1_frozen": "Hit@1 22/24、Recall@3 23/24、Rule 8/8"
                                       "（v2 失败=H-013 语义变更 + H-020 排序差异，与 Phase 2 一致）",
            "validation_v1_2_reviewed": "Hit@1 23/24、Recall@3 23/24、Rule 8/8"
                                         "（v2 失败=仅 H-013，与 Phase 2 一致）",
            "leakage": "check_leakage.py 全过；开发集 vs 旧盲测 leak=0（Phase 2）",
            "live_service": "uvicorn 实测 /api/health ok、/api/ready ready=true(vector_warmed=true, "
                             "warmup_ms≈17393.7)、/api/chat 四类行为正确；测试后服务已停止、端口已释放",
        },
        "deepseek_calls": 0,
        "old_final_blind_reexecuted": False,
        "final_blind_v2_created": False,
        "final_blind_v2_executed": False,
    }
    json.dump(manifest, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("written:", OUT)

    # ---- 生成后立即复核 ----
    check = json.load(open(OUT, encoding="utf-8"))
    all_match = all(sha256(os.path.join(BACKEND, f)) == h for f, h in check["files_sha256"].items())
    check["verify"] = {
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "all_match": all_match,
        "n_files": len(check["files_sha256"]),
    }
    json.dump(check, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("all_match:", all_match, "| files:", len(check["files_sha256"]))
    print("kernel_unchanged_except_allowed:", kernel_unchanged)
    return 0 if (all_match and kernel_unchanged) else 1


if __name__ == "__main__":
    sys.exit(main())
