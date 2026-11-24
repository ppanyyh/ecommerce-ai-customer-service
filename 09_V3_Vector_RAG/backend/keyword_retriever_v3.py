"""V3.0 关键词检索器（仅本地检索，不调用 DeepSeek，不接入 /api/chat）。

检索对象与向量库一致：knowledge_chunks.jsonl 中的 5 商品 + 20 FAQ + 8 规则（不含订单）。

评分设计（确定性、可解释，词表全部来自 knowledge_base.json 已有字段与片段自身字段，
不使用任何评测问题作为关键词，不修改 knowledge_base.json 的 aliases/keywords）：
1. 商品编号/规则编号精确匹配（P001、HR-01，大小写不敏感）：最高权重；
2. 商品名称与别名（kb products.name + aliases）；
3. FAQ 问题与已有 keywords（kb faqs.keywords）、规则已有触发关键词
   （kb handoff_rules.keywords）；
4. 字段名称和属性词（静态属性词表，仅当该词同时出现在对应片段原始 text 中才计分）；
5. 完整短语匹配权重高于单字匹配（按词长加权，>=4字短语额外加分）；
6. 中文字符重合（查询与片段显著字符集交集，低权重、设上限，用于兜底召回）；
7. 订单号（12位数字形如 2026xxxxxxxx）不触发任何编号加分，订单由结构化查询处理。

统一返回结构：
    [{"chunk_id", "text"(原始text), "source", "doc_type", "rank",
      "keyword_score", "matched_terms"}]

运行方式：由混合检索器/评测脚本导入使用。
"""

import json
import os
import re

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNKS_PATH = os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl")
KB_PATH = os.path.join(BACKEND_DIR, "knowledge_base.json")

# 编号与订单号模式
RE_PRODUCT_ID = re.compile(r"\bP\d{3}\b", re.IGNORECASE)
RE_RULE_ID = re.compile(r"\bHR-?\d{2}\b", re.IGNORECASE)
RE_ORDER_ID = re.compile(r"(?<!\d)20\d{10}(?!\d)")

# 属性词表（字段名称/属性词，来自片段原始 text 中出现的规范字段与常用属性问法）
ATTRIBUTE_WORDS = [
    "售价", "价格", "多少钱", "型号", "颜色", "保修", "续航", "电池", "容量",
    "材质", "防水", "降噪", "亮度", "色温", "功率", "定时", "充电", "接口",
    "配列", "轴体", "蓝牙", "包装", "说明书", "耳帽", "内胆", "保温", "隔层",
    "电脑仓", "背光", "兼容", "系统", "发货", "物流", "签收", "退货", "退款",
    "换货", "订单", "支付", "付款", "发票", "投诉", "赔偿", "质量", "地址",
]

# 停用字符（不参与汉字重合统计）
_STOP_CHARS = set("的了吗呢吧啊嘛哦呀是在我你他它们这个那个有和跟与就直接被把让给我说问想能可以怎么怎么样多少什什么")

_index = None


