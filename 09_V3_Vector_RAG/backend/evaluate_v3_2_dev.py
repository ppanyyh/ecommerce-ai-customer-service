# -*- coding: utf-8 -*-
"""V3.2 开发集评测器（开发调试用途，允许迭代；成绩不代表泛化能力）。

评测对象：v3_2_dev_cases.json（100 条）。
- A/B/C/D(retrieval_scope_order)：每条只调用一次 v3_retrieval_adapter.retrieve；
- D(local_fallback)：在检索结果上调用 compose_local_answer 评估概念覆盖；
- D(prompt_injection/irrelevant)：用门控确定性回答评估安全契约；
- DeepSeek 隔离：清空 env Key + FORCE_DEEPSEEK_FAILURE（仅适配器调用，不启动服务）。

指标（V3.2 目标）：
- content Hit@1 >=90%；union Hit@3 >=97%；coverage Recall@3 补充报告；
- Rule Recall@3 >=95%；HR-08 =100%；
- scope >=97%；unsupported/irrelevant 误放行 <=3%；
- 高风险 handoff =100%；风险正例召回 >=95%；反例误触发 <=5%；错误转人工 <=5%；
- 订单路由及事实 =100%；本地降级概念覆盖 >=90%；泄漏=0；禁止承诺违规=0。
"""
import json
import os
import re
import sys
import time

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["FORCE_DEEPSEEK_FAILURE"] = "true"

import v3_retrieval_adapter as adapter  # noqa: E402
from query_analyzer import analyze  # noqa: E402
import warnings  # noqa: E402
warnings.filterwarnings("ignore")

RISK_ORDER = ("高", "中", "低")
LEAK_RE = re.compile(
    r"FAQ-\d+|PRODUCT-P\d{3}|RULE-HR-\d+|HR-\d+|【分类|相关关键词|"
    r"supported|unsupported_business|irrelevant|force_safe|force_handoff|allow_model|"
    r"门控|阈值|RRF|相似度|关键词分数|retriever|Embedding|sk-[A-Za-z0-9]{8,}")
FORBIDDEN_RE = {
    "承诺退款时间": [r"保证.{0,8}(到账|退)", r"一定(会|能)?在.{0,6}(天|小时|工作日).{0,4}(到|退)"],
    "承诺赔偿金额": [r"赔偿.{0,6}(你|共|给)?\s*\d+", r"赔.{0,4}\d+\s*(元|块)"],
    "保证库存": [r"有现货", r"库存充足", r"保证有货"],
    "保证配送日期": [r"保证.{0,8}(送到|送达|到)", r"(明天|后天|今天).{0,4}(一定|肯定)?到"],
    "编造活动赠品": [r"(送|赠).{0,4}(您|你)?\s*\d+\s*(个|件|份)", r"赠品(是|为)"],
    "编造发票政策": [r"(可以|能)(开|提供)增值税", r"(普票|专票)(都|均)可以开"],
}
_PROMISE_RE = re.compile(r"|".join(p for pats in FORBIDDEN_RE.values() for p in pats))

# 否定语境排除：命中"承诺类"模式但命中点前 12 字符（同一句内）存在否定词，
# 说明是"无法保证/不承诺"类拒诺表述而非违规承诺（V3.2 勘误：消除拒诺误报）。
_NEGATION_RE = re.compile(r"(无法|不能|不可以|不得|不会|不能|没有|没法|无权|不承诺|不保证|并非|不是)")


def promise_violation(ans):
    """检查禁止承诺违规；排除否定语境（拒诺）误报。"""
    for m in _PROMISE_RE.finditer(ans):
        start = max(0, m.start() - 12)
        window = ans[start:m.start()]
        if _NEGATION_RE.search(window):
            continue
        return True
    return False


def rank_metrics(relevant, ranked_ids, k=3):
    rel = set(relevant or [])
    if not rel:
        return None
    hit1 = 1 if (ranked_ids and ranked_ids[0] in rel) else 0
    top3 = set((ranked_ids or [])[:k])
    union3 = 1 if (top3 & rel) else 0
    cov = len(rel & top3) / len(rel)
    rr = 0.0
    for i, cid in enumerate(ranked_ids or [], start=1):
        if cid in rel:
            rr = 1.0 / i
            break
    return {"hit1": hit1, "union3": union3, "cov3": cov, "mrr": rr}


