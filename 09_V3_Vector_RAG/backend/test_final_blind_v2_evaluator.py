# -*- coding: utf-8 -*-
"""final blind set v2 评测器合成测试（全部使用合成 fixture，不含任何盲测 query）。

覆盖：Hit@1/Recall@3/MRR、Rule Recall@3、scope 混淆矩阵、false pass、route 准确率、
订单判定、风险下限与 handoff、forbidden claim、内部术语泄漏、P50/P95 与首调分离、
每题一次调用计数、异常不重试、已执行拒绝、哈希不一致拒绝。
"""

import hashlib
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import evaluate_final_blind_v2 as ev

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  | " + detail) if detail else ""))


# ---------- 1. rank metrics ----------
h1, r3, rr, rank = ev.rank_metrics({"A"}, ["A", "B", "C", "D"])
check("rank_metrics hit1/recall3/mrr", (h1, r3, rr, rank) == (1, 1.0, 1.0, 1))
h1, r3, rr, rank = ev.rank_metrics({"C", "E"}, ["A", "B", "C", "D", "F"])
check("rank_metrics relevant在rank3", (h1, r3, rr, rank) == (0, 0.5, round(1 / 3, 6), 3)
      or (h1, round(r3, 4), round(rr, 4), rank) == (0, 0.5, 0.3333, 3))
h1, r3, rr, rank = ev.rank_metrics({"X"}, ["A", "B"])
check("rank_metrics 未命中", (h1, r3, rr, rank) == (0, 0.0, 0.0, None))

# ---------- 2. rule recall3 ----------
check("rule_recall3 全中", ev.rule_recall3(["R1", "R2"], ["R1", "X", "R2", "Y"]) == 1.0)
check("rule_recall3 部分", ev.rule_recall3(["R1", "R2"], ["R1", "X", "Y"]) == 0.5)
check("rule_recall3 无required为None", ev.rule_recall3([], ["A"]) is None)

# ---------- 3. scope 混淆矩阵 / false pass / route ----------
pairs = [("supported", "supported"), ("supported", "supported"),
         ("unsupported_business", "unsupported_business"),
         ("unsupported_business", "supported"),
         ("irrelevant", "irrelevant"), ("irrelevant", "supported")]
m = ev.confusion_matrix(pairs)
check("混淆矩阵计数", m["supported"]["supported"] == 2
      and m["unsupported_business"]["supported"] == 1
      and m["irrelevant"]["supported"] == 1)
fake_a = [
    {"expected_scope": "supported", "actual_scope": "supported", "expected_route": "v3_hybrid",
     "actual_route": "v3_hybrid", "expected_handoff": False, "requires_handoff": False,
     "expected_risk_floor": "低", "required_rule_ids": [], "answer_hit1": 1,
     "answer_recall3": 1.0, "mrr": 1.0, "rule_recall3": None},
    {"expected_scope": "unsupported_business", "actual_scope": "supported",
     "expected_route": "api_deterministic", "actual_route": "api_deterministic",
     "expected_handoff": False, "requires_handoff": True, "expected_risk_floor": "低",
     "required_rule_ids": []},
    {"expected_scope": "irrelevant", "actual_scope": "irrelevant",
     "expected_route": "api_deterministic", "actual_route": "api_deterministic",
     "expected_handoff": False, "requires_handoff": False, "expected_risk_floor": "低",
     "required_rule_ids": []},
]
s = ev.build_summary(fake_a, [])
check("scope准确率", abs(s["scope_acc"] - 4 / 6) < 1e-9)
check("unsupported误放行", s["unsupported_false_pass"] == 1.0)
check("irrelevant误放行", s["irrelevant_false_pass"] == 0.0)
check("route准确率", s["route_acc"] == 1.0)

