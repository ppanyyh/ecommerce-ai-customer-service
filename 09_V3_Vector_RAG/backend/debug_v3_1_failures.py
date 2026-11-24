# -*- coding: utf-8 -*-
"""V3.1 调试：dump validation 失败用例的分析与检索链路（只读诊断，不改任何资产）。"""
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
from hybrid_retriever_v2 import hybrid_search_v2, governed_keyword_search, _fuse
from query_analyzer import analyze
from vector_retriever import vector_search

CASES = [
    "H-006", "H-007", "H-008", "H-009", "H-012",
    "H-013", "H-020", "H-021", "H-022", "H-014", "H-018",
]

with open(os.path.join(BACKEND_DIR, "data", "hybrid_holdout_eval_cases.json"), encoding="utf-8") as f:
    cases = {c["case_id"]: c for c in json.load(f)["cases"]}

lines = []
for cid in CASES:
    c = cases[cid]
    q = c["query"]
    a = analyze(q)
    lines.append(f"===== {cid} | {q}")
    lines.append(f"  scope={a['scope']} intents={a['intents']} required={a['required_rule_ids']} "
                 f"sup={a['supported_intents']} uncov={a['uncovered_intents']} oos={a['out_of_scope_topics']} "
                 f"concern={a['has_concern_scenario']} entity={a['product_ids']} aliases={a['product_aliases']} "
                 f"rewrites={a['rewrites']}")
    kw = governed_keyword_search(q, top_k=10)
    vec = vector_search(q + (" " + " ".join(a["rewrites"]) if a["rewrites"] else ""), top_k=10)
    lines.append("  KW : " + " | ".join(f"{r['chunk_id']}({r['keyword_score']})" for r in kw[:8]))
    lines.append("  VEC: " + " | ".join(f"{r['chunk_id']}({r['similarity']:.3f})" for r in vec[:8]))
    out = hybrid_search_v2(q, top_k=5)
    if out["supported"]:
        lines.append("  FIN: " + " | ".join(
            f"{r['final_rank']}.{r['chunk_id']}(rrf={r['rrf_score']})" for r in out["results"]))
        lines.append(f"  reserved={out['rule_reserved']} missing={out['rule_candidate_missing']}")
    else:
        lines.append(f"  GATED: {out['reason']}")
    lines.append("")

report = "\n".join(lines)
with open(os.path.join(BACKEND_DIR, "data", "v3_1_debug_dump.txt"), "w", encoding="utf-8") as f:
    f.write(report)
print("written v3_1_debug_dump.txt")
