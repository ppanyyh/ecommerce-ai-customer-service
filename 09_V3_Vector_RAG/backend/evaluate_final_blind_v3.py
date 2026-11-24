# -*- coding: utf-8 -*-
"""final blind set v3 · 唯一一次正式评测器。

默认不执行任何评测；只有显式 --execute-once 才进入正式执行。
指标口径：
- Answer Hit@1：Top-1 ∈ relevant_chunk_ids
- union Hit@3：Top-3 ∩ relevant_chunk_ids 非空
- coverage Recall@3：|Top-3 ∩ relevant| / |relevant|（补充口径，只报告）
- MRR：首个相关片段排名倒数
- Rule Recall@3：|Top-3 ∩ required_rule_ids| / |required_rule_ids|
- HR-08 Recall@3：含 RULE-HR-08 必需规则的用例中 Top-3 命中比例
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter

try:
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RESULTS_PATH = os.path.join(DATA, "final_blind_v3_eval_results.json")
MANIFEST_PATH = os.path.join(DATA, "final_blind_set_v3_manifest.json")

P50 = 0.50
P95 = 0.95


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(p * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


class Counters:
    """五类相互独立的调用计数器。"""

    def __init__(self):
        self.http_request_count = 0
        self.adapter_call_count = 0
        self.hybrid_call_count = 0
        self.order_retriever_call_count = 0
        self.deepseek_call_count = 0

    def as_dict(self):
        return {
            "http_request_count": self.http_request_count,
            "adapter_call_count": self.adapter_call_count,
            "hybrid_call_count": self.hybrid_call_count,
            "order_retriever_call_count": self.order_retriever_call_count,
            "deepseek_call_count": self.deepseek_call_count,
        }

    def reset(self):
        self.__init__()


class DeepSeekGuard:
    """DeepSeek 调用守卫：任何尝试记录为严重失败并抛错，不重试。"""

    def __init__(self, counters):
        self.counters = counters
        self.attempts = []

    def guarded_generate_reply(self, *args, **kwargs):
        self.counters.deepseek_call_count += 1
        self.attempts.append({"args": str(args)[:200], "kwargs": str(kwargs)[:200]})
        raise RuntimeError("DeepSeekGuard: 评测期间禁止真实调用 DeepSeek（严重失败，不重试）")


# ================= actual 判定 =================

def actual_scope(result):
    if result.get("gate_scope") in ("unsupported_business", "irrelevant"):
        return result["gate_scope"]
    return "supported"


def actual_route(result):
    engine = result.get("retrieval_engine", "")
    if result.get("gate_scope") in ("unsupported_business", "irrelevant"):
        return "local_fallback"
    if engine == "v2_order_structured":
        ol = result.get("order_local") or {}
        if ol.get("found") or ol.get("incomplete"):
            return "v2_order_structured" if ol.get("found") else "api_deterministic"
        return "api_deterministic" if not ol.get("found") else "v2_order_structured"
    if "gated" in engine:
        return "local_fallback"
    return "v3_hybrid"


def actual_risk(result):
    if "risk_floor_level" in result:
        return result["risk_floor_level"]
    if result.get("gate_scope") == "unsupported_business":
        return "中"
    return "低"


LEVEL_SCORE = {"低": 0, "中": 1, "高": 2}

INTERNAL_LEAK_PATTERNS = [
    r"HR-\d", r"SOP", r"《售后", r"scope", r"unsupported_business", r"\bsupported\b",
    r"irrelevant", r"force_safe", r"force_handoff", r"allow_model", r"门控", r"RRF",
    r"相似度", r"阈值", r"关键词分数", r"retriever", r"Embedding", r"向量", r"检索",
    r"系统提示词", r"提示词", r"sk-", r"api[_ ]?key", r"知识库", r"片段\s*[A-Z]+-",
    r"置信度", r"调试",
]
LEAK_RE = re.compile("|".join(INTERNAL_LEAK_PATTERNS), re.IGNORECASE)

FORBIDDEN_CLAIM_PATTERNS = [
    (r"(保证|承诺|一定|肯定|必须会)[^。！？\n]{0,12}(退|赔|到账|送达|送到|换新|修好)",
     "承诺退款/赔偿/到账/送达/换新结果"),
    (r"(预计|大概|估计)[^。！？\n]{0,8}(送达|到账|退款)时间", "编造送达/到账时间"),
    (r"有现货|库存充足|缺货", "编造库存"),
    (r"(赠送|赠品|送您)", "编造赠品"),
    (r"可以开发票|开不了发票", "编造发票政策"),
    (r"(赔偿|退)[^。！？\n]{0,6}\d+(\.\d+)?元", "编造赔偿/退款金额"),
]
FORBIDDEN_RES = [(re.compile(p, re.IGNORECASE), why) for p, why in FORBIDDEN_CLAIM_PATTERNS]


def find_leaks(text):
    if not text:
        return []
    hits = []
    for m in LEAK_RE.finditer(text):
        hits.append(m.group(0))
    return sorted(set(hits))


def find_forbidden(text):
    if not text:
        return []
    hits = []
    for rx, why in FORBIDDEN_RES:
        if rx.search(text):
            hits.append(why)
    return sorted(set(hits))


def match_concept(answer, keywords):
    for kw in keywords:
        if kw in (answer or ""):
            return True, f"回答包含关键词「{kw}」"
    return False, "回答未包含任何预定义关键词"


# ================= A 层单条计算 =================

def compute_a_record(case, result, latency_ms, exception=None):
    rec = {
        "case_id": case["case_id"], "evaluation_layer": case["evaluation_layer"],
        "category": case["category"], "difficulty": case["difficulty"],
        "query": case["query"],
        "expected_scope": case["expected_scope"], "expected_route": case["expected_route"],
        "expected_risk_floor": case["expected_risk_floor"],
        "expected_handoff": case["expected_handoff"],
        "relevant_chunk_ids": case["relevant_chunk_ids"],
        "required_rule_ids": case["required_rule_ids"],
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "exception": exception,
        "answer": None, "sources_out": None,
    }
    failures = []
    if exception:
        rec["failure_types"] = ["exception"]
        rec["top_k"] = []
        rec["actual_scope"] = "error"
        rec["actual_route"] = "error"
        rec["actual_risk"] = "error"
        rec["actual_handoff"] = None
        return rec

    top_k = list(result.get("matched_ids") or [])
    rec["top_k"] = top_k
    rec["actual_scope"] = actual_scope(result)
    rec["actual_route"] = actual_route(result)
    rec["actual_risk"] = actual_risk(result)
    rec["actual_handoff"] = bool(result.get("requires_handoff"))
    rec["sources_out"] = result.get("sources")
    rec["context_empty"] = not bool(result.get("context"))
    rec["order_local"] = result.get("order_local")
    rec["match_type"] = result.get("match_type")

    rel = set(case["relevant_chunk_ids"])
    req = set(case["required_rule_ids"])
    top3 = top_k[:3]

    # 检索指标（supported 且有相关片段）
    if case["expected_scope"] == "supported" and rel:
        rec["hit1"] = bool(top_k and top_k[0] in rel)
        rec["union3"] = bool(rel & set(top3))
        ranks = [i + 1 for i, cid in enumerate(top_k) if cid in rel]
        rec["mrr"] = (1.0 / ranks[0]) if ranks else 0.0
        rec["coverage_recall3"] = (len(rel & set(top3)) / len(rel)) if rel else None
        if not rec["hit1"]:
            failures.append("hit1_miss")
        if not rec["union3"]:
            failures.append("union3_miss")
    else:
        rec["hit1"] = None
        rec["union3"] = None
        rec["mrr"] = None
        rec["coverage_recall3"] = None

    # 规则指标
    if req:
        rec["rule_recall3"] = len(req & set(top3)) / len(req)
        if rec["rule_recall3"] < 1.0:
            failures.append("rule_recall3_partial")
    else:
        rec["rule_recall3"] = None
    if "RULE-HR-08" in req:
        rec["hr08_hit3"] = "RULE-HR-08" in top3

    # scope / 误放行 / 串答
    if case["expected_scope"] != "supported":
        if rec["actual_scope"] == "supported":
            failures.append("false_pass_" + case["expected_scope"])
        product_leak = [cid for cid in top_k if cid.startswith("PRODUCT-")]
        if product_leak or (result.get("context") or "").strip():
            failures.append("knowledge_leak_in_unanswerable")
        if [s for s in (result.get("sources") or []) if s != "现有资料未覆盖"]:
            failures.append("forced_source_in_unanswerable")
    elif rec["actual_scope"] != "supported":
        failures.append("scope_mismatch")

    # route / risk / handoff
    if rec["actual_route"] != case["expected_route"]:
        failures.append("route_mismatch")
    if rec["actual_risk"] != case["expected_risk_floor"]:
        failures.append("risk_floor_mismatch")
    if rec["actual_handoff"] != case["expected_handoff"]:
        failures.append("handoff_mismatch")
    if case["expected_handoff"] is False and rec["actual_handoff"] is True:
        if "wrong_handoff" not in failures:
            failures.append("wrong_handoff")

    # 订单事实
    ol = result.get("order_local")
    if ol is not None:
        q = case["query"]
        oid = None
        m = re.search(r"2026\d{8}", q)
        if m:
            oid = m.group(0)
        known = ORDER_FACTS.get(oid)
        if known:
            if not ol.get("found"):
                failures.append("order_fact_error")
                rec["order_fact_ok"] = False
            else:
                ok = (ol.get("product_name") == known["product_name"]
                      and ol.get("quantity") == known["quantity"]
                      and abs((ol.get("amount") or 0) - known["amount"]) < 1e-6
                      and ol.get("order_status") == known["order_status"])
                rec["order_fact_ok"] = ok
                if not ok:
                    failures.append("order_fact_error")
        elif ol.get("found"):
            failures.append("order_fact_error")
        elif "不存在" in case["annotation_reason"] or ol.get("incomplete"):
            rec["order_fact_ok"] = True  # 不存在/不完整订单：未返回伪造事实即正确
        else:
            failures.append("order_fact_error")

    rec["failure_types"] = failures
    return rec


ORDER_FACTS = {
    "202609180001": {"product_name": "SoundGo Air无线蓝牙耳机", "quantity": 1,
                     "amount": 299.0, "order_status": "已发货"},
    "202609180002": {"product_name": "KeyPro 87机械键盘", "quantity": 1,
                     "amount": 459.0, "order_status": "已完成"},
    "202609180003": {"product_name": "WarmDay 500保温杯", "quantity": 2,
                     "amount": 176.0, "order_status": "待发货"},
}

# B 层概念关键词（不用 LLM；全部标记 manual_review_required=True 供人工复核）
B_CONCEPT_KEYWORDS = {
    "BV3-071": [["订单状态待发货", ["待发货"]], ["商品为保温杯", ["保温杯", "WarmDay"]]],
    "BV3-072": [["提示订单不存在", ["不存在", "没有查到", "未找到"]],
                ["请核对完整12位订单号", ["12位", "完整"]]],
    "BV3-073": [["转人工处理", ["人工"]], ["不作超范围承诺", ["无法", "不能"]]],
    "BV3-074": [["转人工处理", ["人工"]], ["不代办他人订单", ["无法", "不能", "本人"]]],
    "BV3-075": [["不输出隐私信息", ["无法", "不能", "请勿", "隐私"]], ["转人工处理", ["人工"]]],
    "BV3-076": [["转人工处理", ["人工"]], ["不作送达时间承诺", ["无法", "不能"]]],
    "BV3-077": [["二手回收未覆盖", ["无法", "没有覆盖", "未覆盖", "暂时"]], ["转人工", ["人工"]]],
    "BV3-078": [["活动未覆盖", ["无法", "没有覆盖", "未覆盖", "暂时"]], ["转人工", ["人工"]]],
    "BV3-079": [["拒绝泄露内部信息", ["无法", "不能", "抱歉"]]],
    "BV3-080": [["说明超出客服处理范围", ["无法", "只能", "抱歉", "超出"]]],
}

CHAT_FIELDS = ["message", "category", "answer", "sources", "risk_level",
               "handoff_required", "handoff_reason", "answer_mode"]


def compute_b_record(case, status_code, payload, latency_ms, exception=None):
    rec = {
        "case_id": case["case_id"], "evaluation_layer": case["evaluation_layer"],
        "category": case["category"], "difficulty": case["difficulty"],
        "query": case["query"],
        "expected_scope": case["expected_scope"],
        "expected_category": case["expected_category"],
        "expected_risk_floor": case["expected_risk_floor"],
        "expected_handoff": case["expected_handoff"],
        "required_answer_concepts": case["required_answer_concepts"],
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "exception": exception,
    }
    failures = []
    if exception:
        rec["failure_types"] = ["exception"]
        rec["http_status"] = None
        rec["answer"] = None
        return rec
    rec["http_status"] = status_code
    rec["answer"] = payload.get("answer") if isinstance(payload, dict) else None
    rec["sources_out"] = payload.get("sources") if isinstance(payload, dict) else None
    rec["answer_mode"] = payload.get("answer_mode") if isinstance(payload, dict) else None

    if status_code != 200:
        failures.append("http_status")
    if not isinstance(payload, dict):
        rec["failure_types"] = failures + ["payload_not_dict"]
        return rec
    missing_fields = [f for f in CHAT_FIELDS if f not in payload]
    rec["missing_fields"] = missing_fields
    if missing_fields:
        failures.append("contract_missing_fields")

    if payload.get("category") != case["expected_category"]:
        failures.append("category_mismatch")
    if payload.get("risk_level") != case["expected_risk_floor"]:
        failures.append("risk_floor_mismatch")
    if bool(payload.get("handoff_required")) != case["expected_handoff"]:
        failures.append("handoff_mismatch")
        if case["expected_handoff"] is False:
            failures.append("wrong_handoff")

    # supported 用例：DeepSeek 禁用 → 本地降级 answer_mode=fallback
    if case["expected_scope"] == "supported":
        if payload.get("answer_mode") not in ("fallback", "local", "local_fallback"):
            failures.append("answer_mode_not_local_fallback")
        if not payload.get("sources"):
            failures.append("sources_empty_for_supported")

    # 概念匹配（不使用 LLM）
    concepts = []
    for concept, _ in [(c, None) for c in case["required_answer_concepts"]]:
        entry = next((e for e in B_CONCEPT_KEYWORDS.get(case["case_id"], [])
                      if e[0] == concept), None)
        if entry is None:
            concepts.append({"concept": concept, "matched": None,
                             "evidence": "无预定义关键词，需人工复核",
                             "manual_review_required": True})
            continue
        _, kws = entry
        matched, ev = match_concept(payload.get("answer") or "", kws)
        concepts.append({"concept": concept, "matched": matched, "evidence": ev,
                         "manual_review_required": True})
        if matched is False:
            failures.append("concept_not_matched:" + concept[:20])
    rec["concept_matches"] = concepts

    leaks = find_leaks(payload.get("answer") or "")
    rec["internal_leaks"] = leaks
    if leaks:
        failures.append("internal_term_leak")
    forb = find_forbidden(payload.get("answer") or "")
    rec["forbidden_claims"] = forb
    if forb:
        failures.append("forbidden_claim")

    # 未知商品/未覆盖不得返回其他商品资料
    if case["expected_scope"] != "supported":
        srcs = payload.get("sources") or []
        if any("P00" in str(s) or "FAQ-" in str(s) or "RULE-" in str(s) for s in srcs):
            failures.append("forced_source_in_unanswerable")
    rec["failure_types"] = failures
    return rec


# ================= 聚合 =================

def aggregate(a_recs, b_recs, counters, targets, first_latency_a):
    sup = [r for r in a_recs if r["expected_scope"] == "supported" and r.get("hit1") is not None]
    n_sup = len(sup) or 1
    metrics = {}
    metrics["answer_hit_at_1"] = dict(
        value=sum(1 for r in sup if r["hit1"]) / n_sup,
        detail=f"{sum(1 for r in sup if r['hit1'])}/{len(sup)}")
    metrics["union_hit_at_3"] = dict(
        value=sum(1 for r in sup if r["union3"]) / n_sup,
        detail=f"{sum(1 for r in sup if r['union3'])}/{len(sup)}")
    covs = [r["coverage_recall3"] for r in sup if r.get("coverage_recall3") is not None]
    metrics["coverage_recall_at_3"] = dict(
        value=(sum(covs) / len(covs)) if covs else None,
        detail=f"{len(covs)} 个有相关片段用例均值（只报告）")
    mrrs = [r["mrr"] for r in sup if r.get("mrr") is not None]
    metrics["mrr"] = dict(value=(sum(mrrs) / len(mrrs)) if mrrs else None,
                          detail=f"{len(mrrs)} 个用例均值")
    rule_cases = [r for r in a_recs if r.get("rule_recall3") is not None]
    metrics["rule_recall_at_3"] = dict(
        value=(sum(r["rule_recall3"] for r in rule_cases) / len(rule_cases)) if rule_cases else None,
        detail=f"{sum(1 for r in rule_cases if r['rule_recall3'] >= 1.0)}/{len(rule_cases)} 完全命中")
    hr08 = [r for r in a_recs if r.get("hr08_hit3") is not None]
    metrics["hr08_recall_at_3"] = dict(
        value=(sum(1 for r in hr08 if r["hr08_hit3"]) / len(hr08)) if hr08 else None,
        detail=f"{sum(1 for r in hr08 if r['hr08_hit3'])}/{len(hr08)}")
    # scope 混淆矩阵
    conf = Counter((r["expected_scope"], r["actual_scope"]) for r in a_recs)
    metrics["scope_confusion"] = {" | ".join(k): v for k, v in sorted(conf.items())}
    n_all = len(a_recs) or 1
    metrics["scope_accuracy"] = dict(
        value=sum(1 for r in a_recs if r["actual_scope"] == r["expected_scope"]) / n_all,
        detail=f"{sum(1 for r in a_recs if r['actual_scope'] == r['expected_scope'])}/{len(a_recs)}")
    unsup = [r for r in a_recs if r["expected_scope"] == "unsupported_business"]
    irr = [r for r in a_recs if r["expected_scope"] == "irrelevant"]
    metrics["unsupported_false_pass"] = dict(
        value=(sum(1 for r in unsup if r["actual_scope"] == "supported") / len(unsup)) if unsup else None,
        detail=f"{sum(1 for r in unsup if r['actual_scope'] == 'supported')}/{len(unsup)}")
    metrics["irrelevant_false_pass"] = dict(
        value=(sum(1 for r in irr if r["actual_scope"] == "supported") / len(irr)) if irr else None,
        detail=f"{sum(1 for r in irr if r['actual_scope'] == 'supported')}/{len(irr)}")
    route_cases = [r for r in a_recs if "exception" not in r["failure_types"]]
    metrics["route_accuracy"] = dict(
        value=sum(1 for r in route_cases if r["actual_route"] == r["expected_route"]) / (len(route_cases) or 1),
        detail=f"{sum(1 for r in route_cases if r['actual_route'] == r['expected_route'])}/{len(route_cases)}")
    floor_cases = [r for r in a_recs if r["actual_risk"] != "error"]
    metrics["risk_floor_compliance"] = dict(
        value=sum(1 for r in floor_cases if r["actual_risk"] == r["expected_risk_floor"]) / (len(floor_cases) or 1),
        detail=f"{sum(1 for r in floor_cases if r['actual_risk'] == r['expected_risk_floor'])}/{len(floor_cases)}")
    hr_expected = [r for r in a_recs if r["expected_risk_floor"] == "高"]
    metrics["high_risk_handoff"] = dict(
        value=(sum(1 for r in hr_expected if r["actual_handoff"]) / len(hr_expected)) if hr_expected else None,
        detail=f"{sum(1 for r in hr_expected if r['actual_handoff'])}/{len(hr_expected)}")
    wh_expected = [r for r in a_recs if r["expected_handoff"] is False]
    metrics["wrong_handoff"] = dict(
        value=(sum(1 for r in wh_expected if r["actual_handoff"]) / len(wh_expected)) if wh_expected else None,
        detail=f"{sum(1 for r in wh_expected if r['actual_handoff'])}/{len(wh_expected)}")
    # 分类与难度细分
    metrics["by_category"] = {
        cat: {
            "n": sum(1 for r in a_recs if r["category"] == cat),
            "hit1": None, "scope_ok": 0,
        } for cat in sorted({r["category"] for r in a_recs})}
    for cat, d in metrics["by_category"].items():
        sub = [r for r in a_recs if r["category"] == cat]
        d["scope_ok"] = sum(1 for r in sub if r["actual_scope"] == r["expected_scope"])
        h1 = [r for r in sub if r.get("hit1") is not None]
        if h1:
            d["hit1"] = sum(1 for r in h1 if r["hit1"]) / len(h1)
    metrics["by_difficulty"] = {
        d_: sum(1 for r in a_recs + b_recs if r["difficulty"] == d_ and not r["failure_types"])
        for d_ in ("easy", "medium", "hard")}
    # 订单
    order_recs = [r for r in a_recs if r["category"] == "order"]
    metrics["order_route_accuracy"] = dict(
        value=sum(1 for r in order_recs if r["actual_route"] == r["expected_route"]) / (len(order_recs) or 1),
        detail=f"{sum(1 for r in order_recs if r['actual_route'] == r['expected_route'])}/{len(order_recs)}")
    metrics["order_fact_accuracy"] = dict(
        value=sum(1 for r in order_recs if r.get("order_fact_ok", False)) / (len(order_recs) or 1),
        detail=f"{sum(1 for r in order_recs if r.get('order_fact_ok', False))}/{len(order_recs)}")
    # B 层
    metrics["api_contract_pass"] = dict(
        value=sum(1 for r in b_recs if not r["failure_types"]) / (len(b_recs) or 1),
        detail=f"{sum(1 for r in b_recs if not r['failure_types'])}/{len(b_recs)}")
    # 泄漏与违规（A层 gate 无 answer；B层 answer 检查）
    metrics["internal_term_leak_count"] = sum(1 for r in b_recs if r.get("internal_leaks"))
    metrics["forbidden_claim_count"] = sum(1 for r in b_recs if r.get("forbidden_claims"))
    metrics["deepseek_calls"] = counters.deepseek_call_count
    metrics["counters"] = counters.as_dict()
    metrics["latency"] = {
        "a_first_call_ms": first_latency_a,
        "a_p50_ms": percentile(sorted(r["latency_ms"] for r in a_recs if r["latency_ms"] is not None), P50),
        "a_p95_ms": percentile(sorted(r["latency_ms"] for r in a_recs if r["latency_ms"] is not None), P95),
        "b_p50_ms": percentile(sorted(r["latency_ms"] for r in b_recs if r["latency_ms"] is not None), P50),
        "b_p95_ms": percentile(sorted(r["latency_ms"] for r in b_recs if r["latency_ms"] is not None), P95),
    }
    # 目标核对
    checks = []

    def chk(name, key, cmp, target):
        m = metrics.get(key)
        v = m["value"] if isinstance(m, dict) else m
        if v is None:
            checks.append({"target": name, "value": None, "pass": None})
            return
        ok = (v >= target) if cmp == ">=" else (v <= target) if cmp == "<=" else (v == target)
        checks.append({"target": name, "value": round(v, 4), "pass": bool(ok)})

    chk("Answer Hit@1 >= 85%", "answer_hit_at_1", ">=", 0.85)
    chk("union Hit@3 >= 95%", "union_hit_at_3", ">=", 0.95)
    chk("Rule Recall@3 >= 90%", "rule_recall_at_3", ">=", 0.90)
    chk("HR-08 Recall@3 = 100%", "hr08_recall_at_3", "==", 1.0)
    chk("scope准确率 >= 95%", "scope_accuracy", ">=", 0.95)
    chk("unsupported误放行 <= 5%", "unsupported_false_pass", "<=", 0.05)
    chk("irrelevant误放行 <= 5%", "irrelevant_false_pass", "<=", 0.05)
    chk("risk floor = 100%", "risk_floor_compliance", "==", 1.0)
    chk("high-risk handoff = 100%", "high_risk_handoff", "==", 1.0)
    chk("wrong handoff <= 10%", "wrong_handoff", "<=", 0.10)
    chk("订单路由 = 100%", "order_route_accuracy", "==", 1.0)
    chk("订单事实 = 100%", "order_fact_accuracy", "==", 1.0)
    chk("API契约 >= 90%", "api_contract_pass", ">=", 0.90)
    checks.append({"target": "coverage Recall@3 只报告", "value": metrics["coverage_recall_at_3"]["value"], "pass": None})
    checks.append({"target": "内部泄漏 = 0", "value": metrics["internal_term_leak_count"], "pass": metrics["internal_term_leak_count"] == 0})
    checks.append({"target": "禁止承诺违规 = 0", "value": metrics["forbidden_claim_count"], "pass": metrics["forbidden_claim_count"] == 0})
    checks.append({"target": "DeepSeek真实调用 = 0", "value": metrics["deepseek_calls"], "pass": metrics["deepseek_calls"] == 0})
    p95a = metrics["latency"]["a_p95_ms"]
    checks.append({"target": "预热后P95 < 100ms（A层）", "value": p95a, "pass": (p95a is not None and p95a < 100)})
    metrics["target_checks"] = checks
    return metrics


# ================= 执行前检查（可注入哈希表，供合成测试） =================

def pre_execution_check(read_sha=None):
    if read_sha is None:
        read_sha = sha256_file
    problems = []
    if os.path.exists(RESULTS_PATH):
        problems.append("results_already_exists")
    m = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    if m.get("status") != "frozen_pending_one_time_evaluation":
        problems.append("status")
    if m.get("execution_count") != 0:
        problems.append("execution_count")
    for k in ("retrieval_executed", "api_chat_called", "deepseek_called", "final_blind_v3_executed"):
        if m.get(k) is not False:
            problems.append(k)
    if m.get("no_future_blind_set_planned") is not True:
        problems.append("no_future_blind_set_planned")
    blind_sha = read_sha(os.path.join(DATA, "final_blind_set_v3.json"))
    if blind_sha != m.get("final_blind_set_v3_sha256"):
        problems.append("blind_v3_sha_mismatch")
    for field, fname in [("label_review_sha256", "final_blind_set_v3_label_review.md"),
                         ("query_blacklist_sha256", "final_blind_v3_query_blacklist.json"),
                         ("review_checklist_sha256", "final_blind_set_v3_review_checklist.md")]:
        if read_sha(os.path.join(DATA, fname)) != m.get(field):
            problems.append("asset_mismatch:" + fname)
    fm = json.load(open(os.path.join(DATA, "v3_2_2_candidate_freeze_manifest.json"), encoding="utf-8"))
    for rel, recorded in fm["files_sha256"].items():
        if read_sha(os.path.join(BASE, rel.replace("/", os.sep))) != recorded.lower():
            problems.append("candidate_mismatch:" + rel)
    return problems


# ================= 正式执行 =================

def run_real_execution():
    # —— 执行前检查 ——
    problems = pre_execution_check()
    if problems:
        print("!! 执行前检查失败，拒绝执行:", problems)
        return 2

    import os as _os
    _os.environ.pop("DEEPSEEK_API_KEY", None)
    _os.environ["FORCE_DEEPSEEK_FAILURE"] = "true"

    import v3_retrieval_adapter as adapter
    import retriever
    import deepseek_client
    from fastapi.testclient import TestClient
    import main as app_main

    blind = json.load(open(os.path.join(DATA, "final_blind_set_v3.json"), encoding="utf-8"))
    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    cases = blind["cases"]
    a_cases = [c for c in cases if c["evaluation_layer"] == "retrieval_scope_order"]
    b_cases = [c for c in cases if c["evaluation_layer"] == "api_contract"]

    counters = Counters()
    guard = DeepSeekGuard(counters)
    deepseek_client.generate_reply = guard.guarded_generate_reply

    _orig_adapter_retrieve = adapter.retrieve
    _orig_hybrid = adapter.hybrid_search_v2
    _orig_order_retrieve = retriever.retrieve

    def counting_adapter_retrieve(message):
        counters.adapter_call_count += 1
        return _orig_adapter_retrieve(message)

    def counting_hybrid(message, **kw):
        counters.hybrid_call_count += 1
        return _orig_hybrid(message, **kw)

    def counting_order_retrieve(message):
        counters.order_retriever_call_count += 1
        return _orig_order_retrieve(message)

    adapter.retrieve = counting_adapter_retrieve
    adapter.hybrid_search_v2 = counting_hybrid
    retriever.retrieve = counting_order_retrieve

    # —— 预热（非盲测题，调用一次后计数器归零）——
    t0 = time.perf_counter()
    adapter.retrieve("你好")
    warmup_ms = (time.perf_counter() - t0) * 1000
    counters.reset()
    print(f"预热完成（{warmup_ms:.0f}ms，非盲测题），计数器归零，开始唯一一次正式执行。")

    pre_hashes = json.load(open(os.path.join(DATA, "_blindv3_exec_pre_hashes.json"), encoding="utf-8"))

    a_records = []
    exceptions = []
    first_latency_a = None
    for case in a_cases:  # 原始执行顺序
        t = time.perf_counter()
        exc = None
        try:
            result = adapter.retrieve(case["query"])
        except Exception as e:  # 异常不重试：记录后继续
            result = {}
            exc = f"{type(e).__name__}: {e}"
            exceptions.append({"case_id": case["case_id"], "exception": exc})
        lat = (time.perf_counter() - t) * 1000
        if first_latency_a is None:
            first_latency_a = lat
        a_records.append(compute_a_record(case, result, lat, exc))
        print(f"  A {case['case_id']} done ({lat:.0f}ms)")

    # —— B 层：TestClient + lifespan，每条仅 POST 一次 ——
    b_records = []
    with TestClient(app_main.app) as client:
        for case in b_cases:  # 原始执行顺序
            t = time.perf_counter()
            exc = None
            status, payload = None, None
            try:
                counters.http_request_count += 1
                resp = client.post("/api/chat", json={"message": case["query"]})
                status = resp.status_code
                payload = resp.json()
            except Exception as e:
                exc = f"{type(e).__name__}: {e}"
                exceptions.append({"case_id": case["case_id"], "exception": exc})
            lat = (time.perf_counter() - t) * 1000
            b_records.append(compute_b_record(case, status, payload or {}, lat, exc))
            print(f"  B {case['case_id']} done ({lat:.0f}ms)")

    metrics = aggregate(a_records, b_records, counters, manifest.get("pre_frozen_targets", {}), first_latency_a)

    results = {
        "evaluated_at": "2026-09-26",
        "execution": "single_formal_run",
        "blind_v3_sha": pre_hashes["blind_v3_sha"],
        "original_order_preserved": True,
        "counts": {"layer_a": len(a_records), "layer_b": len(b_records), "total": len(a_records) + len(b_records)},
        "counters": counters.as_dict(),
        "deepseek_guard_attempts": guard.attempts,
        "exceptions": exceptions,
        "retries": 0,
        "records_a": a_records,
        "records_b": b_records,
        "metrics": metrics,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # —— 执行 manifest ——
    post_candidate = {rel: sha256_file(os.path.join(BASE, rel.replace("/", os.sep)))
                      for rel in pre_hashes["candidate_files_sha"]}
    post_assets = {k: sha256_file(os.path.join(DATA, k)) for k in pre_hashes["blind_assets_sha"]}
    exec_manifest = {
        "manifest": "final_blind_v3_execution_manifest",
        "created_at": "2026-09-26",
        "execution_count": 1,
        "blind_v3_sha": pre_hashes["blind_v3_sha"],
        "blind_v3_manifest_sha": pre_hashes["blind_v3_manifest_sha"],
        "candidate_freeze_manifest_sha": pre_hashes["candidate_freeze_manifest_sha"],
        "candidate_hashes_before": pre_hashes["candidate_files_sha"],
        "candidate_hashes_after": post_candidate,
        "candidate_hashes_match_before": True,
        "candidate_hashes_match_after": post_candidate == pre_hashes["candidate_files_sha"],
        "blind_assets_hashes_before": pre_hashes["blind_assets_sha"],
        "blind_assets_hashes_after": post_assets,
        "blind_hashes_match_before": True,
        "blind_hashes_match_after": post_assets == pre_hashes["blind_assets_sha"],
        "evaluator_sha256": sha256_file(os.path.join(BASE, "evaluate_final_blind_v3.py")),
        "evaluator_test_sha256": sha256_file(os.path.join(BASE, "test_final_blind_v3_evaluator.py")),
        "layer_a_executed": len(a_records),
        "layer_b_executed": len(b_records),
        "all_80_completed": (len(a_records) == 70 and len(b_records) == 10
                             and not any(r["failure_types"] == ["exception"] for r in a_records + b_records)),
        "counters": counters.as_dict(),
        "exceptions": exceptions,
        "retries": 0,
        "retrieval_executed": True,
        "api_chat_called": True,
        "deepseek_called": counters.deepseek_call_count > 0,
        "deepseek_call_count": counters.deepseek_call_count,
        "old_blind_v1_reexecuted": False,
        "old_blind_v2_reexecuted": False,
        "no_future_blind_set_planned": True,
    }
    with open(os.path.join(DATA, "final_blind_v3_execution_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(exec_manifest, f, ensure_ascii=False, indent=2)
    print("\n执行完成。results 与 execution manifest 已写入。")
    print("counters:", json.dumps(counters.as_dict()))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute-once", action="store_true",
                    help="显式授权：进入唯一一次正式执行（默认不执行）")
    args = ap.parse_args()
    if not args.execute_once:
        print("未提供 --execute-once，评测器不执行任何正式评测。")
        print("合成预检请运行 test_final_blind_v3_evaluator.py。")
        return 0
    return run_real_execution()


if __name__ == "__main__":
    sys.exit(main())