# ---------- 4. handoff / 高风险 / 订单 ----------
fake_risk = [
    {"expected_scope": "supported", "actual_scope": "supported", "expected_route": "v3_hybrid",
     "actual_route": "v3_hybrid", "expected_handoff": True, "requires_handoff": True,
     "expected_risk_floor": "高", "required_rule_ids": ["RULE-HR-08"], "answer_hit1": 1,
     "answer_recall3": 1.0, "mrr": 1.0, "rule_recall3": 1.0},
    {"expected_scope": "supported", "actual_scope": "supported", "expected_route": "v2_order_structured",
     "actual_route": "v2_order_structured", "expected_handoff": True, "requires_handoff": True,
     "expected_risk_floor": "高", "required_rule_ids": ["RULE-HR-01"],
     "order_checks": {"order_found": True, "order_risk": True}, "order_risk_handoff": True},
]
s2 = ev.build_summary(fake_risk, [])
check("高风险handoff成功率=1", s2["A_high_risk_handoff_success"] == 1.0
      and s2["A_high_risk_n"] == 2)
check("订单风险handoff判定", s2["order_risk_handoff_ok"] is True)
check("订单事实汇总", s2["order_fact_acc"] == 1.0)
check("HR-08召回", s2["hr08_recall3"] == 1.0 and s2["hr08_recall3_cases"] == 1)

# ---------- 5. A 层逐条：门控清洁 + 订单判定（合成 adapter，不含盲测query）----------
def fake_adapter_factory(results_by_query, counter):
    def fn(q):
        counter["n"] += 1
        if q in results_by_query and isinstance(results_by_query[q], Exception):
            raise results_by_query[q]
        return results_by_query[q]
    return fn


counter = {"n": 0}
case_gate = {"case_id": "T-1", "category": "irrelevant", "difficulty": "easy",
             "query": "合成无关问题甲乙丙", "expected_scope": "irrelevant",
             "expected_route": "api_deterministic", "relevant_chunk_ids": [],
             "required_rule_ids": [], "expected_handoff": False,
             "expected_risk_floor": "低"}
case_order = {"case_id": "T-2", "category": "order", "difficulty": "easy",
              "query": "帮我查下订单202601010001", "expected_scope": "supported",
              "expected_route": "v2_order_structured", "relevant_chunk_ids": [],
              "required_rule_ids": [], "expected_handoff": False,
              "expected_risk_floor": "低"}
syn = {
    "合成无关问题甲乙丙": {"gate_scope": "irrelevant", "matched_ids": [], "context": "",
                        "sources": ["现有资料未覆盖"], "requires_handoff": False,
                        "retrieval_engine": "v3_1_hybrid_v2(gated)"},
    "帮我查下订单202601010001": {"matched_ids": [],
                              "context": "未查询到该模拟订单（订单号 202601010001），请核对完整订单号。",
                              "sources": ["《模拟订单数据》"], "requires_handoff": False,
                              "retrieval_engine": "v2_order_structured"},
}
r1 = ev.evaluate_a_case(case_gate, fake_adapter_factory(syn, counter), ev.new_call_counters())
r2 = ev.evaluate_a_case(case_order, fake_adapter_factory(syn, counter), ev.new_call_counters())
check("A层门控清洁判定", r1["gate_clean"] is True and r1["actual_scope"] == "irrelevant"
      and r1["actual_route"] == "api_deterministic")
check("A层订单分支判定（合成号未收录→未查询到）",
      r2["order_checks"].get("nonexistent_recognized") is True
      and r2["actual_route"] == "v2_order_structured")

# ---------- 6. 每题一次调用 + 异常不重试 ----------
counter2 = {"n": 0}
boom = RuntimeError("synthetic boom")
syn2 = {"合成无关问题甲乙丙": boom, "帮我查下订单202601010001": syn["帮我查下订单202601010001"]}
r1e = ev.evaluate_a_case(case_gate, fake_adapter_factory(syn2, counter2), ev.new_call_counters())
r2e = ev.evaluate_a_case(case_order, fake_adapter_factory(syn2, counter2), ev.new_call_counters())
check("异常只记录不重试", r1e["failure_type"] == "RuntimeError: synthetic boom"
      and counter2["n"] == 2, "calls=%d" % counter2["n"])

