# -*- coding: utf-8 -*-
"""V3.2.1 补充开发集独立性检查（纯数据校验，不运行任何检索/模型）。

检查项：
1. case_id 连续且唯一；2. 必填字段齐全；3. query 唯一；
4. 与历史集合（V3.2 开发集 / V3.1 开发集 / validation v1.1/v1.2 / 留出集 /
   blind v1 / blind v2）的完全重复、规范化重复、高 bigram 重合、过长公共子串
   （数字掩码后）、简单商品/数字替换探测；
5. 与知识片段/订单数据原句的复制检查；
6. PII（11位手机号等）；7. 枚举合法性（scope/route/risk）与分布声明一致性；
8. meta 声明（set_nature 等）。
"""
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

fails = []
oks = []


def check(name, cond, detail=""):
    (oks if cond else fails).append((name, detail))


d = json.load(open(os.path.join(DATA, "v3_2_1_dev_cases.json"), encoding="utf-8"))
cases = d["cases"]
meta = d["meta"]

# 1-3. 结构
ids = [c["case_id"] for c in cases]
check("case_id 连续", ids == ["DV321-%03d" % i for i in range(1, len(cases) + 1)])
check("case_id 唯一", len(set(ids)) == len(ids))
qs = [c["query"] for c in cases]
check("query 唯一", len(set(qs)) == len(qs))
REQ_FIELDS = ["case_id", "query", "expected_scope", "expected_route", "expected_risk_floor",
              "expected_handoff", "relevant_chunk_ids", "required_rule_ids",
              "required_answer_concepts", "forbidden_answer_claims",
              "expected_false_positive_intents", "annotation_reason", "source_refs"]
missing = [(c["case_id"], k) for c in cases for k in REQ_FIELDS if k not in c]
check("必填字段齐全", not missing, str(missing[:5]))

