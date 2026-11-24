# -*- coding: utf-8 -*-
"""V3.1：为 FAQ 片段补充意图归一化 retrieval_text（仅使用 FAQ 自身主题域的通用意图短语，
不复制任何测试句子；text 保留原样作为展示/交给模型的内容）。"""
import json
import os

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "knowledge_chunks.jsonl")

# 仅覆盖召回薄弱的 FAQ 意图域；短语为通用能力描述，不来自任何测试题
FAQ_RETRIEVAL_TEXT = {
    "FAQ-006": "查询订单状态和进度。用户想知道订单现在处理到哪个阶段、付款发货售后各环节状态，可提供订单号后协助查询。",
    "FAQ-007": "付款状态延迟说明。用户已付款但订单仍显示待付款、支付状态没有同步更新，属于支付状态短暂延迟。",
    "FAQ-009": "订单发货时间。用户询问订单什么时候发货、是否出库、发货进度如何，需要订单号查询当前状态。",
    "FAQ-011": "修改收货地址。用户想更改订单的配送地址或收货信息，未发货与已发货订单处理方式不同。",
    "FAQ-012": "包裹显示签收但没有收到。用户查物流显示已签收却找不到包裹，需要先排查代收点，再走丢失处理流程。",
    "FAQ-013": "七天无理由退货条件。用户收到商品后不想要了想退货，询问无理由退货的适用条件和申请方式。",
    "FAQ-014": "商品质量问题处理流程。商品出现损坏或故障时，需要保留商品包装和问题凭证，提交订单号与问题描述。",
    "FAQ-015": "拆封商品的退货条件。商品未拆封未使用时退货较容易；拆封使用后可能影响二次销售，需按售后规则确认。",
    "FAQ-016": "退款到账时间。用户询问退款多久到账、退款迟迟没到账，审核通过后仍需支付渠道处理，AI无法保证到账时间。",
    "FAQ-017": "退货运费承担。用户询问退货时寄回运费由谁承担，不同退货原因的运费规则需人工确认。",
}

lines = []
changed = 0
for line in open(P, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    c = json.loads(line)
    if c["chunk_id"] in FAQ_RETRIEVAL_TEXT:
        c["retrieval_text"] = FAQ_RETRIEVAL_TEXT[c["chunk_id"]]
        changed += 1
    lines.append(json.dumps(c, ensure_ascii=False))

with open(P, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

# 复核
ok = 0
for line in open(P, encoding="utf-8"):
    c = json.loads(line)
    if c["doc_type"] == "faq" and c["chunk_id"] in FAQ_RETRIEVAL_TEXT:
        assert c["retrieval_text"] == FAQ_RETRIEVAL_TEXT[c["chunk_id"]]
        ok += 1
print(f"updated retrieval_text for {changed} FAQ chunks; verified {ok}")