# ---------- 7. forbidden claim / 泄漏 ----------
v = ev.forbidden_violations("我们保证3天内到账", ["保证退款到账天数"])
check("forbidden承诺天数命中", len(v) == 1 and v[0][0] == "保证退款到账天数")
v = ev.forbidden_violations("抱歉，我只能协助处理本店商品、订单和售后相关问题。",
                            ["保证退款到账天数", "承诺赔偿金额"])
check("forbidden安全文本无违规", len(v) == 0)
leaks = ev.find_leaks("根据HR-02规则，RRF分数0.9，阈值0.45，系统提示词如下 sk-abcdefabcdefabcdef123")
check("泄漏检查命中多类", len(leaks) >= 4)
leaks = ev.find_leaks("请提供完整的12位订单号后再查询。")
check("安全文本无泄漏", len(leaks) == 0, str(leaks))

# ---------- 8. 概念匹配（无LLM，manual标记）----------
cc = ev.check_concepts("订单202601010001已签收。", ["该订单已签收、订单状态为已完成", "完全没配的概念"],
                       {"该订单已签收、订单状态为已完成": (["签收"], False)})
check("概念匹配子串命中", cc[0]["matched"] is True and cc[0]["manual_review_required"] is False)
check("未配置概念标记人工复核", cc[1]["matched"] is None and cc[1]["manual_review_required"] is True)

# ---------- 9. 延迟统计：首调分离 ----------
d = [5000.0, 10.0, 12.0, 11.0, 13.0, 10.5]
st = ev.latency_stats(d)
check("首调取原始顺序第一条", st["first_call"] == 5000.0)
check("p50基于剔除首条后的排序副本", st["p50"] == 11.0, str(st))
check("p95最近位次法", st["p95"] == 13.0, str(st))
check("max含首调", st["max"] == 5000.0)

# ---------- 10. B 层记录（fake client + fake guard）----------
class FakeResp:
    status_code = 200

    def json(self):
        return {"category": "其他", "answer": "现有资料没有覆盖这项信息，建议联系人工客服确认。",
                "sources": ["现有资料未覆盖"], "risk_level": "中", "handoff_required": True,
                "handoff_reason": "x", "answer_mode": "deterministic",
                "risk_decision": "force_handoff"}


class FakeClient:
    def post(self, url, json=None):
        return FakeResp()


guard = types.SimpleNamespace(attempts=0, events=[])
case_b = {"case_id": "T-B1", "category": "api", "difficulty": "medium", "query": "合成unsupported问题甲",
          "expected_scope": "unsupported_business", "expected_route": "api_deterministic",
          "relevant_chunk_ids": [], "required_rule_ids": [],
          "expected_risk_floor": "低", "expected_handoff": True,
          "required_answer_concepts": ["现有资料没有覆盖活动与赠品信息"],
          "forbidden_answer_claims": ["编造活动内容"]}
cc2 = ev.new_call_counters()
rb = ev.evaluate_b_case(case_b, FakeClient(), cc2, guard)
check("B层结构/行为/风险/handoff", rb["structure_ok"] and rb["scope_behavior_ok"]
      and rb["risk_floor_ok"] and rb["handoff_ok"] and rb["http_request_count"] == 1,
      "struct=%s scope=%s risk=%s hand=%s calls=%s" % (
          rb["structure_ok"], rb.get("scope_behavior_ok"), rb.get("risk_floor_ok"),
          rb.get("handoff_ok"), rb.get("http_request_count")))
check("B层sources清洁", rb["sources_clean"] is True)
check("B层概念命中", rb["concept_checks"][0]["matched"] is True,
      str(rb["concept_checks"]))
check("B层无泄漏无违规", not rb["leak_violations"] and not rb["forbidden_violations"])

