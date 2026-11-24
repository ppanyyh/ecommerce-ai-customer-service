# -*- coding: utf-8 -*-
"""final_blind_set_v1.json 防泄漏与完整性检查（只检查数据，不运行任何检索）。

检查项：
 1. 40个case_id唯一；
 2. query唯一；
 3. 与历史黑名单（eval_query_blacklist.json）无完全重复（规范化后）；
 4. 与历史问题无高比例字符复制（最长公共子串<6 且 字符bigram重合率<=0.6）；
 5. query未出现在knowledge_chunks的text/retrieval_text中（全句包含与>=10字公共片段）；
 6. relevant_chunk_ids全部存在于knowledge_chunks；
 7. required_rule_ids全部存在且doc_type=rule；
 8. 分类数量（product8/faq8/rule8/multi6/no_policy5/irrelevant5）与难度分布（easy10/medium18/hard12）正确；
 9. 可回答30/不可回答10；不可回答relevant为空且expected_supported=false；可回答relevant>=1且expected_supported=true；
10. 无空reason或source_refs；
11. 不含API Key（sk-）或手机号模式；
12. 不含任何订单号（12位以上数字；订单由结构化查询处理，盲测集不得包含）。

退出码：0=全部通过，1=存在失败项。
"""

import json
import os
import re
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）\"'“”‘’…—\-~～？?！]")

EXPECTED_CATEGORY = {"product": 8, "faq": 8, "rule": 8, "multi": 6,
                     "no_policy": 5, "irrelevant": 5}
EXPECTED_DIFFICULTY = {"easy": 10, "medium": 18, "hard": 12}


def normalize(q):
    return PUNCT_RE.sub("", (q or "")).lower()


def longest_common_substring(a, b):
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s} if s else set()


