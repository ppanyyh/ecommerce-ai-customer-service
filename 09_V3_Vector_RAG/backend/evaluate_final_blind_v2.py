# -*- coding: utf-8 -*-
"""V3.1 第五阶段：final blind set v2 一次性正式评测器。

铁律：
- 默认运行（无 --execute-once）只打印评测计划，不执行任何盲测；
- 只有显式 --execute-once 才进入正式评测，且仅允许成功执行一次；
- 每条用例只调用对应运行入口一次（A 层 adapter.retrieve / B 层 POST /api/chat）；
- 异常只记录不重试；已执行过或哈希不一致则拒绝执行；
- 不调用任何 LLM 裁判；不修改盲测清单与标注；
- 全程 DeepSeek 0 调用（清 Key + FORCE_DEEPSEEK_FAILURE + generate_reply 计数守卫）。
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

BLIND_SET = "data/final_blind_set_v2.json"
BLIND_MANIFEST = "data/final_blind_set_v2_manifest.json"
RUNTIME_MANIFEST = "data/v3_1_runtime_freeze_manifest.json"
RESULTS_PATH = "data/final_blind_v2_eval_results.json"
EXEC_MANIFEST_PATH = "data/final_blind_v2_execution_manifest.json"
REPORT_PATH = "data/final_blind_v2_eval_report.md"
REVIEW_PATH = "data/final_blind_v2_api_manual_review.md"

BLIND_SET_SHA = "06bf27e4eb50a3cf5921f82a1b0306a53f3cc1b53fa815b1eb5d3786f3ed18b5"

# ---- 预先固定目标（执行前写定，不得在评测后更改）----
TARGETS = {
    "answer_hit1_min": 0.85,
    "answer_recall3_min": 0.95,
    "rule_recall3_min": 0.90,
    "scope_acc_min": 0.95,
    "unsupported_false_pass_max": 0.05,
    "irrelevant_false_pass_max": 0.05,
    "route_acc": 1.0,
    "hr08_recall3": 1.0,
    "high_risk_handoff": 1.0,
    "order_acc": 1.0,
    "b_http_success": 1.0,
    "b_structure": 1.0,
    "b_risk_floor": 1.0,
    "b_handoff": 1.0,
    "leak_violations": 0,
    "forbidden_violations": 0,
    "deepseek_calls": 0,
    "b_contract_pass_min": 0.90,
}

RISK_ORDER = {"低": 0, "中": 1, "高": 2}
SCOPES = ("supported", "unsupported_business", "irrelevant")

# ---- 面向用户文本的内部术语泄漏检查 ----
LEAK_PATTERNS = [
    (r"HR-\d+", "HR编号"), (r"RULE-HR-\d+", "规则编号"),
    (r"unsupported_business", "scope内部标签"), (r"supported_business", "scope内部标签"),
    (r"\birrelevant\b", "scope内部标签"), (r"\bsupported\b", "scope内部标签"),
    (r"force_safe|force_handoff|allow_model", "风险决策内部模式"),
    (r"门控|RRF|rrf|相似度|阈值|关键词分数|keyword_score|vector_similarity", "检索内部机制"),
    (r"retriever|hybrid_search|Embedding|embedding|chroma|Chroma", "检索内部实现"),
    (r"系统提示词|system prompt|system_prompt", "系统提示词"),
    (r"sk-[A-Za-z0-9]{12,}", "API Key"),
    (r"《售后SOP》|《商品资料》|《模拟订单数据》", "内部SOP/资料名称"),
]

# ---- 禁止承诺通用正则（对所有 B 层回答生效）----
FORBIDDEN_PATTERNS = {
    "编造退款时间": [r"(保证|承诺|一定|肯定|最迟)[^。！？]{0,14}(到账|退款|退回|退给我)",
                    r"\d+\s*天[^。！？]{0,8}(到账|退[款回])",
                    r"(今天|明天|后天)[^。！？]{0,10}(到账|退款)"],
    "保证赔偿金额": [r"(赔偿|赔|补偿)[^。！？]{0,10}\d+\s*元",
                    r"(保证|承诺)[^。！？]{0,10}(赔偿|赔你|补偿)"],
    "保证库存": [r"(保证|承诺|一定|肯定)[^。！？]{0,8}(有货|有现货|库存充足|能买到)"],
    "保证配送日期": [r"(保证|承诺|一定|肯定|最迟)[^。！？]{0,12}(送到|送达|发货|签收)",
                    r"(今天|明天|后天|当天)[^。！？]{0,10}(送到|送达|发货|到)"],
    "编造活动或赠品": [r"(满减|优惠券|赠品|礼品|买一送一|折扣|打折)[^。！？]{0,16}(有|送|领|参加|享受)"],
    "编造发票政策": [r"(可以|能|支持)[^。！？]{0,8}(开专票|开纸质|增值税专用发票|电子发票)",
                    r"开票流程[^。！？]{0,20}(是|为|：)"],
    "泄露他人订单": [r"\d{12}", ],
    "泄露隐私": [r"1[3-9]\d{9}", r"(收货地址|住址)[^。！？]{0,4}(是|为)[:：]?\s*\S+"],
    # 常见禁令的补充映射（与盲测集 forbidden_answer_claims 措辞对齐）
    "保证退款": [r"(保证|承诺|一定|肯定)[^。！？]{0,12}(到账|退款|退回)"],
    "保证退款到账天数": [r"\d+\s*(天|日)[^。！？]{0,8}(到账|退[款回])"],
    "承诺退款到账时间": [r"(保证|承诺|一定)[^。！？]{0,12}(到账|退款)"],
    "承诺退款时间": [r"(保证|承诺|一定)[^。！？]{0,12}(到账|退款)"],
    "保证到账时间": [r"(保证|承诺|一定)[^。！？]{0,12}到账"],
    "承诺赔偿金额": [r"(赔偿|赔|补偿)[^。！？]{0,10}\d+\s*元"],
    "保证明天送达": [r"明天[^。！？]{0,10}(到|送|达)", r"(保证|承诺)[^。！？]{0,10}(送达|送到)"],
    "承诺任何送达日期": [r"(今天|明天|后天|当天|\d+\s*天)[^。！？]{0,10}(送到|送达|到)"],
    "预报天气": [r"(晴|下雨|降雨|多云|气温|小雨|大雨)"],
    "输出任何手机号": [r"1[3-9]\d{9}"],
    "输出任何地址内容": [r"(省|市|区|县|路|街道|小区)[^\s]{0,12}\d*号?"],
    "泄露API Key": [r"sk-[A-Za-z0-9]{12,}"],
    "承诺退款结果与时间": [r"(保证|承诺)[^。！？]{0,12}(到账|退款|退回)"],
    "承诺退款/换货/赔偿金额": [r"(赔偿|赔)[^。！？]{0,10}\d+\s*元",
                           r"(承诺|保证)[^。！？]{0,8}(退款|换货|赔偿)"],
}


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ===========================================================================
# 纯计算函数（合成测试直接覆盖）
# ===========================================================================

def new_call_counters():
    """V3.2 勘误修复：五类彼此独立的计数器（禁止共用同一计数体系）。

    - http_request_count        HTTP POST 次数
    - adapter_call_count        检索适配器入口调用次数
    - hybrid_call_count         hybrid 检索内部调用次数
    - order_retriever_call_count 结构化订单查询调用次数
    - deepseek_call_count       DeepSeek 调用（守卫）次数
    """
    return {"http_request_count": 0, "adapter_call_count": 0,
            "hybrid_call_count": 0, "order_retriever_call_count": 0,
            "deepseek_call_count": 0}


def union_hit3(relevant, ranked_ids, k=3):
    """union Hit@3（正式达标口径）：Top-k 中存在任一合法相关片段即命中（0/1）。"""
    rel = set(relevant or [])
    if not rel:
        return None
    return 1 if (set((ranked_ids or [])[:k]) & rel) else 0


def rank_metrics(relevant, ranked_ids, k=3):
    """relevant: set；ranked_ids: 名次顺序列表。返回 (hit1, recall_k, rr, first_rel_rank)。
    注意 recall_k 为 coverage 口径（覆盖比例），仅作补充指标；正式达标用 union_hit3。"""
    rel = set(relevant or [])
    if not ranked_ids:
        return (0, 0.0, 0.0, None)
    hit1 = 1 if (ranked_ids[0] in rel) else 0
    topk = ranked_ids[:k]
    recall = (len(rel & set(topk)) / len(rel)) if rel else 0.0
    rr, rank = 0.0, None
    for i, cid in enumerate(ranked_ids, start=1):
        if cid in rel:
            rr, rank = 1.0 / i, i
            break
    return (hit1, recall, rr, rank)


def rule_recall3(required, ranked_ids):
    """required 规则出现在 Top-3 的比例；无 required 返回 None。"""
    req = list(required or [])
    if not req:
        return None
    top3 = set((ranked_ids or [])[:3])
    return sum(1 for r in req if r in top3) / len(req)


def latency_stats(deltas_ms):
    """deltas 按原始顺序。首调=原始顺序第一条；P50/P95 用剔除首条后的排序副本。"""
    if not deltas_ms:
        return {"first_call": None, "p50": None, "p95": None, "max": None, "n": 0}
    first = deltas_ms[0]
    rest = sorted(deltas_ms[1:]) if len(deltas_ms) > 1 else deltas_ms[:]

    def pct(sorted_vals, q):
        if not sorted_vals:
            return None
        idx = max(0, math.ceil(q * len(sorted_vals)) - 1)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    return {
        "first_call": round(first, 2),
        "p50": round(pct(rest, 0.50), 2),
        "p95": round(pct(rest, 0.95), 2),
        "max": round(max(deltas_ms), 2),
        "n": len(deltas_ms),
    }


def find_leaks(text):
    """返回 [(类别, 命中片段)]；空文本无泄漏。"""
    out = []
    t = text or ""
    for pat, label in LEAK_PATTERNS:
        m = re.search(pat, t)
        if m:
            out.append((label, m.group(0)))
    return out


def forbidden_violations(answer, forbidden_claims):
    """对回答文本跑通用禁止承诺正则；返回 [(claim, 违规类别, 命中片段)]。"""
    t = answer or ""
    out = []
    for claim in forbidden_claims or []:
        pats = FORBIDDEN_PATTERNS.get(claim)
        if pats is None:
            continue
        for pat in pats:
            m = re.search(pat, t)
            if m:
                out.append((claim, "regex", m.group(0)))
                break
    return out


def check_concepts(answer, concepts, concept_keywords):
    """概念匹配（无 LLM）：按固定关键词映射做子串判定。
    返回 [{concept, matched, evidence, manual_review_required}]。
    concept_keywords[concept] = (keywords:list, manual:bool)
    未在映射中的概念 → manual_review_required=True 且 matched=None。"""
    t = answer or ""
    out = []
    for c in concepts or []:
        cfg = concept_keywords.get(c)
        if cfg is None:
            out.append({"concept": c, "matched": None, "evidence": "未配置自动关键词，需人工复核",
                        "manual_review_required": True})
            continue
        kws, manual = cfg
        hit = next((k for k in kws if k in t), None)
        out.append({"concept": c, "matched": hit is not None,
                    "evidence": ("子串命中: %r" % hit) if hit else "未命中关键词 %s" % kws,
                    "manual_review_required": bool(manual)})
    return out


def actual_scope_of(rec):
    g = rec.get("gate_scope")
    if g in ("unsupported_business", "irrelevant"):
        return g
    return "supported"


def actual_route_of(rec):
    engine = rec.get("retrieval_engine", "")
    if engine == "v2_order_structured":
        return "v2_order_structured"
    if rec.get("gate_scope") in ("unsupported_business", "irrelevant"):
        return "api_deterministic"
    if engine == "v3_1_hybrid_v2":
        return "v3_hybrid"
    return "other:" + (engine or "unknown")


def confusion_matrix(pairs):
    """pairs: [(expected, actual)] → 嵌套 dict。"""
    m = {e: {a: 0 for a in SCOPES} for e in SCOPES}
    for e, a in pairs:
        if e in m and a in m[e]:
            m[e][a] += 1
    return m


# ===========================================================================
# 逐条评测（A 层 / B 层）
# ===========================================================================

def evaluate_a_case(case, adapter_fn, counters):
    """A 层：只调用一次 adapter_fn(query)。counters 为 new_call_counters() 字典。"""
    t0 = time.perf_counter()
    err = None
    rec = {}
    try:
        rec = adapter_fn(case["query"]) or {}
    except Exception as e:  # 异常只记录，不重试
        err = "%s: %s" % (type(e).__name__, e)
    dt = (time.perf_counter() - t0) * 1000.0
    counters["adapter_call_count"] += 1
    if "order" in (case.get("expected_route") or ""):
        counters["order_retriever_call_count"] += 1

    actual_scope = actual_scope_of(rec)
    actual_route = actual_route_of(rec)
    matched_ids = list(rec.get("matched_ids") or [])
    rel = set(case.get("relevant_chunk_ids") or [])
    req_rules = list(case.get("required_rule_ids") or [])

    entry = {
        "case_id": case["case_id"], "layer": "A", "category": case["category"],
        "difficulty": case["difficulty"], "query": case["query"],
        "expected_scope": case["expected_scope"], "actual_scope": actual_scope,
        "expected_route": case["expected_route"], "actual_route": actual_route,
        "retrieval_engine": rec.get("retrieval_engine", ""),
        "adapter_calls": 1, "latency_ms": round(dt, 2),
        "matched_ids_top5": matched_ids[:5],
        "top_k_note": "冻结适配器不暴露分数值；matched_ids 按 final_rank 顺序即 Top-K 名次",
        "context_empty": not rec.get("context"),
        "context_len": len(rec.get("context") or ""),
        "requires_handoff": bool(rec.get("requires_handoff")),
        "handoff_reason": rec.get("handoff_reason", ""),
        "expected_handoff": bool(case.get("expected_handoff")),
        "expected_risk_floor": case.get("expected_risk_floor", "低"),
        "required_rule_ids": req_rules,
        "failure_type": err,
    }

    if actual_scope in ("unsupported_business", "irrelevant") and case["expected_scope"] == actual_scope:
        entry["gate_clean"] = (not matched_ids and entry["context_empty"]
                               and all(s in ("现有资料未覆盖",) for s in (rec.get("sources") or [])))
    else:
        entry["gate_clean"] = None

    if case["expected_scope"] == "supported" and rel and actual_route == "v3_hybrid":
        h1, r3, rr, rank = rank_metrics(rel, matched_ids)
        entry["answer_hit1"] = h1
        entry["answer_recall3"] = r3
        entry["union_hit3"] = union_hit3(rel, matched_ids)
        entry["mrr"] = rr
        entry["first_relevant_rank"] = rank
        entry["rule_recall3"] = rule_recall3(req_rules, matched_ids)
    else:
        entry["answer_hit1"] = None
        entry["answer_recall3"] = None
        entry["union_hit3"] = None
        entry["mrr"] = None
        entry["rule_recall3"] = (None if not req_rules else "order_route_single_call")

    # 订单判定
    if case["expected_route"] == "v2_order_structured":
        q = case["query"]
        m12 = re.search(r"\d{12}", q)
        m611 = re.search(r"(?<!\d)\d{6,11}(?!\d)", q)
        ctx = rec.get("context") or ""
        if m12 and m12.group(0) in ("202609180001", "202609180002", "202609180003"):
            checks = {"order_found": m12.group(0) in matched_ids or m12.group(0) in ctx}
            for fact, kws in ORDER_FACT_KEYWORDS.get(m12.group(0), {}).items():
                checks[fact] = any(k in ctx for k in kws)
        elif m12:
            checks = {"nonexistent_recognized": ("未查询到" in ctx) or ("核对" in ctx)}
        elif m611:
            checks = {"incomplete_recognized": "不完整" in ctx}
        else:
            checks = {"recognized": False}
        entry["order_checks"] = checks
        entry["order_risk_handoff"] = bool(rec.get("requires_handoff")) if "RULE-HR" in json.dumps(
            case.get("required_rule_ids") or [], ensure_ascii=False) else None
    return entry


ORDER_FACT_KEYWORDS = {
    "202609180001": {"amount_299": ["299"]},
    "202609180002": {"signed_completed": ["签收", "已完成"]},
    "202609180003": {"pending_shipment": ["待发货"]},
}


def evaluate_b_case(case, client, counters, guard, retrieval_counter=None):
    """B 层：只 POST 一次。counters 为 new_call_counters() 字典（各计数彼此独立）。
    retrieval_counter 参数保留兼容旧签名但不再参与计数。"""
    t0 = time.perf_counter()
    err = None
    resp = None
    guard_before = guard.attempts
    http_before = counters["http_request_count"]
    adapter_before = counters["adapter_call_count"]
    order_before = counters["order_retriever_call_count"]
    try:
        resp = client.post("/api/chat", json={"message": case["query"], "history": []})
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    dt = (time.perf_counter() - t0) * 1000.0
    counters["http_request_count"] += 1

    status = getattr(resp, "status_code", None)
    try:
        body = resp.json() if resp is not None else {}
    except Exception:
        body = {}
    answer = body.get("answer", "") if isinstance(body, dict) else ""
    sources = body.get("sources", []) if isinstance(body, dict) else []

    expected_empty_input = case["query"] == ""
    expected_status_ok = (200 if not expected_empty_input else 422)
    entry = {
        "case_id": case["case_id"], "layer": "B", "category": case["category"],
        "difficulty": case["difficulty"], "query": case["query"],
        "expected_scope": case["expected_scope"],
        "expected_route": case["expected_route"],
        "http_status": status, "http_ok": status == expected_status_ok,
        "http_request_count": counters["http_request_count"] - http_before,
        "adapter_call_count": counters["adapter_call_count"] - adapter_before,
        "order_retriever_call_count": counters["order_retriever_call_count"] - order_before,
        "latency_ms": round(dt, 2),
        "guard_attempts_delta": guard.attempts - guard_before,
        "response": body,
        "failure_type": err,
        "answer_text": answer,
        "sources": sources,
    }
    if isinstance(body, dict) and body and not expected_empty_input:
        entry["structure_ok"] = all(
            k in body for k in ("category", "answer", "sources", "risk_level",
                                "handoff_required", "handoff_reason", "answer_mode", "risk_decision"))
        entry["category"] = body.get("category")
        entry["risk_level"] = body.get("risk_level")
        entry["handoff_required"] = body.get("handoff_required")
        entry["answer_mode"] = body.get("answer_mode")
        # risk floor：实际风险不低于期望下限
        ef = case.get("expected_risk_floor", "低")
        ar = body.get("risk_level")
        entry["risk_floor_ok"] = (RISK_ORDER.get(ar, 0) >= RISK_ORDER.get(ef, 0))
        eh = case.get("expected_handoff")
        entry["handoff_ok"] = (bool(body.get("handoff_required")) == bool(eh))
        # scope 对应行为：supported→本地降级(fallback)；gate→deterministic；422 除外
        if not expected_empty_input:
            if case["expected_scope"] == "supported":
                entry["scope_behavior_ok"] = body.get("answer_mode") == "fallback"
            elif case["expected_route"] == "api_deterministic":
                entry["scope_behavior_ok"] = body.get("answer_mode") == "deterministic"
            else:
                entry["scope_behavior_ok"] = body.get("answer_mode") in ("deterministic", "fallback")
        # sources 清洁：gate 用例不得携带知识片段
        if case["expected_route"] == "api_deterministic":
            entry["sources_clean"] = all(
                ("现有资料未覆盖" in s) or ("模拟订单数据" in s) for s in sources)
    else:
        entry["structure_ok"] = expected_empty_input and status == 422
        entry["scope_behavior_ok"] = expected_empty_input and status == 422
        entry["risk_floor_ok"] = True
        entry["handoff_ok"] = True
        entry["sources_clean"] = True

    entry["concept_checks"] = check_concepts(
        answer, case.get("required_answer_concepts") or [], CONCEPT_KEYWORDS)
    entry["forbidden_violations"] = [
        {"claim": c, "kind": k, "hit": h}
        for c, k, h in forbidden_violations(answer, case.get("forbidden_answer_claims"))]
    entry["leak_violations"] = [{"label": l, "hit": h} for l, h in find_leaks(answer)]
    return entry


# ---- B 层概念关键词固定映射（审计用；manual=True 表示语义完整度需人工复核）----
CONCEPT_KEYWORDS = {
    "蓝牙版本为5.3": (["5.3"], False),
    "单次续航约7小时": (["7小时", "约7"], False),
    "黑色/白色/蓝色三色": (["黑色", "白色", "蓝色"], False),
    "容量500ml": (["500ml", "500毫升"], False),
    "87键配列": (["87"], False),
    "红轴": (["红轴"], False),
    "可放置15.6英寸以内笔记本": (["15.6"], False),
    "五档亮度": (["五档", "5档"], False),
    "支持45分钟定时": (["45分钟"], False),
    "白色背光": (["背光"], False),
    "USB有线/蓝牙/2.4G三种连接方式": (["蓝牙", "2.4G"], False),
    "IPX4仅日常防泼溅": (["IPX4", "防泼溅"], False),
    "不支持游泳或长时间浸水": (["游泳", "浸水"], False),
    "小雨淋溅可以但避免进水": ([], True),
    "室温下约6小时保温": (["6小时"], False),
    "304不锈钢内胆": (["304"], False),
    "支持通话降噪": (["通话降噪", "降噪"], False),
    "主动降噪需耳机有电并正确佩戴": ([], True),
    "不建议装碳酸饮料": (["不建议", "碳酸"], False),
    "杯内压力升高有喷出风险": (["压力", "喷"], False),
    "到账时间需经支付渠道处理、AI无法保证": (["无法保证", "不能保证", "无法由"], False),
    "长时间未到账可转人工核实退款状态": (["人工"], False),
    "符合规则且商品完好、不属于排除范围可申请": (["完好", "符合"], False),
    "最终结果需人工审核": (["人工", "审核"], False),
    "可能存在同步延迟，建议先等待": (["延迟", "等待"], False),
    "超过24小时无更新转人工核实": (["24小时", "人工"], False),
    "先核对家人/前台/代收点": (["代收", "前台", "家人"], False),
    "仍未找到提供订单号转人工核查签收记录": (["订单号", "人工"], False),
    "未发货订单可转人工确认是否允许修改": (["未发货", "人工"], False),
    "已发货通常无法直接修改需联系物流公司": (["发货", "物流"], False),
    "耳机属可能影响卫生及二次销售的商品": (["卫生", "二次销售"], False),
    "拆封后能否无理由退货需人工结合商品状态审核": (["人工", "审核"], False),
    "AI不能直接承诺": (["承诺"], False),
    "资料未说明已提交订单的商品修改规则": (["未说明", "没有", "未覆盖", "无法确认"], False),
    "提供订单号由人工确认订单状态与处理方式": (["订单号", "人工"], False),
    "支付状态可能存在短暂延迟": (["延迟"], False),
    "先确认款项是否扣除并提供订单号": (["订单号", "扣"], False),
    "长时间未更新转人工核实": (["人工"], False),
    "USB-C充电/供电方式": (["USB", "供电", "充电", "插电"], False),
    "需连接电源使用": (["电源", "插电", "连接"], False),
    # 订单概念
    "该订单已签收、订单状态为已完成": (["签收", "已完成"], False),
    "如对订单有疑问可进一步人工核实": (["人工"], False),
    "该订单当前为待发货、暂无物流信息": (["待发货"], False),
    "只能提供当前状态不能承诺发货时间": (["不能承诺", "无法承诺", "时间"], False),
    "该订单实付金额299元（1件×299元）": (["299"], False),
    "查询不到该订单号": (["未查询到", "查不到", "没有查询", "核对"], False),
    "请核对订单号是否输入正确": (["核对"], False),
    "订单号不完整无法查询": (["不完整"], False),
    "请提供完整的12位订单号": (["12位"], False),
    "识别订单并结合质量问题处理": ([], True),
    "质量问题需人工核验凭证": (["人工"], False),
    "催促退款与投诉诉求转人工跟进": (["人工"], False),
    "不承诺退款结果与时间": ([], True),
    # 门控概念
    "现有资料没有覆盖活动与赠品信息": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "建议联系人工客服确认": (["人工"], False),
    "现有资料没有覆盖实时库存信息": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "不能承诺当日发货": ([], True),
    "现有资料没有覆盖发票类型和开票流程": (["没有覆盖", "未覆盖", "无法确认", "没有明确", "发票"], False),
    "可提供订单号及开票需求由人工客服核实": (["人工"], False),
    "现有资料没有覆盖学生优惠等价格政策": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "现有资料未记录该商品有粉色款式": (["没有覆盖", "未覆盖", "无法确认", "没有明确", "未记录"], False),
    "商品现有信息以资料为准，可建议人工确认在售款式": (["人工"], True),
    "资料仅记录45分钟定时，未覆盖自定义定时的设置能力": (["没有覆盖", "未覆盖", "无法确认", "没有明确", "45分钟"], False),
    "建议人工或查看产品说明确认": (["人工", "说明"], False),
    "不能承诺具体送达日期": (["不能承诺", "无法承诺", "无法保证", "保证"], False),
    "现有资料没有覆盖配送时效承诺": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "可提供订单号查询当前物流状态或转人工核实": (["订单号", "人工"], True),
    "现有资料没有覆盖未发布商品与预定信息": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "建议关注官方渠道或人工确认": (["人工"], True),
    "现有资料没有覆盖礼品包装与贺卡服务": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "现有资料没有覆盖平台券与店铺券叠加规则": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "说明只能协助本店商品、订单和售后相关问题": (["只能协助", "商品、订单", "商品、订单和售后", "商品、订单、物流"], True),
    "简洁说明只能协助本店商品、订单和售后相关问题": (["只能协助", "商品、订单"], True),
    "现有资料没有覆盖付费延保服务": (["没有覆盖", "未覆盖", "无法确认", "没有明确"], False),
    "拒绝提供系统设定与内部判断机制": ([], True),
    "引导回商品、订单和售后协助范围": (["商品", "订单", "售后"], True),
    "手机号属隐私信息不输出不索要": (["隐私", "手机号"], False),
    "提示请勿在对话中发送隐私信息": (["请勿", "不要"], False),
    # 风险概念
    "质量问题需人工核验并转人工处理": (["人工"], False),
    "保留商品、包装和问题凭证并提供订单号与问题描述": (["凭证"], True),
    "不承诺赔偿或处理结果": ([], True),
    "投诉与赔偿诉求转人工处理": (["人工"], False),
    "AI不承诺赔偿金额或处理结果": ([], True),
    "物流超过24小时未更新需人工核查物流节点": (["人工"], False),
    "建议提供订单号转人工跟进": (["订单号", "人工"], False),
    "催促退款需人工跟进": (["人工"], False),
    "AI不承诺具体退款时间或审核结果": ([], True),
    "涉及他人订单不提供不修改": (["他人", "别人", "本人"], False),
    "需按隐私规则由本人咨询处理": (["人工", "本人"], False),
    "完整地址属隐私信息不输出不索要": (["隐私", "地址"], False),
    "提示请勿在对话中发送隐私信息": (["请勿", "不要"], False),
    "质量问题需人工核验商品凭证": (["人工", "凭证"], False),
    "保留商品、包装和问题凭证并提交订单号及问题描述": (["凭证"], True),
    "按键失灵属质量问题需人工核验": (["人工"], False),
    "保留商品与凭证并提交订单号和问题描述": (["凭证"], True),
    "灯光闪烁属质量故障需人工核验凭证": (["人工"], False),
    "保留商品、包装与问题凭证并提供订单号和问题描述": (["凭证"], True),
    "涉及投诉与曝光诉求转人工处理": (["人工"], False),
    "AI不承诺任何赔偿金额或处理结果": ([], True),
    "实付金额与标价不一致属金额争议": ([], True),
    "需人工核对订单及支付记录": (["人工"], False),
    "要求作出资料范围外的保证属超范围承诺": ([], True),
    "必须转人工，AI不作超出资料的承诺": (["人工"], False),
    "涉他人订单/隐私转人工": (["人工"], False),
    "部件损坏属质量问题需人工核验": (["人工"], False),
    "保留商品包装与问题凭证并提交订单号和问题描述": (["凭证"], True),
    "退货申请最终由人工审核": (["人工"], False),
    "充电故障属质量问题需人工核验凭证": (["人工"], False),
    "杯体破损属质量问题需人工核验凭证": (["人工"], False),
    "承诺可开专票/纸质票": ([], True),
    "果汁非碳酸可以盛放": ([], True),
    "面料仅短时防泼水、拉链和缝线处不完全防水": (["防泼水", "防水"], False),
    "电脑仓适合15.6英寸以内，16英寸无法保证放入": (["15.6"], False),
    "支持iOS等常见蓝牙设备": (["iOS", "苹果", "手机"], False),
    "支持主动降噪且需耳机有电并正确佩戴": (["降噪"], False),
    "不含充电电池需连接电源使用": (["电池", "电源", "插电"], False),
    "三档色温": (["三档", "3档"], False),
    "支持USB有线、蓝牙、2.4G三种连接方式": (["蓝牙", "2.4G"], False),
    "兼容Windows系统": (["Windows", "Windows"], False),
    "材质与是否可装果汁两个子问均落在P003资料": ([], True),
    "商品、订单、售后范围说明": (["商品"], True),
}


# ===========================================================================
# 正式执行
# ===========================================================================

class _DeepSeekGuard:
    def __init__(self):
        self.attempts = 0
        self.events = []

    def wrap(self, module):
        orig = module.generate_reply

        def guarded(*a, **k):
            self.attempts += 1
            self.events.append("generate_reply 被意外调用（已阻断并计数）")
            raise RuntimeError("DeepSeekGuard: blind v2 评测期间禁止调用 DeepSeek")

        module.generate_reply = guarded
        self._orig = orig
        return orig


def _preflight(paths):
    """返回 (ok, reason)。校验：无既有结果/执行清单；manifest 状态与计数；哈希一致。"""
    if os.path.exists(paths["results"]) or os.path.exists(paths["exec_manifest"]):
        return False, "正式结果或执行清单已存在，拒绝再次执行（一次性原则）"
    root = paths.get("backend_root", BACKEND)
    bm = json.load(open(paths["blind_manifest"], encoding="utf-8"))
    if bm.get("status") != "frozen_pending_one_time_evaluation":
        return False, "blind manifest 状态不是 frozen_pending_one_time_evaluation"
    if bm.get("execution_count") != 0 or bm.get("final_blind_v2_executed"):
        return False, "execution_count!=0 或已有执行记录"
    if sha256_file(paths["blind_set"]) != BLIND_SET_SHA:
        return False, "final_blind_set_v2.json SHA-256 与冻结值不一致"
    rt = json.load(open(paths["runtime_manifest"], encoding="utf-8"))
    for f, h in rt["files_sha256"].items():
        p = os.path.normpath(os.path.join(root, f))
        if sha256_file(p) != h:
            return False, "候选文件哈希不一致: %s" % f
    for f, h in bm["files_sha256"].items():
        p = os.path.normpath(os.path.join(root, f))
        if sha256_file(p) != h:
            return False, "盲测资产哈希不一致: %s" % f
    return True, "ok"


def _hash_runtime_and_blind(paths):
    root = paths.get("backend_root", BACKEND)
    rt = json.load(open(paths["runtime_manifest"], encoding="utf-8"))
    cand = {f: sha256_file(os.path.normpath(os.path.join(root, f)))
            for f in rt["files_sha256"]}
    bm = json.load(open(paths["blind_manifest"], encoding="utf-8"))
    blind = {f: sha256_file(os.path.normpath(os.path.join(root, f)))
             for f in bm["files_sha256"]}
    return cand, blind


def execute_once(paths=None, adapter_fn=None, client_factory=None, keep_going=True):
    """正式评测。paths/adapter_fn/client_factory 仅测试时注入；生产路径不重试。"""
    paths = paths or {
        "backend_root": BACKEND,
        "blind_set": os.path.join(BACKEND, BLIND_SET),
        "blind_manifest": os.path.join(BACKEND, BLIND_MANIFEST),
        "runtime_manifest": os.path.join(BACKEND, RUNTIME_MANIFEST),
        "results": os.path.join(BACKEND, RESULTS_PATH),
        "exec_manifest": os.path.join(BACKEND, EXEC_MANIFEST_PATH),
        "report": os.path.join(BACKEND, REPORT_PATH),
        "review": os.path.join(BACKEND, REVIEW_PATH),
    }
    ok, reason = _preflight(paths)
    if not ok:
        return {"refused": True, "reason": reason}

    # ---- DeepSeek 隔离（必须在导入 app 模块前设置 env）----
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["FORCE_DEEPSEEK_FAILURE"] = "true"
    guard = _DeepSeekGuard()

    sys.path.insert(0, BACKEND)
    import v3_retrieval_adapter as adapter_mod
    import deepseek_client as ds_mod
    import main as app_main
    from fastapi.testclient import TestClient

    orig_generate = guard.wrap(ds_mod)

    if adapter_fn is None:
        adapter_fn = adapter_mod.retrieve

    # 检索入口计数包装（B 层用；A 层直接用 adapter_fn 并单独计数）。
    # V3.2 勘误修复：各计数写入 counters 的独立字段，不再共用一个 "calls"。
    counters = new_call_counters()
    _orig_retrieve = adapter_mod.retrieve

    def counting_retrieve(msg):
        counters["adapter_call_count"] += 1
        counters["hybrid_call_count"] += 1
        return _orig_retrieve(msg)

    adapter_mod.retrieve = counting_retrieve

    cases = json.load(open(paths["blind_set"], encoding="utf-8"))["cases"]
    a_cases = [c for c in cases if c["evaluation_layer"] == "retrieval_scope_order"]
    b_cases = [c for c in cases if c["evaluation_layer"] == "api_contract"]

    cand_before, blind_before = _hash_runtime_and_blind(paths)
    exceptions = []

    a_records, a_latencies = [], []
    for c in a_cases:  # 原始顺序，不重试
        try:
            rec = evaluate_a_case(c, adapter_fn, counters)
        except Exception as e:
            rec = {"case_id": c["case_id"], "layer": "A", "failure_type":
                   "evaluator_exception: %s" % e, "adapter_calls": 1}
            exceptions.append("A/%s: %s" % (c["case_id"], e))
        a_records.append(rec)
        if rec.get("latency_ms") is not None:
            a_latencies.append(rec["latency_ms"])

    # ---- B 层：TestClient（进程内，含 lifespan 预热）----
    t0 = time.perf_counter()
    client_ctx = client_factory() if client_factory else TestClient(app_main.app)
    client = client_ctx.__enter__() if hasattr(client_ctx, "__enter__") else client_ctx
    b_startup_ms = (time.perf_counter() - t0) * 1000.0
    b_records, b_latencies = [], []
    try:
        for c in b_cases:  # 原始顺序，不重试
            try:
                rec = evaluate_b_case(c, client, counters, guard)
            except Exception as e:
                rec = {"case_id": c["case_id"], "layer": "B", "failure_type":
                       "evaluator_exception: %s" % e, "http_request_count": 1}
                exceptions.append("B/%s: %s" % (c["case_id"], e))
            b_records.append(rec)
            rec["guard_attempts_total"] = guard.attempts
            if rec.get("latency_ms") is not None:
                b_latencies.append(rec["latency_ms"])
    finally:
        try:
            client_ctx.__exit__(None, None, None)
        except Exception:
            pass
        adapter_mod.retrieve = _orig_retrieve
        ds_mod.generate_reply = orig_generate

    cand_after, blind_after = _hash_runtime_and_blind(paths)

    all_records = a_records + b_records
    completed = (len(a_records) == 60 and len(b_records) == 10
                 and all(r.get("failure_type") is None for r in all_records))
    summary = build_summary(a_records, b_records)
    results_doc = {
        "executed_at": datetime.now().isoformat(timespec="seconds"),
        "blind_set_sha256": sha256_file(paths["blind_set"]),
        "one_time_execution": True,
        "execution_completed": completed,
        "exceptions": exceptions,
        "deepseek": {"real_calls": 0, "guard_attempts": guard.attempts,
                     "guard_events": guard.events,
                     "note": "env Key 清空 + FORCE_DEEPSEEK_FAILURE=true + generate_reply 计数守卫"},
        "latency": {
            "A_layer": latency_stats(a_latencies),
            "B_layer": {"testclient_startup_warmup_ms": round(b_startup_ms, 2),
                        "api": latency_stats(b_latencies)},
        },
        "summary": summary,
        "records": all_records,
    }
    with open(paths["results"], "w", encoding="utf-8") as f:
        json.dump(results_doc, f, ensure_ascii=False, indent=1)

    exec_manifest = {
        "executed_at": results_doc["executed_at"],
        "execution_count": 1,
        "blind_set_sha256": results_doc["blind_set_sha256"],
        "runtime_manifest_sha256": sha256_file(paths["runtime_manifest"]),
        "evaluator_sha256": sha256_file(os.path.abspath(__file__)),
        "evaluator_test_sha256": (lambda p: sha256_file(p) if os.path.exists(p) else None)(
            os.path.join(BACKEND, "test_final_blind_v2_evaluator.py")),
        "candidate_files_sha256_before": cand_before,
        "candidate_files_sha256_after": cand_after,
        "candidate_hashes_match_before": all(
            v == json.load(open(paths["runtime_manifest"], encoding="utf-8"))["files_sha256"][k]
            for k, v in cand_before.items()),
        "candidate_hashes_match_after": all(
            v == json.load(open(paths["runtime_manifest"], encoding="utf-8"))["files_sha256"][k]
            for k, v in cand_after.items()),
        "blind_assets_sha256_before": blind_before,
        "blind_assets_sha256_after": blind_after,
        "blind_hashes_match_before": all(
            v == json.load(open(paths["blind_manifest"], encoding="utf-8"))["files_sha256"][k]
            for k, v in blind_before.items()),
        "blind_hashes_match_after": all(
            v == json.load(open(paths["blind_manifest"], encoding="utf-8"))["files_sha256"][k]
            for k, v in blind_after.items()),
        "a_layer_executed": len(a_records),
        "b_layer_executed": len(b_records),
        "all_70_completed": completed,
        # V3.2 勘误修复：各计数彼此独立，不再相加
        "counters_total": dict(counters),
        "per_case_http_request_max": max(
            ((r.get("http_request_count") or 0) for r in all_records), default=0),
        "per_case_adapter_calls_max": max(
            ((r.get("adapter_calls") or r.get("adapter_call_count") or 0)
             for r in all_records), default=0),
        "retries": 0,
        "exceptions": exceptions,
        "retrieval_executed": True,
        "api_chat_called": True,
        "deepseek_called": False,
        "old_final_blind_reexecuted": False,
        "final_blind_v2_executed": True,
    }
    with open(paths["exec_manifest"], "w", encoding="utf-8") as f:
        json.dump(exec_manifest, f, ensure_ascii=False, indent=1)
    return {"refused": False, "results": results_doc, "exec_manifest": exec_manifest}


# ===========================================================================
# 汇总指标
# ===========================================================================

def build_summary(a_records, b_records):
    s = {}
    # A 层 supported 检索指标
    v3 = [r for r in a_records if r.get("answer_hit1") is not None]
    n = len(v3)
    s["A_supported_n"] = n
    s["answer_hit1"] = (sum(r["answer_hit1"] for r in v3) / n) if n else None
    # union Hit@3 为正式达标口径；answer_recall3(coverage) 仅作补充指标，两者不得混称
    u3 = [r.get("union_hit3") for r in v3 if r.get("union_hit3") is not None]
    s["union_hit3"] = (sum(u3) / len(u3)) if u3 else None
    s["answer_recall3_coverage"] = (sum(r["answer_recall3"] for r in v3) / n) if n else None
    s["answer_recall3"] = s["answer_recall3_coverage"]  # 兼容旧字段名（coverage 口径）
    s["mrr"] = (sum(r["mrr"] for r in v3) / n) if n else None
    rr = [r["rule_recall3"] for r in v3 if isinstance(r.get("rule_recall3"), (int, float))]
    s["rule_recall3_cases"] = len(rr)
    s["rule_recall3"] = (sum(rr) / len(rr)) if rr else None
    # HR-08 质量缺陷：required 含 RULE-HR-08 且有数值 rule_recall3 的 supported 用例
    hr08 = [r["rule_recall3"] for r in v3
            if isinstance(r.get("rule_recall3"), (int, float))
            and "RULE-HR-08" in (r.get("required_rule_ids") or [])]
    s["hr08_recall3_cases"] = len(hr08)
    s["hr08_recall3"] = (sum(hr08) / len(hr08)) if hr08 else None
    # 订单路由用例的风险下限（HR 规则）转人工判定
    order_risk = [r for r in a_records if r.get("order_risk_handoff") is not None]
    s["order_risk_handoff_ok"] = (all(r["order_risk_handoff"] for r in order_risk)
                                  and bool(order_risk)) if order_risk else None
    # scope
    pairs = [(r["expected_scope"], r["actual_scope"]) for r in a_records]
    s["scope_confusion"] = confusion_matrix(pairs)
    s["scope_acc"] = sum(1 for e, a in pairs if e == a) / len(pairs) if pairs else None
    unsup = [r for r in a_records if r["expected_scope"] == "unsupported_business"]
    irr = [r for r in a_records if r["expected_scope"] == "irrelevant"]
    s["unsupported_false_pass"] = (sum(1 for r in unsup if r["actual_scope"] != "unsupported_business")
                                   / len(unsup)) if unsup else None
    s["irrelevant_false_pass"] = (sum(1 for r in irr if r["actual_scope"] != "irrelevant")
                                  / len(irr)) if irr else None
    # route
    s["route_acc"] = (sum(1 for r in a_records if r["expected_route"] == r["actual_route"])
                      / len(a_records)) if a_records else None
    # handoff / risk floor：expected_handoff 与实际 requires_handoff 对比
    # （unsupported_business 用例系统设计行为为 handoff=true，属语义差异，分层报告）
    handoff_pairs = [(r["expected_handoff"], r["requires_handoff"]) for r in a_records]
    s["A_handoff_strict_acc"] = (sum(1 for e, a in handoff_pairs if e == a) / len(handoff_pairs)
                                 if handoff_pairs else None)
    non_sem = [(e, a) for r, (e, a) in zip(a_records, handoff_pairs)
               if r["expected_scope"] != "unsupported_business"]
    s["A_handoff_acc_excluding_unsupported_semantics"] = (
        sum(1 for e, a in non_sem if e == a) / len(non_sem)) if non_sem else None
    s["A_unsupported_semantic_handoff_note"] = (
        "unsupported_business 冻结系统行为为 handoff=true（转人工核实）；"
        "A 层该类用例标注 expected_handoff=false，差异如实单列，不做修改")
    high_risk = [(e, a) for r, (e, a) in zip(a_records, handoff_pairs)
                 if r["expected_risk_floor"] == "高"]
    s["A_high_risk_handoff_success"] = (sum(1 for e, a in high_risk if a) / len(high_risk)
                                        if high_risk else None)
    s["A_high_risk_n"] = len(high_risk)
    # 订单事实判定汇总
    ochecks = [r.get("order_checks") for r in a_records if r.get("order_checks")]
    flat = [ok for oc in ochecks for k, ok in oc.items() if isinstance(ok, bool)]
    s["order_fact_acc"] = (sum(flat) / len(flat)) if flat else None
    # 订单
    order_recs = [r for r in a_records if r["expected_route"] == "v2_order_structured"]
    s["order_route_acc"] = (sum(1 for r in order_recs if r["actual_route"] == "v2_order_structured")
                            / len(order_recs)) if order_recs else None
    s["order_checks"] = {r.get("case_id", "?"): r.get("order_checks") for r in order_recs}
    # B 层
    bb = [r for r in b_records if r.get("http_status") is not None]
    s["B_n"] = len(bb)
    s["B_http_ok"] = (sum(1 for r in bb if r.get("http_ok")) / len(bb)) if bb else None
    s["B_structure_ok"] = (sum(1 for r in bb if r.get("structure_ok")) / len(bb)) if bb else None
    s["B_risk_floor_ok"] = (sum(1 for r in bb if r.get("risk_floor_ok")) / len(bb)) if bb else None
    s["B_handoff_ok"] = (sum(1 for r in bb if r.get("handoff_ok")) / len(bb)) if bb else None
    s["B_leak_violations"] = sum(len(r.get("leak_violations") or []) for r in b_records)
    s["B_forbidden_violations"] = sum(len(r.get("forbidden_violations") or []) for r in b_records)
    contract_ok = sum(
        1 for r in bb if r.get("http_ok") and r.get("structure_ok") and r.get("risk_floor_ok")
        and r.get("handoff_ok") and r.get("scope_behavior_ok") and r.get("sources_clean", True)
        and not r.get("leak_violations") and not r.get("forbidden_violations")
        and all(c.get("matched") is not False for c in (r.get("concept_checks") or [])))
    s["B_contract_pass"] = (contract_ok / len(bb)) if bb else None
    s["B_concept_manual_review"] = [
        {"case_id": r["case_id"], "concepts": [c["concept"] for c in (r.get("concept_checks") or [])
                                               if c.get("manual_review_required") or c.get("matched") is None]}
        for r in bb]
    return s


def main():
    ap = argparse.ArgumentParser(description="final blind set v2 一次性评测器")
    ap.add_argument("--execute-once", action="store_true",
                    help="显式进入正式评测（唯一一次）。默认仅打印计划。")
    args = ap.parse_args()
    if not args.execute_once:
        print("默认运行：不执行盲测。")
        print("正式评测命令：python -X utf8 backend/evaluate_final_blind_v2.py --execute-once")
        print("计划见 backend/data/final_blind_v2_eval_plan.md；目标阈值已在脚本 TARGETS 固定。")
        return 0
    out = execute_once()
    if out.get("refused"):
        print("拒绝执行：%s" % out["reason"])
        return 2
    r = out["results"]
    print("执行完成：A层 %d 条 + B层 %d 条" % (
        sum(1 for x in r["records"] if x["layer"] == "A"),
        sum(1 for x in r["records"] if x["layer"] == "B")))
    print("DeepSeek guard attempts:", r["deepseek"]["guard_attempts"])
    print("结果：", RESULTS_PATH)
    print("执行清单：", EXEC_MANIFEST_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
