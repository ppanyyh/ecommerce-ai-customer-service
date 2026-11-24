# -*- coding: utf-8 -*-
"""冻结 final candidate 检索代码（只读哈希 + 配置常量提取，不运行任何检索）。

生成 backend/data/final_candidate_freeze_manifest.json：
- 6 个文件的 SHA-256；
- Embedding 模型 / collection 名称与版本（读取 index_manifest.json）；
- RRF 参数 / epsilon / 通用词降权配置（从 hybrid_retriever_v2.py 源码常量提取）；
- 同义词扩展 / 风险意图映射（从 query_analyzer.py 源码常量提取）；
- 冻结时间。

约束：本脚本不导入 keyword_retriever / vector_retriever / hybrid_retriever，
不发起任何检索；冻结后至最终盲测运行前，这些哈希必须保持不变。
"""

import ast
import hashlib
import json
import os
import re
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

FILES = [
    "query_analyzer.py",
    "keyword_retriever_v3.py",
    "vector_retriever.py",
    "hybrid_retriever_v2.py",
    "data/knowledge_chunks.jsonl",
    "build_vector_index.py",
]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def module_constants(py_path):
    """用 ast 解析模块级常量赋值（不执行模块代码）。"""
    tree = ast.parse(open(py_path, encoding="utf-8").read())
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            try:
                consts[name] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass
    return consts


def main():
    hashes = {}
    for rel in FILES:
        p = os.path.join(BACKEND, rel)
        if not os.path.exists(p):
            raise SystemExit(f"缺少待冻结文件: {p}")
        hashes[rel] = sha256_of(p)

    with open(os.path.join(DATA, "index_manifest.json"), encoding="utf-8") as f:
        idx = json.load(f)

    v2_consts = module_constants(os.path.join(BACKEND, "hybrid_retriever_v2.py"))
    qa_consts = module_constants(os.path.join(BACKEND, "query_analyzer.py"))

    manifest = {
        "purpose": "最终盲测候选代码冻结：final blind set 运行前以下哈希必须保持不变；"
                   "冻结后本阶段不得修改检索代码与知识片段。",
        "frozen_at": datetime.now().isoformat(timespec="seconds"),
        "files_sha256": hashes,
        "embedding_model": idx.get("embedding_model"),
        "vector_dimension": idx.get("vector_dimension"),
        "collection": idx.get("collection"),
        "collection_data_version": idx.get("data_version"),
        "chunks_sha256_in_index_manifest": idx.get("chunks_sha256"),
        "rrf_params": {
            "RRF_K": v2_consts.get("RRF_K"),
            "KEYWORD_WEIGHT": v2_consts.get("KEYWORD_WEIGHT"),
            "VECTOR_WEIGHT": v2_consts.get("VECTOR_WEIGHT"),
            "KEYWORD_TOP_N": v2_consts.get("KEYWORD_TOP_N"),
            "VECTOR_TOP_N": v2_consts.get("VECTOR_TOP_N"),
        },
        "epsilon_params": {
            "EPSILON": v2_consts.get("EPSILON"),
            "ALIAS_BOOST": v2_consts.get("ALIAS_BOOST"),
        },
        "keyword_governance": {
            "GENERIC_WEAK_WORDS": sorted(v2_consts.get("GENERIC_WEAK_WORDS") or []),
            "WEAK_WORD_CAP": v2_consts.get("WEAK_WORD_CAP"),
            "HAN_CHAR_SCORE": v2_consts.get("HAN_CHAR_SCORE"),
            "HAN_OVERLAP_CAP": v2_consts.get("HAN_OVERLAP_CAP"),
        },
        "product_synonym_extension": {
            "source": "query_analyzer.EXTENDED_SYNONYMS（仅 V3 检索层，不修改 V2 knowledge_base.json）",
            "mapping": qa_consts.get("EXTENDED_SYNONYMS"),
        },
        "risk_intent_config": {
            "source": "query_analyzer.INTENT_RULE_MAP（通用意图 -> 必需规则片段）",
            "intent_rule_map": qa_consts.get("INTENT_RULE_MAP"),
        },
        "unit_test_evidence": "test_hybrid_v2_validation.py 20/20 通过；"
                              "四模式回归（validation_set_v1）8 项成功条件全部 PASS（2026-09-25）。",
    }

    out = os.path.join(DATA, "final_candidate_freeze_manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    for k, v in hashes.items():
        print(f"{k}  {v[:16]}...")
    print("frozen_at:", manifest["frozen_at"])


if __name__ == "__main__":
    main()
