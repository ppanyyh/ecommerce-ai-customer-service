# -*- coding: utf-8 -*-
"""V2.0 前端端到端测试（playwright + 本机 Edge，无头）。

用例1-8、10：通过 http://127.0.0.1:8000/（FastAPI 托管，后端在线）
用例9：通过 http://127.0.0.1:8001/（静态目录服务，后端不在该端口）→ 验证本地规则回退

输出：e2e_report.txt（不输出任何敏感信息）
"""
import json
import re
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
STATIC = "http://127.0.0.1:8001"
OUT = []

# 双层输出原则：用户可见 answer 禁止出现内部检索/决策信息
LEAK_RE = re.compile(
    r"根据《|依据《|《[^》]{1,24}》|根据[^。？！]{0,8}资料|依据[^。？！]{0,8}资料"
    r"|HR-\d|FAQ-\d|SOP|知识库|现有资料未覆盖|资料未覆盖"
    r"|AI无法|AI不|模型判断|模型返回|risk_level|handoff_required|answer_mode"
    r"|force_safe|force_handoff|allow_model|DeepSeek|模拟数据"
)

MODE_TEXT = {
    "AI生成": "deepseek",
    "确定性规则": "deterministic",
    "本地降级": "fallback",
    "本地规则回答": "local",
}


def log(msg):
    OUT.append(msg)
    print(msg)


def send_and_wait(page, text, timeout_ms=40000):
    """输入并发送，等待本轮回答完成（发送按钮恢复可用且无加载气泡）。"""
    page.fill("#inputBox", text)
    page.click("#sendBtn")
    page.wait_for_function(
        """() => {
            const btn = document.getElementById('sendBtn');
            const loading = document.querySelector('.loading-bubble');
            return btn && !btn.disabled && !loading;
        }""",
        timeout=timeout_ms,
    )
    page.wait_for_timeout(300)


def last_ai(page):
    """取最后一条AI回复的文本与分析面板内容。"""
    bubbles = page.query_selector_all(".msg.ai .ai-bubble")
    answer = bubbles[-1].inner_text() if bubbles else ""
    return {
        "answer": answer,
        "category": page.inner_text("#anCategory").strip(),
        "risk": page.inner_text("#anRisk").strip(),
        "transfer": page.inner_text("#anTransfer").strip(),
        "mode": page.inner_text("#anMode").strip(),
        "basis": page.inner_text("#anBasis").strip(),
    }


def run_page_tests(page, base_url, cases, tag, console_errors):
    results = []
    for c in cases:
        send_and_wait(page, c["q"])
        r = last_ai(page)
        # 双层输出检查：用户可见回答不得含内部依据/规则编号
        leak = LEAK_RE.search(r["answer"])
        ok_flags = [("无内部信息泄露", leak is None)]
        for key, check in c["checks"].items():
            try:
                ok_flags.append((key, check(r)))
            except Exception:
                ok_flags.append((key, False))
        all_ok = all(v for _, v in ok_flags)
        results.append({"case": c["name"], "ok": all_ok, "detail": r, "flags": ok_flags})
        log(f"[{tag}] {c['name']}: {'PASS' if all_ok else 'FAIL'}")
        for k, v in ok_flags:
            if not v:
                log(f"    未通过检查项: {k}")
        log(f"    分类={r['category']} 风险={r['risk']} 转人工={r['transfer']} 模式={r['mode']}")
        log(f"    回答前80字: {r['answer'][:80].replace(chr(10), ' / ')}")
    return results


