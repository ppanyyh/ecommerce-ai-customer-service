# -*- coding: utf-8 -*-
"""V2.0 阶段六集成测试：/api/chat 全链路（retriever -> DeepSeek -> 本地校验兜底 -> 降级）+ 双层输出口径。

运行方式（backend 目录下）：
    python test_chat_integration.py

说明：
- 使用 fastapi.testclient（HTTP 层集成测试，不启动长期后台服务）；
- 涉及真实 DeepSeek 调用（Key 从 backend/.env 读取，仅本地存在，绝不打印）；
- FORCE_DEEPSEEK_FAILURE=true 用于回退测试（模拟失败，不发起真实请求、不泄露 Key）；
- 测试结束后自动恢复该环境变量为关闭状态；
- 覆盖三种风险决策模式：force_safe / force_handoff / allow_model。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import main
import retriever
from fastapi.testclient import TestClient

client = TestClient(main.app)
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()  # 仅用于泄露断言，绝不输出

RESULTS = []          # (用例, 检查项, 通过?, 详情)
REPORT_LINES = []


def check(case: str, item: str, cond: bool, detail: str = ""):
    RESULTS.append((case, item, bool(cond), detail))


def snapshot_stats() -> dict:
    return dict(main.STATS)


def validate_common(case: str, resp, message: str):
    """所有用例共通校验：HTTP 200、六字段+answer_mode+risk_decision、sources 合法、Key 不泄露。"""
    check(case, "HTTP状态=200", resp.status_code == 200, f"实际={resp.status_code}")
    data = resp.json()
    expected_keys = {"category", "answer", "sources", "risk_level",
                     "handoff_required", "handoff_reason", "answer_mode", "risk_decision"}
    check(case, "字段结构完整", expected_keys.issubset(data.keys()),
          f"实际字段={sorted(data.keys())}")
    check(case, "answer非空", bool(str(data.get("answer", "")).strip()))
    check(case, "sources为非空字符串数组",
          isinstance(data.get("sources"), list) and data["sources"]
          and all(isinstance(s, str) and s.strip() for s in data["sources"]),
          f"sources={data.get('sources')}")
    check(case, "risk_level合法", data.get("risk_level") in ("低", "中", "高"),
          f"实际={data.get('risk_level')}")
    check(case, "risk_decision合法",
          data.get("risk_decision") in ("force_safe", "force_handoff", "allow_model"),
          f"实际={data.get('risk_decision')}")
    check(case, "handoff与reason自洽",
          (not data.get("handoff_required")) or bool(str(data.get("handoff_reason", "")).strip()),
          f"handoff={data.get('handoff_required')}, reason={data.get('handoff_reason')}")
    # sources 必须来自 retriever 返回的来源
    allowed = set(retriever.retrieve(message)["sources"])
    srcs_ok = all(s in allowed for s in data.get("sources", []))
    check(case, "sources均在retriever来源内", srcs_ok,
          f"允许={sorted(allowed)}, 实际={data.get('sources')}")
    # API Key 泄露检查（只做断言，不打印 Key）
    body_text = json.dumps(data, ensure_ascii=False)
    check(case, "响应不泄露APIKey", (not API_KEY) or (API_KEY not in body_text))
    return data


CASES = [
    ("TC-01", "P001耳机续航多久", {
        "category": {"商品"},
        "answer_mode": {"deepseek"},
        "handoff": {False},
        "risk_min": "低",
        "decision": {"allow_model"},
        "answer_contains": ("小时",),
    }),
    ("TC-02", "P002价格、连接方式和保修", {
        "category": {"商品"},
        "answer_mode": {"deepseek"},
        "handoff": {False},
        "risk_min": "低",
        "decision": {"allow_model"},
        "answer_contains": ("459",),
    }),
    ("TC-03", "查询订单202609180001", {
        "category": {"订单与支付"},
        "answer_mode": {"deepseek"},
        "handoff": {False},
        "risk_min": "低",
        "decision": {"allow_model"},
        "answer_contains": ("运输中", "已发货", "顺丰"),
    }),
    ("TC-04", "202609180002退款到哪一步", {
        "category": {"售后"},          # 单纯退款进度查询：统一“售后”
        "answer_mode": {"deepseek"},
        "handoff": {False},            # 不含催促/金额争议/投诉 → 不转人工
        "risk_eq": "低",               # 即使模型返回中风险也覆盖为低
        "decision": {"force_safe"},
        "answer_contains": ("退款审核", "审核中", "退款"),
    }),
    ("TC-05", "商品质量有问题怎么办", {
        "category": {"售后"},
        "answer_mode": {"deepseek"},
        "handoff": {True},             # HR-08 质量问题凭证核验：必须转人工
        "risk_min": "高",
        "decision": {"force_handoff"},
        "answer_contains": ("凭证", "订单", "人工"),
    }),
    ("TC-06", "我要投诉并要求三倍赔偿", {
        "category": {"售后"},          # 投诉赔偿统一“售后”
        "answer_mode": {"deepseek"},
        "handoff": {True},             # HR-01 投诉与赔偿：必须转人工
        "risk_eq": "高",
        "decision": {"force_handoff"},
        "answer_contains": ("人工",),
    }),
    ("TC-07", "查询不存在的订单202609189999", {
        "category": {"订单与支付"},
        "answer_mode": {"deterministic"},
        "handoff": {False},
        "risk_eq": "低",
        "decision": {"force_safe"},
        "answer_contains": ("未查询到该模拟订单",),
    }),
    ("TC-08", "北京今天会下雨吗", {
        "category": {"其他"},          # 完全无关问题：不转人工、不调模型
        "answer_mode": {"deterministic"},
        "handoff": {False},
        "risk_eq": "低",
        "decision": {"force_safe"},
        "answer_contains": ("只能协助处理商品、订单、物流和售后",),
    }),
]

# 用户新增的 6 条口径回归用例
REGRESSION_CASES = [
    ("RG-01", "202609180002退款到哪一步？", {
        "category": {"售后"}, "risk_eq": "低", "handoff": {False},
        "answer_mode": {"deepseek"}, "decision": {"force_safe"},
    }),
    ("RG-02", "202609180002为什么还不退款？请立即处理", {
        "category": {"售后"}, "risk_min": "中", "handoff": {True},
        "answer_mode": {"deepseek"}, "decision": {"force_handoff"},
    }),
    ("RG-03", "退款金额不对，我要投诉", {
        "category": {"售后"}, "risk_eq": "高", "handoff": {True},
        "answer_mode": {"deepseek"}, "decision": {"force_handoff"},
    }),
    ("RG-04", "北京今天会下雨吗？", {
        "category": {"其他"}, "risk_eq": "低", "handoff": {False},
        "answer_mode": {"deterministic"}, "decision": {"force_safe"},
        "answer_contains": ("只能协助处理商品、订单、物流和售后",),
    }),
    ("RG-05", "可以开发票吗？", {
        "category": {"其他"}, "handoff": {True},          # 资料缺少政策 → 建议转人工
        "answer_mode": {"deepseek"}, "decision": {"allow_model"},
        "answer_contains": ("人工", "暂时无法确认"),
    }),
    ("RG-06", "我要投诉并要求三倍赔偿", {
        "category": {"售后"}, "risk_eq": "高", "handoff": {True},
        "answer_mode": {"deepseek"}, "decision": {"force_handoff"},
    }),
]


def risk_at_least(actual: str, floor: str) -> bool:
    order = ("低", "中", "高")
    return order.index(actual) >= order.index(floor)


def run_case(case: str, message: str, exp: dict):
    before = snapshot_stats()
    resp = client.post("/api/chat", json={"message": message})
    data = validate_common(case, resp, message)

    check(case, "category正确", data.get("category") in exp["category"],
          f"期望{exp['category']}, 实际={data.get('category')}")
    check(case, "answer_mode正确", data.get("answer_mode") in exp["answer_mode"],
          f"期望{exp['answer_mode']}, 实际={data.get('answer_mode')}")
    check(case, "handoff判断正确", data.get("handoff_required") in exp["handoff"],
          f"期望{exp['handoff']}, 实际={data.get('handoff_required')}")
    if exp.get("risk_eq"):
        check(case, f"风险等级={exp['risk_eq']}", data.get("risk_level") == exp["risk_eq"],
              f"实际={data.get('risk_level')}")
    if exp.get("risk_min"):
        check(case, "风险不低于下限", risk_at_least(data.get("risk_level", "低"), exp["risk_min"]),
              f"下限={exp['risk_min']}, 实际={data.get('risk_level')}")
    if exp.get("decision"):
        check(case, "risk_decision正确", data.get("risk_decision") in exp["decision"],
              f"期望{exp['decision']}, 实际={data.get('risk_decision')}")
    if exp.get("answer_contains"):
        hit = any(k in data.get("answer", "") for k in exp["answer_contains"])
        check(case, f"answer包含关键信息{exp['answer_contains']}", hit)
    # 双层输出原则：用户可见 answer 不得含内部依据/规则编号（sources 等内部字段不受限）
    leak = main._internal_leak(data.get("answer", ""))
    check(case, "answer无内部依据/规则编号泄露", leak is None, f"命中={leak}")

    expect_attempt = exp["answer_mode"] == {"deepseek"}
    delta = main.STATS["deepseek_attempts"] - before["deepseek_attempts"]
    if not expect_attempt:
        check(case, "未调用DeepSeek", delta == 0, f"实际尝试次数={delta}")
    report(f"[{case}] mode={data['answer_mode']} category={data['category']} "
           f"risk={data['risk_level']} handoff={data['handoff_required']} "
           f"decision={data['risk_decision']} attempts+{delta} sources={data['sources']}")
    report(f"    answer: {data['answer'][:120].replace(chr(10), ' ')}")


def run_main_cases():
    report("== 一、8条集成用例（含真实DeepSeek调用） ==")
    for case, message, exp in CASES:
        run_case(case, message, exp)


def run_regression_cases():
    report("")
    report("== 二、业务口径回归用例（6条，风险决策模式） ==")
    for case, message, exp in REGRESSION_CASES:
        run_case(case, message, exp)


def run_extra_deterministic_cases():
    report("")
    report("== 三、补充确定性用例（空输入 / 隐私 / 不完整订单号） ==")
    extras = [
        ("TC-EX1", "   ", {"category": {"其他"}, "answer_mode": {"deterministic"}, "handoff": {False}, "risk_eq": "低"}),
        ("TC-EX2", "帮我查一下别人的订单", {"category": {"其他"}, "answer_mode": {"deterministic"}, "handoff": {True}, "risk_eq": "高"}),
        ("TC-EX3", "我的订单号是20260918", {"category": {"订单与支付"}, "answer_mode": {"deterministic"}, "handoff": {False}, "risk_eq": "低",
                        "answer_contains": ("12位",)}),
    ]
    for case, message, exp in extras:
        run_case(case, message, exp)


def run_health_case():
    report("")
    report("== 四、health 接口 ==")
    resp = client.get("/api/health")
    data = resp.json()
    check("HC-01", "HTTP状态=200", resp.status_code == 200)
    check("HC-01", "mode=hybrid_rag_with_structured_orders", data.get("mode") == "hybrid_rag_with_structured_orders", f"实际={data.get('mode')}")
    check("HC-01", "deepseek_configured为布尔", isinstance(data.get("deepseek_configured"), bool))
    check("HC-01", "响应不泄露APIKey", (not API_KEY) or (API_KEY not in json.dumps(data)))
    check("HC-01", "版本=3.2.3", data.get("version") == "3.2.3")
    report(f"health 响应：{json.dumps(data, ensure_ascii=False)}")


def run_fallback_case():
    report("")
    report("== 五、回退测试（FORCE_DEEPSEEK_FAILURE=true，模拟失败不泄露Key） ==")
    os.environ["FORCE_DEEPSEEK_FAILURE"] = "true"
    try:
        case, message = "FB-01", "P001耳机续航多久"
        before = snapshot_stats()
        resp = client.post("/api/chat", json={"message": message})
        data = validate_common(case, resp, message)
        check(case, "answer_mode=fallback", data.get("answer_mode") == "fallback", f"实际={data.get('answer_mode')}")
        allowed = set(retriever.retrieve(message)["sources"])
        check(case, "sources保留", all(s in allowed for s in data["sources"]) and data["sources"],
              f"sources={data['sources']}")
        check(case, "风险不降低", risk_at_least(data.get("risk_level", "低"), "低"))
        check(case, "handoff不被降低",
              data.get("handoff_required") == (retriever.retrieve(message)["requires_handoff"] or False))
        check(case, "未发起真实API调用", main.STATS["deepseek_attempts"] == before["deepseek_attempts"])
        report(f"[{case}] mode=fallback risk={data['risk_level']} handoff={data['handoff_required']} sources={data['sources']}")

        # 高风险用例的降级：风险与转人工判断不得低于本地规则
        case2, message2 = "FB-02", "商品质量有问题怎么办"
        resp2 = client.post("/api/chat", json={"message": message2})
        data2 = validate_common(case2, resp2, message2)
        check(case2, "answer_mode=fallback", data2.get("answer_mode") == "fallback", f"实际={data2.get('answer_mode')}")
        check(case2, "handoff保持True", data2.get("handoff_required") is True, f"实际={data2.get('handoff_required')}")
        check(case2, "风险保持高（不降低）", data2.get("risk_level") == "高", f"实际={data2.get('risk_level')}")
        report(f"[{case2}] mode=fallback risk={data2['risk_level']} handoff={data2['handoff_required']}")
    finally:
        os.environ.pop("FORCE_DEEPSEEK_FAILURE", None)  # 恢复关闭状态
    report("FORCE_DEEPSEEK_FAILURE 已恢复关闭")

    # 恢复验证：开关关闭后重新走 DeepSeek
    case3, message3 = "FB-03", "P001耳机续航多久"
    resp3 = client.post("/api/chat", json={"message": message3})
    data3 = validate_common("FB-03", resp3, message3)
    check("FB-03", "恢复后answer_mode=deepseek", data3.get("answer_mode") == "deepseek", f"实际={data3.get('answer_mode')}")
    report(f"[FB-03] 恢复后 mode={data3['answer_mode']}")


def report(line: str):
    REPORT_LINES.append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass


def main_test():
    report("V2.0 阶段六集成测试（/api/chat 全链路 + 双层输出口径，含风险决策模式与内部信息泄露检查）")
    report("")

    run_main_cases()
    run_regression_cases()
    run_extra_deterministic_cases()
    run_health_case()
    run_fallback_case()

    total = len(RESULTS)
    passed = sum(1 for _, _, ok, _ in RESULTS if ok)
    failed = [(c, i, d) for c, i, ok, d in RESULTS if not ok]

    report("")
    report("== 六、统计 ==")
    report(f"检查项：{passed}/{total} 通过")
    stats = main.STATS
    report(f"DeepSeek实际调用次数(attempts)={stats['deepseek_attempts']}，"
           f"成功={stats['deepseek_success']}，失败/未过校验={stats['deepseek_failed']}")
    report(f"确定性回答次数={stats['deterministic']}，降级回答次数={stats['fallback']}")
    if failed:
        report("未通过项：")
        for c, i, d in failed:
            report(f"  ✗ [{c}] {i} {d}")
    else:
        report("未通过项：无")
    report("P0/P1问题：" + ("存在，见未通过项" if failed else "未发现"))

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_chat_report.txt"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(REPORT_LINES) + "\n")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main_test())
