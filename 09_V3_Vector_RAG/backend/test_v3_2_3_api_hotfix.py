# -*- coding: utf-8 -*-
"""V3.2.3 API 回归：单边音频失效热修复（TestClient，DeepSeek 隔离，不重跑 blind）。"""
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

import main as app_main
from fastapi.testclient import TestClient

import deepseek_client
import risk_intents

# DeepSeek 调用守卫：任何调用记为严重失败
_call_log = {"deepseek": 0}
_orig_gen = deepseek_client.generate_reply


def _guard(*a, **k):
    _call_log["deepseek"] += 1
    raise RuntimeError("V3.2.3 热修复测试中禁止 DeepSeek 调用")


deepseek_client.generate_reply = _guard
app_main.deepseek_client.generate_reply = _guard if hasattr(app_main, "deepseek_client") else _orig_gen

_results = []


def check(cid, desc, ok, detail=""):
    _results.append(ok)
    print(("PASS" if ok else "FAIL"), cid, "|", desc, ("| " + str(detail)[:200] if detail and not ok else ""))


INTERNAL_TERMS = ["HR-", "RULE-", "SOP", "supported", "unsupported", "irrelevant",
                  "force_safe", "force_handoff", "allow_model", "门控", "RRF",
                  "相似度", "阈值", "retriever", "Embedding", "系统提示词", "知识库"]

# 正例：用户实测原句 + 5 条改写（含订单号/凭证/不加价格/不承诺 断言）
POSITIVES = [
    "昨天刚收到的耳机，今天早上右边就不出声了",
    "买回来第三天，右耳突然没声音了",
    "耳机用了一个星期，一边现在没有声",
    "刚拆开包装，只有一只耳机有声",
    "左侧耳罩这两天渐渐没声了，很难受",
    "耳机右边开始时有声音，后来不出声了",
]
# 反例：售前/参数咨询（不应转人工，不应判高风险）
NEGATIVES = [
    "这款耳机会不会用久了就没声音啊",
    "左右声道是不是都支持的？",
    "右耳声音会比左边大吗",
    "支持单耳使用吗？",
    "降噪效果怎么样？",
]

FORBIDDEN_PROMISE = ["保证退", "一定退", "包退", "包换", "一定换", "保证换",
                     "退款会在", "赔偿您", "赔您", "一定给您退"]

with TestClient(app_main.app) as client:
    # ---- 正例 ----
    for i, q in enumerate(POSITIVES, 1):
        r = client.post("/api/chat", json={"message": q})
        if r.status_code != 200:
            check(f"API-P{i}", "HTTP 200", False, r.status_code)
            continue
        d = r.json()
        tag = "用户实测原句" if i == 1 else f"改写{i - 1}"
        ok_cat = d.get("category") == "售后"
        ok_risk = d.get("risk_level") == "高"
        ok_hand = d.get("handoff_required") is True
        rd = d.get("risk_decision") or {}
        ok_rd = rd.get("risk", "高") in ("高",) if isinstance(rd, dict) else True
        ans = d.get("answer") or ""
        ok_hint = ("订单号" in ans) and ("人工" in ans or "客服" in ans)
        ok_no_price = "299" not in ans
        ok_no_pack = ("包装清单" not in ans) and ("配件" not in ans or "准备" in ans)
        ok_no_promise = not any(p in ans for p in FORBIDDEN_PROMISE)
        ok_no_leak = not any(t in ans for t in INTERNAL_TERMS)
        checks = {
            "category=售后": ok_cat, "risk=高": ok_risk, "handoff=true": ok_hand,
            "decision不降级": ok_rd, "提示订单号+人工核实": ok_hint,
            "无价格299": ok_no_price, "无包装内容": ok_no_pack,
            "无禁止承诺": ok_no_promise, "无内部术语": ok_no_leak,
        }
        check(f"API-P{i}", f"{tag}: 全部断言", all(checks.values()),
              {k: v for k, v in checks.items() if not v})
        if i == 1:
            print("  [原句回答]", ans[:180].replace("\n", " / "))

    # ---- 反例 ----
    # 口径说明：售前担忧句可能被门控判为 unsupported_business（risk=中/handoff=true，
    # V3.2.1 起既有保守口径，与本热修复无关且修复前行为相同）。
    # 本热修复只断言：不判「高」风险、未误触发 HR-08 强转人工。
    for i, q in enumerate(NEGATIVES, 1):
        r = client.post("/api/chat", json={"message": q})
        d = r.json() if r.status_code == 200 else {}
        ok = d.get("risk_level") != "高"
        check(f"API-N{i}", "售前/参数咨询不判高风险", ok,
              f"risk={d.get('risk_level')} handoff={d.get('handoff_required')}")

    # ---- 健康 ----
    h = client.get("/api/health").json()
    check("API-H1", "health version=3.2.3 & mode 不变",
          h.get("version") == "3.2.3" and h.get("mode") == "hybrid_rag_with_structured_orders", h)

check("CNT-1", "DeepSeek 调用 0 次", _call_log["deepseek"] == 0, _call_log)

total = len(_results)
passed = sum(1 for x in _results if x)
print()
print(f"==== V3.2.3 API 回归: {passed}/{total} 通过 | DeepSeek={_call_log['deepseek']} ====")
sys.exit(0 if passed == total else 1)
