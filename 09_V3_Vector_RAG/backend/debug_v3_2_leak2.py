# -*- coding: utf-8 -*-
"""验证当前代码下 leak/forbidden/order 用例的真实行为（不调用 DeepSeek）。"""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import v3_retrieval_adapter as adapter
import evaluate_v3_2_dev as ev

with open("data/v3_2_dev_cases.json", "r", encoding="utf-8") as f:
    cases = {c["case_id"]: c for c in json.load(f)["cases"]}

IDS = ["DV3-003", "DV3-017", "DV3-019", "DV3-027", "DV3-028", "DV3-082", "DV3-083",
       "DV3-094", "DV3-080", "DV3-084"]

for cid in IDS:
    c = cases[cid]
    r = adapter.retrieve(c["query"])
    if r.get("gate_scope"):
        ans = r.get("gate_user_answer", "")
    else:
        ans = adapter.compose_local_answer(c["query"], r) or ""
    leak = bool(ev.LEAK_RE.search(ans))
    forb = bool(ev._PROMISE_RE.search(ans))
    print("=" * 70)
    print(f"{cid} engine={r.get('retrieval_engine')} handoff={r.get('requires_handoff')} leak={leak} forb={forb}")
    print(f"  Q: {c['query']}")
    print(f"  ANS: {ans[:300]}")
    if leak:
        m = ev.LEAK_RE.search(ans)
        print(f"  LEAK_HIT: {m.group(0)}")
    if forb:
        m = ev._PROMISE_RE.search(ans)
        print(f"  FORBID_HIT: {m.group(0)}")
    if c.get("expected_route") == "v2_order_structured":
        print(f"  ctx: {(r.get('context') or '')[:150]}")
