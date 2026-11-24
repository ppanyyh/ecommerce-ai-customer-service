# -*- coding: utf-8 -*-
"""检索器测试（阶段三验收，无 API 费用）：
- 数据一致性检查 8 项；
- 12 条检索测试（编号/别名/关键词/评分/风险规则驱动，不针对完整句子写死）。

运行：.\\.venv\\Scripts\\python.exe backend\\test_retriever.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retriever  # noqa: E402
from retriever import retrieve  # noqa: E402

KB = retriever.KB
KB_PATH = retriever._KB_PATH

passed, partial, failed = 0, 0, 0


def judge(checks):
    """checks: [(ok, name)] -> 通过/部分通过/不通过 并打印失败项。"""
    global passed, partial, failed
    bad = [n for ok, n in checks if not ok]
    if not bad:
        passed += 1
        print("  结果: 通过")
        return False
    if any(ok for ok, _ in checks):
        partial += 1
    else:
        failed += 1
    print("  结果:", "部分通过" if any(ok for ok, _ in checks) else "不通过", "| 未通过项:", "; ".join(bad))
    return True


def section(title):
    print("\n" + "=" * 62 + "\n" + title + "\n" + "=" * 62)


# ============================== 一、数据一致性检查 ==============================
section("一、数据一致性检查（knowledge_base.json）")
kb_text = open(KB_PATH, encoding="utf-8").read()
kb = json.loads(kb_text)  # 检查7：JSON能正常解析

orders = KB["orders"]
c = [
    (len(KB["products"]) == 5, f"商品数量=5（实际{len(KB['products'])}）"),
    (len(KB["faqs"]) == 20, f"FAQ数量=20（实际{len(KB['faqs'])}）"),
    (len(orders) == 3, f"订单数量=3（实际{len(orders)}）"),
    (all(abs(o["unit_price"] * o["quantity"] - o["amount"]) < 0.001 for o in orders),
     "unit_price × quantity = amount（3笔全部成立）"),
    (all(o["product_id"] in retriever.PRODUCTS for o in orders),
     "订单商品编号均可关联到商品"),
    (all(r.get("source", "").strip() for r in KB["products"] + KB["faqs"] + orders + KB["handoff_rules"]),
     "所有记录 source 均不为空"),
    (True, "JSON 正常解析"),
    ("sk-" not in kb_text and "DEEPSEEK_API_KEY=" not in kb_text,
     "不包含真实 API Key（无 sk- 凭据格式）"),
]
for ok, name in c:
    print(("  ✓ " if ok else "  ✗ ") + name)
consistency_ok = all(ok for ok, _ in c)
print(f"一致性检查: {'全部通过' if consistency_ok else '存在失败项'}")

# ============================== 二、12条检索测试 ==============================
section("二、检索测试（12条，无API费用）")


def run_case(no, title, q, checks):
    global passed, partial, failed
    print(f"\n[TC-{no:02d}] {title}\n  输入: {q}")
    r = retrieve(q)
    print(f"  match_type={r['match_type']} | matched_ids={r['matched_ids']} | sources={r['sources']}"
          f" | handoff={r['requires_handoff']} | confidence={r['confidence']:.2f}")
    print("  context摘要: " + r["context"].replace("\n", " ⏎ ")[:150])
    before = (passed, partial, failed)
    judge(checks(r))
    if (passed, partial, failed) == before:
        pass
    return r


# 1. P001续航
run_case(1, "商品编号+续航参数", "P001续航怎么样？", lambda r: [
    (r["match_type"] == "product", "match_type=product"),
    (r["matched_ids"] == ["P001"], "matched_ids=[P001]"),
    (r["sources"] == ["《商品资料》P001"], "sources=《商品资料》P001"),
    ("单次续航" in r["context"] and "综合续航" in r["context"], "context含单次/综合续航"),
    (r["requires_handoff"] is False, "不需要转人工"),
])

# 2. 商品别名+价格
run_case(2, "商品别名检索", "保温杯多少钱？", lambda r: [
    (r["match_type"] == "product", "match_type=product（经别名'保温杯'命中）"),
    (r["matched_ids"] == ["P003"], "matched_ids=[P003]（未误匹配其他商品）"),
    ("售价" in r["context"] and "88" in r["context"], "context含售价88元"),
    (r["requires_handoff"] is False, "不需要转人工"),
])

# 3. 商品多属性
run_case(3, "同句多属性提问", "P002价格、连接方式和保修多久？", lambda r: [
    (r["match_type"] == "product", "match_type=product"),
    (r["matched_ids"] == ["P002"], "matched_ids=[P002]"),
    (all(k in r["context"] for k in ("售价", "连接方式", "保修期限")), "context同时含售价/连接方式/保修期限三项"),
    (r["requires_handoff"] is False, "不需要转人工"),
])

# 4-6. 三笔订单
run_case(4, "订单202609180001查询", "查询订单202609180001", lambda r: [
    (r["match_type"] == "order", "match_type=order"),
    (r["matched_ids"] == ["202609180001"], "matched_ids=[202609180001]"),
    ("订单状态：已发货" in r["context"] and "运输中" in r["context"], "context含已发货/运输中"),
    ("[来源：《模拟订单数据》订单202609180001]" in r["context"], "context带来源标签"),
    (r["requires_handoff"] is False, "纯查询不需要转人工"),
])
run_case(5, "订单202609180002退款进度", "202609180002退款到哪一步？", lambda r: [
    (r["match_type"] == "order", "match_type=order"),
    (r["matched_ids"] == ["202609180002"], "matched_ids=[202609180002]"),
    (all(k in r["context"] for k in ("已完成", "已签收", "退款审核中")), "context含已完成/已签收/退款审核中"),
    ("存在进行中的售后申请" in r["context"], "context含进行中售后申请提示"),
    (r["requires_handoff"] is False, "仅查询退款进度不强制转人工"),
])
run_case(6, "订单202609180003发货时间", "订单202609180003什么时候发货", lambda r: [
    (r["match_type"] == "order", "match_type=order"),
    (r["matched_ids"] == ["202609180003"], "matched_ids=[202609180003]"),
    ("待发货" in r["context"], "context含待发货"),
    (r["requires_handoff"] is False, "不需要转人工"),
])

# 7. 不存在的12位订单号
run_case(7, "不存在的完整订单号", "查询订单202609189999", lambda r: [
    ("未查询到该模拟订单" in r["context"], "明确返回未查询到该模拟订单"),
    (r["matched_ids"] == [], "未模糊匹配到任何现有订单"),
    ("不得编造" in r["context"], "context声明不得编造"),
])

# 8. 不完整订单号
run_case(8, "不完整订单号提示", "帮我查一下20260918", lambda r: [
    ("12位" in r["context"], "提示提供完整12位订单号"),
    (r["matched_ids"] == [], "未匹配到其他订单"),
    (r["requires_handoff"] is False, "低风险不需要转人工"),
])

# 9. 商品质量问题
run_case(9, "商品质量问题", "商品质量有问题怎么办？", lambda r: [
    (r["match_type"] == "faq" and "FAQ-014" in r["matched_ids"], "命中FAQ-014"),
    (r["requires_handoff"] is True, "质量问题需人工核验凭证，建议转人工"),
    ("《售后SOP》质量问题处理" in r["sources"], "sources含《售后SOP》质量问题处理"),
    ("保留" in r["context"] or "凭证" in r["context"], "context含提交材料口径"),
])

# 10. 退货运费（资料未明确）
run_case(10, "退货运费（资料未明确）", "退货运费由谁承担？", lambda r: [
    (r["match_type"] == "faq" and "FAQ-017" in r["matched_ids"], "命中FAQ-017"),
    (r["requires_handoff"] is True, "资料无明确规则依据→转人工"),
    ("现有资料未明确" in r["context"], "context说明资料未明确运费规则"),
    ("[来源：" in r["context"], "context片段带来源标签"),
])

# 11. 投诉三倍赔偿
run_case(11, "投诉三倍赔偿（风险规则）", "我要投诉并要求三倍赔偿。", lambda r: [
    (r["match_type"] in ("faq", "risk"), "match_type=faq/risk"),
    (any(i.startswith("HR-") for i in r["matched_ids"]), "命中风险规则（HR-xx）"),
    ("《售后SOP》必须转人工" in r["sources"], "sources含《售后SOP》必须转人工"),
    (r["requires_handoff"] is True, "必须转人工"),
    ("不得直接承诺" in r["context"] or "不承诺" in r["context"], "context声明AI不作赔偿承诺"),
])

# 12. 与电商无关的天气问题
run_case(12, "无关问题（资料未覆盖）", "今天天气怎么样？", lambda r: [
    (r["matched"] is False and r["match_type"] == "none", "matched=false且match_type=none"),
    (r["sources"] == ["现有资料未覆盖"], "sources=[现有资料未覆盖]"),
    ("不得编造" in r["context"], "context说明不得编造"),
    (r["requires_handoff"] is True, "知识库无明确依据→转人工"),
])

# ============================== 三、汇总 ==============================
section("三、测试汇总")
total = passed + partial + failed
print(f"用例总数: {total}（应=12）")
print(f"通过: {passed} | 部分通过: {partial} | 不通过: {failed}")
print(f"数据一致性检查: {'8/8 通过' if consistency_ok else '存在失败项'}")
print("是否调用DeepSeek: 否（纯本地检索，无API费用）")
sys.exit(0 if (failed == 0 and consistency_ok and total == 12) else 1)
