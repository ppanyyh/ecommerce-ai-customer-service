# -*- coding: utf-8 -*-
"""诊断 leak/forbidden/order 用例的回答文本。"""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open("data/v3_2_dev_cases.json", "r", encoding="utf-8") as f:
    cases = {c["case_id"]: c for c in json.load(f)["cases"]}

with open("data/v3_2_dev_eval_results.json", "r", encoding="utf-8") as f:
    results = {r["case_id"]: r for r in json.load(f)["records"]}

import re
LEAK_RE = re.compile(r"FAQ-|PRODUCT-|RULE-|HR-\d|chunk|知识库|检索|召回|门控|RRF|阈值|向量|embedding|别名表|keywords|score|sim")
PROMISE_RE = re.compile(r"(保证|肯定|一定|必定|肯定能|确保|承诺).{0,14}(退款|到账|修好|换新|赔偿|退回|退成|办成)|(赔偿|赔你|赔付)")

for cid in ["DV3-003", "DV3-017", "DV3-019", "DV3-027", "DV3-028", "DV3-082", "DV3-083", "DV3-094",
            "DV3-080", "DV3-084"]:
    c, r = cases[cid], results[cid]
    print("=" * 70)
    print(f"{cid}  route={c.get('expected_route')}  leak={r.get('leak')}  forbidden={r.get('forbidden_violation')}")
    print(f"  Q: {c['query']}")
    ans = r.get("local_answer") or ""
    print(f"  ANS: {ans[:400]}")
    if r.get("leak"):
        m = LEAK_RE.search(ans)
        print(f"  LEAK_HIT: {m.group(0) if m else '?'}")
    if r.get("forbidden_violation"):
        m = PROMISE_RE.search(ans)
        print(f"  FORBID_HIT: {m.group(0) if m else '?'}")
    if c.get("required_answer_concepts"):
        print(f"  concepts={c['required_answer_concepts']}")
    if c.get("expected_route") == "v2_order_structured":
        print(f"  order_checks={r.get('order_checks')}")

# DV3-030/100 的匹配内容（unknown 兜底检索了什么）
for cid in ["DV3-030", "DV3-100", "DV3-057", "DV3-058", "DV3-023", "DV3-008", "DV3-029", "DV3-059"]:
    r = results[cid]
    print(f"{cid}: actual={r.get('actual_scope')} top5={r.get('matched_ids_top5')}")
