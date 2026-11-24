# -*- coding: utf-8 -*-
"""V3.2.3 归档后安全热修复专项测试：单边音频失效表达（HR-08）。

30 条全新测试（15 正例 + 15 反例），不复制 blind v3 问题。
正例四重断言：detect_risk_intents 含 post_purchase_defect / rule_id=RULE-HR-08 /
query_analyzer.required_rule_ids 含 RULE-HR-08 / has_post_purchase_defect=true。
反例断言：不因 单边/左右/声音 等普通词误触发 HR-08。
"""
import io
import os
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ["FORCE_DEEPSEEK_FAILURE"] = "true"

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import risk_intents
import query_analyzer

_results = []


def check(cid, desc, ok, detail=""):
    _results.append((cid, ok))
    print(("PASS" if ok else "FAIL"), cid, "|", desc, ("| " + detail if detail and not ok else ""))


# ============ A. 应触发 HR-08：15 条（全部全新表达） ============
POSITIVES = [
    ("P01", "左耳 connected 突然连接词", "左耳突然没声音了，急死我了"),
    ("P02", "右耳 + 连接词就", "昨天刚拿到的耳机，今天右边就没声了"),
    ("P03", "一边 + 现在", "耳机一边现在没有声，听歌只有半个世界"),
    ("P04", "另一边 + 完全", "这对耳塞另一边完全不响"),
    ("P05", "状态变化：开始有声后来不出声", "右边开始时有声音，后来不出声了"),
    ("P06", "单边 + 声音没了", "我的耳机单边声音没了"),
    ("P07", "只有一只响", "只有一只耳机有声，另外那只一点动静都没有"),
    ("P08", "一个响另一个不响", "一个耳朵能响，另一个没声"),
    ("P09", "连接词怎么", "右耳怎么没声了？昨天还好好的"),
    ("P10", "连接词又", "修完拿回来，右边又不出声了"),
    ("P11", "连接词已经", "左耳已经没声音两天了"),
    ("P12", "收货语境 + 单边", "刚拆箱就发现只有单边能响"),
    ("P13", "使用一段时间后", "用了半个月，左边渐渐没声了"),
    ("P14", "另一只 + 没声音", "两只耳塞另一只没声音"),
    ("P15", "单耳 + 失声", "右边那只耳机失声了"),
]

for cid, desc, q in POSITIVES:
    hits = risk_intents.detect_risk_intents(q)
    hit = next((h for h in hits if h.get("intent") == "post_purchase_defect"), None)
    ok1 = hit is not None and hit["rule_id"] == "RULE-HR-08"
    a = query_analyzer.analyze(q)
    ok2 = "RULE-HR-08" in (a.get("required_rule_ids") or [])
    ok3 = a.get("has_post_purchase_defect") is True
    check(cid, desc + " [四重断言]", ok1 and ok2 and ok3,
          f"intent_hit={ok1} analyzer_req={ok2} has_defect={ok3}")

# ============ B. 不应触发：15 条（全新表达） ============
NEGATIVES = [
    ("N01", "售前担忧：会不会没声", "这耳机会不会用一段时间就没声音啊"),
    ("N02", "售前担忧：容易没声吗", "请问这款容易没声吗？"),
    ("N03", "参数咨询：左右声道", "左右声道是不是都支持的？"),
    ("N04", "参数咨询：音量", "右耳声音会比左边大吗"),
    ("N05", "参数咨询：降噪", "它的降噪效果怎么样？"),
    ("N06", "参数咨询：单耳使用", "支持单耳使用吗？开会想留一只耳朵"),
    ("N07", "参数咨询：佩戴", "左耳佩戴久了会不会不舒服？"),
    ("N08", "正常声道描述", "我平时喜欢把声音调到右边声道，左声道做备用"),
    ("N09", "售前担忧：怕不怕坏", "这东西怕不怕坏，想用三年"),
    ("N10", "普通参数：电池", "耳机电池能撑多少小时？"),
    ("N11", "普通参数：防水", "运动出汗会不会进水坏掉？"),
    ("N12", "音质咨询", "左右耳音质是一样的吗？"),
    ("N13", "功能咨询：连接", "它能同时连两台设备吗？"),
    ("N14", "参数咨询：延迟", "打游戏延迟高不高？"),
    ("N15", "普通商品咨询", "这个耳机有哪些颜色可以选？"),
]

for cid, desc, q in NEGATIVES:
    hits = risk_intents.detect_risk_intents(q)
    hr08 = [h for h in hits if h.get("rule_id") == "RULE-HR-08"]
    check(cid, desc + " [不误触发HR-08]", not hr08,
          f"误触发: {[(h['rule_id'], h.get('intent')) for h in hr08]}")


total = len(_results)
passed = sum(1 for _, ok in _results if ok)
print()
print(f"==== V3.2.3 专项测试: {passed}/{total} 通过 ====")
sys.exit(0 if passed == total else 1)
