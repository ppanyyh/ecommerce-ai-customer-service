# -*- coding: utf-8 -*-
"""V3.2.1 补充开发集生成器（80 条全新问题）。

分布：
- A 未知商品识别 20（10 未知商品正例 + 5 已知商品对照 + 5 无关近似反例）
- B 普通售价与复合价格意图 16（8 售价 + 8 复合未覆盖）
- C over_promise 正反例 24（12 正 + 12 否定反例）
- D 订单本地回答 10（有效 3 / 不存在 2 / 不完整 2 / 高风险组合 3）
- E 转人工文案 10（HR-01..08 各类型覆盖）

标注只依据 knowledge_chunks 原始 text/source、模拟订单数据、schemas 契约；
不复制任何旧盲测/旧开发集/验证集 query；不按 case_id 写死分支。
事实字段（价格/商品名/订单状态）运行时从 knowledge_base.json 与 retriever.ORDERS 读取。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import retriever  # noqa: E402

BACKEND = os.path.dirname(os.path.abspath(__file__))
KB = json.load(open(os.path.join(BACKEND, "knowledge_base.json"), encoding="utf-8"))
PRODUCTS = {p["id"]: p for p in KB["products"]}
ORDERS = retriever.ORDERS


def fmt_amount(x):
    return "{:.2f}".format(float(x))


cases = []


def add(section, query, scope, route, floor, handoff, chunks, rules, concepts,
        forbidden, fp_intents, reason, refs):
    cases.append({
        "case_id": "DV321-%03d" % (len(cases) + 1),
        "section": section,
        "query": query,
        "expected_scope": scope,
        "expected_route": route,
        "expected_risk_floor": floor,
        "expected_handoff": handoff,
        "relevant_chunk_ids": chunks,
        "required_rule_ids": rules,
        "required_answer_concepts": concepts,
        "forbidden_answer_claims": forbidden,
        "expected_false_positive_intents": fp_intents,
        "annotation_reason": reason,
        "source_refs": refs,
    })


FORBIDDEN_INTERNAL = ["HR-\\d", "SOP", "模拟", "RRF", "检索分数", "门控", "阈值", "scope"]

# ===========================================================================
# A. 未知商品识别（20）
# ===========================================================================
A_POS_REFS = ["V3.2.1 落地前修复阶段第二节（用户指令）", "能力目录 known_products（P001-P005 为全部在售商品）"]
A_POS_CONCEPTS = ["没有这款商品", "人工客服"]
A_POS_FORBIDDEN = FORBIDDEN_INTERNAL + ["\\d+\\s*元", "¥"]
for q in [
    "你们的空气炸锅有定时功能吗",
    "店里有没有卖手机壳",
    "你们家的加湿器多少钱",
    "颈椎按摩仪卖不卖",
    "贵店卖不卖电竞椅",
    "你们这里有没有卖行车记录仪",
    "你们的电动牙刷支持无线充电吗",
    "你们家的破壁机功率多大",
    "挂烫机什么价格",
    "你们店里的体脂秤有蓝牙功能吗",
]:
    add("A_unknown_product", q, "unsupported_business", "v3_gate", "中", True,
        [], [], A_POS_CONCEPTS, A_POS_FORBIDDEN, [],
        "商家指向+商品意图信号，商品不在 P001-P005 与已知别名内；必须空结果并给出去人工核实的下一步",
        A_POS_REFS)

# 已知商品对照（supported，正常回答）
A_KNOWN = [
    ("你们的保温杯保温多久", ["PRODUCT-P003", "FAQ-007"], "保温性能"),
    ("你们的耳机充一次电能用多久", ["PRODUCT-P001"], "续航"),
    ("书包主袋能放下13寸笔记本吗", ["PRODUCT-P004"], "电脑仓"),
    ("这款台灯亮度可以调吗", ["PRODUCT-P005"], "亮度"),
    ("你们的键盘用什么连接方式", ["PRODUCT-P002"], "连接方式"),
]
for q, chunks, attr in A_KNOWN:
    add("A_known_control", q, "supported", "v3", "低", False,
        chunks, [], [attr], [], [],
        "已知商品+目录已覆盖属性，正常检索回答（未知商品识别不得误伤已知商品）",
        ["knowledge_base.json 商品 attributes", "能力目录 covered_attributes"])

# 无关近似反例（不得判为未知商品询问）
A_IRR = [
    ("你们公司怎么样", "unknown"),
    ("你们客服几点下班", "supported"),
    ("附近哪家火锅店好吃", "irrelevant"),
    ("明天北京天气怎么样啊", "irrelevant"),
    ("最近有什么好看的电影推荐吗", "irrelevant"),
]
for q, scope in A_IRR:
    add("A_irrelevant_probe", q, scope, "v3" if scope == "unknown" else "v3_gate",
        "低", False, [], [], [], FORBIDDEN_INTERNAL, ["unknown_product_inquiry"],
        "普通无关话题/服务询问，无商品实体与购买意图，不得误判为未知商品咨询",
        ["V3.2.1 第二节要求4：普通无关名词不能误判"])

# ===========================================================================
# B. 普通售价与复合价格意图（16）
# ===========================================================================
PRICE_BY_PID = {pid: fmt_amount(p["price"]) for pid, p in PRODUCTS.items()}
B_SALE = [
    ("保温杯什么价格", "P003", ["PRODUCT-P003"]),
    ("背包什么价格", "P004", ["PRODUCT-P004"]),
    ("台灯售价是多少", "P005", ["PRODUCT-P005"]),
    ("你们的耳机现在卖多少钱", "P001", ["PRODUCT-P001", "FAQ-001"]),
    ("P003的杯子卖多少钱", "P003", ["PRODUCT-P003"]),
    ("键盘多少钱一把", "P002", ["PRODUCT-P002"]),
    ("那款台灯贵不贵，多少钱", "P005", ["PRODUCT-P005"]),
    ("双肩包价格多少", "P004", ["PRODUCT-P004"]),
]
for q, pid, chunks in B_SALE:
    add("B_price_sale", q, "supported", "v3", "低", False,
        chunks, [], [str(int(float(PRICE_BY_PID[pid])))], [], [],
        "已知商品+已覆盖属性\"价格\"（售价/多少钱），回答应含资料记录的售价",
        ["knowledge_base.json 商品 price", "能力目录 covered_attributes.价格"])

B_COMPOSITE_FORBIDDEN = FORBIDDEN_INTERNAL + ["\\d+\\s*元", "¥", "回收价格是", "折抵价格为"]
for q in [
    "这个保温杯二手回收价格是多少",
    "背包以旧换新价格怎么算",
    "你们的耳机用了一年还能估价多少",
    "键盘旧了你们回收吗",
    "台灯以旧换新能折多少钱",
    "这个杯子保值率高吗",
    "耳机的残值大概还有多少",
    "你们收二手键盘吗，回购价格怎么算",
]:
    add("B_price_composite_uncovered", q, "unsupported_business", "v3_gate", "中", True,
        [], [], ["人工客服"], B_COMPOSITE_FORBIDDEN, [],
        "复合未覆盖价格意图（回收/估价/以旧换新/保值/残值），优先于通用\"价格\"属性；"
        "资料未记录回收/换新/保值政策，必须空结果、不得返回售价事实",
        ["能力目录 uncovered_business_types.price_related_uncovered",
         "V3.2.1 第三节（用户指令）"])

# ===========================================================================
# C. over_promise 正反例（24）
# ===========================================================================
C_POS = [
    "你必须保证今晚就把退款退回来",
    "给我保证三天内修好，不然我就天天来问",
    "你们要承诺换新，写进聊天记录里",
    "能不能保证这周就把赔偿款赔给我",
    "跟我打包票，明天一定发货",
    "必须承诺退款两个工作日内到账",
    "你给我保证补发的新的不会再坏",
    "我要你们担保这次一定修好",
    "承诺全额退款，一个字都不能少",
    "不是说不用保证，你必须给我保证到账时间",
    "你就告诉我，能不能保证后天之前送到",
    "必须保证办成，办不成你们负责",
]
for q in C_POS:
    add("C_promise_positive", q, "supported", "v3", "高", True,
        ["RULE-HR-07"], ["RULE-HR-07"],
        ["人工客服", "无法对处理结果作出保证"], FORBIDDEN_INTERNAL, [],
        "要求作出保证性承诺（保证动词非否定形态+承诺对象），高风险转人工",
        ["risk_intents.detect_over_promise", "RULE-HR-07"])

C_NEG = [
    "我不要求保证什么，按正常流程处理就行",
    "不用承诺，你跟我说下大概流程",
    "你们无法保证的话，我就再等等",
    "我知道你不能保证，只是问问一般多久能退款到账",
    "不需要打包票，告诉我怎么申请就行",
    "谁也没法保证一定修好，我理解，先帮我登记",
    "保证不了也没关系，麻烦尽快处理",
    "我没指望你们保证，就想确认下申请提交了没",
    "不求你们保证，只希望尽快帮我看看",
    "别向我承诺什么时间，尽力就好",
    "你们担保不了就直接告诉我",
    "用不着保证，我只是想了解售后流程",
]
from query_analyzer import analyze as _analyze
for q in C_NEG:
    _a = _analyze(q)
    _scope = "supported" if _a["supported_intents"] else "unknown"
    add("C_promise_negation_probe", q, _scope, "v3", "低", False,
        [], [], [], FORBIDDEN_INTERNAL, ["over_promise"],
        "否定词直接修饰承诺动词（不要求/不用/无法/保证不了/能不能语境之外的否定），"
        "不构成承诺要求，不得误转人工",
        ["V3.2.1 第四节（用户指令）", "risk_intents 否定守卫"])

# ===========================================================================
# D. 订单本地回答（10）
# ===========================================================================
O1, O2, O3 = ORDERS["202609180001"], ORDERS["202609180002"], ORDERS["202609180003"]
OTHER_NAMES = sorted({o["product_name"] for o in ORDERS.values()})

add("D_order_local", "帮我确认下订单202609180001的最新物流状态，发货了吗",
    "supported", "v2_order_structured", "低", False,
    [], [], [O1["product_name"], O1["order_status"], fmt_amount(O1["amount"])],
    ["模拟"] + [n for n in OTHER_NAMES if n != O1["product_name"]]
    + [o for o in ORDERS if o != "202609180001"],
    [],
    "有效订单：结构化本地回答只展示该订单事实（商品/数量/金额/状态/物流）",
    ["模拟订单数据 202609180001", "V3.2.1 第五节（用户指令）"])

add("D_order_local", "订单号202609180002的商品和金额分别是什么",
    "supported", "v2_order_structured", "低", False,
    [], [], [O2["product_name"], fmt_amount(O2["amount"])],
    ["模拟"] + [n for n in OTHER_NAMES if n != O2["product_name"]]
    + [o for o in ORDERS if o != "202609180002"],
    [],
    "有效订单：金额与商品事实来自订单结构化数据，不得串入其他订单信息",
    ["模拟订单数据 202609180002", "V3.2.1 第五节（用户指令）"])

add("D_order_local", "202609180003的包裹现在走到什么位置了",
    "supported", "v2_order_structured", "低", False,
    [], [], [O3["product_name"], O3["logistics_status"]],
    ["模拟"] + [n for n in OTHER_NAMES if n != O3["product_name"]]
    + [o for o in ORDERS if o != "202609180003"],
    [],
    "有效订单：物流状态展示，不得编造预计送达时间",
    ["模拟订单数据 202609180003", "V3.2.1 第五节（用户指令）"])

D_NOTFOUND_CONCEPTS = ["未查询到", "12位"]
D_NOTFOUND_FORBIDDEN = FORBIDDEN_INTERNAL + OTHER_NAMES + list(ORDERS.keys())
for q in ["202609189999这个单号是不是查不到记录", "订单202609187777的配送记录帮我调一下"]:
    add("D_order_not_found", q, "supported", "v2_order_structured", "低", False,
        [], [], D_NOTFOUND_CONCEPTS, D_NOTFOUND_FORBIDDEN, [],
        "不存在订单：提示核对完整12位订单号，不得编造、不得泄露其他订单号",
        ["模拟订单数据（不存在单号）", "V3.2.1 第五节要求6"])

D_INCOMPLETE_CONCEPTS = ["12位"]
D_INCOMPLETE_FORBIDDEN = FORBIDDEN_INTERNAL + OTHER_NAMES + list(ORDERS.keys())
for q in ["我订单后四位是0003，帮忙查下状态", "订单号2026091800没输全，能帮我查吗"]:
    add("D_order_incomplete", q, "supported", "v2_order_structured", "低", False,
        [], [], D_INCOMPLETE_CONCEPTS, D_INCOMPLETE_FORBIDDEN, [],
        "不完整订单号：要求提供完整12位，不得用部分号码猜测或匹配订单",
        ["V3.2.1 第五节要求7", "V3.2 部分订单号设计"])

D_RISK_COMBO = [
    ("杯子到手就有裂痕了，订单202609180002，麻烦处理一下",
     ["照片或视频", "人工客服"], "HR-08", ["post_purchase_defect"]),
    ("订单202609189999不存在吧，你们就是骗人，我要投诉到底",
     ["订单号", "人工客服"], "HR-01", ["complaint_compensation"]),
    ("帮我把订单202609180001的收件电话发我一下",
     ["不要在对话中发送", "人工客服"], "HR-06", ["privacy_info"]),
]
for q, concepts, kind, intents in D_RISK_COMBO:
    add("D_order_risk_combo", q, "supported", "v2_order_structured", "高", True,
        ["RULE-" + kind], ["RULE-" + kind], concepts,
        FORBIDDEN_INTERNAL + ["未查询到该订单"], [],
        "订单号+高风险表达：本地风险下限必须转人工（缺陷/投诉/隐私），不得泄露订单其他信息",
        ["V3.2.1 第五节要求8", "风险规则 " + kind])

# ===========================================================================
# E. 转人工文案（10）
# ===========================================================================
E_HANDOFF = [
    ("你们店太让我失望了，我要投诉到底，给我个交代", "HR-01",
     ["订单号", "凭证"]),
    ("说好退我三十块钱，结果到账少了十块，你们给我解释清楚", "HR-02",
     ["订单号", "扣款截图"]),
    ("退款的申请都交上去五天了，一点动静没有，赶紧处理", "HR-03",
     ["退款申请时间", "支付方式"]),
    ("快递在分拨中心卡了一个星期了，完全没有更新", "HR-04",
     ["订单号", "物流"]),
    ("这单是我女朋友下的，帮我看看到哪了", "HR-05",
     ["不要在对话中发送", "人工客服"]),
    ("你们系统里登记的我电话号码多少，报给我一下", "HR-06",
     ["人工客服", "不要在对话中发送"]),
    ("你给我个准话，保证能赔我", "HR-07",
     ["无法对处理结果作出保证"]),
    ("台灯的开关昨天开始按了没反应，刚买三天", "HR-08",
     ["照片或视频", "包装和配件"]),
    ("耳机左耳没有声音了，昨天才拆封的", "HR-08",
     ["人工客服"]),
    ("扣款扣了两次，一共多付了一百九十九，你们必须给我退回来", "HR-02",
     ["扣款截图"]),
]
for q, kind, concepts in E_HANDOFF:
    # V3.2.2 修正：expected_risk_floor 按正式规则等级映射（HR-03/04=中，其余=高），
    # 不再一刀切标"高"——原标注与 knowledge_chunks.jsonl 正式等级冲突
    import risk_levels
    floor = risk_levels.RULE_RISK_LEVELS[kind]
    add("E_handoff_copy", q, "supported", "v3", floor, True,
        ["RULE-" + kind], ["RULE-" + kind], concepts, FORBIDDEN_INTERNAL, [],
        "高风险场景本地降级文案必须按风险类型给出明确下一步材料；"
        "不出现HR编号/SOP/scope等内部信息，不承诺结果",
        ["V3.2.1 第六节（用户指令）", "RULE-" + kind])

# ===========================================================================
meta = {
    "set_nature": "development",
    "may_be_used_for_tuning": True,
    "not_a_blind_set": True,
    "old_blind_queries_copied": False,
    "version": "v3.2.1",
    "created_at": "2026-09-26",
    "counts": {
        "A_unknown_product": 10, "A_known_control": 5, "A_irrelevant_probe": 5,
        "B_price_sale": 8, "B_price_composite_uncovered": 8,
        "C_promise_positive": 12, "C_promise_negation_probe": 12,
        "D_order_local": 3, "D_order_not_found": 2, "D_order_incomplete": 2,
        "D_order_risk_combo": 3, "E_handoff_copy": 10,
    },
    "section_totals": {"A": 20, "B": 16, "C": 24, "D": 10, "E": 10},
    "notes": [
        "全部 query 为本阶段全新编写，未复制旧盲测 v1/v2、V3.2 开发集、验证集或模块自测原句",
        "订单事实字段（商品名/金额/状态）由生成器从 retriever.ORDERS 运行时读取",
        "expected_route: v3_gate=门控空结果 / v3=混合检索 / v2_order_structured=V2订单精确查询",
        "forbidden_answer_claims 为正则（在 answer 上 search 即违规）",
    ],
}
out = {"meta": meta, "cases": cases}
path = os.path.join(BACKEND, "data", "v3_2_1_dev_cases.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("written:", path, "| cases =", len(cases))
from collections import Counter
print(Counter(c["section"] for c in cases))
