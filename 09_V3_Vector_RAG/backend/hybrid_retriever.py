"""V3.0 混合检索器（关键词 + 向量 RRF 融合；不调用 DeepSeek，不接入 /api/chat）。

hybrid_search(query, top_k=5) 流程：
1. keyword_retriever_v3.keyword_search 取 Top-10；
2. vector_retriever.vector_search 取 Top-10；
3. Reciprocal Rank Fusion 融合（固定参数 RRF_K=60，KEYWORD_WEIGHT=VECTOR_WEIGHT=1.0）：
       score = KEYWORD_WEIGHT / (RRF_K + keyword_rank)
             + VECTOR_WEIGHT / (RRF_K + vector_rank)
   某结果只存在于一种检索时，只计算该项；
4. 按 chunk_id 去重后按 rrf_score 降序返回 Top-K；
5. text 一律使用原始 text（两个子检索器均已从 knowledge_chunks.jsonl 取回原始内容，
   规则片段的 retrieval_text 仅用于 Embedding，不会作为 context 返回）。

业务确定性优先级：
- 查询中出现完整商品编号（如 P001）且对应商品在候选中时，该商品强制置顶
  （id_boost=True），满足"完整商品编号命中时对应商品必须优先"；
- 订单号（12位数字）不触发任何检索加分，订单继续由结构化查询处理；
- 风险拦截仍由 V2 本地风险检测保证，混合检索只补充资料召回，不替代权限与风险判断；
- FAQ 与规则语义相近时两者都保留，不因相似而删除其一。

返回字段：
    {"chunk_id", "text", "source", "doc_type",
     "keyword_rank"(int|None), "vector_rank"(int|None),
     "keyword_score"(float|None), "vector_similarity"(float|None),
     "rrf_score", "final_rank", "id_boost"(仅置顶时为 True)}
"""

import re

from keyword_retriever_v3 import keyword_search, detect_order_query
from vector_retriever import vector_search

RRF_K = 60
KEYWORD_WEIGHT = 1.0
VECTOR_WEIGHT = 1.0
KEYWORD_TOP_N = 10
VECTOR_TOP_N = 10

RE_ANY_ID = re.compile(r"\b(P\d{3}|HR-?\d{2})\b", re.IGNORECASE)


def hybrid_search(query, top_k=5):
    query = (query or "").strip()
    if not query:
        return []

    kw = keyword_search(query, top_k=KEYWORD_TOP_N)
    vec = vector_search(query, top_k=VECTOR_TOP_N)

    kw_map = {r["chunk_id"]: (r["rank"], r) for r in kw}
    vec_map = {r["chunk_id"]: (r["rank"], r) for r in vec}

    all_ids = list(dict.fromkeys(
        [r["chunk_id"] for r in kw] + [r["chunk_id"] for r in vec]
    ))  # 去重并保持首现顺序

    fused = []
    for cid in all_ids:
        k_rank, v_rank = kw_map.get(cid, (None, None))[0], vec_map.get(cid, (None, None))[0]
        score = 0.0
        if k_rank is not None:
            score += KEYWORD_WEIGHT / (RRF_K + k_rank)
        if v_rank is not None:
            score += VECTOR_WEIGHT / (RRF_K + v_rank)
        k_rec = kw_map[cid][1] if cid in kw_map else None
        v_rec = vec_map[cid][1] if cid in vec_map else None
        fused.append({
            "chunk_id": cid,
            "text": (k_rec or v_rec)["text"],
            "source": (k_rec or v_rec)["source"],
            "doc_type": (k_rec or v_rec)["doc_type"],
            "keyword_rank": k_rank,
            "vector_rank": v_rank,
            "keyword_score": k_rec["keyword_score"] if k_rec else None,
            "vector_similarity": v_rec["similarity"] if v_rec else None,
            "rrf_score": round(score, 6),
        })

    fused.sort(key=lambda r: (-r["rrf_score"],
                              r["keyword_rank"] if r["keyword_rank"] is not None else 99,
                              r["vector_rank"] if r["vector_rank"] is not None else 99,
                              r["chunk_id"]))

    # 业务确定性：完整商品/规则编号命中 → 对应片段强制置顶
    id_boost_applied = False
    m = RE_ANY_ID.search(query)
    if m and not detect_order_query(query):
        raw = m.group(0).upper()
        digits = re.sub(r"\D", "", raw)          # "001" / "01"
        if raw.startswith("P"):
            target_cid = "PRODUCT-P" + digits    # PRODUCT-P001
        else:
            target_cid = "RULE-HR-" + digits     # RULE-HR-01（hr01 亦归一化）
        for i, r in enumerate(fused):
            if r["chunk_id"] == target_cid:
                top = fused.pop(i)
                top["id_boost"] = True
                fused.insert(0, top)
                id_boost_applied = True
                break

    results = []
    for final_rank, r in enumerate(fused[:max(int(top_k), 1)], start=1):
        r["final_rank"] = final_rank
        if not id_boost_applied or not r.get("id_boost"):
            r.pop("id_boost", None)
        results.append(r)
    return results


if __name__ == "__main__":
    for r in hybrid_search("P001续航多久", top_k=5):
        print(f"{r['final_rank']}. {r['chunk_id']} [{r['doc_type']}] rrf={r['rrf_score']:.6f} "
              f"kw={r['keyword_rank']} vec={r['vector_rank']}")