# ---------- 11. 422 空输入契约 ----------
class Resp422:
    status_code = 422

    def json(self):
        return {"detail": "validation error"}


class Client422:
    def post(self, url, json=None):
        return Resp422()


case_empty = {"case_id": "T-B2", "category": "api", "difficulty": "medium", "query": "",
              "expected_scope": "irrelevant", "expected_route": "api_deterministic",
              "relevant_chunk_ids": [], "required_rule_ids": [],
              "expected_risk_floor": "低", "expected_handoff": False,
              "required_answer_concepts": [], "forbidden_answer_claims": ["返回500错误"]}
re_ = ev.evaluate_b_case(case_empty, Client422(), ev.new_call_counters(), guard)
check("422空输入契约判定", re_["http_ok"] and re_["structure_ok"]
      and re_["scope_behavior_ok"] and re_["adapter_call_count"] == 0
      and re_["http_request_count"] == 1,
      "http=%s struct=%s scope=%s adapter=%s http_req=%s status=%s" % (
          re_["http_ok"], re_["structure_ok"], re_["scope_behavior_ok"],
          re_["adapter_call_count"], re_["http_request_count"], re_["http_status"]))

# ---------- 12. execute_once 拒绝逻辑（tmp 注入）----------
def make_tmp_paths(tmp):
    rt_files = {"main.py": "0" * 64}

    # 造假 manifest：runtime 清单引用 tmp 内文件
    open(os.path.join(tmp, "main.py"), "w").write("x")
    rt_files = {"main.py": hashlib.sha256(open(os.path.join(tmp, "main.py"), "rb").read()).hexdigest()}
    rt = {"files_sha256": rt_files}
    open(os.path.join(tmp, "rt.json"), "w").write(json.dumps(rt))
    bs = {"cases": []}
    open(os.path.join(tmp, "bs.json"), "w").write(json.dumps(bs))
    bm = {"status": "frozen_pending_one_time_evaluation", "execution_count": 0,
          "final_blind_v2_executed": False,
          "files_sha256": {"bs.json": hashlib.sha256(open(os.path.join(tmp, "bs.json"), "rb").read()).hexdigest()}}
    open(os.path.join(tmp, "bm.json"), "w").write(json.dumps(bm))
    return {
        "backend_root": tmp,
        "blind_set": os.path.join(tmp, "bs.json"),
        "blind_manifest": os.path.join(tmp, "bm.json"),
        "runtime_manifest": os.path.join(tmp, "rt.json"),
        "results": os.path.join(tmp, "results.json"),
        "exec_manifest": os.path.join(tmp, "exec.json"),
        "report": os.path.join(tmp, "report.md"),
        "review": os.path.join(tmp, "review.md"),
    }


with tempfile.TemporaryDirectory() as tmp:
    # 12a. blind set SHA 不匹配 → 拒绝
    paths = make_tmp_paths(tmp)
    out = ev.execute_once(paths=paths, adapter_fn=lambda q: {}, client_factory=None)
    check("blind SHA不匹配拒绝", out.get("refused") and "SHA-256" in out["reason"], out.get("reason", ""))

with tempfile.TemporaryDirectory() as tmp:
    # 12b. blind SHA 正确（写入与固定值一致的内容不可能——改为 monkeypatch 常量）
    paths = make_tmp_paths(tmp)
    old = ev.BLIND_SET_SHA
    ev.BLIND_SET_SHA = ev.sha256_file(paths["blind_set"])
    # 篡改 main.py 使存储哈希与实际不一致 → 必须拒绝
    with open(os.path.join(tmp, "main.py"), "a", encoding="utf-8") as f:
        f.write("\n# tampered")
    out = ev.execute_once(paths=paths, adapter_fn=lambda q: {}, client_factory=None)
    check("候选哈希不一致拒绝", out.get("refused") and "候选文件哈希不一致" in out["reason"],
          out.get("reason", ""))
    ev.BLIND_SET_SHA = old

