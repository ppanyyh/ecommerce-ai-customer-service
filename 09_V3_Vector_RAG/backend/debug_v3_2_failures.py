# -*- coding: utf-8 -*-
"""V3.2 首轮评测失败用例诊断：一次性输出 analyze 细节，不调用 DeepSeek。"""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from query_analyzer import analyze
from risk_intents import detect_risk_intents

with open("data/v3_2_dev_cases.json", "r", encoding="utf-8") as f:
    cases = json.load(f)["cases"]
by_id = {c["case_id"]: c for c in cases}

SCOPE_FP = ["DV3-007", "DV3-008", "DV3-015", "DV3-023", "DV3-029", "DV3-050",
            "DV3-057", "DV3-058", "DV3-059", "DV3-030", "DV3-100"]
INTENT_MISS = ["DV3-004", "DV3-010", "DV3-026", "DV3-028"]

for cid in SCOPE_FP:
    c = by_id[cid]
    q = c["query"]
    a = analyze(q)
    print("=" * 70)
    print(f"{cid}  expected_scope={c.get('expected_scope')}  expected_route={c.get('expected_route')}")
    print(f"  Q: {q}")
    print(f"  got: scope={a['scope']} gate_reason={a['gate_reason']}")
    print(f"  pids={a.get('product_ids')} exact={a.get('exact_product_ids')}")
    print(f"  supported_intents={a.get('supported_intents')}")
    print(f"  uncovered_intents={a.get('uncovered_intents')}")
    print(f"  out_of_scope={a.get('out_of_scope_topics')}")
    print(f"  covered_attrs={a.get('covered_attributes')} kw={a.get('covered_attribute_keywords')}")
    print(f"  commerce={a.get('has_commerce_signal')} generic_quality={a.get('has_generic_quality_question')} concern={a.get('has_concern_scenario')}")
    print(f"  reasons={a.get('reasons')}")
    print(f"  note={c.get('note', '')[:80]}")

print()
print("#" * 70)
print("RISK INTENT MISS")
for cid in INTENT_MISS:
    c = by_id[cid]
    q = c["query"]
    hits = detect_risk_intents(q)
    a = analyze(q)
    print("=" * 70)
    print(f"{cid}  expected_intent={c.get('expected_risk_intent') or c.get('expected_intents')}")
    print(f"  Q: {q}")
    print(f"  detect_risk_intents={hits}")
    print(f"  analyze.intents={a.get('intents')}")
    print(f"  note={c.get('note', '')[:100]}")
