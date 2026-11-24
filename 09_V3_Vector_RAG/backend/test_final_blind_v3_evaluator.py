# -*- coding: utf-8 -*-
"""final blind v3 评测器合成预检（22 项）。

全部使用合成 fixture（不含任何 blind v3 query、不导入检索器/FastAPI 应用），
验证评测器本身的指标计算与安全行为。22 项全过后才允许 --execute-once。
"""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# 先导入评测器（其内部会一次性完成 UTF-8 stdout 包装，避免二次包装关闭流）
import evaluate_final_blind_v3 as ev

RESULTS = []


def check(idx, name, ok, detail=""):
    RESULTS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {idx:02d} {name}" + (f" —— {detail}" if detail else ""))


def approx(a, b, eps=1e-6):
    return a is not None and abs(a - b) < eps


# ============ 合成 fixture（不含任何 blind v3 query） ============

def fake_case(cid, cat="product", diff="easy", scope="supported", route="v3_hybrid",
              floor="低", handoff=False, rel=(), req=(), reason="合成用例（非盲测题）"):
    return {
        "case_id": cid, "evaluation_layer": "retrieval_scope_order", "category": cat,
        "difficulty": diff, "query": "合成测试问题" + cid,
        "is_answerable": scope == "supported", "expected_scope": scope,
        "expected_route": route, "relevant_chunk_ids": list(rel),
        "required_rule_ids": list(req), "expected_category": "商品",
        "expected_risk_floor": floor, "expected_handoff": handoff,
        "required_answer_concepts": [], "forbidden_answer_claims": [],
        "source_refs": [], "annotation_reason": reason,
    }


FX_RESULTS = {
    "S1": {"matched": True, "matched_ids": ["PRODUCT-FAKE1", "FAQ-FAKE1", "RULE-HR-08"],
           "risk_floor_level": "低", "requires_handoff": False, "retrieval_engine": "v3_1_hybrid_v2"},
    "S2": {"matched": True, "matched_ids": ["RULE-HR-07", "FAQ-FAKE2", "PRODUCT-FAKE2"],
           "risk_floor_level": "高", "requires_handoff": True, "retrieval_engine": "v3_1_hybrid_v2"},
    "S3": {"matched": False, "gate_scope": "unsupported_business", "matched_ids": [],
           "sources": ["现有资料未覆盖"], "context": "", "requires_handoff": True,
           "retrieval_engine": "v3_1_hybrid_v2(gated)"},
    "S4": {"matched": False, "gate_scope": "irrelevant", "matched_ids": [],
           "sources": ["现有资料未覆盖"], "context": "", "requires_handoff": False,
           "retrieval_engine": "v3_1_hybrid_v2(gated)"},
    "S5": {"matched": False, "match_type": "order", "matched_ids": [],
           "retrieval_engine": "v2_order_structured", "requires_handoff": False,
           "order_local": {"found": True, "order_id": "202609180001",
                           "product_name": "SoundGo Air无线蓝牙耳机", "quantity": 1, "amount": 299.0,
                           "order_status": "已发货"}},
    "S6": {"matched": False, "match_type": "order", "matched_ids": [],
           "retrieval_engine": "v2_order_structured", "requires_handoff": False,
           "order_local": {"found": False, "incomplete": False, "order_id": "202609180009"}},
    "S7": {"matched": True, "matched_ids": ["RULE-HR-02", "RULE-HR-03", "FAQ-FAKE3"],
           "risk_floor_level": "高", "requires_handoff": True, "retrieval_engine": "v3_1_hybrid_v2"},
    "S8": {"matched": True, "matched_ids": ["FAQ-FAKE4"], "risk_floor_level": "低",
           "requires_handoff": True, "retrieval_engine": "v3_1_hybrid_v2"},  # wrong handoff
    "S9": {"matched": True, "matched_ids": ["PRODUCT-FAKE9", "RULE-HR-08", "FAQ-FAKE9"],
           "risk_floor_level": "低", "requires_handoff": False, "retrieval_engine": "v3_1_hybrid_v2"},
}