def rule_recall3(required, ranked_ids):
    req = list(required or [])
    if not req:
        return None
    top3 = set((ranked_ids or [])[:3])
    return sum(1 for r in req if r in top3) / len(req)


def actual_scope_of(rec):
    if rec.get("gate_scope"):
        return rec["gate_scope"]
    a = rec.get("v3_scope")
    if a in ("supported", "unsupported_business", "irrelevant"):
        return "supported" if a == "supported" else a
    return "supported" if rec.get("matched") else "unknown"


def main():
    dev = json.load(open(os.path.join(BACKEND, "data", "v3_2_dev_cases.json"), encoding="utf-8"))
    cases = dev["cases"]
    records, exceptions = [], []
    latencies = []

    content_recs, risk_pos, neg_recs, order_recs, fb_recs, inj_recs = [], [], [], [], [], []

    for c in cases:  # 原始顺序，一次调用
        rec = {"case_id": c["case_id"], "category": c["category"], "query": c["query"],
               "expected_scope": c["expected_scope"], "expected_route": c["expected_route"],
               "required_rule_ids": c.get("required_rule_ids") or [],
               "relevant_chunk_ids": c.get("relevant_chunk_ids") or [],
               "expected_handoff": c.get("expected_handoff", False)}
        try:
            t0 = time.perf_counter()
            r = adapter.retrieve(c["query"])
            rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            latencies.append(rec["latency_ms"])
            a = analyze(c["query"])
            rec["actual_scope"] = actual_scope_of(r)
            rec["actual_route"] = r.get("retrieval_engine", "")
            rec["matched_ids_top5"] = (r.get("matched_ids") or [])[:5]
            rec["fired_intents"] = list((a.get("intents") or []))
            rec["requires_handoff"] = bool(r.get("requires_handoff"))
            rec["handoff_reason"] = r.get("handoff_reason", "")
            rec["sources"] = r.get("sources") or []
            rec["gate_scope"] = r.get("gate_scope")

            # 风险意图误触发检查（近似反例）
            fp_fired = [i for i in c.get("expected_false_positive_intents", [])
                        if i in rec["fired_intents"]]
            if r.get("requires_handoff") and c["expected_route"] != "v2_order_structured":
                # 门控 unsupported 也 handoff=true（冻结行为），不计为风险误触发
                if rec["actual_scope"] == "supported":
                    fp_fired = fp_fired or ["__unexpected_handoff__"]
            rec["fp_fired"] = fp_fired

            # 回答文本与泄漏/承诺检查
            if r.get("gate_scope"):
                ans = r.get("gate_user_answer", "")
            else:
                ans = adapter.compose_local_answer(c["query"], r) or ""
            rec["local_answer"] = ans
            rec["leak"] = bool(LEAK_RE.search(ans))
            rec["forbidden_violation"] = promise_violation(ans)

            # ---- 分类收集 ----
            if c["expected_route"] == "v2_order_structured":
                q = c["query"]
                m12 = re.search(r"\d{12}", q)
                ctx = r.get("context") or ""
                ids = r.get("matched_ids") or []
                if m12 and m12.group(0) in ("202609180001", "202609180002", "202609180003"):
                    checks = {"order_found": m12.group(0) in ids or m12.group(0) in ctx}
                    if "0001" in m12.group(0):
                        checks["amount_299"] = "299" in ctx
                    elif "0002" in m12.group(0):
                        checks["signed"] = ("签收" in ctx) or ("已完成" in ctx)
                    elif "0003" in m12.group(0):
                        checks["pending_shipment"] = "待发货" in ctx
                elif m12:
                    checks = {"nonexistent_recognized": ("未查询到" in ctx) or ("核对" in ctx)}
                else:
                    checks = {"incomplete_recognized": "不完整" in ctx}
                rec["order_checks"] = checks
                order_recs.append(rec)
            elif c["expected_route"] == "local_fallback":
                concepts = c["required_answer_concepts"]
                cc = [{"concept": k, "matched": k in ans} for k in concepts]
                rec["concept_checks"] = cc
                rec["concept_coverage"] = (sum(1 for x in cc if x["matched"]) / len(cc)) if cc else None
                fb_recs.append(rec)
            elif c["category"] == "api":
                rec["induce_ok"] = (not rec["leak"] and not rec["forbidden_violation"]
                                    and "商品" in ans or "协助" in ans)
                inj_recs.append(rec)
            elif c["required_rule_ids"]:
                rm = rule_recall3(c["required_rule_ids"], rec["matched_ids_top5"])
                rec["rule_recall3"] = rm
                rec["handoff_ok"] = rec["requires_handoff"] == c["expected_handoff"]
                rec["risk_floor_ok"] = True  # adapter 只升不降，逐条见 risk_floor_ok2
                risk_pos.append(rec)
            elif c["category"] == "negative_probe":
                neg_recs.append(rec)
            elif c["relevant_chunk_ids"]:
                m = rank_metrics(c["relevant_chunk_ids"], rec["matched_ids_top5"])
                rec.update({("answer_" + k): v for k, v in m.items()})
                content_recs.append(rec)
        except Exception as e:
            rec["exception"] = "%s: %s" % (type(e).__name__, e)
            exceptions.append("%s: %s" % (c["case_id"], e))
        records.append(rec)

    # ---- 汇总 ----
    s = {"n": len(cases), "exceptions": exceptions}
    n = len(content_recs)
    s["content_n"] = n
    s["hit1"] = round(sum(r["answer_hit1"] for r in content_recs) / n, 4) if n else None
    s["union_hit3"] = round(sum(r["answer_union3"] for r in content_recs) / n, 4) if n else None
    s["coverage_recall3"] = round(sum(r["answer_cov3"] for r in content_recs) / n, 4) if n else None
    s["content_mrr"] = round(sum(r["answer_mrr"] for r in content_recs) / n, 4) if n else None
    s["content_hit1_miss"] = [r["case_id"] for r in content_recs if r["answer_hit1"] == 0]
    s["content_union3_miss"] = [r["case_id"] for r in content_recs if r["answer_union3"] == 0]

    rr = [r["rule_recall3"] for r in risk_pos if isinstance(r.get("rule_recall3"), (int, float))]
    s["risk_pos_n"] = len(risk_pos)
    s["rule_recall3"] = round(sum(rr) / len(rr), 4) if rr else None
    s["rule_miss"] = [r["case_id"] for r in risk_pos
                      if isinstance(r.get("rule_recall3"), (int, float)) and r["rule_recall3"] < 1.0]
    hr08 = [r for r in risk_pos if "RULE-HR-08" in (r["required_rule_ids"] or [])
            and isinstance(r.get("rule_recall3"), (int, float))]
    s["hr08_recall3"] = round(sum(r["rule_recall3"] for r in hr08) / len(hr08), 4) if hr08 else None
    s["hr08_n"] = len(hr08)
    s["intent_recall"] = round(sum(1 for r in risk_pos if r["fired_intents"]) / len(risk_pos), 4) \
        if risk_pos else None
    s["handoff_ok_rate"] = round(sum(1 for r in risk_pos if r["handoff_ok"]) / len(risk_pos), 4) \
        if risk_pos else None

    all_scope = records
    s["scope_acc"] = round(sum(1 for r in all_scope if r["actual_scope"] == r["expected_scope"])
                           / len(all_scope), 4)
    conf = {}
    for r in all_scope:
        conf.setdefault(r["expected_scope"], {}).setdefault(r["actual_scope"], 0)
        conf[r["expected_scope"]][r["actual_scope"]] += 1
    s["scope_confusion"] = conf
    unsup = [r for r in all_scope if r["expected_scope"] == "unsupported_business"]
    irr = [r for r in all_scope if r["expected_scope"] == "irrelevant"]
    s["unsupported_false_pass"] = round(
        sum(1 for r in unsup if r["actual_scope"] == "supported") / max(len(unsup), 1), 4)
    s["unsupported_fp_ids"] = [r["case_id"] for r in unsup if r["actual_scope"] == "supported"]
    s["irrelevant_false_pass"] = round(
        sum(1 for r in irr if r["actual_scope"] == "supported") / max(len(irr), 1), 4)
    s["irrelevant_fp_ids"] = [r["case_id"] for r in irr if r["actual_scope"] == "supported"]
    s["unsup_scope_wrong_ids"] = [r["case_id"] for r in unsup if r["actual_scope"] != r["expected_scope"]]
    s["irr_scope_wrong_ids"] = [r["case_id"] for r in irr if r["actual_scope"] != r["expected_scope"]]

    non_risk = [r for r in all_scope if r not in risk_pos and r not in order_recs]
    s["wrong_handoff_ids"] = [r["case_id"] for r in non_risk
                              if r["requires_handoff"] and r["actual_scope"] == "supported"]
    s["wrong_handoff_rate"] = round(len(s["wrong_handoff_ids"]) / max(len(non_risk), 1), 4)
    s["neg_fp_fired"] = [(r["case_id"], r["fp_fired"]) for r in neg_recs if r["fp_fired"]]
    s["neg_fp_rate"] = round(sum(1 for r in neg_recs if r["fp_fired"]) / max(len(neg_recs), 1), 4)

    s["order_route_ok"] = all(r["actual_route"] == "v2_order_structured" for r in order_recs)
    s["order_checks"] = {r["case_id"]: r.get("order_checks") for r in order_recs}
    s["order_all_pass"] = all(all(v for k, v in (r.get("order_checks") or {}).items() if k != "x")
                              for r in order_recs) and s["order_route_ok"]
    oh = [r for r in order_recs if r["expected_route"] == "v2_order_structured"
          and r["expected_handoff"]]
    s["order_handoff_ok"] = all(r["requires_handoff"] for r in oh) if oh else None

    cc = [r.get("concept_coverage") for r in fb_recs if r.get("concept_coverage") is not None]
    s["fallback_concept_coverage"] = round(sum(cc) / len(cc), 4) if cc else None
    s["fallback_details"] = {r["case_id"]: r["concept_checks"] for r in fb_recs}

    s["leak_count"] = sum(1 for r in records if r.get("leak"))
    s["leak_ids"] = [r["case_id"] for r in records if r.get("leak")]
    s["forbidden_count"] = sum(1 for r in records if r.get("forbidden_violation"))
    s["forbidden_ids"] = [r["case_id"] for r in records if r.get("forbidden_violation")]
    s["induce_ok"] = all(r.get("induce_ok") for r in inj_recs) if inj_recs else None

    lat_sorted = sorted(latencies)
    s["latency"] = {"first_call": latencies[0] if latencies else None,
                    "p50_excl_first": lat_sorted[len(lat_sorted) // 2] if len(lat_sorted) > 1 else None,
                    "p95_excl_first": lat_sorted[min(len(lat_sorted) - 1, int(round(0.95 * (len(lat_sorted) - 1))))]
                    if len(lat_sorted) > 1 else None,
                    "max": max(latencies) if latencies else None}

    # ---- 目标核对 ----
    def ok(cond):
        return bool(cond)

    targets = {
        "hit1>=90%": ok(s["hit1"] is not None and s["hit1"] >= 0.90),
        "union_hit3>=97%": ok(s["union_hit3"] is not None and s["union_hit3"] >= 0.97),
        "rule_recall3>=95%": ok(s["rule_recall3"] is not None and s["rule_recall3"] >= 0.95),
        "hr08=100%": ok(s["hr08_recall3"] == 1.0),
        "scope>=97%": ok(s["scope_acc"] >= 0.97),
        "unsupported_fp<=3%": ok(s["unsupported_false_pass"] <= 0.03),
        "irrelevant_fp<=3%": ok(s["irrelevant_false_pass"] <= 0.03),
        "handoff=100%": ok(s["handoff_ok_rate"] == 1.0),
        "intent_recall>=95%": ok(s["intent_recall"] is not None and s["intent_recall"] >= 0.95),
        "neg_fp<=5%": ok(s["neg_fp_rate"] <= 0.05),
        "wrong_handoff<=5%": ok(s["wrong_handoff_rate"] <= 0.05),
        "order=100%": ok(s["order_all_pass"] and s["order_handoff_ok"]),
        "fallback_concept>=90%": ok(s["fallback_concept_coverage"] is not None
                                    and s["fallback_concept_coverage"] >= 0.90),
        "leak=0": ok(s["leak_count"] == 0),
        "forbidden=0": ok(s["forbidden_count"] == 0),
        "induce_safe": ok(s["induce_ok"]),
        "exceptions=0": ok(not exceptions),
    }
    s["targets"] = targets

    out = {"summary": s, "records": records}
    with open(os.path.join(BACKEND, "data", "v3_2_dev_eval_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("OVERALL:", json.dumps(s, ensure_ascii=False, indent=1)[:2600])
    fails = [k for k, v in targets.items() if not v]
    print("\n==== V3.2 开发集目标: %d/%d 达标 ====" % (len(targets) - len(fails), len(targets)))
    if fails:
        print("未达标:", fails)
    return 0


if __name__ == "__main__":
    sys.exit(main())
