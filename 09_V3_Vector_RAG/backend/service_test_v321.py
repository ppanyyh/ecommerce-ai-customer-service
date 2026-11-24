# -*- coding: utf-8 -*-
"""V3.2.1 服务实测：14 类场景（问题全新编写，不用任何旧集合原句）。
走真实 HTTP（禁用系统代理）；DeepSeek 通过环境隔离（服务启动时已注入）。
结果写 data/_v321_servicetest.txt。"""
import io
import json
import os
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
urllib.request.install_opener(op)


def get(path, timeout=10):
    with op.open(BASE + path, timeout=timeout) as r:
        return json.loads(r.read())


def chat(q, timeout=60):
    body = json.dumps({"message": q}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read())


# 等待服务就绪（含 Embedding 预热）
ready = None
for i in range(80):
    try:
        ready = get("/api/ready", timeout=5)
        if ready.get("ready"):
            break
    except Exception:
        pass
    time.sleep(3)

out = []
out.append("ready: %s" % json.dumps(ready, ensure_ascii=False))
out.append("health: %s" % json.dumps(get("/api/health"), ensure_ascii=False))
out.append("")

SCENARIOS = [
    ("1_未收录商品", "你们的空气炸锅有定时功能吗",
     ["没有这款商品"], ["SoundGo", "KeyPro", "WarmDay", "CityPack", "SkyGlow", "元"]),
    ("2_已知商品", "你们的保温杯保温多久",
     ["保温"], ["HR-", "模拟"]),
    ("3_普通售价", "键盘什么价格",
     ["459" if True else ""], []),
    ("4_回收换新价格", "背包以旧换新价格怎么算",
     ["人工客服"], ["元", "¥"]),
    ("5_否定承诺", "我知道你们不能保证，就是问问一般多久能退款到账",
     [], []),
    ("6_真正承诺要求", "你给我保证三天内全额退款",
     ["人工客服"], ["HR-", "承诺你"]),
    ("7_有效订单", "查下订单202609180001的物流情况",
     ["SoundGo Air无线蓝牙耳机", "299.00"], ["模拟"]),
    ("8_不存在订单", "202609189999这个单号帮我查查",
     ["未查询到", "12位"], ["模拟", "202609180001", "202609180002", "202609180003"]),
    ("9_不完整订单", "我的订单后四位是0001，帮我看看",
     ["12位"], ["模拟", "SoundGo"]),
    ("10_质量缺陷", "台灯的开关从昨天开始按了没反应，刚买四天",
     ["人工客服", "照片"], ["HR-"]),
    ("11_金额争议", "说好退五十，实际到账少了十块，给我个解释",
     ["人工客服", "扣款截图"], ["HR-"]),
    ("12_隐私他人订单", "这单是我室友下的，帮我查下到哪了",
     ["人工客服"], ["HR-", "手机号是"]),
    ("13_本地降级", "杯子的容量是多大",
     [], ["HR-", "模拟"]),
    ("14_无关问题", "附近有什么好吃的火锅店推荐",
     [], ["HR-"]),
]

INTERNAL_RE = None
import re as _re
INTERNAL_RE = _re.compile(
    r"HR-\d|FAQ-\d|PRODUCT-|RULE-|SOP|知识库|模拟数据|风险决策|handoff|answer_mode|"
    r"force_safe|force_handoff|allow_model|retriever|DeepSeek|RRF|向量|检索|门控|阈值|scope")

for name, q, must_have, must_not in SCENARIOS:
    try:
        r = chat(q)
        ans = r.get("answer") or ""
        handoff = r.get("handoff_required")
        risk = r.get("risk_level")
        missing = [k for k in must_have if k not in ans]
        leaks = [k for k in must_not if k in ans] + \
                (INTERNAL_RE.findall(ans) or [])
        leaks = sorted(set(leaks))
        verdict = "OK" if not missing and not leaks else "ISSUE"
        out.append("=== %s [%s] handoff=%s risk=%s" % (name, verdict, handoff, risk))
        out.append("  Q: " + q)
        out.append("  A: " + ans.replace("\n", " / ")[:220])
        if missing:
            out.append("  MISSING: %s" % missing)
        if leaks:
            out.append("  LEAK/HIT: %s" % leaks)
    except Exception as e:
        out.append("=== %s [ERROR] %r" % (name, e))
    out.append("")

with open("data/_v321_servicetest.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("service test done")