def _load_kb():
    with open(KB_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_index():
    """构建每个片段的关键词索引（编号/别名/关键词/属性词/显著汉字集）。"""
    kb = _load_kb()
    alias_map = {p["id"]: {"name": p.get("name", ""), "aliases": p.get("aliases", [])}
                 for p in kb.get("products", [])}
    faq_kw = {f["id"]: f.get("keywords", []) for f in kb.get("faqs", [])}
    rule_kw = {r["id"]: r.get("keywords", []) for r in kb.get("handoff_rules", [])}

    records = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            rid = c["ref_id"]
            rec = {
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                "source": c["source"],
                "doc_type": c["doc_type"],
                "ref_id": rid,
                "title": c.get("title", ""),
                "category": c.get("category", ""),
                "id_token": rid.lower(),           # p001 / hr-01
                "id_norm": rid.replace("-", "").lower(),  # hr01（容错）
                "aliases": [],
                "keywords": [],
            }
            if c["doc_type"] == "product":
                info = alias_map.get(rid, {})
                rec["aliases"] = [info.get("name", "")] + list(info.get("aliases", []))
            elif c["doc_type"] == "faq":
                rec["keywords"] = list(faq_kw.get(rid, []))
                rec["aliases"] = [c.get("title", "")]
            elif c["doc_type"] == "rule":
                rec["keywords"] = list(rule_kw.get(rid, []))
                rec["aliases"] = [c.get("title", "")]
            # 显著汉字集：标题+别名+关键词中的汉字
            salient = "".join(rec["aliases"]) + "".join(rec["keywords"]) + rec["title"]
            rec["salient_chars"] = {ch for ch in salient if "\u4e00" <= ch <= "\u9fff"}
            rec["text_chars"] = {ch for ch in c["text"] if "\u4e00" <= ch <= "\u9fff"}
            records.append(rec)
    return records


def _get_index():
    global _index
    if _index is None:
        _index = _build_index()
    return _index


def keyword_search(query, top_k=10):
    """关键词检索。返回统一结构列表（keyword_score 降序，平分时按片段文件顺序）。"""
    query = (query or "").strip()
    if not query:
        return []
    q = query.lower()
    q_chars = {ch for ch in q if "\u4e00" <= ch <= "\u9fff"}

    scored = []
    for idx, rec in enumerate(_get_index()):
        terms = []
        score = 0.0

        # 1. 编号精确匹配（订单号模式不参与，先剥离避免误配）
        q_no_order = RE_ORDER_ID.sub(" ", q)
        id_hit = False
        if RE_PRODUCT_ID.search(q_no_order.upper()) or RE_RULE_ID.search(q_no_order.upper()):
            toks = {m.group(0).lower().replace("-", "") for m in
                    RE_PRODUCT_ID.finditer(q_no_order.upper())} | \
                   {m.group(0).lower().replace("-", "") for m in
                    RE_RULE_ID.finditer(q_no_order.upper())}
            if rec["id_norm"] in toks:
                score += 50.0
                id_hit = True
                terms.append(f"{rec['ref_id']}(编号精确命中)")

        # 2. 名称与别名（完整短语包含匹配）
        for alias in rec["aliases"]:
            alias_l = alias.lower()
            if len(alias_l) >= 2 and alias_l in q_no_order:
                score += 8.0 if len(alias_l) >= 4 else 6.0
                terms.append(alias)

        # 3. FAQ/规则已有关键词（短语权重高于单字）
        for kw in rec["keywords"]:
            kw_l = kw.lower()
            if kw_l in q_no_order:
                if len(kw_l) >= 2:
                    score += 6.0 + (2.0 if len(kw_l) >= 4 else 0.0)  # 完整短语加分
                    terms.append(kw)
                else:
                    score += 1.0  # 单字关键词低权重
                    terms.append(kw)

        # 4. 属性词：查询与该片段原始 text 同时出现才计分
        for w in ATTRIBUTE_WORDS:
            if w in q and w in rec["text"]:
                score += 1.5
                terms.append(f"{w}(属性)")

        # 6. 汉字重合兜底（显著字符集 ∩ 查询，低权重，上限3.0）
        overlap = q_chars & rec["salient_chars"]
        score += min(0.2 * len(overlap), 3.0)
        if overlap:
            terms.append(f"汉字重合x{len(overlap)}")

        if score > 0:
            scored.append((score, idx, rec, terms))

    scored.sort(key=lambda t: (-t[0], t[1]))
    results = []
    for rank, (score, _, rec, terms) in enumerate(scored[:max(int(top_k), 1)], start=1):
        results.append({
            "chunk_id": rec["chunk_id"],
            "text": rec["text"],  # 原始 text，与向量检索器口径一致
            "source": rec["source"],
            "doc_type": rec["doc_type"],
            "rank": rank,
            "keyword_score": round(score, 4),
            "matched_terms": terms,
        })
    return results


def detect_order_query(query):
    """识别查询中是否含 12 位订单号（2026xxxxxxxx）。订单由结构化查询处理，不走知识检索。"""
    return bool(RE_ORDER_ID.search(query or ""))


if __name__ == "__main__":
    for r in keyword_search("P001的耳机续航多久", top_k=3):
        print(f"{r['rank']}. {r['chunk_id']} [{r['doc_type']}] score={r['keyword_score']} terms={r['matched_terms']}")
