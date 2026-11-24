"""V3.0 正式向量索引构建脚本（不调用 DeepSeek，不接入 /api/chat）。

功能：
1. 读取 backend/data/knowledge_chunks.jsonl（5商品 + 20FAQ + 8规则 = 33条，订单不入库）；
2. 加载本地 Embedding 模型 BAAI/bge-small-zh-v1.5（文档向量不加查询指令前缀）；
3. 写入 Chroma PersistentClient（data/chroma_db，collection: ecommerce_kb_v1）；
4. 使用 upsert，重复运行不会产生重复记录；
5. 生成 backend/data/index_manifest.json 索引清单（含 SHA-256）。

索引内容与展示内容分离（v1.1）：
- Embedding 使用片段的 retrieval_text（规则片段的关键词扩写文本）；
- retrieval_text 不存在时回退使用 text；
- 原始 text 作为正式业务内容，由 vector_retriever.py 按 chunk_id 从
  knowledge_chunks.jsonl 取回，避免把检索扩写内容当作正式政策展示给用户或交给模型。

安全约定：
- 禁止 client.reset()；
- 只有显式传 --rebuild 时，才删除并重建 ecommerce_kb_v1 这一个 collection；
- 不删除其他 collection 或任何目录；不读取/输出 API Key。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\build_vector_index.py            # 增量 upsert
    .\\.venv\\Scripts\\python.exe backend\\build_vector_index.py --rebuild  # 删除并重建 collection
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
DATA_DIR = os.path.join(BACKEND_DIR, "data")
CHUNKS_PATH = os.path.join(DATA_DIR, "knowledge_chunks.jsonl")
MANIFEST_PATH = os.path.join(DATA_DIR, "index_manifest.json")
CHROMA_DB_DIR = os.path.join(PROJECT_DIR, "data", "chroma_db")

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
COLLECTION = "ecommerce_kb_v1"
DATA_VERSION = "1.2"  # V3.1：FAQ 片段新增意图归一化 retrieval_text（提升口语化召回）

# Chroma metadata 只保留简单标量字段（text 作为 document 存储，不入 metadata）
META_KEYS = ("source", "doc_type", "ref_id", "category", "title", "version", "simulated")


def load_chunks():
    chunks, ids = [], []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            for key in ("chunk_id", "text", "source"):
                if not c.get(key):
                    raise SystemExit(f"[STOP] 第{lineno}行缺少必填字段 {key}")
            if c["chunk_id"] in ids:
                raise SystemExit(f"[STOP] chunk_id 重复: {c['chunk_id']}（第{lineno}行）")
            ids.append(c["chunk_id"])
            chunks.append(c)
    return chunks


def embedding_text(chunk):
    """索引内容与展示内容分离：优先 retrieval_text，缺失时回退原始 text。"""
    return (chunk.get("retrieval_text") or "").strip() or chunk["text"]


def main():
    parser = argparse.ArgumentParser(description="构建正式向量索引 ecommerce_kb_v1")
    parser.add_argument("--rebuild", action="store_true",
                        help="删除并重建 ecommerce_kb_v1 collection（不影响其他 collection）")
    args = parser.parse_args()

    chunks = load_chunks()
    counts = {}
    for c in chunks:
        counts[c["doc_type"]] = counts.get(c["doc_type"], 0) + 1
    n_retrieval = sum(1 for c in chunks if (c.get("retrieval_text") or "").strip())
    print(f"[1] 读取片段: {len(chunks)} 条 | 分类: {counts} | 使用 retrieval_text: {n_retrieval} 条")
    if any(c["doc_type"] == "order" for c in chunks):
        raise SystemExit("[STOP] 订单片段不允许进入向量数据库")

    print(f"[2] 加载 Embedding 模型: {MODEL_NAME}")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()

    print("[3] 生成文档向量（不加查询指令前缀；Embedding 用 retrieval_text，缺失回退 text）")
    texts = [embedding_text(c) for c in chunks]
    embeddings = model.encode(texts, normalize_embeddings=True)

    print(f"[4] 打开 Chroma PersistentClient: {CHROMA_DB_DIR}")
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DB_DIR)

    existing = {c.name for c in client.list_collections()}
    if args.rebuild:
        if COLLECTION in existing:
            client.delete_collection(COLLECTION)  # 仅删除目标 collection
            print(f"    --rebuild: 已删除旧 collection {COLLECTION}")
        existing.discard(COLLECTION)
    if existing:
        print(f"    其他 collection 保持不变: {sorted(existing)}")

    col = client.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})
    col.upsert(
        ids=[c["chunk_id"] for c in chunks],
        documents=texts,
        embeddings=[e.tolist() for e in embeddings],
        metadatas=[{k: c.get(k) for k in META_KEYS} for c in chunks],
    )
    total_in_db = col.count()
    print(f"[5] upsert 完成，collection 数量: {total_in_db}")
    if total_in_db != len(chunks):
        raise SystemExit(f"[STOP] 数量不一致: db={total_in_db} jsonl={len(chunks)}")

    # ---------- 索引清单 ----------
    sha256 = hashlib.sha256(open(CHUNKS_PATH, "rb").read()).hexdigest()
    manifest = {
        "collection": COLLECTION,
        "embedding_model": MODEL_NAME,
        "vector_dimension": dim,
        "total_chunks": len(chunks),
        "doc_type_counts": counts,
        "chunks_sha256": sha256,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "contains_orders": False,
        "data_version": DATA_VERSION,
        "embedding_source": "retrieval_text 优先（规则片段8条均使用），缺失时回退 text；原始 text 由 vector_retriever 按 chunk_id 从 knowledge_chunks.jsonl 取回。",
        "notes": "订单不进入向量数据库：订单通过订单号精确查询，避免相似度检索串单与隐私风险；所有数据为模拟数据。",
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[6] 清单已写入: {MANIFEST_PATH}")
    print(f"    SHA-256: {sha256[:16]}... | 维度: {dim} | 含订单: 否 | 数据版本: {DATA_VERSION}")


if __name__ == "__main__":
    main()