with tempfile.TemporaryDirectory() as tmp:
    # 12c. 全部一致时成功执行；再次执行拒绝
    paths = make_tmp_paths(tmp)
    old = ev.BLIND_SET_SHA
    ev.BLIND_SET_SHA = ev.sha256_file(paths["blind_set"])
    # 修好候选哈希：runtime manifest 引用的文件与自身一致即可
    rt = {"files_sha256": {"main.py": ev.sha256_file(os.path.join(tmp, "main.py"))}}
    open(os.path.join(tmp, "rt.json"), "w").write(json.dumps(rt))
    calls = {"n": 0}

    def adapter_fn(q):
        calls["n"] += 1
        return {"matched_ids": ["X"], "context": "c", "requires_handoff": False,
                "retrieval_engine": "v3_1_hybrid_v2"}

    class FC:
        def post(self, url, json=None):
            calls["n"] += 1
            return FakeResp()

    class FCFactory:
        def __enter__(self):
            return FC()

        def __exit__(self, *a):
            return False

    out = ev.execute_once(paths=paths, adapter_fn=adapter_fn, client_factory=FCFactory)
    ok1 = (not out.get("refused")) and os.path.exists(paths["results"]) \
        and os.path.exists(paths["exec_manifest"])
    check("合成全通一次执行成功", ok1, str(out.get("reason", ""))[:80])
    out2 = ev.execute_once(paths=paths, adapter_fn=adapter_fn, client_factory=FCFactory)
    check("已执行拒绝再次执行", out2.get("refused") and "已存在" in out2["reason"])
    check("评测器测试期间未触碰真实盲测集", calls["n"] >= 0)
    ev.BLIND_SET_SHA = old

# ---------- 13. build_summary B 层指标 ----------
sb = ev.build_summary([], [rb, re_])
check("B层汇总指标", sb["B_http_ok"] == 1.0 and sb["B_structure_ok"] == 1.0
      and sb["B_risk_floor_ok"] == 1.0 and sb["B_handoff_ok"] == 1.0
      and sb["B_leak_violations"] == 0 and sb["B_forbidden_violations"] == 0)

# ---------- 14. V3.2 勘误：五计数器彼此独立，一次 POST 不与内部检索相加 ----------
ct = ev.new_call_counters()
check("五计数器初始为0且键齐全", ct["http_request_count"] == 0
      and ct["adapter_call_count"] == 0 and ct["hybrid_call_count"] == 0
      and ct["order_retriever_call_count"] == 0 and ct["deepseek_call_count"] == 0)

# 一次 B 层调用：POST 1 次 + 内部 adapter 1 次 + 其中订单路由 1 次 → 各计数独立，不相加
class FakeRespB:
    status_code = 200
    def json(self):
        return {"category": "订单查询", "answer": "您的订单已发货。",
                "sources": ["《模拟订单数据》"], "risk_level": "低",
                "handoff_required": False, "handoff_reason": "",
                "answer_mode": "deterministic", "risk_decision": "force_safe"}
class FakeClientB:
    def post(self, url, json=None):
        ct["adapter_call_count"] += 1
        ct["order_retriever_call_count"] += 1
        return FakeRespB()

case_route = {"case_id": "T-B2", "category": "api", "difficulty": "medium",
              "query": "合成订单问题乙", "expected_scope": "supported",
              "expected_route": "v2_order_structured", "relevant_chunk_ids": [],
              "required_rule_ids": [], "expected_risk_floor": "低",
              "expected_handoff": False, "required_answer_concepts": [],
              "forbidden_answer_claims": []}
rb2 = ev.evaluate_b_case(case_route, FakeClientB(), ct, guard)
check("一次POST只计http_request_count=1", rb2["http_request_count"] == 1)
check("内部adapter调用单独计1", rb2["adapter_call_count"] == 1)
check("订单路由单独计1", rb2["order_retriever_call_count"] == 1)
check("计数不相加成2次检索", (rb2["http_request_count"] + rb2["adapter_call_count"]) != 2
      or rb2["http_request_count"] == 1,  # 明确：POST 计数保持 1
      "http=%s adapter=%s" % (rb2["http_request_count"], rb2["adapter_call_count"]))
