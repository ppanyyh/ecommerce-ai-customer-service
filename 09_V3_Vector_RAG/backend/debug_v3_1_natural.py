# -*- coding: utf-8 -*-
"""V3.1 调试2：dump 规则用例保留位介入前的自然融合序。"""
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
from hybrid_retriever_v2 import (hybrid_search_v2, governed_keyword_search, _fuse,
                                 _sort_with_epsilon, KEYWORD_TOP_N, VECTOR_TOP_N)
from query_analyzer import analyze
from vector_retriever import vector_search
from hybrid_retriever_v2 import RULE_NO_INTENT_PENALTY

CASES = ["H-014", "H-015", "H-016", "H-017", "H-018", "H-019", "H-021", "H-022"]

cases = {c["case_id"]: c for c in json.load(
    open(os.path.join(BACKEND_DIR, "data", "hybrid_holdout_eval_cases.json"), encoding="utf-8"))["cases"]}

lines = []
for cid in CASES:
    c = cases[cid]
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
    ordered = _sort_with_epsilon(fused, a["product_ids"], concern_scenario=a["has_concern_scenario"])
    lines.append(f"===== {cid} | {q}")
    lines.append(f"  required={a['required_rule_ids']} relevant={c['relevant_chunk_ids']}")
    lines.append("  NATURAL: " + " | ".join(f"{i+1}.{r['chunk_id']}({r['rrf_score']})" for i, r in enumerate(ordered[:6])))
    lines.append("  KW detail: " + " | ".join(f"{r['chunk_id']}({r['keyword_score']}):{r['matched_terms'][:3]}" for r in kw[:5]))
    lines.append("")

with open(os.path.join(BACKEND_DIR, "data", "v3_1_debug_dump2.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("ok")
