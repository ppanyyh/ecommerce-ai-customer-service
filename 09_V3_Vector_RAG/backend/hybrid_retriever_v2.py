"""V3.0 业务感知混合检索器 v2（关键词评分治理 + RRF 融合 + 业务规则后处理）。

原 backend/hybrid_retriever.py 保留不动，作为 hybrid_rrf_v1 基线；
本模块为第二版（hybrid_business_v2），仅本地检索，不调用 DeepSeek，不接入 /api/chat。

相对 v1 的改进（依据 retrieval_failure_diagnosis.json）：
1. 关键词评分治理 governed_keyword_search（在 V1 关键词检索结果之上重新计分，
   不修改被冻结的 keyword_retriever_v3.py，不修改 kb 的 aliases/keywords）：
   - 通用弱词降权：商品/购物/问题/怎么样/质量/订单/处理 单独出现不能构成高置信命中
     （每片段弱词贡献上限 WEAK_WORD_CAP=0.5）；
   - 多通道封顶：同一词通过 业务关键词/属性词 命中时只按最高通道计一次；
     已被明确匹配短语覆盖的汉字不再重复计入汉字重合；
   - 汉字重合仅作弱辅助：0.15/字、上限 0.8，低于任何明确业务词（单字关键词=1.0），
     "没有明确业务词时不能仅靠汉字重合进入高位"。
2. 实体保护：
   - 完整商品编号（P001）命中 → 对应 PRODUCT 片段强制 Top-1（与 v1 相同 id_boost）；
   - 商品名称/可靠别名/扩展同义词命中 → 对应 PRODUCT 片段 rrf_score += ALIAS_BOOST
     （业务提升，但保留相关 FAQ：boost 小于一个 RRF 名次差，配合 epsilon 裁决）。
3. epsilon 并列裁决（排序比较器）：
   分数差 < EPSILON 时视为并列 → 先比 vector_similarity（高者优先），
   再比是否明确实体匹配，最后按 chunk_id 稳定排序。
4. 风险规则保留位：仅当 query_analyzer 识别出具体风险意图（required_rule_ids）时：
   - 必需规则在候选 Top-10 中 → 确保进入最终 Top-3（不要求 Top-1）；
   - 最终 Top-3 结构 = 1 个可回答内容片段（doc_type != rule 的最高分者）+ 必需规则 + 综合分最高者；
   - 规则不在候选中 → 记录 rule_candidate_missing，不凭空创建资料；
   - 泛化词（质量/购物等）不会触发保留位（analyzer 不把泛化质量咨询算作缺陷意图）。
5. 业务范围门控：query_analyzer 判定 is_supported_domain=False 时直接返回
   {"supported": False, "reason": ..., "results": []}，不进入质量售后规则，不转人工。

固定融合参数与 v1 一致：RRF_K=60，KEYWORD_WEIGHT=VECTOR_WEIGHT=1.0，双路各取 Top-10。
text 一律为原始 text（与 v1 相同，retrieval_text 仅用于 Embedding）。

返回（dict）：
    {"supported": bool, "reason": str|None, "results": [...], "analysis": {...},
     "rule_reserved": [...], "rule_candidate_missing": [...]}
results 元素字段与 v1 一致（chunk_id/text/source/doc_type/keyword_rank/vector_rank/
keyword_score/vector_similarity/rrf_score/final_rank），治理后关键词分记为 keyword_score。
"""

import functools
import re

from keyword_retriever_v3 import (
    _get_index, ATTRIBUTE_WORDS, RE_ORDER_ID, RE_PRODUCT_ID,
)
from query_analyzer import analyze, EXTENDED_SYNONYMS
from vector_retriever import vector_search
import risk_intents  # noqa: F402  （安全网 HR-08 售前守卫复用）

RRF_K = 60
KEYWORD_WEIGHT = 1.0
VECTOR_WEIGHT = 1.0
KEYWORD_TOP_N = 10
VECTOR_TOP_N = 10

