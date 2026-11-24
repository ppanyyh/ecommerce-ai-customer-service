# -*- coding: utf-8 -*-
"""V3.1 第三阶段：/api/chat 端到端集成测试（V3.1 混合检索接入后）。

运行方式（backend 目录下或项目根目录）：
    python backend/test_v3_1_api_integration.py

要点：
- 全程 DeepSeek 调用次数必须为 0：本测试显式清空 DEEPSEEK_API_KEY，
  并验证无 Key 时 generate_reply 抛 DeepSeekConfigError（不发起网络请求）；
  supported 问题在无 Key 时走本地降级（answer_mode=fallback）。
- 不使用旧 final blind set 题目；全部测试表达为本阶段重新编写。
- 覆盖 16 类：商品参数 / 已覆盖FAQ / 普通退货 / 质量缺陷 / 投诉赔偿 /
  已知订单 / 不存在订单 / 发票未覆盖 / 促销赠品未覆盖 / 未知商品 /
  完全无关 / 空输入 / 重复请求 / DeepSeek不可用降级 / health / ready。
- 校验：HTTP 200、六字段+answer_mode+risk_decision、sources 合法、
  用户文案不含内部术语、门控结果不携带知识来源、订单无回归、前端字段兼容。
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- DeepSeek 调用隔离：先清空 Key 再导入 main（load_dotenv 不覆盖已存在变量）----
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ.pop("FORCE_DEEPSEEK_FAILURE", None)

import main                      # noqa: E402
import deepseek_client           # noqa: E402
import v3_retrieval_adapter      # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

RESULTS = []


def check(case, item, cond, detail=""):
    RESULTS.append((case, item, bool(cond), detail))
    print(("[PASS] " if cond else "[FAIL] ") + f"{case} | {item}" + (f" | {detail}" if detail and not cond else ""))


# 用户可见文案不得出现内部术语（比 main._INTERNAL_LEAK_RE 更严：含门控/scope/分数等）
_USER_LEAK_RE = re.compile(
    r"HR-\d|FAQ-\d|SOP|知识库|门控|gated|scope|supported|unsupported|irrelevant"
    r"|相似度|向量|关键词|RRF|rf|阈值|评分|分数|retriev|检索|DeepSeek|API|模型判断"
    r"|风险决策|risk_level|handoff|answer_mode|来源|内部分析"
)

EXPECTED_FIELDS = {"category", "answer", "sources", "risk_level",
                   "handoff_required", "handoff_reason", "answer_mode", "risk_decision"}

API = "/api/chat"


def common(case, resp, expect_mode=None, expect_handoff=None, min_risk=None):
    data = resp.json()
    body = __import__("json").dumps(data, ensure_ascii=False)
    check(case, "HTTP状态=200", resp.status_code == 200, f"实际={resp.status_code} {body[:200]}")
    check(case, "字段结构完整(前端兼容)", EXPECTED_FIELDS.issubset(data.keys()), f"实际={sorted(data.keys())}")
    check(case, "answer非空", bool(str(data.get("answer", "")).strip()))
    check(case, "sources为字符串数组",
          isinstance(data.get("sources"), list) and all(isinstance(s, str) for s in data["sources"]),
          f"sources={data.get('sources')}")
    check(case, "risk_level合法", data.get("risk_level") in ("低", "中", "高"), f"实际={data.get('risk_level')}")
    check(case, "answer_mode合法", data.get("answer_mode") in ("deterministic", "deepseek", "fallback"),
          f"实际={data.get('answer_mode')}")
    check(case, "risk_decision合法", data.get("risk_decision") in ("force_safe", "force_handoff", "allow_model"),
          f"实际={data.get('risk_decision')}")
    ans = str(data.get("answer", ""))
    check(case, "answer无内部术语", not _USER_LEAK_RE.search(ans), f"命中={_USER_LEAK_RE.findall(ans)[:3]}")
    if expect_mode is not None:
        check(case, f"answer_mode={expect_mode}", data.get("answer_mode") == expect_mode, f"实际={data.get('answer_mode')}")
    if expect_handoff is not None:
        check(case, f"handoff_required={expect_handoff}", data.get("handoff_required") == expect_handoff,
              f"实际={data.get('handoff_required')}")
    if min_risk is not None:
        order = ("低", "中", "高")
        check(case, f"risk_level>={min_risk}",
              order.index(data.get("risk_level", "低")) >= order.index(min_risk),
              f"实际={data.get('risk_level')}")
    return data


def post(client, msg):
    return client.post(API, json={"message": msg, "history": []})


def main_test():
    # ---- DeepSeek 隔离的直接证明：无 Key 时配置异常，不发起网络请求 ----
    try:
        deepseek_client.generate_reply(message="隔离验证", context="（无资料片段）")
        check("DeepSeek隔离", "无Key调用抛DeepSeekConfigError", False, "未抛异常")
    except deepseek_client.DeepSeekConfigError:
        check("DeepSeek隔离", "无Key调用抛DeepSeekConfigError", True)
    except Exception as e:
        check("DeepSeek隔离", "无Key调用抛DeepSeekConfigError", False, f"异常类型={type(e).__name__}")

    with TestClient(main.app) as client:  # with 触发 lifespan 预热
        # ---- 1) 已知商品参数（supported；无Key → 本地降级）----
        r = post(client, "机械键盘在苹果电脑上能用吗，Mac系统兼容不兼容？")
        d = common("C01商品参数", r, expect_mode="fallback")
        check("C01商品参数", "sources来自知识库(非现有资料未覆盖)",
              bool(d["sources"]) and "现有资料未覆盖" not in d["sources"], f"sources={d['sources']}")
        check("C01商品参数", "无Key本地降级(不走真实DeepSeek)", main.STATS["deepseek_success"] == 0)

        # ---- 2) 已覆盖FAQ ----
        r = post(client, "付款成功了订单还是显示待付款，这是什么情况？")
        d = common("C02已覆盖FAQ", r, expect_mode="fallback")
        check("C02已覆盖FAQ", "sources来自知识库", "现有资料未覆盖" not in d["sources"], f"sources={d['sources']}")

        # ---- 3) 普通退货（supported，低风险）----
        r = post(client, "刚下单的键盘还没拆包装，不想要了想退，流程怎么走？")
        d = common("C03普通退货", r, expect_mode="fallback", expect_handoff=False)

        # ---- 4) 已发生质量缺陷（HR-08 风险下限 → 转人工）----
        r = post(client, "刚收到的保温杯杯盖拧不开，螺纹那里好像坏了")
        d = common("C04质量缺陷", r, expect_handoff=True, min_risk="高")
        check("C04质量缺陷", "风险等级不被降低", d["risk_level"] == "高", f"实际={d['risk_level']}")

        # ---- 5) 投诉或赔偿（HR-01 → 转人工）----
        r = post(client, "你们再不处理我就去投诉，必须赔偿我的损失")
        d = common("C05投诉赔偿", r, expect_handoff=True, min_risk="高")

        # ---- 6) 已知订单查询（V2 结构化订单，无回归）----
        r = post(client, "订单202609180003用的哪家快递？现在物流到哪儿了？")
        d = common("C06已知订单", r, expect_mode="fallback")
        check("C06已知订单", "category=订单与支付", d["category"] == "订单与支付", f"实际={d['category']}")
        check("C06已知订单", "sources为订单资料",
              any("模拟订单" in s for s in d["sources"]), f"sources={d['sources']}")
        check("C06已知订单", "低风险不转人工", d["risk_level"] == "低" and not d["handoff_required"])

        # ---- 6b) 订单号 + 高风险表达：本地风险下限不被降低 ----
        r = post(client, "订单202609180001你们必须马上退款赔偿我，不然我投诉到底")
        d = common("C06b订单+高风险", r, expect_handoff=True, min_risk="中")
        check("C06b订单+高风险", "转人工原因非空", bool(str(d.get("handoff_reason", "")).strip()))

        # ---- 7) 不存在订单（确定性，不调模型）----
        r = post(client, "帮我查一下订单202609189999现在的状态")
        d = common("C07不存在订单", r, expect_mode="deterministic")
        check("C07不存在订单", "提示核对订单号", "核对" in d["answer"], f"answer={d['answer'][:40]}")
        check("C07不存在订单", "category=订单与支付", d["category"] == "订单与支付")

        # ---- 8) 发票政策未覆盖（unsupported_business，确定性，不调模型）----
        r = post(client, "下单的时候忘了要发票，现在还能补开吗？")
        d = common("C08发票未覆盖", r, expect_mode="deterministic", expect_handoff=True)
        check("C08发票未覆盖", "告知资料无法确认并给下一步",
              ("没有覆盖" in d["answer"]) and ("人工" in d["answer"]), f"answer={d['answer']}")
        check("C08发票未覆盖", "sources不伪造知识来源",
              d["sources"] == ["现有资料未覆盖"], f"sources={d['sources']}")
        check("C08发票未覆盖", "无知识片段编号混入answer", not _USER_LEAK_RE.search(d["answer"]))

        # ---- 9) 未记录促销或赠品（unsupported_business）----
        r = post(client, "这周店里有什么满减活动或者赠品吗？")
        d = common("C09促销赠品未覆盖", r, expect_mode="deterministic", expect_handoff=True)
        check("C09促销赠品未覆盖", "sources不伪造", d["sources"] == ["现有资料未覆盖"])

        # ---- 10) 未知商品（unsupported_business）----
        r = post(client, "你们店里卖不卖充电宝？")
        d = common("C10未知商品", r, expect_mode="deterministic", expect_handoff=True)

        # ---- 11) 完全无关问题（irrelevant，确定性，不调模型）----
        r = post(client, "最近有什么好看的电影推荐一下呗")
        d = common("C11完全无关", r, expect_mode="deterministic", expect_handoff=False)
        check("C11完全无关", "范围说明文案", "商品" in d["answer"] and "售后" in d["answer"], f"answer={d['answer']}")
        check("C11完全无关", "不携带知识来源", d["sources"] == ["现有资料未覆盖"], f"sources={d['sources']}")
        check("C11完全无关", "risk_decision=force_safe", d["risk_decision"] == "force_safe")

        # ---- 12) 空输入 ----
        # 既有契约：message min_length=1（schemas 未改动，冻结基线内）→ 空字符串 422 校验拒绝；
        # 纯空白（长度>=1）通过校验，由确定性分支给出引导文案。
        r = post(client, "")
        check("C12空输入", "空字符串返回422校验拒绝(非500)", r.status_code == 422, f"实际={r.status_code}")
        r = post(client, "    ")
        d = common("C12空输入-纯空白", r, expect_mode="deterministic")
        check("C12空输入-纯空白", "给出引导文案", "咨询" in d["answer"] or "输入" in d["answer"], f"answer={d['answer'][:40]}")

        # ---- 13) 连续快速点击 / 重复请求 ----
        results = [post(client, "双肩包的面料耐磨吗？") for _ in range(3)]
        check("C13重复请求", "三次均HTTP 200", all(x.status_code == 200 for x in results))
        bodies = [x.json() for x in results]
        check("C13重复请求", "三次answer_mode一致",
              len({b["answer_mode"] for b in bodies}) == 1, f"实际={ {b['answer_mode'] for b in bodies} }")
        check("C13重复请求", "三次category一致", len({b["category"] for b in bodies}) == 1)

        # ---- 14) DeepSeek强制失败：HTTP仍200（FORCE_DEEPSEEK_FAILURE）----
        os.environ["FORCE_DEEPSEEK_FAILURE"] = "true"
        try:
            r = post(client, "耳机的防水等级是多少？")
            d = common("C14强制失败降级", r, expect_mode="fallback")
            check("C14强制失败降级", "HTTP仍200且不泄露Key", r.status_code == 200 and "sk-" not in __import__("json").dumps(d))
        finally:
            os.environ.pop("FORCE_DEEPSEEK_FAILURE", None)

        # ---- 15) /api/health ----
        r = client.get("/api/health")
        check("C15健康检查", "HTTP 200", r.status_code == 200)
        h = r.json()
        check("C15健康检查", "status=ok", h.get("status") == "ok")
        check("C15健康检查", "deepseek_configured=False(测试隔离)", h.get("deepseek_configured") is False)
        check("C15健康检查", "不返回Key内容", "sk-" not in __import__("json").dumps(h))

        # ---- 16) /api/ready（lifespan 预热完成后 ready=true）----
        r = client.get("/api/ready")
        check("C16就绪检查", "HTTP 200", r.status_code == 200)
        rd = r.json()
        check("C16就绪检查", "ready=true", rd.get("ready") is True, f"实际={rd}")
        check("C16就绪检查", "vector_warmed=true", rd.get("vector_warmed") is True)
        check("C16就绪检查", "warmup_ms已记录", isinstance(rd.get("warmup_ms"), (int, float)))

        # ---- 前端静态兼容（路由未被 /api 覆盖）----
        r = client.get("/")
        if r.status_code == 200:
            check("C17前端静态", "根路径返回HTML", "text/html" in r.headers.get("content-type", ""),
                  f"content-type={r.headers.get('content-type')}")
        else:
            check("C17前端静态", "根路径返回HTML", False, f"status={r.status_code}（frontend目录未挂载?）")

    # ---- 全局 DeepSeek 计数 ----
    check("全局", "DeepSeek成功调用次数=0", main.STATS["deepseek_success"] == 0, f"STATS={main.STATS}")
    check("全局", "DeepSeek真实网络调用=0(无Key仅配置异常)",
          main.STATS["deepseek_failed"] == main.STATS["deepseek_attempts"], f"STATS={main.STATS}")


def report():
    total = len(RESULTS)
    passed = sum(1 for _, _, ok, _ in RESULTS if ok)
    failed = [(c, i, d) for c, i, ok, d in RESULTS if not ok]
    print("\n===== V3.1 API 集成测试结论 =====")
    print(f"通过 {passed}/{total}")
    for c, i, d in failed:
        print(f"  [FAIL] {c} | {i} | {d}")
    print("DeepSeek STATS:", main.STATS)
    return 0 if not failed else 1


if __name__ == "__main__":
    main_test()
    sys.exit(report())
