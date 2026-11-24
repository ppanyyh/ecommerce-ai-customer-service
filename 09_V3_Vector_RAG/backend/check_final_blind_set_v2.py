# -*- coding: utf-8 -*-
"""V3.1 第四阶段：final blind set v2 纯数据校验（16 项）。

只读取数据文件（盲测集、黑名单、知识库、清单、评审文档），
禁止导入/调用任何检索器、适配器或 API。发现问题只允许修改盲测题或标注。
"""

import hashlib
import json
import os
import re
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  | " + detail) if detail else ""))


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）\"'“”‘’…—\-~～]")


def normalize(q):
    return PUNCT_RE.sub("", (q or "")).lower()


def bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def lcs_len(a, b):
    # 经典 DP，规模小（<100 字符）可接受
    m, n = len(a), len(b)
    prev = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def main():
    bs_path = os.path.join(DATA, "final_blind_set_v2.json")
    bl_path = os.path.join(DATA, "final_blind_v2_query_blacklist.json")
    kb_path = os.path.join(DATA, "knowledge_chunks.jsonl")
    review_path = os.path.join(DATA, "final_blind_set_v2_label_review.md")
    rt_manifest_path = os.path.join(DATA, "v3_1_runtime_freeze_manifest.json")

    bs = json.load(open(bs_path, encoding="utf-8"))
    cases = bs["cases"]
    bl = json.load(open(bl_path, encoding="utf-8"))
    kb_rows = [json.loads(l) for l in open(kb_path, encoding="utf-8")]
    kb_ids = {r["chunk_id"] for r in kb_rows}
    rule_ids = {r["chunk_id"] for r in kb_rows if r.get("doc_type") == "rule"}
    kb_texts = [re.sub(r"\s", "", (r.get("text") or "").lower()) for r in kb_rows]

    queries = [c["query"] for c in cases]
    normed = [normalize(q) for q in queries]

    # 1. case_id 唯一且连续（BV2-001..070）
    ids = [c["case_id"] for c in cases]
    expected = [f"BV2-{i:03d}" for i in range(1, len(cases) + 1)]
    check("01 case_id唯一且连续", ids == expected and len(set(ids)) == len(ids),
          f"n={len(ids)}")

    # 2. query 唯一
    check("02 query唯一(含规范化唯一)", len(set(queries)) == len(queries)
          and len(set(normed)) == len(normed), "")

    # 3. 与历史黑名单无完全重复
    bl_normed = {normalize(e["query"]): e["query"] for e in bl["entries"]}
    dup = [q for q, nq in zip(queries, normed) if nq in bl_normed]
    check("03 与历史黑名单无完全重复", not dup, "; ".join(dup[:5]))

    # 4. 与历史查询无简单改写（规范化相等已查；此处：bigram Jaccard>=0.6 或 LCS/长度>=0.75）
    near = []
    for c, nq in zip(cases, normed):
        bg = bigrams(nq)
        for bn, orig in bl_normed.items():
            if abs(len(bn) - len(nq)) > 12:
                continue
            bgb = bigrams(bn)
            inter = len(bg & bgb)
            union = len(bg | bgb)
            jac = inter / union if union else 0.0
            lcs = lcs_len(nq, bn)
            if jac >= 0.6 or (len(nq) > 8 and lcs / max(len(nq), 1) >= 0.75):
                near.append(f"{c['case_id']} ~ [{orig[:24]}] jac={jac:.2f} lcs={lcs}/{len(nq)}")
                break
    check("04 与历史查询无简单改写", not near, "; ".join(near[:6]))

    # 5. query 未复制 knowledge_chunks 完整句子（规范化后包含任一片段>=30字连续子串）
    kb_copy = []
    for c, nq in zip(cases, normed):
        for kt in kb_texts:
            if len(kt) >= 30:
                step, win = 6, 30
                for i in range(0, len(kt) - win + 1, step):
                    if kt[i:i + win] in nq:
                        kb_copy.append(c["case_id"])
                        break
                else:
                    continue
                break
    check("05 query未复制知识库完整句子", not kb_copy, "; ".join(kb_copy[:5]))

    # 6. relevant_chunk_ids 全部存在
    bad_ref = []
    for c in cases:
        for rid in c["relevant_chunk_ids"]:
            if rid not in kb_ids:
                bad_ref.append(f"{c['case_id']}:{rid}")
    check("06 relevant_chunk_ids全部存在", not bad_ref, "; ".join(bad_ref[:6]))

    # 7. required_rule_ids 全部存在且 doc_type=rule
    bad_rule = []
    for c in cases:
        for rid in c["required_rule_ids"]:
            if rid not in rule_ids:
                bad_rule.append(f"{c['case_id']}:{rid}")
    check("07 required_rule_ids全部存在且为规则", not bad_rule, "; ".join(bad_rule[:6]))

    # 8. supported 用例标注结构完整
    supp_bad = []
    for c in cases:
        if c["expected_scope"] == "supported":
            ok = bool(c["relevant_chunk_ids"]) or c["expected_route"] == "v2_order_structured"
            ok = ok and "required_answer_concepts" in c and "forbidden_answer_claims" in c
            if not ok:
                supp_bad.append(c["case_id"])
    check("08 supported标注结构完整", not supp_bad, "; ".join(supp_bad[:6]))

    # 9. unsupported/irrelevant 的 relevant_chunk_ids 为空
    gate_bad = []
    for c in cases:
        if c["expected_scope"] in ("unsupported_business", "irrelevant"):
            if c["relevant_chunk_ids"] or c.get("is_answerable", True):
                gate_bad.append(c["case_id"])
    check("09 不可回答用例relevant为空且is_answerable=false", not gate_bad,
          "; ".join(gate_bad[:6]))

    # 10. scope/route/category 组合合法
    valid_scope = {"supported", "unsupported_business", "irrelevant"}
    valid_route = {"v3_hybrid", "v2_order_structured", "api_deterministic"}
    valid_cat_a = {"product", "faq", "rule", "multi", "order",
                   "unsupported_business", "irrelevant"}
    combo_bad = []
    for c in cases:
        if c["expected_scope"] not in valid_scope or c["expected_route"] not in valid_route:
            combo_bad.append(c["case_id"] + ":scope/route")
            continue
        if c["evaluation_layer"] == "retrieval_scope_order" and c["category"] not in valid_cat_a:
            combo_bad.append(c["case_id"] + ":category")
            continue
        if c["expected_scope"] == "supported" and c["expected_route"] == "api_deterministic":
            combo_bad.append(c["case_id"] + ":supported不可走api_deterministic")
        if c["expected_scope"] == "unsupported_business" and c["expected_route"] != "api_deterministic":
            combo_bad.append(c["case_id"] + ":unsupported必须确定性")
        if c["category"] == "unsupported_business" and c["expected_scope"] != "unsupported_business":
            combo_bad.append(c["case_id"] + ":category/scope不一致")
        if c["category"] == "irrelevant" and c["expected_scope"] != "irrelevant":
            combo_bad.append(c["case_id"] + ":category/scope不一致")
    check("10 scope/route/category组合合法", not combo_bad, "; ".join(combo_bad[:6]))

    # 11. 数量与难度分布
    from collections import Counter
    cat = Counter(c["category"] for c in cases
                  if c["evaluation_layer"] == "retrieval_scope_order")
    diff = Counter(c["difficulty"] for c in cases)
    target_cat = {"product": 8, "faq": 10, "rule": 10, "multi": 8, "order": 6,
                  "unsupported_business": 10, "irrelevant": 8}
    cat_ok = dict(cat) == target_cat and len(cases) == 70
    diff_ok = dict(diff) == {"easy": 14, "medium": 32, "hard": 24}
    b_cnt = sum(1 for c in cases if c["evaluation_layer"] == "api_contract")
    check("11 数量与难度分布符合要求", cat_ok and diff_ok and b_cnt == 10,
          f"cats={dict(cat)} diffs={dict(diff)} B层={b_cnt}")

    # 12. 多答案/风险/缺陷/订单用例数达标
    multi_ans = [c for c in cases if len(c["relevant_chunk_ids"]) >= 2]
    risk = [c for c in cases if c["required_rule_ids"]]
    defect = [c for c in cases if "RULE-HR-08" in c["required_rule_ids"]]
    order = [c for c in cases if c["category"] == "order"]
    ok12 = (len(multi_ans) >= 12 and len(risk) >= 16 and len(defect) >= 6
            and len(order) == 6)
    check("12 多答案≥12/风险≥16/缺陷≥6/订单=6", ok12,
          f"多答案={len(multi_ans)} 风险={len(risk)} 缺陷={len(defect)} 订单={len(order)}")

    # 13. 不含 API Key、真实手机号、真实个人数据
    key_re = re.compile(r"sk-[A-Za-z0-9]{16,}")
    phone_re = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    id_re = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
    pii = []
    for c in cases:
        blob = c["query"] + json.dumps(
            {k: v for k, v in c.items() if k != "query"}, ensure_ascii=False)
        if key_re.search(blob):
            pii.append(c["case_id"] + ":key")
        for m in phone_re.finditer(blob):
            pii.append(f"{c['case_id']}:phone[{m.group()}]")
        if id_re.search(blob):
            pii.append(c["case_id"] + ":idcard")
    check("13 无APIKey/真实手机号/身份证", not pii, "; ".join(pii[:6]))

    # 14. 无检索结果/相似度/排名等运行后字段
    forbidden_keys = {"similarity", "score", "rank", "hit", "rrf", "retrieved",
                      "keyword_score", "vector_similarity", "rrf_score", "final_rank"}
    run_bad = []
    for c in cases:
        hit = forbidden_keys & set(c.keys())
        if hit:
            run_bad.append(c["case_id"] + ":" + ",".join(hit))
        if re.search(r"相似度|检索命中|rrf\s*[:==]", c["annotation_reason"]):
            run_bad.append(c["case_id"] + ":reason含运行后信息")
    check("14 无运行后字段", not run_bad, "; ".join(run_bad[:6]))

    # 15. label review 覆盖全部 70 条
    review = open(review_path, encoding="utf-8").read()
    missing = [c["case_id"] for c in cases if c["case_id"] not in review]
    check("15 label review覆盖全部用例", not missing,
          f"缺失{len(missing)}条: {missing[:6]}")

    # 16. runtime freeze manifest 哈希仍一致
    rt = json.load(open(rt_manifest_path, encoding="utf-8"))
    diff_files = [f for f, h in rt["files_sha256"].items() if sha256_file(os.path.join(BACKEND, f)) != h]
    check("16 runtime冻结13文件哈希一致", not diff_files, "; ".join(diff_files[:6]))

    fails = [r for r in results if not r[1]]
    print(f"\n==== 校验汇总: {len(results) - len(fails)}/{len(results)} 通过 ====")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