def main():
    static_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8001",
         "--directory", r"F:\电商AI客服助手\08_V2_DeepSeek\frontend"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            all_console_errors = []
            all_page_errors = []

            # ---------- 后端在线：用例1-8 + 用例10 ----------
            page = browser.new_page()
            page.on("console", lambda m: all_console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: all_page_errors.append(str(e)))
            page.goto(BASE + "/", wait_until="networkidle")
            status_chip = page.inner_text("#apiStatus").strip()
            log(f"[8000] 状态标签: {status_chip}")

            cases_online = [
                {"name": "TC1 P001耳机续航",
                 "q": "P001耳机续航多久？",
                 "checks": {
                     "模式=AI生成": lambda r: r["mode"] == "AI生成",
                     "分类=商品": lambda r: r["category"] == "商品",
                     "风险=低": lambda r: r["risk"] == "低",
                     "不转人工": lambda r: r["transfer"] == "不需要",
                     "回答非空": lambda r: len(r["answer"].strip()) > 10,
                 }},
                {"name": "TC2 P002价格/连接/保修",
                 "q": "P002的价格、连接方式和保修是多久？",
                 "checks": {
                     "模式=AI生成": lambda r: r["mode"] == "AI生成",
                     "分类=商品": lambda r: r["category"] == "商品",
                     "多属性完整(含价格)": lambda r: ("售价" in r["answer"] or "元" in r["answer"] or "价格" in r["answer"]),
                     "多属性完整(含连接/蓝牙)": lambda r: ("连接" in r["answer"] or "蓝牙" in r["answer"] or "2.4G" in r["answer"] or "有线" in r["answer"]),
                     "多属性完整(含保修)": lambda r: "保修" in r["answer"],
                 }},
                {"name": "TC3 查询订单202609180001",
                 "q": "查询订单202609180001",
                 "checks": {
                     "模式=AI生成": lambda r: r["mode"] == "AI生成",
                     "分类=订单与支付": lambda r: r["category"] == "订单与支付",
                     "回答含订单号": lambda r: "202609180001" in r["answer"],
                     "回答含商品": lambda r: ("商品" in r["answer"] or "订单" in r["answer"]),
                 }},
                {"name": "TC4 退款进度查询",
                 "q": "202609180002退款到哪一步？",
                 "checks": {
                     "模式=AI生成": lambda r: r["mode"] == "AI生成",
                     "分类=售后": lambda r: r["category"] == "售后",
                     "风险=低": lambda r: r["risk"] == "低",
                     "不转人工": lambda r: r["transfer"] == "不需要",
                 }},
                {"name": "TC5 催促退款",
                 "q": "202609180002为什么还不退款？请立即处理",
                 "checks": {
                     "模式=AI生成": lambda r: r["mode"] == "AI生成",
                     "分类=售后": lambda r: r["category"] == "售后",
                     "风险=中或高": lambda r: r["risk"] in ("中", "高"),
                     "转人工": lambda r: r["transfer"] == "需要转人工",
                 }},
                {"name": "TC6 投诉三倍赔偿",
                 "q": "我要投诉并要求三倍赔偿",
                 "checks": {
                     "模式=AI生成": lambda r: r["mode"] == "AI生成",
                     "分类=售后": lambda r: r["category"] == "售后",
                     "风险=高": lambda r: r["risk"] == "高",
                     "转人工": lambda r: r["transfer"] == "需要转人工",
                 }},
                {"name": "TC7 不存在订单",
                 "q": "查询订单202609189999",
                 "checks": {
                     "模式=确定性规则": lambda r: r["mode"] == "确定性规则",
                     "分类=订单与支付": lambda r: r["category"] == "订单与支付",
                     "提示核对订单号": lambda r: ("未查询到" in r["answer"] or "核对" in r["answer"]),
                     "不转人工": lambda r: r["transfer"] == "不需要",
                 }},
                {"name": "TC8 天气问题",
                 "q": "北京今天会下雨吗？",
                 "checks": {
                     "模式=确定性规则": lambda r: r["mode"] == "确定性规则",
                     "分类=其他": lambda r: r["category"] == "其他",
                     "风险=低": lambda r: r["risk"] == "低",
                     "不转人工": lambda r: r["transfer"] == "不需要",
                     "无关问题引导话术": lambda r: "只能协助处理商品、订单、物流和售后" in r["answer"],
                 }},
            ]
            online_results = run_page_tests(page, BASE, cases_online, "8000", all_console_errors)

            # ---------- 用例10：空输入 + 快速连续点击 ----------
            log("[8000] TC10 空输入与快速连续点击")
            errors_before = len(all_console_errors) + len(all_page_errors)
            users_before = len(page.query_selector_all(".msg.user"))
            for _ in range(5):
                page.click("#sendBtn")  # 空输入连点5次
            page.wait_for_timeout(500)
            empty_ok = len(page.query_selector_all(".msg.user")) == users_before
            tip_visible = page.is_visible("#inputTip")
            page.fill("#inputBox", "P003保温效果如何？")
            for _ in range(4):  # 输入后快速连点4次
                page.click("#sendBtn")
                page.wait_for_timeout(50)
            try:
                page.wait_for_function(
                    """() => { const b=document.getElementById('sendBtn'); return b && !b.disabled; }""",
                    timeout=40000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            users_after = len(page.query_selector_all(".msg.user"))
            singles_ok = users_after == users_before + 1  # 连点4次只新增1条提问
            no_js_err = (len(all_console_errors) + len(all_page_errors)) == errors_before
            log(f"    空输入不发送: {'PASS' if empty_ok else 'FAIL'}; 空输入提示显示: {'PASS' if tip_visible else 'FAIL'}; "
                f"连点只发一次(新增提问={users_after - users_before}): {'PASS' if singles_ok else 'FAIL'}; "
                f"无新增JS错误: {'PASS' if no_js_err else 'FAIL'}")

            # ---------- 用例9：后端不可用 → 本地规则回退 ----------
            page2 = browser.new_page()
            page2.on("console", lambda m: all_console_errors.append("static:" + m.text) if m.type == "error" else None)
            page2.on("pageerror", lambda e: all_page_errors.append("static:" + str(e)))
            page2.goto(STATIC + "/", wait_until="load")
            page2.wait_for_timeout(1500)
            chip2 = page2.inner_text("#apiStatus").strip()
            log(f"[8001] 状态标签: {chip2}")
            send_and_wait(page2, "P001耳机续航多久？")
            r9 = last_ai(page2)
            tc9_ok = (r9["mode"] == "本地规则回答" and len(r9["answer"]) > 10
                      and r9["category"] == "商品")
            log(f"[8001] TC9 后端不可用回退: {'PASS' if tc9_ok else 'FAIL'} "
                f"(模式={r9['mode']} 分类={r9['category']} 回答前60字={r9['answer'][:60]})")
            # 页面未崩溃：可继续交互
            send_and_wait(page2, "查询订单202609180001")
            r9b = last_ai(page2)
            alive_ok = len(r9b["answer"]) > 10
            log(f"[8001] TC9b 页面未崩溃可继续交互: {'PASS' if alive_ok else 'FAIL'}")

            # ---------- 汇总 ----------
            total = len(online_results) + 1 + 1
            passed = sum(1 for r in online_results if r["ok"]) + (1 if tc9_ok else 0) + (1 if alive_ok else 0)
            log("")
            log(f"端到端合计: {passed}/{total} 组通过")
            log(f"控制台红色错误: {len(all_console_errors)} 条; 页面异常: {len(all_page_errors)} 条")
            for e in (all_console_errors + all_page_errors)[:10]:
                log(f"  ERR: {e[:200]}")
            log(f"TC10 明细: 空输入={empty_ok} 提示={tip_visible} 单次发送={singles_ok} 无JS错误={no_js_err}")

            # 状态标签断言
            log(f"8000状态标签应为'AI服务已连接': {'PASS' if status_chip == 'AI服务已连接' else 'FAIL(' + status_chip + ')'}")
            log(f"8001状态标签应为'本地模式': {'PASS' if chip2 == '本地模式' else 'FAIL(' + chip2 + ')'}")

            browser.close()
    finally:
        static_proc.terminate()

    with open(r"F:\电商AI客服助手\08_V2_DeepSeek\backend\e2e_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(OUT))


if __name__ == "__main__":
    main()
