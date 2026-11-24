# -*- coding: utf-8 -*-
"""V3.2.1 补充开发集评测器。

- 每条用例一次 retrieve（订单路由或混合检索），随后确定性分支或本地降级组稿；
- DeepSeek 隔离：调用前清除 API Key 并设置 FORCE_DEEPSEEK_FAILURE=1（全程 0 次调用）；
- 指标：未知商品误放行率、商品串答、售价/复合价格区分、over_promise 正例召回与
  否定误触发、高风险 handoff、订单事实准确率与串单、本地降级概念覆盖、
  内部信息泄漏、禁止承诺违规。
"""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

# DeepSeek 隔离（必须在 import main 之前）
os.environ["FORCE_DEEPSEEK_FAILURE"] = "1"
os.environ.pop("DEEPSEEK_API_KEY", None)

import main  # noqa: E402
import risk_intents  # noqa: E402
import retriever  # noqa: E402

CASES_PATH = os.path.join(BACKEND, "data", "v3_2_1_dev_cases.json")
OUT_PATH = os.path.join(BACKEND, "data", "v3_2_1_dev_eval_results.json")

d = json.load(open(CASES_PATH, encoding="utf-8"))
cases = d["cases"]

PRODUCT_NAMES = sorted({p["name"] for p in json.load(
    open(os.path.join(BACKEND, "knowledge_base.json"), encoding="utf-8"))["products"]})

records = []
for c in cases:
    t0 = time.perf_counter()
    r = main.v3_retrieval_adapter.retrieve(c["query"])
    retrieve_ms = (time.perf_counter() - t0) * 1000.0
    det = main._deterministic_reply(c["query"], r)
    if det is not None:
        answer = det.answer
        handoff = det.handoff_required
        risk = det.risk_level
        mode = "deterministic"
    else:
        resp = main._fallback_reply(r, c["query"])
        answer = resp.answer
        handoff = resp.handoff_required
        risk = resp.risk_level
        mode = "fallback"

    # 实际 scope
    gate_scope = r.get("gate_scope")
    if gate_scope:
        actual_scope = gate_scope
    elif r.get("retrieval_engine") == "v2_order_structured":
        actual_scope = "supported"
    else:
        actual_scope = r.get("v3_scope") or (
            "supported" if (r.get("matched") or r.get("requires_handoff")) else "unsupported_business")

    rec = {
        "case_id": c["case_id"], "section": c["section"], "query": c["query"],
        "expected_scope": c["expected_scope"], "actual_scope": actual_scope,
        "scope_ok": actual_scope == c["expected_scope"],
        "expected_handoff": c["expected_handoff"], "actual_handoff": handoff,
        "handoff_ok": handoff == c["expected_handoff"],
        "expected_risk_floor": c["expected_risk_floor"], "actual_risk": risk,
        "answer": answer, "mode": mode, "retrieve_ms": round(retrieve_ms, 2),
        "results_count": len(r.get("matched_ids") or []),
        "concept_checks": [{"concept": k, "matched": k in (answer or "")}
                           for k in c["required_answer_concepts"]],
        "concept_coverage": (
            sum(1 for k in c["required_answer_concepts"] if k in (answer or ""))
            / max(len(c["required_answer_concepts"]), 1))
        if c["required_answer_concepts"] else None,
        "forbidden_hits": [p for p in c["forbidden_answer_claims"]
                           if re.search(p, answer or "")],
        "fp_intent_checks": [],
    }
    # 期望不触发的意图（近似反例）：以最终 handoff 状态 + 检索意图复核
    for intent in c["expected_false_positive_intents"]:
        fired = intent in {x["intent"] for x in risk_intents.detect_risk_intents(c["query"])}
        rec["fp_intent_checks"].append({"intent": intent, "fired": fired})
    records.append(rec)

s = {}
sec = lambda name: [r for r in records if r["section"].startswith(name)]

# --- A 未知商品 ---
apos = [r for r in sec("A_unknown_product")]
s["unknown_fp_ids"] = [r["case_id"] for r in apos
                       if not r["scope_ok"] or r["actual_handoff"] is not True
                       or r["results_count"] != 0]
s["unknown_fp_rate"] = len(s["unknown_fp_ids"]) / max(len(apos), 1)
# 商品串答：未知商品正例 answer 不得出现任何已知商品名称
cross = []
for r in apos:
    hit_names = [n for n in PRODUCT_NAMES if n and n in (r["answer"] or "")]
    if hit_names:
        cross.append((r["case_id"], hit_names))
s["cross_product_leak"] = cross
# 已知商品对照必须 supported 且非空结果
akn = sec("A_known_control")
s["known_control_fail"] = [r["case_id"] for r in akn if not r["scope_ok"] or r["results_count"] == 0]
# 无关近似反例不得触发未知商品询问
airr = sec("A_irrelevant_probe")
s["irr_probe_fail"] = [r["case_id"] for r in airr
                       if any(x["fired"] for x in r["fp_intent_checks"])]

# --- B 价格 ---
bsale = sec("B_price_sale")
s["sale_price_fail"] = [r["case_id"] for r in bsale
                        if not r["scope_ok"] or (r["concept_coverage"] or 0) < 1.0]
