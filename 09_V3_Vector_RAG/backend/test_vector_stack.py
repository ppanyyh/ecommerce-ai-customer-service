"""V3.0 向量 RAG 技术栈验证脚本（本阶段仅验证，不构建正式知识库，不调用 DeepSeek）。

验证内容：
1. 本地加载中文 Embedding 模型 BAAI/bge-small-zh-v1.5（首次运行从官方仓库下载）；
2. 生成向量并检查维度一致性、NaN/无穷值、语义相似度排序；
3. Chroma PersistentClient（data/chroma_test）写入 3 条测试文档；
4. 查询 Top-1 命中退款文档；
5. 重建客户端后验证持久化。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\test_vector_stack.py

约定：
- 文档片段生成向量时【不加】查询指令前缀；
- 用户查询生成向量时加前缀："为这个句子生成表示以用于检索相关文章："（bge 官方约定）；
- 模型仅从 HuggingFace 官方仓库下载，失败即报错停止，不静默替换其他模型；
- 不读取、不输出任何 API Key。
"""

import json
import math
import os
import sys

# 保证相对路径基于本文件位置（backend/），不依赖终端目录
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
CHROMA_TEST_DIR = os.path.join(PROJECT_DIR, "data", "chroma_test")

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

RESULTS = []          # (名称, 是否通过, 详情)
COLLECTION = "vector_stack_test"


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


