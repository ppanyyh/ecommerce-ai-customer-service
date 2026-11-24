# -*- coding: utf-8 -*-
"""V3.2.2 服务实测（问题全新编写，不用旧集合原句）。
验证：HR-01..08 风险等级与 handoff、多风险取最高、health/ready 新版本标识、
DeepSeek 0 次、停服无残留（进程检查由外部执行）。结果写 data/_v322_servicetest.txt。"""
import io
import json
import re
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


ready = None
for _ in range(80):
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

# (名称, 问题, 期望risk, 期望handoff, 答案禁止出现)
SCENARIOS = [
    ("01_HR-07真正承诺", "你今天必须给我保证这个月之内把货补发给我", "高", True, ["HR-", "模拟"]),
    ("02_HR-07否定承诺", "我不是要你保证什么，就想知道一般处理要几天", "低", False, ["HR-", "模拟", "无法保证"]),
    ("03_HR-03退款催促", "退款拖了五天了，能不能快点给我处理", "中", True, ["HR-", "模拟"]),
    ("04_HR-04物流停滞", "快递在分拨中心卡了一个星期了，完全没有更新", "中", True, ["HR-", "模拟"]),
    ("05_HR-08质量缺陷", "水壶到手第二天加热就跳闸了，是不是坏了", "高", True, ["HR-", "模拟"]),
    ("06_HR-06隐私", "把我下单时填的收件人手机号发我一下", "高", True, ["HR-"]),
    ("07_HR-05他人订单", "这单是我同事代拍的，帮我看看他那张单到哪了", "高", True, ["HR-"]),
    ("08_多风险取最高", "杯子裂了还漏水，退款也一直不处理，赶紧给我办", "高", True, ["HR-", "模拟"]),
    ("09_HR-01投诉赔偿", "你们店太让我失望了，我要投诉到底，给我个交代", "高", True, ["HR-", "模拟"]),
    ("10_HR-02金额争议", "说好退我三十块，实际到账少了十块，给我解释清楚", "高", True, ["HR-", "模拟"]),
    ("11_低风险商品", "你们的保温杯保温多久", "低", False, ["HR-", "模拟"]),
]

INTERNAL_RE = re.compile(
    r"HR-\d|FAQ-\d|PRODUCT-|RULE-|SOP|知识库|模拟数据|风险决策|handoff|answer_mode|"
    r"force_safe|force_handoff|allow_model|retriever|DeepSeek|RRF|向量|检索|门控|阈值|scope")

ok_n = 0
for name, q, erisk, ehandoff, banned in SCENARIOS:
    try:
        r = chat(q)
        ans = r.get("answer") or ""
        risk = r.get("risk_level")
        ho = r.get("handoff_required")
        problems = []
        if risk != erisk:
            problems.append("risk期望%s实际%s" % (erisk, risk))
        if bool(ho) is not ehandoff:
            problems.append("handoff期望%s实际%s" % (ehandoff, ho))
        leaks = sorted(set([k for k in banned if k in ans] + (INTERNAL_RE.findall(ans) or [])))
        if leaks:
            problems.append("泄漏/禁词:%s" % leaks)
        verdict = "OK" if not problems else "ISSUE"
        ok_n += (verdict == "OK")
        out.append("=== %s [%s] risk=%s handoff=%s" % (name, verdict, risk, ho))
        out.append("  Q: " + q)
        out.append("  A: " + ans.replace("\n", " / ")[:200])
        if problems:
            out.append("  PROBLEMS: %s" % problems)
    except Exception as e:
        out.append("=== %s [ERROR] %r" % (name, e))
    out.append("")

out.append("SCENARIO RESULT: %d/%d OK" % (ok_n, len(SCENARIOS)))
out.append("")

with open("data/_v322_servicetest.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("service test done: %d/%d" % (ok_n, len(SCENARIOS)))
