# -*- coding: utf-8 -*-
"""V3.2 开发集独立性与泄漏检查（纯数据校验，禁止导入任何检索器）。

检查 v3_2_dev_cases.json 与全部历史查询（blind v1/v2、V3.1 开发集、
validation v1.1/v1.2、旧测试与调试脚本、API 集成测试——来自
final_blind_v2_query_blacklist.json）之间：
1) 完全重复；2) 规范化重复；3) bigram Jaccard 高重合；4) 过长公共子串；
5) 简单商品/数字替换近似；6) 与知识库整句复制；
另校验：case_id 唯一连续、字段齐全、scope/route/category 合法、
数量分布符合需求（>=100 条，40/30/20/10）。
"""
import json
import os
import re
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  | " + detail) if detail else ""))


def norm(q):
    return re.sub(r"[\s，。；；,\.?!？！?：:、'\"“”‘’（）()【】\[\]\-_/\\~～·…]", "", (q or "").lower())


def bigrams(s):
    s = norm(s)
    return set(s[i:i + 2] for i in range(len(s) - 1)) if len(s) > 1 else {s}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def lcs_len(a, b):
    """最长公共子串（滑动窗口实现，避免 O(n^2) DP 过大）。"""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0
    best, short, long_ = 0, (a if len(a) <= len(b) else b), (b if len(a) <= len(b) else a)
    win = len(short)
    while win >= 8:  # 只关心 >=8 的长公共子串
        for i in range(0, len(short) - win + 1):
            if short[i:i + win] in long_:
                return win
        win -= 1
    return best


def digit_mask(s):
    return re.sub(r"\d+", "#", norm(s))


def product_mask(s):
    return re.sub(r"p0?0?[1-5]|耳机|键盘|保温杯|双肩包|背包|台灯|水杯|书包|杯子|音箱|鼠标", "＠", s)