def main():
    print("=" * 60)
    print("V3.0 向量 RAG 技术栈验证")
    print("=" * 60)

    # ---------- 1) 加载本地 Embedding 模型 ----------
    print(f"\n[1] 加载 Embedding 模型: {MODEL_NAME}（首次运行将从官方仓库下载）")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL_NAME)  # 仅官方模型标识，不指向本地替代文件
    except Exception as e:
        print(f"[STOP] 模型加载/下载失败，按要求停止，不替换其他模型: {type(e).__name__}: {e}")
        summary(exit_code=1, model_loaded=False)
        return

    dim = model.get_sentence_embedding_dimension()
    check("模型加载成功", True, f"维度={dim}")

    # ---------- 2) 生成 3 条测试向量 ----------
    texts = [
        "我的退款什么时候到账",
        "退款进度一直没有更新",
        "北京今天会下雨吗",
    ]
    print("\n[2] 生成测试向量（文档片段不加查询指令）")
    emb = model.encode(texts, normalize_embeddings=True)
    check("成功生成3个向量", emb.shape[0] == 3, f"shape={emb.shape}")
    check("向量维度一致", emb.ndim == 2 and len(set(len(r) for r in emb)) == 1,
          f"每条维度={emb.shape[1]}，共{emb.shape[0]}条")

    flat = emb.flatten().tolist()
    bad = [v for v in flat if math.isnan(v) or math.isinf(v)]
    check("无NaN和无穷值", not bad, f"异常值数量={len(bad)}")

    # ---------- 3) 相似度：退款×退款 > 退款×天气 ----------
    import numpy as np
    def cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    sim_refund_refund = cos(emb[0], emb[1])
    sim_refund_weather = cos(emb[0], emb[2])
    sim_refund2_weather = cos(emb[1], emb[2])
    print(f"\n[3] 相似度：退款1×退款2={sim_refund_refund:.4f} | "
          f"退款1×天气={sim_refund_weather:.4f} | 退款2×天气={sim_refund2_weather:.4f}")
    check("退款问题间相似度高于退款与天气",
          sim_refund_refund > sim_refund_weather and sim_refund_refund > sim_refund2_weather,
          f"{sim_refund_refund:.4f} vs {sim_refund_weather:.4f}/{sim_refund2_weather:.4f}")

    # ---------- 4) Chroma PersistentClient 写入 ----------
    print(f"\n[4] 创建 Chroma PersistentClient: {CHROMA_TEST_DIR}")
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_TEST_DIR)
    # 重建同名 collection，保证脚本可重复运行
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    docs = [
        {"id": "DOC-REFUND-01", "text": "退款进度处理：退款申请提交后进入审核，审核通过后原路退回，进度可在订单详情查看。",
         "meta": {"source": "售后SOP-测试", "type": "sop", "doc_id": "DOC-REFUND-01"}},
        {"id": "DOC-BATTERY-01", "text": "商品续航说明：SoundGo Air无线蓝牙耳机单次续航约7小时，配合充电盒综合续航约28小时。",
         "meta": {"source": "商品资料-测试", "type": "product", "doc_id": "DOC-BATTERY-01"}},
        {"id": "DOC-LOGISTICS-01", "text": "物流异常处理：物流长时间未更新或显示签收但未收到，需联系承运方核实并登记补发流程。",
         "meta": {"source": "售后SOP-测试", "type": "sop", "doc_id": "DOC-LOGISTICS-01"}},
    ]
    col.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[d["meta"] for d in docs],
        # 文档向量由本地模型生成（不加查询指令前缀）
        embeddings=[e.tolist() for e in model.encode([d["text"] for d in docs], normalize_embeddings=True)],
    )
    count_after_add = col.count()
    check("Chroma写入3条文档", count_after_add == 3, f"count={count_after_add}")
    check("metadata包含source/type/doc_id",
          all(set(d["meta"]) == {"source", "type", "doc_id"} for d in docs),
          json.dumps(docs[0]["meta"], ensure_ascii=False))

    # ---------- 5) 查询 Top-1 ----------
    query = "退款一直没到账怎么办"
    print(f"\n[5] 查询: {query}（查询向量加 bge 官方检索指令前缀）")
    q_emb = model.encode([QUERY_PREFIX + query], normalize_embeddings=True)
    res = col.query(query_embeddings=[q_emb[0].tolist()], n_results=3)
    top1 = res["ids"][0][0]
    top1_doc = res["documents"][0][0]
    top1_dist = res["distances"][0][0] if res.get("distances") else None
    print(f"    Top-1: {top1} | 距离={top1_dist:.4f}" if top1_dist is not None else f"    Top-1: {top1}")
    check("Top-1命中退款进度处理", top1 == "DOC-REFUND-01", f"ids={[i for i in res['ids'][0]]}")

    # ---------- 6) 持久化：重建客户端后仍可读 ----------
    print("\n[6] 重建客户端验证持久化")
    del client, col
    client2 = chromadb.PersistentClient(path=CHROMA_TEST_DIR)
    col2 = client2.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})
    count_reload = col2.count()
    res2 = col2.query(query_embeddings=[q_emb[0].tolist()], n_results=1)
    top1_reload = res2["ids"][0][0] if res2["ids"] else None
    check("重启后collection和数据仍可读取", count_reload == 3 and top1_reload == "DOC-REFUND-01",
          f"count={count_reload}, top1={top1_reload}")

    # ---------- 汇总 ----------
    summary(exit_code=0 if all(ok for _, ok, _ in RESULTS) else 1, model_loaded=True, dim=dim,
            sims=(sim_refund_refund, sim_refund_weather, sim_refund2_weather),
            chroma_count=count_after_add, top1=top1)


def summary(exit_code, model_loaded=False, dim=None, sims=None, chroma_count=None, top1=None):
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 60)
    print(f"验证完成: {passed}/{total} 检查项通过 | 模型加载: {'是' if model_loaded else '否'}"
          + (f" | 维度: {dim}" if dim else "")
          + (f" | 相似度(退款×退款, 退款×天气): {sims[0]:.4f}/{sims[1]:.4f}/{sims[2]:.4f}" if sims else "")
          + (f" | Chroma写入: {chroma_count}条" if chroma_count is not None else "")
          + (f" | Top-1: {top1}" if top1 else ""))
    print("本阶段仅为技术栈验证：未构建正式知识库，未调用 DeepSeek。")
    fails = [name for name, ok, _ in RESULTS if not ok]
    if fails:
        print("未通过项: " + "; ".join(fails))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
