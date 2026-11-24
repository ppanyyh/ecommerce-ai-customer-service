# -*- coding: utf-8 -*-
"""V3.1 第三阶段：/api/chat 的 V3.1 混合检索适配器。

职责边界：只做接口适配，不复制、不改写 V3.1 检索算法（算法在冻结的
hybrid_retriever_v2 / query_analyzer / keyword_retriever_v3 / vector_retriever 中）。

1. 订单路由：消息含完整 12 位或疑似 6-11 位订单号 → 委托 V2 retriever.retrieve，
   完整保留结构化订单精确查询（存在性、状态、金额、物流、风险标注）；
   订单数据不写入向量库。
2. 其余问题 → hybrid_retriever_v2.hybrid_search_v2（V3.1 冻结检索内核）。
3. 将 V3 结果转换为 main.py 现有回答流程需要的 retrieval 结构
   （matched / match_type / matched_ids / sources / context /
   requires_handoff / handoff_reason，兼容 V2 的 _fallback_category）。
4. context 一律使用知识片段原始 text（retrieval_text 仅用于索引，不作为事实输出）。
5. 风险下限：结果中的规则片段（RULE-HR-*）或 analyzer 识别的风险意图
   → requires_handoff=True + 对应规则原因（取最高风险）。
6. 门控三分类：unsupported_business / irrelevant → 返回 gate_scope 标记的空结果结构，
   由 main.py 确定性分支本地回复（不调用 DeepSeek、不携带任何知识片段）。
7. 面向用户的信息边界：HR 编号、内部 SOP 名称、scope 内部标签、门控逻辑、
   向量相似度、关键词/RRF 分数、阈值等只保留在内部结构（handoff_reason /
   context / sources），不进入面向用户的 answer。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import retriever  # noqa: E402  （复用 V2 订单精确查询、风险规则、清洗工具）
import risk_intents  # noqa: E402  （V3.2.1：订单路由的补充本地风险下限）
from hybrid_retriever_v2 import hybrid_search_v2  # noqa: E402（冻结检索内核）

TOP_K = 5

# V3.2.2：统一风险等级定义（原 _RISK_ORDER=("高","中","低") 为反序缺陷，
# 会在多风险候选中取较低风险；现统一使用 risk_levels 的显式映射）
import risk_levels as risk_levels_mod

# 门控确定性回复结构（main.py 的 _deterministic_reply 按 gate_scope 分支处理）
_GATE_BASE = {
    "matched": False,
    "match_type": "v3_gate",
    "matched_ids": [],
    "sources": ["现有资料未覆盖"],
    "context": "",
    "confidence": 0.0,
    "retrieval_engine": "v3_1_hybrid_v2(gated)",
}


def _gated(scope: str, user_answer: str, requires_handoff: bool, reason: str) -> dict:
    r = dict(_GATE_BASE)
    r.update({
        "gate_scope": scope,
        "gate_user_answer": user_answer,
        "requires_handoff": requires_handoff,
        "handoff_reason": reason,
    })
    return r


def _risk_floor(chunk_ids, required_rule_ids, use_matched_rules=False):
    """根据 analyzer/安全网识别的必需规则，返回 (是否转人工, 原因, 风险等级)。
    V3.2 修订：仅"必需规则"（意图通道或安全网启用）触发转人工；
    仅出现在 Top-K 结果中的规则片段不再单独触发（避免普通问题被规则片段
    的偶发召回误判为高风险）。use_matched_rules 保留兼容旧调用。
    V3.2 bug 修复：required_rule_ids 可能带 "RULE-" 前缀（INTENT_RULE_MAP 与
    安全网返回 chunk_id 风格），而 retriever.RULES 的 id 是 "HR-01" 风格——
    统一去前缀后再匹配，否则风险意图全部无法触发转人工。
    V3.2.2：返回值增加规则风险等级（多规则取最高，统一映射），供 main
    的风险兜底链使用——规则等级不得被模型或本地结果降低。"""
    ids = set()
    for rid in required_rule_ids or []:
        if isinstance(rid, str) and rid:
            ids.add(rid[5:] if rid.startswith("RULE-") else rid)
    if use_matched_rules:
        for cid in chunk_ids or []:
            if isinstance(cid, str) and cid.startswith("RULE-"):
                ids.add(cid[len("RULE-"):])
    hits = [r for r in retriever.RULES if r["id"] in ids]
    if not hits:
        return False, "", "低"
    top = max(hits, key=lambda r: risk_levels_mod.RISK_SCORE[risk_levels_mod.normalize_risk(r["risk_level"])])
    level = risk_levels_mod.max_risk(*(r["risk_level"] for r in hits))
    return True, top["reason"], level


def _from_v3(message: str) -> dict:
    out = hybrid_search_v2(message, top_k=TOP_K)
    analysis = out.get("analysis") or {}

    # ---- 门控三分类：unsupported_business / irrelevant（含 unknown 证据不足兜底）----
    if not out.get("supported", True):
        scope = analysis.get("scope")
        if scope not in ("unsupported_business", "irrelevant"):
            scope = (out.get("gate_evidence") or {}).get("final_scope", "unsupported_business")
        if scope == "irrelevant":
            return _gated(
                "irrelevant",
                "抱歉，我只能协助处理本店商品、订单和售后相关问题。",
                requires_handoff=False, reason="")
        # unsupported_business：告知资料未覆盖 + 下一步（联系人工/提供订单号由人工核实）
        user_answer = (out.get("reason") or "现有资料没有覆盖这项信息，建议联系人工客服确认。").strip()
        return _gated(
            "unsupported_business",
            user_answer,
            requires_handoff=True,
            reason="知识库没有明确依据，必须转人工（《售后SOP》必须转人工）")

    # ---- supported：Top-K 原始片段构造 context ----
    results = out.get("results") or []
    if not results:
        # 理论上不会出现（supported 必有结果）；兜底按 V2 无命中处理
        return {
            "matched": False, "match_type": "v3_no_results", "matched_ids": [],
            "sources": ["现有资料未覆盖"], "context": "", "confidence": 0.0,
            "requires_handoff": False, "handoff_reason": "",
            "retrieval_engine": "v3_1_hybrid_v2(empty)",
        }

    ordered = sorted(results, key=lambda r: r.get("final_rank", 99))
    matched_ids = [r["chunk_id"] for r in ordered]
    ctx_lines, sources = [], []
    matched_texts = []
    for r in ordered:
        if r["source"] not in sources:
            sources.append(r["source"])
        ctx_lines.append("[来源：{}]片段 {}：{}".format(r["source"], r["chunk_id"], r["text"]))
        matched_texts.append({
            "chunk_id": r["chunk_id"],
            "text": r["text"],
            "source": r["source"],
            "doc_type": r["doc_type"],
        })
    context = "\n".join(ctx_lines)

    handoff, reason, rule_risk = _risk_floor(matched_ids, analysis.get("required_rule_ids"))
    top_type = ordered[0]["doc_type"]
    if handoff:
        match_type = "risk"          # _fallback_category -> 售后
    elif top_type == "product":
        match_type = "product"       # -> 商品
    else:
        match_type = "faq"           # -> 按 FAQ 分类（含订单与支付/物流等）

    # V3.2.1：转人工类型（HR-01..08，供 main 本地降级按风险类型给出下一步文案；
    # 仅内部字段，不进入用户可见 answer）
    handoff_kinds = sorted({
        (rid[5:] if rid.startswith("RULE-") else rid)
        for rid in (analysis.get("required_rule_ids") or [])})

    return {
        "matched": True,
        "match_type": match_type,
        "matched_ids": matched_ids,
        "sources": sources,
        "context": context,
        "matched_texts": matched_texts,
        "confidence": 1.0,
        "requires_handoff": handoff,
        "handoff_reason": reason,
        "handoff_kinds": handoff_kinds,
        # V3.2.2：必需规则的最高风险等级（风险兜底下限，不得被模型/本地降低）
        "risk_floor_level": rule_risk if handoff else "低",
        "retrieval_engine": "v3_1_hybrid_v2",
        # 内部调试信息（不进入用户可见 answer）
        "v3_scope": analysis.get("scope", "supported"),
        "v3_entity_pids": analysis.get("product_ids") or [],
        "v3_attr_keywords": analysis.get("covered_attribute_keywords") or [],
    }


def _order_local_payload(t: str) -> dict | None:
    """V3.2.1：结构化订单本地降级回答所需的最小字段集。
    只读取 V2 retriever.ORDERS 中该订单自身字段；不经向量库、不含任何其他订单；
    不编造预计送达/退款时间/审核结果。"""
    m12 = retriever._DIGIT12_RE.search(t)
    if m12:
        oid = m12.group(1)
        o = retriever.ORDERS.get(oid)
        if not o:
            return {"found": False, "incomplete": False, "order_id": oid}
        return {
            "found": True, "order_id": oid,
            "product_name": o.get("product_name", ""),
            "quantity": o.get("quantity"),
            "amount": o.get("amount"),
            "order_status": o.get("order_status", ""),
            "logistics_status": o.get("logistics_status", ""),
            "logistics_company": o.get("logistics_company", ""),
            "tracking_number": o.get("tracking_number", ""),
            "aftersales_status": o.get("aftersales_status", "无"),
        }
    return {"found": False, "incomplete": True}


def retrieve(message: str) -> dict:
    """/api/chat 的 V3.1 检索入口（与 retriever.retrieve 同构的返回结构）。"""
    t = retriever._clean(message or "")

    # ---- 订单路由：完整 12 位 / 疑似 6-11 位订单号 → V2 结构化订单查询 ----
    # 同时包含订单号与高风险表达时，V2 订单分支自带风险标注，
    # main.py 的 _risk_decision 本地风险下限仍然生效（模型不得降低风险）。
    if retriever._DIGIT12_RE.search(t) or retriever._DIGIT611_RE.search(t):
        r = retriever.retrieve(message)
        r["retrieval_engine"] = "v2_order_structured"
        # V3.2.1：附加结构化订单本地回答字段与转人工类型（不改变 V2 返回结构）
        r["order_local"] = _order_local_payload(t)
        _hits = retriever._detect_risk(t)
        kinds = {h["id"] for h in _hits}
        # V3.2.1 本地风险下限补充：V2 关键词表未覆盖的新表述（如已购缺陷描述）
        # 由 V3 结构化风险意图识别补充。只增不减：合并后若 V2 未判 handoff 而
        # V3 识别出风险意图，则提升为转人工（本地风险下限不得被降低）。
        try:
            v3_hits = risk_intents.detect_risk_intents(t)
            kinds |= {h["rule_id"][5:] for h in v3_hits}
        except Exception:
            v3_hits = []
        r["handoff_kinds"] = sorted(kinds)
        if kinds and not r.get("requires_handoff"):
            top = max(v3_hits, key=lambda h: risk_levels_mod.RISK_SCORE[
                risk_levels_mod.normalize_risk(
                    next(x["risk_level"] for x in retriever.RULES if x["id"] == h["rule_id"][5:]))])
            r["requires_handoff"] = True
            r["handoff_reason"] = next(
                x["reason"] for x in retriever.RULES if x["id"] == top["rule_id"][5:])
        # V3.2.2：规则等级风险兜底下限（V2 命中 + V3 意图合并 kinds 取最高）
        r["risk_floor_level"] = (
            risk_levels_mod.kinds_risk_level(r.get("handoff_kinds") or [])
            if (r.get("requires_handoff") or r.get("handoff_kinds"))
            else "低")
        return r

    # ---- 部分订单号识别（V3.2 新增，V3 适配层处理，不改动冻结的 V2）：----
    # 用户只提供"后四位/末四位 XXXX"时，V2 的 6-11 位正则无法识别。
    # 原则与 V2 一致：不得用部分号码猜测或模糊匹配订单，只能请求完整单号。
    m_part = _PARTIAL_ORDER_RE.search(t)
    if m_part:
        return {
            "matched": False, "match_type": "order", "matched_ids": [],
            "sources": ["《模拟订单数据》"],
            "context": ("你提供的订单号不完整（仅{}位：{}）。".format(
                len(m_part.group(1)), m_part.group(1))
                + "为避免匹配到错误订单，请提供完整的12位订单号后再查询。"),
            "confidence": 0.8,
            "requires_handoff": False, "handoff_reason": "",
            "retrieval_engine": "v2_order_structured",
            # 订单路由属支持域（供评测器 actual_scope 判定与 main 回答分支使用）
            "v3_scope": "supported",
            # V3.2.1：不完整订单号 → 本地回答要求完整12位
            "order_local": {"found": False, "incomplete": True},
            "handoff_kinds": [],
        }

    # ---- 其余问题 → V3.1 混合检索（冻结内核）----
    try:
        return _from_v3(message)
    except Exception:
        # 适配层兜底：V3 检索异常时不阻断服务，回退 V2 检索路径
        r = retriever.retrieve(message)
        r["retrieval_engine"] = "v2_fallback_on_v3_error"
        return r


# ===========================================================================
# V3.2 本地降级回答组稿（无 LLM；DeepSeek 不可用时 supported 问题不再只返回
# 通用致歉，而是基于检索结果原始 text 提取安全事实组稿）。
# 约束：
# - 只使用知识片段原始 text（retrieval_text 不作为事实来源）；
# - 不输出 HR 编号、SOP 名称、scope、门控、阈值、检索分数等内部信息；
# - 不编造资料外承诺；高风险不承诺结果，说明所需材料并明确转人工。
# ===========================================================================
import re as _re

# "后四位/末四位 XXXX" 部分订单号模式（仅 3-5 位数字的口述片段，避免与
# 商品编号/年份等混淆；完整 12 位与 6-11 位由 V2 正则优先处理）
_PARTIAL_ORDER_RE = _re.compile(r"(?:后|末)(?:四|4)位(?:是|:|：)?\s*(\d{3,5})")

_SENT_SPLIT_RE = _re.compile(r"[。；;！!？?\n\r]+")
_Q_STOP_CHARS = set("的吗呢吧的了是在我和跟与就还又再能可以要请帮我查看看下么什么多少几多久什么时候有无没不有对想")

# ---- 片段文本元信息净化（这些标记属于知识库内部结构，不得进入用户答案）----
_FAQ_PREFIX_RE = _re.compile(r"FAQ-\d+【[^】]*】\s*问题[:：]\s*")
_PRODUCT_PREFIX_RE = _re.compile(r"商品编号\s*P\d{3}\s*[:：]\s*")
_RULE_PREFIX_RE = _re.compile(r"售后转人工规则\s*HR-\d+\s*[:：]\s*")
_KEYWORDS_TAIL_RE = _re.compile(r"相关关键词[:：][^。；;！!？?\n]*")
_ALIAS_PAREN_RE = _re.compile(r"（别名[:：][^）]*）")
_CHUNK_ID_RE = _re.compile(r"\b(?:FAQ|PRODUCT|RULE)-[A-Z0-9-]+\b")


def _sanitize_text(text):
    """剥离片段文本中的内部元信息（chunk 编号/分类标记/关键词尾注/别名括号）。"""
    t = _FAQ_PREFIX_RE.sub("", text or "")
    t = _PRODUCT_PREFIX_RE.sub("", t)
    t = _RULE_PREFIX_RE.sub("", t)
    t = _KEYWORDS_TAIL_RE.sub("", t)
    t = _ALIAS_PAREN_RE.sub("", t)
    t = _CHUNK_ID_RE.sub("", t)
    # V3.2.1：片段原文中自指"知识库"的表述属内部口径，不进入用户答案
    # （FAQ-018："当前知识库没有统一的价保规则" → "当前没有统一的价保规则"）
    t = t.replace("当前知识库", "当前").replace("知识库", "")
    return t


# 多片段分点时的最大使用片段数（无实体指称的多意图问题）
_LOCAL_MAX_CHUNKS = 2
# 单片段最多提取句子数
_LOCAL_MAX_SENTS = 2
# 第 2 片段入选的最低句子相关分
_LOCAL_CHUNK2_MIN_SCORE = 0.45
# 属性关键词命中加成（问的是已覆盖属性时，优先含该关键词的句子）
_ATTR_BONUS = 0.30


def _sentence_score(sentence, query, attr_keywords=()):
    """句子与查询的相关性：查询实义字符覆盖度 + 数字加成 + 属性关键词加成。"""
    q_chars = set(c for c in query if c not in _Q_STOP_CHARS and not c.isspace())
    if not q_chars:
        return 0.0
    s_chars = set(sentence)
    overlap = len(q_chars & s_chars)
    score = overlap / max(len(q_chars), 1)
    # 查询问数量/时长而句中含数字时加成（参数类问题）
    if _re.search(r"几|多少|多久|多长|多大|几小时|几天", query) and _re.search(r"\d|[一二两三四五六七八九十]", sentence):
        score += 0.15
    # 目录已覆盖属性关键词命中加成（如"续航"→"单次续航约7小时"）
    for kw in attr_keywords or ():
        if kw and kw in sentence:
            score += _ATTR_BONUS
            break
    return score


def _extract_fact_sentences(text, query, attr_keywords=(), max_sents=_LOCAL_MAX_SENTS):
    """从片段原始 text（净化后）提取与查询最相关的句子（安全事实）。"""
    clean = _sanitize_text(text)
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(clean) if s.strip()]
    if not sents:
        return []
    scored = [(_sentence_score(s, query, attr_keywords), i, s) for i, s in enumerate(sents)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    picked = [t for t in scored if t[0] > 0][:max_sents]
    picked.sort(key=lambda t: t[1])  # 恢复原文顺序
    return [t[2] for t in picked]


def compose_local_answer(message, retrieval):
    """V3.2 本地降级组稿。返回用户可见回答文本；无法组稿时返回 None。

    - 高风险（requires_handoff）：不承诺结果，说明需要提供的材料，明确转人工；
    - supported：从 Top 片段原始 text 提取相关句子；查询明确指称某商品时只用
      Top-1 片段（避免混入其他商品内容），多意图/泛询可并入第 2 片段；
    - 不使用 LLM，不泄露 chunk 编号/分类标记/关键词尾注等内部信息。
    """
    if retrieval.get("gate_scope"):
        return None  # 门控场景由确定性分支处理
    if retrieval.get("requires_handoff"):
        return ("这个问题涉及售后权益核实，需要由人工客服为你处理。"
                "请提供订单号，并保留好商品、包装和问题部位的照片或视频凭证，"
                "人工客服会根据凭证为你核实处理，处理结果以人工核实为准。")
    texts = retrieval.get("matched_texts") or []
    # V3.2.1：规则片段（RULE-HR-*）属内部风控依据，其原文一律不进入用户答案
    #（含"未转人工"场景——规则条文的触发条件/处理方式不是面向消费者的事实）。
    texts = [t for t in texts
             if not str(t.get("chunk_id", "")).startswith("RULE-")]
    if not texts:
        return None
    attr_keywords = retrieval.get("v3_attr_keywords") or []
    has_entity = bool(retrieval.get("v3_entity_pids"))
    max_chunks = 1 if has_entity else _LOCAL_MAX_CHUNKS

    parts, prev_score = [], None
    for t in texts[:max(_LOCAL_MAX_CHUNKS, 1) * 2]:
        if len(parts) >= max_chunks:
            break
        sents = _extract_fact_sentences(t.get("text", ""), message, attr_keywords)
        if not sents:
            continue
        best = max(_sentence_score(_sanitize_text(s), message, attr_keywords) for s in sents)
        if prev_score is not None and best < _LOCAL_CHUNK2_MIN_SCORE:
            break  # 后续片段与问题相关性不足，不混入
        parts.append("，".join(sents) if len(sents) > 1 else sents[0])
        prev_score = best
    if not parts:
        return None
    if len(parts) == 1:
        answer = parts[0] + "。"
    else:
        answer = "1. {}；\n2. {}。".format(parts[0].rstrip("。；;"), parts[1].rstrip("。；;"))
    answer += "（以上为现有资料中的信息，如仍有疑问可提供订单号，由人工客服进一步核实。）"
    return answer