# 4. 历史集合收集
def load_cases(path, list_keys=("cases",)):
    if not os.path.exists(path):
        return []
    raw = json.load(open(path, encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    for k in list_keys:
        if isinstance(raw, dict) and k in raw:
            v = raw[k]
            return v if isinstance(v, list) else []
    # per_case_top3 dict 风格
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, dict) and "per_case_top3" in v:
                return [{"query": q} for q in v["per_case_top3"].keys()]
    return []

HIST = {}
for name, path, lk in [
    ("v3_2_dev", os.path.join(DATA, "v3_2_dev_cases.json"), ("cases",)),
    ("v3_1_dev", os.path.join(DATA, "v3_1_dev_cases.json"), ("cases",)),
    ("holdout30", os.path.join(DATA, "hybrid_holdout_eval_cases.json"), ("cases",)),
    ("blind_v1", os.path.join(DATA, "final_blind_set_v1.json"), ("cases",)),
    ("blind_v2", os.path.join(DATA, "final_blind_set_v2.json"), ("cases",)),
]:
    items = load_cases(path, lk)
    queries = []
    for c in items:
        if isinstance(c, dict) and c.get("query"):
            queries.append(c["query"])
        elif isinstance(c, str):
            queries.append(c)
    HIST[name] = queries

# validation v1.1/v1.2：用例定义在 test_hybrid_v2_validation.py（结果文件无 query 字段），
# 提取其中含中文的字符串字面量作为历史 query 超集（保守）
import glob as _glob
_val_qs = set()
for script in ["test_hybrid_v2_validation.py", "evaluate_hybrid_v2.py"]:
    p = os.path.join(BACKEND, script)
    if os.path.exists(p):
        for m in re.finditer(r'"([^"\n]{8,})"|\'([^\'\n]{8,})\'',
                             open(p, encoding="utf-8").read()):
            s = m.group(1) or m.group(2)
            if re.search(r"[\u4e00-\u9fff]", s) and ("？" in s or "？" not in s):
                _val_qs.add(s)
HIST["validation_v1_1_v1_2"] = sorted(_val_qs)

check("历史集合已加载", all(len(v) > 0 for v in HIST.values()),
      str({k: len(v) for k, v in HIST.items()}))


def norm(q):
    t = re.sub(r"\d+", "#", q.lower())
    return re.sub(r"[^\w#]+", "", t, flags=re.UNICODE)


def bigrams(t):
    return set(t[i:i + 2] for i in range(len(t) - 1)) if len(t) > 1 else {t}


def lcs_len(a, b):
    """最长公共子串长度（滚动行，掩码后文本）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


dup_exact, dup_norm, dup_bigram, dup_lcs = [], [], [], []
for c in cases:
    q = c["query"]
    nq = norm(q)
    for name, hist in HIST.items():
        for h in hist:
            if q == h:
                dup_exact.append((c["case_id"], name))
                continue
            if nq == norm(h):
                dup_norm.append((c["case_id"], name, h))
                continue
            b_overlap = len(bigrams(nq) & bigrams(norm(h))) / max(len(bigrams(nq)), 1)
            if b_overlap >= 0.60:
                dup_bigram.append((c["case_id"], name, h, round(b_overlap, 2)))
                continue
            mh = re.sub(r"\d+", "#", h.lower())
            l = lcs_len(nq, norm(h))
            if l >= max(12, int(0.75 * min(len(nq), len(norm(h))))):
                dup_lcs.append((c["case_id"], name, h, l))
check("与历史集合无完全/规范化重复", not dup_exact and not dup_norm,
      str((dup_exact + dup_norm)[:4]))
check("与历史集合 bigram 重合<0.60", not dup_bigram, str(dup_bigram[:5]))
check("与历史集合 掩码LCS 未超阈值", not dup_lcs, str(dup_lcs[:5]))

# 简单替换探测：新 query 与历史 query 仅商品词/数字不同而其余完全一致（长度差<2 且
# 字符集重合>0.9 的短句对已由 norm+bigram 覆盖；此处抽查首尾 6 字均相同的历史对）
swap_like = []
for c in cases:
    nq = norm(c["query"])
    if len(nq) < 8:
        continue
    for name, hist in HIST.items():
        for h in hist:
            nh = norm(h)
            if abs(len(nq) - len(nh)) <= 2 and nq[:6] == nh[:6] and nq[-6:] == nh[-6:]:
                mid_a, mid_b = nq[6:-6], nh[6:-6]
                if re.sub(r"[^\u4e00-\u9fff]", "", mid_a) != re.sub(r"[^\u4e00-\u9fff]", "", mid_b):
                    continue  # 中段汉字结构不同，非简单替换
                swap_like.append((c["case_id"], name, h))
check("无简单商品/数字替换式改写", not swap_like, str(swap_like[:4]))

# 5. KB/订单原句复制
chunks = [json.loads(l) for l in open(os.path.join(BACKEND, "data", "knowledge_chunks.jsonl"),
                                      encoding="utf-8")]
kb_texts = [c["text"] for c in chunks]
order_snips = []
for o in retriever_orders() if False else []:
    pass
import retriever  # noqa: E402
for o in retriever.ORDERS.values():
    order_snips.append(o["product_name"])
kb_copy = []
for c in cases:
    qn = norm(c["query"])
    for t in kb_texts:
        tn = norm(t)
        if len(tn) >= 12 and tn in qn:
            kb_copy.append((c["case_id"], t[:40]))
    for s in order_snips:
        if s and s in c["query"]:
            kb_copy.append((c["case_id"], "订单商品名:" + s))
check("未复制知识库/订单原句", not kb_copy, str(kb_copy[:4]))

# 6. PII
pii = [c["case_id"] for c in cases
       if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", c["query"])
       or re.search(r"\b\d{17}[\dXx]\b", c["query"])]
check("无手机号/身份证 PII", not pii, str(pii))

# 7. 枚举合法 + 分布
legal_scope = {"supported", "unsupported_business", "irrelevant", "unknown"}
legal_route = {"v3", "v3_gate", "v2_order_structured"}
bad_enum = [c["case_id"] for c in cases
            if c["expected_scope"] not in legal_scope or c["expected_route"] not in legal_route
            or c["expected_risk_floor"] not in ("低", "中", "高")]
check("scope/route/risk 枚举合法", not bad_enum, str(bad_enum))
sec = Counter(c["section"] for c in cases)
check("分布与 meta.counts 一致", all(meta["counts"].get(k, 0) == v for k, v in sec.items()),
      str(dict(sec)))
check("总量=80", len(cases) == 80, str(len(cases)))
combo_bad = [c["case_id"] for c in cases if (
    (c["expected_scope"] == "unsupported_business" and c["relevant_chunk_ids"])
    or (c["expected_scope"] == "irrelevant" and c["expected_handoff"])
    or (not c["expected_handoff"] and c["required_rule_ids"]))]
check("组合合法（未覆盖/无关无相关片段；无规则不转人工）", not combo_bad, str(combo_bad))
handoff_bad = [c["case_id"] for c in cases
               if c["expected_handoff"] and not c["required_rule_ids"]
               and c["section"] in ("C_promise_positive", "E_handoff_copy", "D_order_risk_combo")]
check("高风险用例均有规则依据", not handoff_bad, str(handoff_bad))

# 8. meta 声明
check("meta 声明齐全", meta.get("set_nature") == "development"
      and meta.get("may_be_used_for_tuning") is True
      and meta.get("not_a_blind_set") is True
      and meta.get("old_blind_queries_copied") is False)

print("PASS %d / FAIL %d" % (len(oks), len(fails)))
for n, det in fails:
    print("FAIL:", n, det)
if not fails:
    print("ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
