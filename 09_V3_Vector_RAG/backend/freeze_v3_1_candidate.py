# -*- coding: utf-8 -*-
"""V3.1 第二阶段：候选版本冻结清单生成。

冻结范围 = 用户指定的候选代码 + 索引数据 + 启动/校验模块。
生成后立即重新计算全部文件哈希，all_match=true 才算冻结成功。
本脚本只读源文件、只写清单文件，不修改任何候选文件。

输出：backend/data/v3_1_candidate_freeze_manifest.json
"""
import hashlib
import json
import os
import platform
import sys
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
OUT = os.path.join(BACKEND, "data", "v3_1_candidate_freeze_manifest.json")

FILES = [
    "query_analyzer.py",
    "keyword_retriever_v3.py",
    "vector_retriever.py",
    "hybrid_retriever_v2.py",
    "build_vector_index.py",
    "main.py",
    "schemas.py",
    "prompts.py",
    "data/knowledge_chunks.jsonl",
    "data/index_manifest.json",
]


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    import chromadb
    import sentence_transformers

    files_sha = {f: sha256(os.path.join(BACKEND, f)) for f in FILES}
    # 评测资产哈希（记录用，不作为冻结候选；冻结后保持不可修改）
    eval_assets = {
        "data/hybrid_holdout_eval_cases_v1_1_frozen.json": sha256(
            os.path.join(BACKEND, "data", "hybrid_holdout_eval_cases_v1_1_frozen.json")),
        "data/hybrid_holdout_eval_cases_v1_2_reviewed.json": sha256(
            os.path.join(BACKEND, "data", "hybrid_holdout_eval_cases_v1_2_reviewed.json")),
        "data/v3_1_dev_cases.json": sha256(os.path.join(BACKEND, "data", "v3_1_dev_cases.json")),
        "data/final_blind_set_v1.json": sha256(os.path.join(BACKEND, "data", "final_blind_set_v1.json")),
    }
    index_manifest = json.load(open(os.path.join(BACKEND, "data", "index_manifest.json"), encoding="utf-8"))

    manifest = {
        "manifest": "v3_1_candidate_freeze_manifest",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "phase": "V3.1 Phase 2（标注口径定稿、回归复核、候选冻结）",
        "frozen_after": ("开发集/双口径 validation/单元/延迟/泄漏全部测试达标后冻结；"
                          "冻结后不得修改候选代码、knowledge_chunks、阈值，不得依据旧盲测结果增补关键词。"),
        "files_sha256": files_sha,
        "eval_assets_sha256_reference": eval_assets,
        "environment": {
            "python": platform.python_version(),
            "chromadb": chromadb.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "embedding_model": index_manifest["embedding_model"],
            "vector_dimension": index_manifest["vector_dimension"],
            "collection": index_manifest["collection"],
            "data_version": index_manifest["data_version"],
            "index_built_at": index_manifest["built_at"],
            "chunks_sha256_in_index": index_manifest["chunks_sha256"],
        },
        "retrieval_params": {
            "RRF_K": 60, "KEYWORD_WEIGHT": 1.0, "VECTOR_WEIGHT": 1.0,
            "KEYWORD_TOP_N": 10, "VECTOR_TOP_N": 10,
            "EPSILON": 0.0003, "ALIAS_BOOST": 0.0002,
            "KEYWORD_GATE_THRESHOLD": 3.0, "VECTOR_GATE_THRESHOLD": 0.40,
            "note_gate_config": "无独立门控配置文件；全部阈值/参数为 hybrid_retriever_v2.py 与 query_analyzer.py 模块常量，随文件一并冻结。",
        },
        "risk_rule_mapping": {
            "version": "V2 kb 口径（8 条 HR 规则，与 knowledge_base.json 一致，未新增）",
            "map": {
                "complaint_compensation": "RULE-HR-01", "amount_dispute": "RULE-HR-02",
                "refund_urge": "RULE-HR-03", "logistics_stall": "RULE-HR-04",
                "other_order": "RULE-HR-05", "privacy_info": "RULE-HR-06",
                "over_promise": "RULE-HR-07", "post_purchase_defect": "RULE-HR-08",
            },
        },
        "results": {
            "dev_set": {
                "file": "v3_1_dev_cases.json", "n": 60,
                "nature": "开发集（允许调试迭代，非盲测集）；结果仅证明拟合通过",
                "leakage_vs_old_blind": "check_v3_1_dev_set.py：exact=0, near=0，通过",
                "hit1": "36/40 (90.0%)", "recall3": "40/40 (100%)", "mrr": 0.95,
                "rule_recall3": "17/17 (100%)", "supported_accuracy": "60/60 (100%)",
                "scope_accuracy": "60/60 (100%)", "unanswerable_false_pass": "0/20 (0%)",
                "defect_hr08_top3": "7/7 (100%)",
                "dv046_scope": "unsupported_business（正确）",
            },
            "validation_v1_1_frozen": {
                "file": "hybrid_holdout_eval_cases_v1_1_frozen.json",
                "hit1": "22/24 (91.7%)", "recall3": "23/24 (95.8%)", "mrr": 0.9375,
                "rule_recall3": "8/8 (100%)",
                "deviations": [
                    "H-013：发票按 V3.1 业务口径判 unsupported_business（results=[]），旧检索兼容指标下计失败——有意业务语义变更，非检索缺陷",
                    "H-020：hit1 miss（top3=[FAQ-013,FAQ-015,FAQ-017] 全部为 v1.2 相关集；v1.1 口径 Top-1 为 FAQ-013 不计入）——部分相关性排序差异，v1.2 已批准保留",
                ],
                "results_file": "hybrid_v2_validation_results_v1_1_frozen.json",
            },
            "validation_v1_2_reviewed": {
                "file": "hybrid_holdout_eval_cases_v1_2_reviewed.json",
                "evaluation_status": "annotation-corrected exploratory evaluation（不参与最终盲测成绩）",
                "hit1": "23/24 (95.8%)", "recall3": "23/24 (95.8%)", "mrr": 0.9583,
                "rule_recall3": "8/8 (100%)",
                "deviations": [
                    "H-013：同上，发票业务语义变更（唯一失败；除 H-013 外 23/24 全通过）",
                ],
                "results_file": "hybrid_v2_validation_results_v1_2_reviewed.json",
            },
            "deepseek_calls": 0,
            "old_final_blind_reexecuted": False,
        },
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
    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())
