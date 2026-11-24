# -*- coding: utf-8 -*-
"""V3.1 调试3：开发集规则用例自然序 + DV-018/046 双路明细。"""
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
from hybrid_retriever_v2 import (governed_keyword_search, _fuse, _sort_with_epsilon,
                                 KEYWORD_TOP_N, VECTOR_TOP_N, RULE_NO_INTENT_PENALTY)
from query_analyzer import analyze
from vector_retriever import vector_search

RULE_CASES = ["DV-022", "DV-024", "DV-025", "DV-026", "DV-029", "DV-032"]
OTHER = ["DV-018", "DV-046"]

dev = {c["case_id"]: c for c in json.load(
    open(os.path.join(BACKEND_DIR, "data", "v3_1_dev_cases.json"), encoding="utf-8"))["cases"]}

lines = []
for cid in RULE_CASES + OTHER:
    c = dev[cid]
    q = c["query"]
    a = analyze(q)
    vec_query = q + (" " + " ".join(a["rewrites"]) if a["rewrites"] else "")
    kw = governed_keyword_search(q, top_k=KEYWORD_TOP_N)
    vec = vector_search(vec_query, top_k=VECTOR_TOP_N)
    fused = _fuse(kw, vec)
    if not a["required_rule_ids"]:
        for r in fused:
            if r["doc_type"] == "rule":
                r["rrf_score"] = round(max(r["rrf_score"] - RULE_NO_INTENT_PENALTY, 0.0), 6)
    if a["product_aliases"]:
        for r in fused:
            if r["doc_type"] == "product" and any(pid in r["chunk_id"] for pid in a["product_ids"]):
                if not r.get("id_boost"):
                    r["rrf_score"] = round(r["rrf_score"] + 0.0002, 6)
    ordered = _sort_with_epsilon(fused, a["product_ids"],
                                 concern_scenario=a["has_concern_scenario"])
    lines.append(f"===== {cid} | {q}")
    lines.append(f"  required={a['required_rule_ids']} relevant={c['relevant_chunk_ids']} "
                 f"sup={a['supported_intents']} concern={a['has_concern_scenario']} entity={a['product_ids']}")
    lines.append("  NATURAL: " + " | ".join(
        f"{i+1}.{r['chunk_id']}({r['rrf_score']},expl={r.get('explicit_evidence')})"
        for i, r in enumerate(ordered[:6])))
    lines.append("  KW: " + " | ".join(f"{r['chunk_id']}({r['keyword_score']},expl={r['explicit_evidence']}):{r['matched_terms'][:3]}" for r in kw[:5]))
    lines.append("  VEC: " + " | ".join(f"{r['chunk_id']}({r['similarity']:.3f})" for r in vec[:6]))
    lines.append("")

with open(os.path.join(BACKEND_DIR, "data", "v3_1_debug_dump3.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("ok")
