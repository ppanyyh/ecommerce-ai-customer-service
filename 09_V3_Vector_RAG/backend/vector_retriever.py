"""V3.0 向量检索器（仅本地检索，不调用 DeepSeek，不接入 /api/chat）。

提供 vector_search(query, top_k=5, filters=None)：
- 查询向量使用 BGE 官方推荐检索指令前缀："为这个句子生成表示以用于检索相关文章："；
- 文档向量不加该前缀（构建脚本保证）；
- 索引内容与展示内容分离：Chroma 中存储的是 Embedding 用文本（规则片段为
  retrieval_text 关键词扩写），本检索器按 chunk_id 从 knowledge_chunks.jsonl
  取回原始 text 作为返回的正式业务内容，扩写文本仅随结果附带在 embedded_text
  字段中供核对，不作为展示/政策内容；
- 支持按 doc_type / category 过滤（Chroma where 条件）；
- 返回统一结构，同时保留原始 distance 与转换后的 similarity（余弦：similarity = 1 - distance）；
- 不使用未经测试的固定相似度阈值；无结果时返回空列表。

运行方式：由构建/评测脚本导入使用，或独立验证：
    from vector_retriever import vector_search
    vector_search("退款一直没到账怎么办", top_k=3)
"""

import json
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
CHROMA_DB_DIR = os.path.join(PROJECT_DIR, "data", "chroma_db")
CHUNKS_PATH = os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl")

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
COLLECTION = "ecommerce_kb_v1"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_model = None
_col = None
_original_texts = None  # chunk_id -> 原始 text（正式业务内容）


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _get_collection():
    global _col
    if _col is None:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
        _col = client.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})
    return _col


def _get_original_texts():
    """chunk_id -> knowledge_chunks.jsonl 中的原始 text（展示/交给模型的正式内容）。"""
    global _original_texts
    if _original_texts is None:
        mapping = {}
        with open(CHUNKS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                c = json.loads(line)
                mapping[c["chunk_id"]] = c.get("text", "")
        _original_texts = mapping
    return _original_texts


def _build_where(filters):
    """构造 Chroma where 条件：仅支持 doc_type / category 的等值过滤。"""
    if not filters:
        return None
    conds = []
    if filters.get("doc_type"):
        conds.append({"doc_type": str(filters["doc_type"])})
    if filters.get("category"):
        conds.append({"category": str(filters["category"])})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def vector_search(query, top_k=5, filters=None):
    """语义检索。query: 用户问题；filters: {"doc_type": ..., "category": ...}（可选）。

    返回字段中：
    - text: 原始业务内容（来自 knowledge_chunks.jsonl，交给模型/展示用）；
    - embedded_text: 构建索引时实际参与 Embedding 的文本（规则片段为关键词扩写）。
    """
    query = (query or "").strip()
    if not query:
        return []

    col = _get_collection()
    if col.count() == 0:
        return []

    model = _get_model()
    q_emb = model.encode([QUERY_PREFIX + query], normalize_embeddings=True)

    res = col.query(
        query_embeddings=[q_emb[0].tolist()],
        n_results=min(max(int(top_k), 1), col.count()),
        where=_build_where(filters),
        include=["documents", "metadatas", "distances"],
    )

    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    originals = _get_original_texts()
    results = []
    for rank, (cid, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists), start=1):
        meta = meta or {}
        distance = float(dist)
        results.append({
            "chunk_id": cid,
            "text": originals.get(cid, doc or ""),  # 原始 text；jsonl 缺失时回退索引内文档
            "embedded_text": doc or "",
            "source": meta.get("source", ""),
            "doc_type": meta.get("doc_type", ""),
            "ref_id": meta.get("ref_id", ""),
            "category": meta.get("category", ""),
            "distance": round(distance, 6),
            "similarity": round(1.0 - distance, 6),  # 余弦距离 -> 相似度
            "rank": rank,
        })
    return results


if __name__ == "__main__":
    # 独立验证入口
    for r in vector_search("退款一直没到账怎么办", top_k=3):
        print(f"{r['rank']}. {r['chunk_id']} [{r['doc_type']}] sim={r['similarity']:.4f} | {r['source']}")
        print(f"    text(原始): {r['text'][:60]}...")
        print(f"    embedded:   {r['embedded_text'][:60]}...")
