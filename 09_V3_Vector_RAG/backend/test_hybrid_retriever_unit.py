"""V3.0 混合检索器基础单元测试（技术验证，不使用留出测试集，不调用 DeepSeek）。

验证项：
1. 返回结果按 rrf_score 降序；
2. chunk_id 不重复；
3. keyword_rank / vector_rank 与两个子检索器的真实排名一致；
4. 只有关键词结果时仍可进入排名（vector_rank=None）；
5. 只有向量结果时仍可进入排名（keyword_rank=None）；
6. 同时命中两种检索时获得融合分数（等于两项 RRF 分量之和）；
7. 商品编号 P001 精确命中（对应商品必须置顶）；
8. 订单号不被当成向量知识回答（无 order 片段、订单号不出现在任何返回 text 中）；
9. 原始 text 与 retrieval_text 不混淆（规则片段返回"触发条件为"原文，
   不含 retrieval_text 的"触发类型："标记）；
10. 不调用 DeepSeek（静态检查三个检索模块源码不含 deepseek/网络调用）。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\test_hybrid_retriever_unit.py
"""

import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from hybrid_retriever import hybrid_search, RRF_K, KEYWORD_WEIGHT, VECTOR_WEIGHT  # noqa: E402
from keyword_retriever_v3 import keyword_search, detect_order_query  # noqa: E402
from vector_retriever import vector_search  # noqa: E402

CHUNKS_PATH = os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


def original_texts():
    out = {}
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                out[c["chunk_id"]] = c
    return out


def rrf_expected(k_rank, v_rank):
    s = 0.0
    if k_rank is not None:
        s += KEYWORD_WEIGHT / (RRF_K + k_rank)
    if v_rank is not None:
        s += VECTOR_WEIGHT / (RRF_K + v_rank)
    return round(s, 6)


def main():
    chunks = original_texts()

    # 技术验证问题（少量，非留出集）
    tech_queries = [
        "蓝牙耳机充电盒续航",
        "键盘蓝牙连接",
        "退款什么时候到账",
        "物流一直不动",
        "保温杯装汽水",
    ]

    # 1. rrf_score 降序
    ok1 = True
    for q in tech_queries:
        rs = hybrid_search(q, top_k=5)
        scores = [r["rrf_score"] for r in rs]
        if scores != sorted(scores, reverse=True):
            ok1 = False
    check("1.结果按rrf_score降序", ok1)

    # 2. chunk_id 去重
    ok2 = True
    for q in tech_queries:
        rs = hybrid_search(q, top_k=5)
        ids = [r["chunk_id"] for r in rs]
        if len(ids) != len(set(ids)):
            ok2 = False
    check("2.chunk_id不重复", ok2)

    # 3. keyword_rank/vector_rank 与子检索器一致
    ok3 = True
    for q in tech_queries:
        kw = {r["chunk_id"]: r["rank"] for r in keyword_search(q, top_k=10)}
        vec = {r["chunk_id"]: r["rank"] for r in vector_search(q, top_k=10)}
        for r in hybrid_search(q, top_k=5):
            cid = r["chunk_id"]
            if r["keyword_rank"] != kw.get(cid) or r["vector_rank"] != vec.get(cid):
                ok3 = False
    check("3.keyword_rank/vector_rank记录正确", ok3)

    # 4/5. 单侧结果仍可进入排名
    has_kw_only = has_vec_only = False
    for q in tech_queries + ["台灯定时功能", "耳机主动降噪效果"]:
        kw = {r["chunk_id"] for r in keyword_search(q, top_k=10)}
        vec = {r["chunk_id"] for r in vector_search(q, top_k=10)}
        for r in hybrid_search(q, top_k=10):
            if r["chunk_id"] in kw and r["chunk_id"] not in vec and r["vector_rank"] is None \
                    and r["keyword_rank"] is not None:
                has_kw_only = True
            if r["chunk_id"] in vec and r["chunk_id"] not in kw and r["keyword_rank"] is None \
                    and r["vector_rank"] is not None:
                has_vec_only = True
    check("4.只有关键词结果时仍可进入排名", has_kw_only)
    check("5.只有向量结果时仍可进入排名", has_vec_only)

    # 6. 双侧命中时 rrf 分数 = 两分量之和
    ok6 = True
    for q in tech_queries:
        kw = {r["chunk_id"]: r["rank"] for r in keyword_search(q, top_k=10)}
        vec = {r["chunk_id"]: r["rank"] for r in vector_search(q, top_k=10)}
        for r in hybrid_search(q, top_k=5):
            cid = r["chunk_id"]
            if cid in kw and cid in vec:
                if abs(r["rrf_score"] - rrf_expected(kw[cid], vec[cid])) > 1e-6:
                    ok6 = False
    check("6.双侧命中获得融合分数", ok6)

    # 7. P001 精确命中置顶
    rs = hybrid_search("P001这个耳机充电一次能用多久", top_k=5)
    check("7.商品编号P001精确命中且置顶",
          bool(rs) and rs[0]["chunk_id"] == "PRODUCT-P001",
          f"top1={rs[0]['chunk_id'] if rs else None}")

    # 8. 订单号不被当成向量知识回答
    order_q = "帮我查一下订单202609180001发货到哪了"
    rs = hybrid_search(order_q, top_k=5)
    no_order_doc = all(r["doc_type"] != "order" for r in rs)
    no_leak_text = all("202609180001" not in r["text"] for r in rs)
    check("8.订单号不进入混合检索回答",
          no_order_doc and no_leak_text and detect_order_query(order_q),
          f"results={len(rs)} order_doc={not no_order_doc} leak={not no_leak_text}")

    # 9. 原始 text 与 retrieval_text 不混淆
    rs = hybrid_search("投诉赔偿怎么处理", top_k=5)
    hr01 = next((r for r in rs if r["chunk_id"] == "RULE-HR-01"), None)
    ok9 = False
    if hr01:
        orig = chunks["RULE-HR-01"]["text"]
        ok9 = (hr01["text"] == orig and "触发条件为" in hr01["text"]
               and "触发类型：" not in hr01["text"])
    check("9.返回原始text而非retrieval_text", ok9,
          f"HR-01 in top5={hr01 is not None}")

    # 10. 不调用 DeepSeek（静态检查）
    ok10 = True
    for fname in ("keyword_retriever_v3.py", "hybrid_retriever.py", "vector_retriever.py"):
        src = open(os.path.join(BACKEND_DIR, fname), encoding="utf-8").read().lower()
        if "deepseek" in src.replace("不调用 deepseek", "").replace("不调用deepseek", ""):
            ok10 = False
    check("10.检索代码不调用DeepSeek", ok10)

    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n单元测试结论: {n_pass}/{len(RESULTS)} 通过")
    sys.exit(0 if n_pass == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