bcomp = sec("B_price_composite_uncovered")
s["composite_price_fail"] = [r["case_id"] for r in bcomp
                             if not r["scope_ok"] or r["results_count"] != 0
                             or (r["concept_coverage"] or 0) < 1.0]

# --- C over_promise ---
cpos = sec("C_promise_positive")
s["promise_pos_recall_ids"] = [r["case_id"] for r in cpos
                               if not (r["actual_handoff"] is True and r["handoff_ok"])]
s["promise_pos_recall"] = 1 - len(s["promise_pos_recall_ids"]) / max(len(cpos), 1)
cneg = sec("C_promise_negation_probe")
s["promise_neg_fp_ids"] = [r["case_id"] for r in cneg
                           if r["actual_handoff"] is True
                           or any(x["fired"] for x in r["fp_intent_checks"])]
s["promise_neg_fp_rate"] = len(s["promise_neg_fp_ids"]) / max(len(cneg), 1)

# --- D 订单 ---
dall = sec("D_order")
s["order_fail"] = [r["case_id"] for r in dall if not r["handoff_ok"] or not r["scope_ok"]]
s["order_concept_fail"] = [r["case_id"] for r in dall
                           if r["concept_coverage"] is not None and r["concept_coverage"] < 1.0]
# 串单：订单用例 answer 不得出现其他订单号/其他订单商品名
order_cross = []
order_ids = set(retriever.ORDERS.keys())
name_by_oid = {oid: o["product_name"] for oid, o in retriever.ORDERS.items()}
for r in dall:
    m = re.findall(r"2026\d{8}", c_query := r["query"])
    expected_oids = {x for x in m if x in order_ids}
    for oid in order_ids - expected_oids:
        if oid in (r["answer"] or ""):
            order_cross.append((r["case_id"], "order_id", oid))
        other_name = name_by_oid[oid]
        if expected_oids and other_name != name_by_oid[next(iter(expected_oids))] \
                and other_name in (r["answer"] or ""):
            order_cross.append((r["case_id"], "product_name", other_name))
s["order_cross"] = order_cross

# --- E 转人工文案 ---
eh = sec("E_handoff_copy")
s["handoff_copy_fail"] = [r["case_id"] for r in eh
                          if r["actual_handoff"] is not True or (r["concept_coverage"] or 0) < 1.0]

# --- 全局 ---
s["handoff_fail_all"] = [r["case_id"] for r in records if not r["handoff_ok"]]
leak_re = main._INTERNAL_LEAK_RE
s["leak_ids"] = [(r["case_id"], leak_re.search(r["answer"]).group(0))
                 for r in records if r["answer"] and leak_re.search(r["answer"])]
_PROMISE_VIOLATION_RE = re.compile(
    r"(?<!无法)(?<!不能)(?:保证|承诺|一定|必定|肯定)[^。？！?!]{0,12}(?:退款|到账|赔付|赔偿|退回)"
    r"|(?:退款|赔偿|到账|退回)[^。？！?!]{0,12}\d+\s*(?:个?工作日|天|小时|分钟)内(?:退|到|赔)")
s["forbidden_ids"] = [r["case_id"] for r in records if r["forbidden_hits"]]
s["scope_fail_all"] = [r["case_id"] for r in records if not r["scope_ok"]]
concept_cases = [r for r in records if r["concept_coverage"] is not None]
s["fallback_concept_coverage"] = (
    sum(r["concept_coverage"] for r in concept_cases) / max(len(concept_cases), 1))
s["concept_coverage_fail_ids"] = [r["case_id"] for r in concept_cases if r["concept_coverage"] < 1.0]
lat = sorted(r["retrieve_ms"] for r in records)
s["latency_ms"] = {"p50": round(lat[len(lat) // 2], 2), "p95": round(lat[int(len(lat) * 0.95)], 2)}

# --- 目标核对（第九节） ---
targets = {
    "unknown_fp_rate_eq_0": s["unknown_fp_rate"] == 0,
    "cross_product_leak_eq_0": not s["cross_product_leak"],
    "known_control_all_pass": not s["known_control_fail"],
    "irr_probe_all_pass": not s["irr_probe_fail"],
    "sale_price_100": not s["sale_price_fail"],
    "composite_price_100": not s["composite_price_fail"],
    "promise_pos_recall_ge_95": s["promise_pos_recall"] >= 0.95,
    "promise_neg_fp_eq_0": s["promise_neg_fp_rate"] == 0,
    "high_risk_handoff_100": not s["handoff_fail_all"],
    "order_all_pass": not s["order_fail"] and not s["order_concept_fail"],
    "order_cross_eq_0": not s["order_cross"],
    "concept_coverage_ge_95": s["fallback_concept_coverage"] >= 0.95,
    "leak_eq_0": not s["leak_ids"],
    "forbidden_eq_0": not s["forbidden_ids"],
    "scope_all_pass": not s["scope_fail_all"],
}
s["targets"] = targets
s["targets_passed"] = "%d/%d" % (sum(1 for v in targets.values() if v), len(targets))

out = {"summary": s, "records": records}
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(json.dumps({k: v for k, v in s.items()
                  if k not in ("order_cross", "cross_product_leak", "leak_ids")},
                 ensure_ascii=False, indent=1)[:2600])
print("written:", OUT_PATH)
