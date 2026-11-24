# -*- coding: utf-8 -*-
"""本地知识检索器（阶段三）：retrieve(message) -> dict。

检索顺序：输入清洗 -> 订单号识别 -> 风险检测（独立维度）-> 商品检索 -> FAQ评分 -> 无匹配兜底。
只把命中的少量片段组装进 context（带[来源：...]标签），不把完整知识库发给模型。
业务口径全部来自 backend/knowledge_base.json（转述自原始资料，未编造）。
"""

import json
import os
import re

_KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base.json")
with open(_KB_PATH, encoding="utf-8") as _f:
    KB = json.load(_f)

PRODUCTS = {p["id"]: p for p in KB["products"]}
PRODUCT_ALIASES = {}
for _p in KB["products"]:
    for _a in [_p["id"], _p["name"]] + _p["aliases"]:
        PRODUCT_ALIASES[_a.lower()] = _p["id"]
ORDERS = {o["order_id"]: o for o in KB["orders"]}
FAQS = KB["faqs"]
RULES = KB["handoff_rules"]

# 商品属性同义词 -> 规格键（keys 与 knowledge_base.json attributes 一致）
ATTR_SYNONYMS = [
    ("续航", ["单次续航", "综合续航"]), ("电池", ["电池容量"]),
    ("防水", ["防护等级", "防水能力"]), ("游泳", ["防护等级", "注意事项"]),
    ("浸水", ["防护等级", "注意事项"]), ("防泼溅", ["防护等级"]),
    ("价格", ["售价"]), ("多少钱", ["售价"]), ("售价", ["售价"]), ("价位", ["售价"]),
    ("保修", ["保修期限"]), ("材质", ["材质"]), ("容量", ["容量"]),
    ("轴", ["轴体"]), ("连接", ["连接方式"]), ("蓝牙", ["蓝牙版本", "连接方式"]),
    ("降噪", ["降噪能力"]), ("色温", ["色温"]), ("亮度", ["亮度"]), ("功率", ["功率"]),
    ("充电", ["充电接口", "供电"]), ("供电", ["供电"]), ("接口", ["充电接口"]),
    ("定时", ["定时"]), ("颜色", ["颜色"]), ("配列", ["配列"]), ("键数", ["配列"]),
    ("电脑", ["电脑仓"]), ("笔记本", ["电脑仓"]), ("包装", ["包装内容"]), ("配件", ["包装内容"]),
    ("兼容", ["兼容设备", "系统兼容"]), ("系统", ["系统兼容"]), ("型号", ["型号"]),
    ("保温", ["保温参考"]),
]
_ATTR_KEYS = {k for attrs in (p["attributes"] for p in KB["products"]) for k in attrs} | {"售价"}

_PUNCT_RE = re.compile(r"[。？！?!，,、：:；;（）()\[\]{}【】\"'“”‘’…—~·<>《》]")
_DIGIT12_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_DIGIT611_RE = re.compile(r"(?<!\d)(\d{6,11})(?!\d)")


def _clean(text: str) -> str:
    """输入清洗：去多余空格、统一小写、去常见标点；不改变订单号与商品编号。"""
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return _PUNCT_RE.sub(" ", t)


def _empty(matched=False, match_type="none", **kw) -> dict:
    base = {
        "matched": matched, "match_type": match_type, "matched_ids": [],
        "sources": [], "context": "", "confidence": 0.0,
        "requires_handoff": False, "handoff_reason": "",
    }
    base.update(kw)
    return base


def _detect_risk(t: str):
    """风险检测（独立于问题分类）：命中即返回 (rule, rule_ids)。"""
    hits = []
    for r in RULES:
        if any(k in t for k in r["keywords"]):
            hits.append(r)
    return hits


def _risk_flag(hits):
    if not hits:
        return False, "", []
    top = max(hits, key=lambda r: ("高", "中", "低").index(r["risk_level"]))
    return True, top["reason"], hits


def _order_context(o: dict) -> str:
    lines = [
        f"[来源：{o['source']}]",
        f"订单号：{o['order_id']}（模拟数据）",
        f"商品：{o['product_name']} x{o['quantity']}（单价{o['unit_price']:.2f}元，合计{o['amount']:.2f}元）",
        f"订单状态：{o['order_status']}",
        f"物流状态：{o['logistics_status']}" + (f"（{o['logistics_company']} {o['tracking_number']}）" if o["tracking_number"] else ""),
        f"售后状态：{o['aftersales_status']}",
    ]
    if o["aftersales_status"] != "无":
        lines.append("提示：该订单存在进行中的售后申请，审核结果需人工处理，AI不作承诺。")
    return "\n".join(lines)


def _product_context(p: dict, attr_keys=None) -> str:
    keys = list(p["attributes"].keys()) if attr_keys is None else [k for k in attr_keys if k in _ATTR_KEYS]
    lines = [f"[来源：{p['source']}]", f"商品编号：{p['id']}", f"商品名称：{p['name']}"]
    for k in keys:
        # 售价存于独立 price 字段（与《商品资料》售价一致），其余取 attributes
        value = f"¥{p['price']:.2f}" if k == "售价" else p["attributes"][k]
        lines.append(f"{k}：{value}")
    if p.get("notes") and (attr_keys is None or any(k in ("防护等级", "注意事项") for k in (attr_keys or []))):
        lines.append("补充说明：" + " ".join(p["notes"]))
    return "\n".join(lines)