def main():
    dev = json.load(open(os.path.join(DATA, "v3_2_dev_cases.json"), encoding="utf-8"))
    cases = dev["cases"]
    bl = json.load(open(os.path.join(DATA, "final_blind_v2_query_blacklist.json"), encoding="utf-8"))
    hist = []
    for e in bl.get("entries", []):
        hist.append((e.get("source_file", ""), e.get("normalized_query") or norm(e.get("query", ""))))
    hist_norms = set(n for _, n in hist)

    # 1. case_id 唯一且连续
    ids = [c["case_id"] for c in cases]
    check("case_id唯一且连续(DV3-001..100)",
          len(set(ids)) == len(ids) == 100
          and ids == ["DV3-%03d" % i for i in range(1, 101)])

    # 2. 字段齐全
    need = ["case_id", "query", "expected_scope", "expected_route", "relevant_chunk_ids",
            "required_rule_ids", "expected_risk_floor", "expected_handoff",
            "expected_false_positive_intents", "required_answer_concepts",
            "forbidden_answer_claims", "annotation_reason", "source_refs"]
    missing = [c["case_id"] for c in cases for k in need if k not in c]
    check("必填字段齐全", not missing, str(missing[:5]))

    # 3. query 唯一
    qs = [c["query"] for c in cases]
    check("query唯一", len(set(qs)) == len(qs))

    # 4. 与历史查询无完全/规范化重复
    exact = [c["case_id"] for c in cases if norm(c["query"]) in hist_norms]
    check("与历史查询无完全重复", not exact, str(exact[:5]))

    # 5. 近重复（bigram>=0.6 或 LCS>=75% 或 掩码规范化相同）
    near = []
    for c in cases:
        nq, bg = norm(c["query"]), bigrams(c["query"])
        for src, hn in hist:
            if not hn:
                continue
            if jaccard(bg, bigrams(hn)) >= 0.6:
                near.append((c["case_id"], "bigram", src))
                break
            la, lb = len(digit_mask(c["query"])), len(digit_mask(hn))
            if min(la, lb) >= 10 and lcs_len(digit_mask(c["query"]), digit_mask(hn)) >= 0.75 * min(la, lb):
                near.append((c["case_id"], "lcs", src))
                break
            if digit_mask(c["query"]) == digit_mask(hn) or product_mask(c["query"]) == product_mask(hn):
                if abs(la - lb) <= 8:
                    near.append((c["case_id"], "mask", src))
                    break
    check("与历史查询无近重复(bigram/LCS/掩码)", not near, str(near[:6]))

    # 6. 不复制知识库整句（30字滑窗）
    kb_lines = []
    with open(os.path.join(BACKEND, "data", "knowledge_chunks.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            kb_lines.append(r.get("text", ""))
            if r.get("retrieval_text"):
                kb_lines.append(r["retrieval_text"])
    kb_norm = norm(" ".join(kb_lines))
    copied = []
    for c in cases:
        nq = norm(c["query"])
        if len(nq) < 30:
            continue
        for i in range(0, len(nq) - 29, 10):
            if nq[i:i + 30] in kb_norm:
                copied.append(c["case_id"])
                break
    check("未复制知识库句子(30字滑窗)", not copied, str(copied[:5]))

    # 7. scope/route/category 合法
    scopes = {"supported", "unsupported_business", "irrelevant"}
    routes = {"v3_hybrid", "v2_order_structured", "api_deterministic", "local_fallback"}
    bad = [c["case_id"] for c in cases
           if c["expected_scope"] not in scopes or c["expected_route"] not in routes]
    check("scope/route取值合法", not bad, str(bad[:5]))

    # 8. 组合合法性：unanswered 的 relevant 为空；supported 有依据
    bad2 = []
    for c in cases:
        if c["expected_scope"] in ("unsupported_business", "irrelevant") and c["relevant_chunk_ids"]:
            bad2.append(c["case_id"])
        if (c["expected_scope"] == "supported" and c["expected_route"] == "v3_hybrid"
                and not c["relevant_chunk_ids"] and c["category"] not in ("order",)):
            bad2.append(c["case_id"])
    check("scope与relevant组合合法", not bad2, str(bad2[:5]))

    # 9. 数量与分布
    n_a = sum(1 for c in cases if c["case_id"] <= "DV3-040")
    n_b = sum(1 for c in cases if "DV3-041" <= c["case_id"] <= "DV3-070")
    n_c = sum(1 for c in cases if "DV3-071" <= c["case_id"] <= "DV3-090")
    n_d = sum(1 for c in cases if c["case_id"] >= "DV3-091")
    check("分布 A=40 B=30 C=20 D=10 (共>=100)",
          (n_a, n_b, n_c, n_d) == (40, 30, 20, 10) and len(cases) >= 100,
          "A=%d B=%d C=%d D=%d" % (n_a, n_b, n_c, n_d))

    # 10. 风险正例数与规则覆盖
    risk_pos = [c for c in cases if c["required_rule_ids"]
                and c["expected_handoff"] and c["expected_scope"] == "supported"]
    rules_covered = {r for c in risk_pos for r in c["required_rule_ids"]}
    check("风险正例>=15且HR-01~08全覆盖", len(risk_pos) >= 15 and len(rules_covered) == 8,
          "n=%d rules=%s" % (len(risk_pos), sorted(rules_covered)))
    # 近似反例数
    neg = [c for c in cases if c["expected_false_positive_intents"]]
    check("风险近似反例>=15", len(neg) >= 15, "n=%d" % len(neg))
    # 缺陷正例
    hr08 = [c for c in risk_pos if "RULE-HR-08" in c["required_rule_ids"]]
    check("质量缺陷正例>=5", len(hr08) >= 5, "n=%d" % len(hr08))
    # 订单用例
    od = [c for c in cases if c["expected_route"] == "v2_order_structured"]
    check("订单用例=5(有效/不存在/不完整/状态金额/高风险)", len(od) == 5, "n=%d" % len(od))
    # 诱导/降级
    lf = [c for c in cases if c["expected_route"] == "local_fallback"]
    inj = [c for c in cases if c["category"] == "api"]
    check("本地降级>=3且诱导>=2", len(lf) >= 3 and len(inj) >= 2,
          "lf=%d inj=%d" % (len(lf), len(inj)))

    # 11. meta 声明
    m = dev.get("meta", {})
    check("meta声明开发集性质", m.get("set_nature") == "development"
          and m.get("may_be_used_for_tuning") is True
          and m.get("not_a_blind_set") is True
          and m.get("old_blind_queries_copied") is False)

    # 12. 不含 PII / 密钥
    pii = [c["case_id"] for c in cases
           if re.search(r"1[3-9]\d{9}", c["query"]) or "sk-" in c["query"]]
    check("不含手机号样PII与密钥样字串", not pii, str(pii[:5]))

    fails = [r for r in RESULTS if not r[1]]
    print("\n==== 开发集独立性与泄漏检查: %d/%d 通过 ====" % (len(RESULTS) - len(fails), len(RESULTS)))
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