def main():
    blind = json.load(open(os.path.join(DATA, "final_blind_set_v1.json"), encoding="utf-8"))
    cases = blind["cases"]
    blacklist = json.load(open(os.path.join(DATA, "eval_query_blacklist.json"), encoding="utf-8"))
    bl_norms = [e["normalized"] for e in blacklist["queries"]]

    chunks = {}
    _chunks_raw = {}
    with open(os.path.join(BACKEND, "data", "knowledge_chunks.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                texts = [c.get("text", "")]
                if c.get("retrieval_text"):
                    texts.append(c["retrieval_text"])
                chunks[c["chunk_id"]] = {"doc_type": c.get("doc_type"), "texts": texts}
                _chunks_raw[c["chunk_id"]] = c

    results = []

    def check(no, name, ok, detail=""):
        results.append((no, name, bool(ok), detail))

    # 1. case_id 唯一
    ids = [c["case_id"] for c in cases]
    check(1, "case_id唯一且共40条", len(ids) == 40 and len(set(ids)) == 40,
          f"n={len(ids)} unique={len(set(ids))}")

    # 2. query 唯一
    qs = [c["query"] for c in cases]
    check(2, "query唯一", len(set(qs)) == len(qs), f"unique={len(set(qs))}/{len(qs)}")

    # 3/4. 与黑名单查重
    exact_dup, high_copy = [], []
    for c in cases:
        nq = normalize(c["query"])
        if nq in bl_norms:
            exact_dup.append(c["case_id"])
            continue
        for bn in bl_norms:
            lcs = longest_common_substring(nq, bn)
            if lcs >= 6:
                high_copy.append((c["case_id"], lcs))
                break
            qb, bb = bigrams(nq), bigrams(bn)
            if qb and bb and len(qb & bb) / max(len(qb), 1) > 0.6:
                high_copy.append((c["case_id"], f"bigram={len(qb & bb) / len(qb):.2f}"))
                break
    check(3, "与历史黑名单无完全重复", not exact_dup, str(exact_dup))
    check(4, "无高比例字符复制(LCS<6且bigram<=0.6)", not high_copy, str(high_copy[:5]))

    # 5. query 不出现在知识片段中
    #    实体词豁免：商品标题/别名/型号必然同时出现在query与商品片段中（回答所必需），
    #    属合法引用而非复制；比对前先从query中剥离这些实体词。
    entity_tokens = set()
    for c_id, c_info in _chunks_raw.items():
        if c_info.get("doc_type") == "product":
            _raw_text = c_info.get("text", "")
            for tok in re.findall(r"别名：([^）]*)", _raw_text):
                for t in tok.split("、"):
                    nt = normalize(t)
                    if len(nt) >= 2:
                        entity_tokens.add(nt)
            nt = normalize(c_info.get("title", ""))
            if len(nt) >= 2:
                entity_tokens.add(nt)
            # 型号形如 SGA-01 / KP-87 / WD-500 / CP-20 / LM-01
            for m in re.finditer(r"(?<![A-Za-z0-9])[A-Z]{1,4}-?\d{2}[A-Za-z]?(?![0-9A-Za-z])",
                                 _raw_text):
                nt = normalize(m.group(0))
                if len(nt) >= 3:
                    entity_tokens.add(nt)

    def strip_entities(nq):
        for tok in sorted(entity_tokens, key=len, reverse=True):
            nq = nq.replace(tok, " ")
        return nq

    chunk_hits = []
    for c in cases:
        nq = strip_entities(normalize(c["query"]))
        for cid, info in chunks.items():
            for t in info["texts"]:
                nt = normalize(t)
                if nq.strip() and nq in nt:
                    chunk_hits.append((c["case_id"], cid, "full"))
                    break
                if longest_common_substring(nq, nt) >= 10:
                    chunk_hits.append((c["case_id"], cid, "lcs>=10"))
                    break
    check(5, "query未出现在knowledge_chunks(text/retrieval_text)", not chunk_hits,
          str(chunk_hits[:5]))

    # 6/7. ID 合法性
    bad_ids, bad_rules = [], []
    for c in cases:
        for rid in c["relevant_chunk_ids"]:
            if rid not in chunks:
                bad_ids.append((c["case_id"], rid))
        for rrule in c["required_rule_ids"]:
            if rrule not in chunks or chunks[rrule]["doc_type"] != "rule":
                bad_rules.append((c["case_id"], rrule))
    check(6, "relevant_chunk_ids全部存在", not bad_ids, str(bad_ids))
    check(7, "required_rule_ids全部存在且doc_type=rule", not bad_rules, str(bad_rules))

    # 8/9. 数量与结构
    cat_cnt, diff_cnt = {}, {}
    ans = sum(1 for c in cases if c["is_answerable"])
    unans = len(cases) - ans
    for c in cases:
        cat_cnt[c["category"]] = cat_cnt.get(c["category"], 0) + 1
        diff_cnt[c["difficulty"]] = diff_cnt.get(c["difficulty"], 0) + 1
    check(8, "分类与难度分布正确",
          cat_cnt == EXPECTED_CATEGORY and diff_cnt == EXPECTED_DIFFICULTY,
          f"cat={cat_cnt} diff={diff_cnt}")
    struct_bad = []
    for c in cases:
        if c["is_answerable"]:
            if not c["relevant_chunk_ids"] or c["expected_supported"] is not True:
                struct_bad.append(c["case_id"])
        else:
            if c["relevant_chunk_ids"] or c["required_rule_ids"] \
                    or c["expected_supported"] is not False:
                struct_bad.append(c["case_id"])
        # expected_doc_types 与 relevant 一致性
        dt = {chunks[r]["doc_type"] for r in c["relevant_chunk_ids"] if r in chunks}
        if set(c["expected_doc_types"]) != dt:
            struct_bad.append(c["case_id"] + ":doc_types")
    check(9, "可回答30/不可回答10且结构正确",
          ans == 30 and unans == 10 and not struct_bad,
          f"ans={ans} unans={unans} bad={struct_bad[:5]}")

    # 10. reason / source_refs 非空
    empty_meta = [c["case_id"] for c in cases
                  if not (c.get("reason") or "").strip() or not c.get("source_refs")]
    check(10, "无空reason或source_refs", not empty_meta, str(empty_meta))

    # 11. 无 API Key / 手机号
    leak_pat = []
    for c in cases:
        if re.search(r"sk-[A-Za-z0-9]{16,}", c["query"]):
            leak_pat.append((c["case_id"], "apikey"))
        if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", c["query"]):
            leak_pat.append((c["case_id"], "phone"))
    check(11, "不含API Key或手机号", not leak_pat, str(leak_pat))

    # 12. 不含订单号（12位以上数字序列）
    order_hits = [(c["case_id"], m.group(0))
                  for c in cases for m in [re.search(r"\d{12,}", c["query"])] if m]
    check(12, "不含订单号(12位以上数字)", not order_hits, str(order_hits))

    n_pass = sum(1 for _, _, ok, _ in results if ok)
    for no, name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {no:>2}. {name}" + (f" | {detail}" if detail and not ok else ""))
    print(f"\n检查结论: {n_pass}/{len(results)} 通过")
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