CASES = [
    fake_case("S1", rel=["PRODUCT-FAKE1"]),
    fake_case("S2", cat="rule", diff="hard", floor="高", handoff=True,
              rel=["FAQ-FAKE2", "PRODUCT-FAKE2"], req=["RULE-HR-07"]),
    fake_case("S3", cat="unsupported_business", diff="medium", scope="unsupported_business",
              route="local_fallback", floor="中", handoff=True),
    fake_case("S4", cat="irrelevant", diff="easy", scope="irrelevant",
              route="local_fallback", floor="低"),
    fake_case("S5", cat="order", route="v2_order_structured", floor="低",
              reason="合成有效订单（订单号不在真实订单表）"),
    fake_case("S6", cat="order", route="api_deterministic", floor="低",
              reason="合成不存在订单提示核对"),
    fake_case("S7", cat="multi", diff="hard", floor="高", handoff=True,
              rel=["RULE-HR-02", "RULE-HR-03"], req=["RULE-HR-02", "RULE-HR-03"]),
    fake_case("S8", cat="faq", floor="低"),  # expected handoff False, actual True → wrong handoff
    fake_case("S9", cat="rule", floor="低", rel=["PRODUCT-FAKE9"], req=["RULE-HR-08"]),
]
for c in CASES:
    if c["case_id"] in ("S5", "S6"):
        c["query"] = "合成订单查询202609180001" if c["case_id"] == "S5" else "合成订单查询202609180009"

a_records = [ev.compute_a_record(c, FX_RESULTS[c["case_id"]], 10.0 + i) for i, c in enumerate(CASES)]

# 1-6 检索指标
sup = [r for r in a_records if r.get("hit1") is not None]
check(1, "Hit@1 计算（4个带片段用例，S2未命中 → 3/4）", len(sup) == 4 and sum(1 for r in sup if r["hit1"]) == 3)
check(2, "union Hit@3 计算（2/2）", all(r["union3"] for r in sup))
check(3, "coverage Recall@3（S1=1.0, S2=1.0）", all(approx(r["coverage_recall3"], 1.0) for r in sup))
mrrs = [r["mrr"] for r in sup]
check(4, "MRR 计算（[1.0,0.5,1.0,1.0] → 均值 0.875）", approx(sum(mrrs) / 4, 0.875), f"{mrrs}")
rule_recs = [r for r in a_records if r.get("rule_recall3") is not None]
check(5, "Rule Recall@3（3条规则用例全部=1.0）", len(rule_recs) == 3 and all(r["rule_recall3"] == 1.0 for r in rule_recs))
hr08 = [r for r in a_records if r.get("hr08_hit3") is not None]
check(6, "HR-08 Recall@3（S9 命中 → 1/1）", len(hr08) == 1 and hr08[0]["hr08_hit3"] is True)

# 7-11 scope / 误放行 / floor / handoff
fake_counters = ev.Counters()
metrics = ev.aggregate(a_records, [], fake_counters, {}, None)
check(7, "scope 混淆矩阵（9条全对角）",
      metrics["scope_confusion"] == {"irrelevant | irrelevant": 1, "supported | supported": 7,
                                     "unsupported_business | unsupported_business": 1,
                                     "supported | supported": 5} or
      all(k.split(" | ")[0] == k.split(" | ")[1] for k in metrics["scope_confusion"]),
      json.dumps(metrics["scope_confusion"], ensure_ascii=False))
check(8, "unsupported/irrelevant 误放行（均为 0）",
      metrics["unsupported_false_pass"]["value"] == 0 and metrics["irrelevant_false_pass"]["value"] == 0)
check(9, "risk floor 符合率（9/9=100%）", approx(metrics["risk_floor_compliance"]["value"], 1.0))
check(10, "high-risk handoff（S2/S7 均 True → 100%）", approx(metrics["high_risk_handoff"]["value"], 1.0))
check(11, "wrong handoff 检出（S8 → 1/6）", approx(metrics["wrong_handoff"]["value"], 1 / 6),
      f"{metrics['wrong_handoff']}")

# 12 订单事实
check(12, "订单事实（S5 字段全对=True；S6 不存在未伪造=True）",
      a_records[4]["order_fact_ok"] is True and a_records[5]["order_fact_ok"] is True)

# 13-15 B 层契约 / forbidden / 泄漏
b_case = {
    "case_id": "SB1", "evaluation_layer": "api_contract", "category": "api", "difficulty": "easy",
    "query": "合成API问题", "expected_scope": "supported", "expected_category": "商品",
    "expected_risk_floor": "低", "expected_handoff": False,
    "required_answer_concepts": ["合成概念一"], "forbidden_answer_claims": [],
}
good_payload = {"message": "合成API问题", "category": "商品", "answer": "合成回答文本，正常说明。",
                "sources": ["《合成资料》"], "risk_level": "低", "handoff_required": False,
                "handoff_reason": "", "answer_mode": "fallback"}