# ---- 可配置参数（初始值只用于精度并列/极小差距裁决，不做大范围覆盖）----
EPSILON = 0.0003          # RRF 分数差小于该值视为并列，按 vector_similarity 等裁决
ALIAS_BOOST = 0.0002      # 别名/同义词实体提升（小于半个 RRF 名次差，避免盖过直接命中的 FAQ）

# ---- 业务范围门控证据阈值（V3.1，仅用于 analyzer 无法判断的 "unknown" 问题；
#      在 v3_1_dev_cases.json 新开发集上校准，不针对旧盲测题设置）----
KEYWORD_GATE_THRESHOLD = 3.0   # 治理后关键词证据：明确业务词（别名/关键词）命中即 ≥6
VECTOR_GATE_THRESHOLD = 0.40   # 向量相似度：商品属性类口语问题约 0.40+，域外问题明显更低

# ---- 检索治理参数（V3.1，在 v3_1_dev_cases.json 上校准）----
RULE_NO_INTENT_PENALTY = 0.002  # 无风险意图时规则片段降权（≈3个RRF名次差）：
                                # 规则是转人工元信息，非风险场景不应压过内容片段

# ---- V3.2 风险语义安全网阈值（仅用 V3.2 开发集校准，禁止用任何盲测数据校准）----
RULE_NET_VEC_SIM = 0.42     # 规则片段向量相似度启用阈值（漏检改写 0.42+，售前咨询 ≤0.37）

# ---- 面向用户的门控文案（不含内部规则号/门控/阈值/分数）----
USER_REASON_UNSUPPORTED = "现有资料没有覆盖这项信息，建议联系人工客服确认。"
USER_REASON_IRRELEVANT = "抱歉，我只能协助处理本店商品、订单和售后相关问题。"

# ---- 关键词评分治理参数 ----
GENERIC_WEAK_WORDS = {"商品", "购物", "问题", "怎么样", "质量", "订单", "处理"}
WEAK_WORD_CAP = 0.5       # 通用弱词每片段贡献上限（不能单独构成高置信命中）
HAN_CHAR_SCORE = 0.15     # 汉字重合每字得分（弱辅助）
HAN_OVERLAP_CAP = 0.8     # 汉字重合上限（低于任何明确业务词的最小贡献 1.0）