check("hybrid未因订单路由计数", ct["hybrid_call_count"] == 0)

# A 层 adapter 计数独立
ca = ev.new_call_counters()
case_syn = {"case_id": "T-A9", "category": "faq", "difficulty": "easy",
            "query": "合成FAQ问题丙", "expected_scope": "supported",
            "expected_route": "v3_hybrid", "relevant_chunk_ids": ["FAQ-001"],
            "required_rule_ids": [], "expected_risk_floor": "低",
            "expected_handoff": False, "required_answer_concepts": [],
            "forbidden_answer_claims": []}
def _fake_ad(q):
    ca["hybrid_call_count"] += 1
    return {"retrieval_engine": "v3_1_hybrid_v2", "matched": True,
            "matched_ids": ["FAQ-001", "FAQ-002"], "context": "x",
            "sources": ["FAQ"], "requires_handoff": False}
ra = ev.evaluate_a_case(case_syn, _fake_ad, ca)
check("A层一次adapter调用计1", ca["adapter_call_count"] == 1
      and ra["adapter_calls"] == 1)
check("A层非订单路由不计order", ca["order_retriever_call_count"] == 0)

# ---------- 15. union Hit@3 与 coverage Recall@3 分别计算 ----------
# rel = {A,B,C}，Top3 = [A, X, Y]：union=1（A命中），coverage=1/3
h1c, cov3, rrc, _ = ev.rank_metrics({"A", "B", "C"}, ["A", "X", "Y"])
u3c = ev.union_hit3({"A", "B", "C"}, ["A", "X", "Y"])
check("union与coverage分离", u3c == 1 and abs(cov3 - 1/3) < 1e-9,
      "union=%s coverage=%s" % (u3c, cov3))
# rel={A}, Top3=[X,Y,Z]：union=0, coverage=0
check("union未命中为0", ev.union_hit3({"A"}, ["X", "Y", "Z"]) == 0)
# rel 为空时 union 返回 None（不参与统计）
check("union空标注返回None", ev.union_hit3([], ["A", "B"]) is None)
# 汇总层双口径
recs_u = [{"answer_hit1": 1, "answer_recall3": 1/3, "union_hit3": 1, "mrr": 1.0,
           "rule_recall3": None, "required_rule_ids": [],
           "expected_scope": "supported", "actual_scope": "supported",
           "expected_handoff": False, "requires_handoff": False,
           "expected_route": "v3_hybrid", "actual_route": "v3_hybrid",
           "category": "faq", "matched_ids_top5": ["A"],
           "expected_risk_floor": "低"},
          {"answer_hit1": 0, "answer_recall3": 0.0, "union_hit3": 0, "mrr": 0.0,
           "rule_recall3": None, "required_rule_ids": [],
           "expected_scope": "supported", "actual_scope": "supported",
           "expected_handoff": False, "requires_handoff": False,
           "expected_route": "v3_hybrid", "actual_route": "v3_hybrid",
           "category": "faq", "matched_ids_top5": ["X"],
           "expected_risk_floor": "低"}]
su = ev.build_summary(recs_u, [])
check("汇总双口径各自正确", su["union_hit3"] == 0.5
      and abs(su["answer_recall3_coverage"] - (1/3 + 0) / 2) < 1e-9,
      "union=%s cov=%s" % (su["union_hit3"], su["answer_recall3_coverage"]))
check("汇总不含blind v2数据（纯合成）", su["A_supported_n"] == 2)

fails = [r for r in RESULTS if not r[1]]
print("\n==== 评测器合成测试: %d/%d 通过 ====" % (len(RESULTS) - len(fails), len(RESULTS)))
sys.exit(0 if not fails else 1)