def _faq_score(t: str, f: dict) -> float:
    score = 0.0
    for k in f["keywords"]:
        if k.lower() in t:
            score += len(k) + 1
    for k in f.get("specific_keywords", []):
        if k in t:
            score += len(k) + 2  # 专用条目加权，优先于泛化FAQ
    if f["category"] in t:
        score += 1
    return score


def _find_product(t: str):
    for alias, pid in PRODUCT_ALIASES.items():
        if alias in t:
            return PRODUCTS[pid]
    return None


def _asked_attrs(t: str):
    """识别句中询问的属性（支持多属性），返回命中的规格键列表。"""
    keys = []
    for syn, ks in ATTR_SYNONYMS:
        if syn in t:
            for k in ks:
                if k in _ATTR_KEYS and k not in keys:
                    keys.append(k)
    return keys


def retrieve(message: str) -> dict:
    t = _clean(message)

    # ---------- 1) 订单号识别（12位完整优先，不得模糊匹配） ----------
    m12 = _DIGIT12_RE.search(t)
    if m12:
        oid = m12.group(1)
        o = ORDERS.get(oid)
        if o:
            handoff, reason, hits = _risk_flag(_detect_risk(t))
            return _empty(True, "order", matched_ids=[oid],
                          sources=[o["source"]], context=_order_context(o),
                          confidence=1.0, requires_handoff=handoff, handoff_reason=reason)
        known = "、".join(sorted(ORDERS))
        return _empty(True, "order",
                      sources=["《模拟订单数据》"],
                      context=(f"未查询到该模拟订单（订单号 {oid}）。当前知识库仅包含以下模拟订单：{known}，"
                               f"不得编造不存在订单的任何信息。"),
                      confidence=0.9)
    m611 = _DIGIT611_RE.search(t)
    if m611:
        return _empty(True, "order",
                      sources=["《模拟订单数据》"],
                      context=(f"你输入的订单号可能不完整（检测到 {m611.group(1)}，共{len(m611.group(1))}位）。"
                               f"请提供完整的12位订单号后再查询；不得猜测或匹配其他订单。"),
                      confidence=0.8)

    # ---------- 2) 风险检测（独立维度，先记录，最后统一并入返回） ----------
    risk_hits = _detect_risk(t)
    handoff, reason, risk_hits = _risk_flag(risk_hits)

    # ---------- 3) 商品检索（编号/全名/别名，支持多属性） ----------
    product = _find_product(t)
    attr_keys = _asked_attrs(t) if product else []

    # ---------- 4) FAQ评分（最多3条，低于阈值不强配） ----------
    scored = sorted(((_faq_score(t, f), f) for f in FAQS), key=lambda x: -x[0])
    faq_hits = [f for s, f in scored if s >= 2][:3]

    # ---------- 5) 分支决策 ----------
    if product and attr_keys:
        # 命中商品且识别出属性（含多属性）-> 商品资料上下文
        return _empty(True, "product", matched_ids=[product["id"]],
                      sources=[product["source"]], context=_product_context(product, attr_keys),
                      confidence=0.95, requires_handoff=handoff, handoff_reason=reason)
    if faq_hits:
        ids = [f["id"] for f in faq_hits]
        srcs, ctx = [], []
        for f in faq_hits:
            if f["source"] not in srcs:
                srcs.append(f["source"])
            ctx.append(f"[来源：{f['source']}]FAQ {f['id']}（{f['category']}）：{f['question']}\n标准回答：{f['answer']}")
        if risk_hits:
            for r in risk_hits:
                if r["source"] not in srcs:
                    srcs.append(r["source"])
                if r["id"] not in ids:
                    ids.append(r["id"])
            ctx.append("[来源：" + risk_hits[0]["source"] + "]风险规则命中：" + risk_hits[0]["reason"])
        if not handoff and any(f["no_clear_basis"] for f in faq_hits):
            handoff = True
            reason = "现有资料没有该问题的明确规则依据，必须转人工（《售后SOP》必须转人工：知识库没有明确依据）"
        best = faq_hits[0]
        return _empty(True, "faq", matched_ids=ids, sources=srcs,
                      context="\n\n".join(ctx),
                      confidence=min(0.95, 0.55 + 0.05 * _faq_score(t, best) / 4),
                      requires_handoff=handoff, handoff_reason=reason)
    if product:
        # 命中商品但未识别出具体属性 -> 返回商品概要（全部规格）
        return _empty(True, "product", matched_ids=[product["id"]],
                      sources=[product["source"]], context=_product_context(product),
                      confidence=0.85, requires_handoff=handoff, handoff_reason=reason)
    if risk_hits:
        # 仅有风险诉求（如投诉赔偿）-> 返回转人工规则上下文
        srcs, ids, ctx = [], [], []
        for r in risk_hits:
            ids.append(r["id"])
            if r["source"] not in srcs:
                srcs.append(r["source"])
            ctx.append(f"[来源：{r['source']}]规则 {r['id']}（{r['name']}）：{r['reason']}（风险等级：{r['risk_level']}）")
        return _empty(True, "risk", matched_ids=ids, sources=srcs,
                      context="\n".join(ctx) + "\n注：AI不得直接承诺赔偿金额、退款结果或到账时间。",
                      confidence=0.85, requires_handoff=True, handoff_reason=reason)
    # ---------- 6) 无匹配 ----------
    return _empty(False, "none", sources=["现有资料未覆盖"],
                  context="现有资料未覆盖该问题，信息不足。不得编造商品、订单、政策或任何资料中不存在的内容；"
                          "如无法确认，应说明信息不足并建议转人工。",
                  confidence=0.0, requires_handoff=True,
                  handoff_reason="知识库没有明确依据，必须转人工（《售后SOP》必须转人工）")