RULE_ID_RE = re.compile(r"(?<![A-Za-z0-9])HR-?\d{2}(?![0-9])", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 治理后关键词检索（复用被冻结的 keyword_retriever_v3 索引数据，重新计分）
# ---------------------------------------------------------------------------
def _extended_alias_phrases():
    by_pid = {}
    for syn, pid in EXTENDED_SYNONYMS.items():
        by_pid.setdefault(pid, []).append(syn.lower())
    return by_pid


_EXT_ALIASES = None


def _get_ext_aliases():
    global _EXT_ALIASES
    if _EXT_ALIASES is None:
        _EXT_ALIASES = _extended_alias_phrases()
    return _EXT_ALIASES


def governed_keyword_search(query, top_k=10):
    """带评分治理的关键词检索。返回结构与 v1 keyword_search 一致（score 为治理后分）。"""
    query = (query or "").strip()
    if not query:
        return []
    q = query.lower()
    q_no_order = RE_ORDER_ID.sub(" ", q)
    q_chars = {ch for ch in q if "\u4e00" <= ch <= "\u9fff"}
    ext = _get_ext_aliases()

    scored = []
    for idx, rec in enumerate(_get_index()):
        terms = []
        evidence = 0.0          # 明确业务证据（编号/别名/业务关键词/属性词）
        weak_words = 0.0        # 通用弱词累计（上限 WEAK_WORD_CAP）
        han_part = 0.0          # 汉字重合（弱辅助，上限 HAN_OVERLAP_CAP）
        matched_strings = []    # 已计分的明确字符串（用于多通道封顶/汉字去重）

        # 1. 编号精确匹配（与 v1 相同：订单号先剥离）
        q_no_order_up = q_no_order.upper()
        if RE_PRODUCT_ID.search(q_no_order_up) or RULE_ID_RE.search(q_no_order_up):
            toks = {m.group(0).lower().replace("-", "") for m in RE_PRODUCT_ID.finditer(q_no_order_up)}
            toks |= {m.group(0).lower().replace("-", "") for m in RULE_ID_RE.finditer(q_no_order_up)}
            if rec["id_norm"] in toks:
                evidence += 50.0
                matched_strings.append(rec["ref_id"].lower())
                terms.append(f"{rec['ref_id']}(编号精确命中)")

        # 2. 名称与别名（含扩展同义词；完整短语包含匹配）
        aliases = list(rec["aliases"]) + ext.get(rec["ref_id"], [])
        for alias in aliases:
            alias_l = alias.lower()
            if len(alias_l) >= 2 and alias_l in q_no_order:
                evidence += 8.0 if len(alias_l) >= 4 else 6.0
                matched_strings.append(alias_l)
                terms.append(alias)

        # 3. 业务关键词（通用弱词单独降权）
        for kw in rec["keywords"]:
            kw_l = kw.lower()
            if kw_l not in q_no_order:
                continue
            if kw_l in GENERIC_WEAK_WORDS:
                weak_words += 0.25  # 累计受 WEAK_WORD_CAP 约束
                terms.append(f"{kw}(弱词)")
            else:
                evidence += 8.0 if len(kw_l) >= 4 else (6.0 if len(kw_l) >= 2 else 1.0)
                matched_strings.append(kw_l)
                terms.append(kw)

        # 4. 属性词：与片段原始 text 同时出现才计分；弱词表中的属性词跳过；
        #    同一词已通过业务关键词通道计分则不再叠加（多通道封顶）
        for w in ATTRIBUTE_WORDS:
            if w in GENERIC_WEAK_WORDS:
                continue
            if w in q and w in rec["text"]:
                if w in matched_strings:
                    continue
                evidence += 1.5
                matched_strings.append(w)
                terms.append(f"{w}(属性)")

        # 5. 汉字重合：仅弱辅助；已被明确匹配短语覆盖的汉字不重复计分
        covered = set("".join(matched_strings))
        overlap = (q_chars & rec["salient_chars"]) - covered
        if overlap:
            han_part = min(HAN_CHAR_SCORE * len(overlap), HAN_OVERLAP_CAP)
            terms.append(f"汉字重合x{len(overlap)}")

        weak_words = min(weak_words, WEAK_WORD_CAP)
        if evidence == 0:
            # 无明确业务证据时，弱证据整体不超过 HAN_OVERLAP_CAP(0.8)，
            # 永远低于任何明确业务词（单字关键词=1.0）——不能仅靠汉字重合进入高位。
            weak = min(weak_words + han_part, HAN_OVERLAP_CAP)
        else:
            weak = weak_words + han_part
        score = evidence + weak
        if score > 0:
            scored.append((score, idx, rec, terms, evidence > 0))

    scored.sort(key=lambda t: (-t[0], t[1]))
    results = []
    for rank, (score, _, rec, terms, expl) in enumerate(scored[:max(int(top_k), 1)], start=1):
        results.append({
            "chunk_id": rec["chunk_id"],
            "text": rec["text"],
            "source": rec["source"],
            "doc_type": rec["doc_type"],
            "rank": rank,
            "keyword_score": round(score, 4),
            "matched_terms": terms,
            # 是否存在显式业务证据（编号/别名/业务关键词/属性词命中）：
            # 仅靠通用弱词或汉字重合命中的片段该值为 False，
            # 用于融合并列时"显式业务证据优先"裁决（V3.1 调修）。
            "explicit_evidence": expl,
        })
    return results


# ---------------------------------------------------------------------------
# V3.2 风险语义安全网（独立风险候选通道）
# ---------------------------------------------------------------------------
def _rule_safety_net(query, vec_rule_hits, analysis):
    """对规则片段做独立证据判定（analyzer 意图通道漏检时的第二通道）。

    证据条件（组合式，防止单个信号触发）：
    1. 语义证据：某规则片段向量相似度 >= RULE_NET_VEC_SIM；
    2. 语境守卫：存在电商语境信号（has_commerce_signal）；
    3. 正反例差距守卫：以下"良性解释"成立时不启用——
       - analyzer 已识别普通业务意图（supported_intents，如退款进度/物流查询）；
       - 命中能力目录已覆盖属性（商品属性询问）；
       - 售前质量咨询句式（HR-08 专用守卫，复用 risk_intents 的售前守卫语义）。
    返回 [{"chunk_id", "reasons", "vec_sim"}]，仅内部调试使用。
    """
    if not analysis.get("has_commerce_signal"):
        return []
    if analysis.get("supported_intents"):
        return []
    if analysis.get("covered_attributes"):
        return []
    # V3.2.1 否定守卫：句中承诺动词均为否定形态（不能保证/保证不了/不用承诺…）
    # 时，"保证/修复"类语义相似不应作为启用安全网的证据（否定承诺不构成风险诉求）。
    if risk_intents.over_promise_negated(query):
        return []
    enabled = []
    for r in (vec_rule_hits or []):
        sim = r.get("similarity")
        if sim is None or sim < RULE_NET_VEC_SIM:
            continue
        cid = r["chunk_id"]
        reasons = ["vec>=%.2f" % RULE_NET_VEC_SIM]
        if cid == "RULE-HR-08" and risk_intents._DEFECT_PRESALE_GUARD.search(query):
            continue  # 售前质量咨询句式：缺陷规则不启用
        enabled.append({"chunk_id": cid, "reasons": reasons, "vec_sim": round(sim, 4)})
    return enabled


# ---------------------------------------------------------------------------
# 功能确认询问（类别级模式）："好使吗/好用吗/能用吗/灵不灵"等问的是使用体验或
# 兼容确认，解答型 FAQ（兼容/使用说明）通常比商品参数片段更贴切；
# 与担忧式问法同层：该场景下不启用实体优先与显式证据裁决（V3.2）。
# ---------------------------------------------------------------------------
_FUNCTION_CONFIRM_RE = re.compile(
    r"(好使|好用|使得住|能用|灵不灵|顺不顺|跟手)(吗|么|不)")


# ---------------------------------------------------------------------------
# RRF 融合 + epsilon 并列裁决
# ---------------------------------------------------------------------------
def _fuse(kw, vec):
    kw_map = {r["chunk_id"]: r for r in kw}
    vec_map = {r["chunk_id"]: r for r in vec}
    all_ids = list(dict.fromkeys([r["chunk_id"] for r in kw] + [r["chunk_id"] for r in vec]))
    fused = []
    for cid in all_ids:
        k_rec, v_rec = kw_map.get(cid), vec_map.get(cid)
        k_rank = k_rec["rank"] if k_rec else None
        v_rank = v_rec["rank"] if v_rec else None
        score = 0.0
        if k_rank is not None:
            score += KEYWORD_WEIGHT / (RRF_K + k_rank)
        if v_rank is not None:
            score += VECTOR_WEIGHT / (RRF_K + v_rank)
        base = k_rec or v_rec
        fused.append({
            "chunk_id": cid,
            "text": base["text"],
            "source": base["source"],
            "doc_type": base["doc_type"],
            "keyword_rank": k_rank,
            "vector_rank": v_rank,
            "keyword_score": k_rec["keyword_score"] if k_rec else None,
            "explicit_evidence": bool(k_rec["explicit_evidence"]) if k_rec else False,
            "vector_similarity": v_rec["similarity"] if v_rec else None,
            "rrf_score": round(score, 6),
        })
    return fused


def _sort_with_epsilon(fused, entity_pids, epsilon=EPSILON, concern_scenario=False,
                       intent_guided=False, function_confirm=False):
    """按 rrf_score 降序；差值 < epsilon 视为并列，裁决顺序：
    1. 实体片段且同时是关键词 Top-1（用户以名称/别名直接指代该商品）时，
       中性属性询问优先该商品片段；担忧式问法、带明确业务意图或功能确认
       询问（"好使吗/好用吗"等，解答型 FAQ 更贴切）时不启用实体优先；
    2. 显式业务证据优先（仅在"中性属性询问"场景，即非担忧、无明确业务意图时）：
       rrf 并列时，关键词侧有编号/别名/业务关键词/属性词等显式证据的片段，
       优先于仅靠汉字重合进入候选的片段；
    3. 否则 vector_similarity 高者优先；
    4. 最后按 chunk_id 稳定排序。
    intent_guided=True 表示用户携带明确业务意图（退款/发票/退货等）：
    实体商品片段只是上下文，解答型内容优先，跳过第 1/2 级实体与显式证据裁决。"""

    def entity_top_kw(r):
        if concern_scenario or intent_guided or function_confirm:
            return False
        return (any(pid in r["chunk_id"] for pid in entity_pids)
                and r["keyword_rank"] == 1)

    def cmp(a, b):
        sa, sb = a["rrf_score"], b["rrf_score"]
        if abs(sa - sb) >= epsilon:
            return -1 if sa > sb else 1
        ea, eb = entity_top_kw(a), entity_top_kw(b)
        if ea != eb:
            return -1 if ea else 1
        if not concern_scenario and not intent_guided and not function_confirm:
            xa = bool(a.get("explicit_evidence"))
            xb = bool(b.get("explicit_evidence"))
            if xa != xb:
                return -1 if xa else 1
        va = a["vector_similarity"] if a["vector_similarity"] is not None else -1.0
        vb = b["vector_similarity"] if b["vector_similarity"] is not None else -1.0
        if va != vb:
            return -1 if va > vb else 1
        if a["chunk_id"] != b["chunk_id"]:
            return -1 if a["chunk_id"] < b["chunk_id"] else 1
        return 0

    return sorted(fused, key=functools.cmp_to_key(cmp))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _gated_response(reason, analysis):
    """门控拒答响应（results 为空，reason 为面向用户的自然表达）。"""
    return {
        "supported": False,
        "reason": reason,
        "results": [],
        "analysis": analysis,
        "rule_reserved": [],
        "rule_candidate_missing": [],
    }


def hybrid_search_v2(query, top_k=5, epsilon=EPSILON):
    query = (query or "").strip()

    analysis = analyze(query)
    scope = analysis.get("scope", "unknown")

    # 业务范围门控：unsupported_business / irrelevant 直接拒答（面向用户的自然原因）；
    # supported 直接进入检索；unknown 交由下方检索证据判定。
    if scope in ("unsupported_business", "irrelevant"):
        reason = analysis.get("gate_reason") or (
            USER_REASON_UNSUPPORTED if scope == "unsupported_business" else USER_REASON_IRRELEVANT)
        return _gated_response(reason, analysis)

    if not query:
        return {"supported": True, "reason": None, "results": [],
                "analysis": analysis, "rule_reserved": [], "rule_candidate_missing": []}

    # FAQ 口语意图归一化：将 analyzer 给出的通用改写短语并入向量查询，提升召回
    rewrites = analysis.get("rewrites") or []
    vec_query = query + (" " + " ".join(rewrites) if rewrites else "")

    kw = governed_keyword_search(query, top_k=KEYWORD_TOP_N)
    vec = vector_search(vec_query, top_k=VECTOR_TOP_N)
    fused = _fuse(kw, vec)

    # unknown 兜底：analyzer 无明确信号时，用检索证据判断是否有足够支持；
    # 证据不足时按电商语境归类为 unsupported_business / irrelevant，不返回牵强结果。
    if scope == "unknown":
        kw_top = kw[0]["keyword_score"] if kw else 0.0
        vec_top = vec[0]["similarity"] if vec else 0.0
        if kw_top < KEYWORD_GATE_THRESHOLD and vec_top < VECTOR_GATE_THRESHOLD:
            final_scope = ("unsupported_business" if analysis.get("has_commerce_signal")
                           else "irrelevant")
            reason = (USER_REASON_UNSUPPORTED if final_scope == "unsupported_business"
                      else USER_REASON_IRRELEVANT)
            resp = _gated_response(reason, analysis)
            resp["gate_evidence"] = {"keyword_top_score": kw_top, "vector_top_similarity": vec_top,
                                     "final_scope": final_scope}
            return resp

    entity_pids = analysis["product_ids"]

    # 实体注入：用户明确指名商品（编号/别名/同义词）时，对应 PRODUCT 片段必须进入
    # 候选池——双路 Top-10 都没召回时不因其缺席而失去实体保护（V3.1 调修）。
    if entity_pids:
        index_by_id = {rec["chunk_id"]: rec for rec in _get_index()}
        present_ids = {r["chunk_id"] for r in fused}
        for pid in entity_pids:
            target = "PRODUCT-" + pid
            if target not in present_ids and target in index_by_id:
                rec = index_by_id[target]
                fused.append({
                    "chunk_id": rec["chunk_id"],
                    "text": rec["text"],
                    "source": rec["source"],
                    "doc_type": rec["doc_type"],
                    "keyword_rank": None,
                    "vector_rank": None,
                    "keyword_score": None,
                    "vector_similarity": None,
                    "rrf_score": 0.0,
                    "entity_injected": True,
                })

    # 无风险意图时规则片段降权：规则是转人工元信息，只有 analyzer 识别出
    # 具体风险意图时才作为主要结果；非风险场景不应压过内容片段（V3.1 调修）。
    # V3.2：降权后若安全网启用，启用规则不参与降权复核（保留位保证 Top-3）。
    if not analysis["required_rule_ids"]:
        for r in fused:
            if r["doc_type"] == "rule":
                r["rrf_score"] = round(max(r["rrf_score"] - RULE_NO_INTENT_PENALTY, 0.0), 6)
                r["rule_penalty_no_intent"] = True

    # ------------------------------------------------------------------
    # V3.2 风险语义安全网（独立风险候选通道，第二通道）：
    # analyzer 意图通道（第一通道）漏检时，对 8 条规则片段单独做证据判定——
    # 证据条件：规则业务关键词命中数 >= 2；或关键词命中 >=1 且规则向量相似度达标。
    # 阈值只用 V3.2 开发集校准，禁止用任何盲测数据校准。
    # 启用的规则并入 required_rule_ids 走保留位（确保进 Top-3，
    # 但不无条件抢占普通商品/FAQ 的 Top-1——头部裁决由保留位逻辑决定）。
    # 启用原因记录在 analysis["safety_net"]（仅内部调试，不展示给用户）。
    # ------------------------------------------------------------------
    if not analysis["required_rule_ids"]:
        vec_rule = vector_search(vec_query, top_k=3, filters={"doc_type": "rule"})
        net = _rule_safety_net(query, vec_rule, analysis)
        if net:
            net_ids = [e["chunk_id"] for e in net][:2]
            analysis["required_rule_ids"] = net_ids
            analysis["safety_net"] = net
            # 启用规则若不在候选池，注入 fused（与实体注入同构）
            index_by_id = {rec["chunk_id"]: rec for rec in _get_index()}
            present_ids = {r["chunk_id"] for r in fused}
            for nid in net_ids:
                if nid not in present_ids and nid in index_by_id:
                    rec = index_by_id[nid]
                    fused.append({
                        "chunk_id": rec["chunk_id"],
                        "text": rec["text"],
                        "source": rec["source"],
                        "doc_type": rec["doc_type"],
                        "keyword_rank": None,
                        "vector_rank": None,
                        "keyword_score": None,
                        "vector_similarity": None,
                        "rrf_score": 0.0,
                        "safety_net_injected": True,
                    })

    # 实体保护 2：名称/别名/同义词 → 业务提升（不移出已有更高分内容片段）。
    # V3.1：用户带明确业务意图（退款/发票/退货等）或担忧式问法时，实体商品片段只是
    # 上下文——跳过别名提升，交给向量相似度裁决（如发票咨询中"台灯"不应压过 FAQ-018）。
    intent_guided = bool(analysis.get("supported_intents"))
    entity_context_mode = intent_guided or analysis.get("has_concern_scenario", False)
    if analysis["product_aliases"] and not entity_context_mode:
        alias_pids = set(entity_pids)
        for r in fused:
            if r["doc_type"] == "product" and any(pid in r["chunk_id"] for pid in alias_pids):
                if not r.get("id_boost"):
                    r["rrf_score"] = round(r["rrf_score"] + ALIAS_BOOST, 6)
                    r["entity_boost"] = True

    ordered = _sort_with_epsilon(fused, entity_pids, epsilon,
                                 concern_scenario=analysis.get("has_concern_scenario", False),
                                 intent_guided=intent_guided,
                                 function_confirm=bool(_FUNCTION_CONFIRM_RE.search(query)))

    # 实体保护 1：完整商品编号（仅用户显式敲出 PXXX 时）→ 强制 Top-1。
    # V3.1 修正：别名/同义词推导出的商品不再强制 Top-1（此前会把"耳机→P001"这类
    # 别名命中强推到首位，压过双路排名都更高的 FAQ 内容片段）；别名只走 ALIAS_BOOST
    # 与 epsilon 裁决。编号命中在 epsilon 排序之后执行，保证不被比较器重新压回。
    exact_ids = analysis.get("exact_product_ids") or []
    if exact_ids and not RE_ORDER_ID.search(query):
        for pid in exact_ids:
            target = "PRODUCT-" + pid
            for i, r in enumerate(ordered):
                if r["chunk_id"] == target:
                    top = ordered.pop(i)
                    top["id_boost"] = True
                    ordered.insert(0, top)
                    break
            else:
                continue
            break

    # 风险规则保留位（仅在 analyzer 识别出具体风险意图时生效）。
    # V3.1 调修——Top-3 头部裁决：
    #   a) 自然榜首即必需规则时保留其首位——规则凭自身关键词/向量证据赢得榜首
    #      （如金额争议、隐私类问题），规则（转人工元信息）就是首要正确结果；
    #   b) 否则内容片段优先：Top-1 = 最高分非规则片段，必需规则（最多2条）随后
    #      确保进入 Top-3（转人工元信息不丢失，但不把低分规则顶到内容之前）。
    required_ids = list(analysis["required_rule_ids"])
    rule_reserved = []
    rule_missing = []
    if required_ids:
        cand_ids = {r["chunk_id"] for r in ordered}
        present = [rid for rid in required_ids if rid in cand_ids]
        rule_missing = [rid for rid in required_ids if rid not in cand_ids]
        if present:
            rules = [r for r in ordered if r["chunk_id"] in present][:2]  # Top-3 内最多 2 条规则
            c1 = next((r for r in ordered if r["doc_type"] != "rule"), None)
            top0 = ordered[0] if ordered else None
            if top0 is not None and top0["doc_type"] == "rule" and top0["chunk_id"] in present:
                head = top0
            else:
                head = c1
            chosen = [head] if head is not None else []
            for r in rules:
                if r["chunk_id"] not in {x["chunk_id"] for x in chosen}:
                    chosen.append(r)
            if c1 is not None and c1["chunk_id"] not in {x["chunk_id"] for x in chosen}:
                chosen.append(c1)
            chosen_ids = {r["chunk_id"] for r in chosen}
            rest = [r for r in ordered if r["chunk_id"] not in chosen_ids]
            ordered = chosen + rest
            rule_reserved = [r["chunk_id"] for r in rules]

    results = []
    for final_rank, r in enumerate(ordered[:max(int(top_k), 1)], start=1):
        r["final_rank"] = final_rank
        results.append(r)

    return {
        "supported": True,
        "reason": None,
        "results": results,
        "analysis": analysis,
        "rule_reserved": rule_reserved,
        "rule_candidate_missing": rule_missing,
    }


if __name__ == "__main__":
    import json
    for q in ["P001的耳机续航多久", "书包侧面能装下16寸电脑吗", "杯子到手就有裂痕要退款"]:
        out = hybrid_search_v2(q, top_k=3)
        print(q, "supported=", out["supported"])
        for r in out["results"]:
            print(f"  {r['final_rank']}. {r['chunk_id']} [{r['doc_type']}] rrf={r['rrf_score']:.6f} "
                  f"kw={r['keyword_rank']} vec={r['vector_rank']}")