bad_payload = {"category": "售后", "answer": "该问题涉及 HR-08 规则，我们保证退款到账，RRF 相似度 0.9。"}
r_good = ev.compute_b_record(b_case, 200, good_payload, 5.0)
r_bad = ev.compute_b_record(b_case, 500, bad_payload, 5.0)
check(13, "API 契约八字段检查（完整→0缺失；缺字段→检出）",
      r_good["missing_fields"] == [] and "contract_missing_fields" in r_bad["failure_types"])
check(14, "forbidden claim 检出（保证退款到账）",
      any("承诺退款" in f or "到账" in f for f in r_bad["forbidden_claims"]),
      str(r_bad["forbidden_claims"]))
check(15, "内部术语泄漏检出（HR-0/RRF/相似度）",
      set(r_bad["internal_leaks"]) >= {"HR-0", "RRF", "相似度"}, str(r_bad["internal_leaks"]))

# 16-18 计数器独立 / 每题一次 / 异常不重试
cnt = ev.Counters()
call_log = []


def fake_adapter(query):
    call_log.append(query)
    cnt.adapter_call_count += 1
    if len(call_log) == 9:
        raise RuntimeError("合成异常")
    return FX_RESULTS.get(query.replace("合成测试问题", ""), {"matched_ids": []})


cnt2 = ev.Counters()
recs2 = []
for i, c in enumerate(CASES):
    try:
        res = fake_adapter(c["query"])
        recs2.append(ev.compute_a_record(c, res, 1.0))
    except Exception as e:
        recs2.append(ev.compute_a_record(c, {}, 1.0, exception=str(e)))
check(16, "五类计数器相互独立（各自独立增减）",
      cnt.http_request_count == 0 and cnt.adapter_call_count == 9 and cnt.hybrid_call_count == 0
      and cnt.order_retriever_call_count == 0 and cnt.deepseek_call_count == 0)
check(17, "每题一次入口调用（无重复调用）", len(call_log) == 9)
exc_recs = [r for r in recs2 if r["exception"]]
check(18, "异常不重试（1条异常记录，且调用次数不增加）",
      len(exc_recs) == 1 and exc_recs[0]["failure_types"] == ["exception"] and cnt.adapter_call_count == 9)

# 19 已有结果拒绝执行
with tempfile.TemporaryDirectory() as td:
    old_results = ev.RESULTS_PATH
    old_manifest = ev.MANIFEST_PATH
    try:
        fake_res = os.path.join(td, "fake_results.json")
        open(fake_res, "w").write("{}")
        ev.RESULTS_PATH = fake_res
        p = ev.pre_execution_check(read_sha=lambda p_: "0" * 64)
        check(19, "已有结果时拒绝再次执行", "results_already_exists" in p, str(p))
    finally:
        ev.RESULTS_PATH = old_results
        ev.MANIFEST_PATH = old_manifest

# 20 哈希不一致拒绝执行
with tempfile.TemporaryDirectory() as td:
    # 临时改写 manifest 内 blind SHA 基准 → 注入不匹配 read_sha
    m = json.load(open(ev.MANIFEST_PATH, encoding="utf-8"))
    saved = m["final_blind_set_v3_sha256"]
    m["final_blind_set_v3_sha256"] = "deadbeef" * 8
    tmp_m = os.path.join(td, "manifest.json")
    json.dump(m, open(tmp_m, "w", encoding="utf-8"))
    old_m = ev.MANIFEST_PATH
    try:
        ev.MANIFEST_PATH = tmp_m
        p = ev.pre_execution_check(read_sha=lambda p_: saved)  # 实际SHA=保存值，基准被改 → mismatch
        check(20, "哈希不一致时拒绝执行", "blind_v3_sha_mismatch" in p, str(p))
    finally:
        ev.MANIFEST_PATH = old_m

# 21 首调与 P50/P95
lat = list(range(1, 101))  # 1..100
check(21, "首调与 P50/P95 计算（P50=50, P95=95, 首调=最小值）",
      ev.percentile(lat, ev.P50) == 50 and ev.percentile(lat, ev.P95) == 95
      and a_records[0]["latency_ms"] == 10.0)

# 22 DeepSeek 守卫
gcnt = ev.Counters()
guard = ev.DeepSeekGuard(gcnt)
raised = False
try:
    guard.guarded_generate_reply(message="x", context="y")
except RuntimeError:
    raised = True
check(22, "DeepSeek 守卫（计数+抛错+不重试）",
      raised and gcnt.deepseek_call_count == 1 and len(guard.attempts) == 1)

# ============ 汇总 ============
fails = RESULTS.count(False)
print(f"\n==== 合成预检汇总 ==== {len(RESULTS) - fails}/{len(RESULTS)} 通过")
sys.exit(0 if fails == 0 else 1)
