# -*- coding: utf-8 -*-
"""V3.2.2 最终阶段一 · 步骤九：final_blind_set_v3 泄漏与完整性检查（24 项）

只读取文件，禁止导入任何检索器、FastAPI 应用或模型。
ngram/LCS 比较仅在中文（含汉字）字符上进行——数字（如12位订单号）与拉丁字符
（如型号 KP87、LDAC）不参与 ngram，以免订单号/型号的固有重合造成误报；
数字骨架单独用于"商品/数字替换"检测（第 8 项）。
"""
import hashlib
import json
import os
import re
import sys
from collections import Counter

sys.stdout = io = sys.stdout
try:
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）\"'“”‘’…—\-~～·！？]")
ZH_RE = re.compile(r"[\u4e00-\u9fff]+")
ALLOWED_CASE_KEYS = {"case_id", "evaluation_layer", "category", "difficulty", "query",
                     "is_answerable", "expected_scope", "expected_route",
                     "relevant_chunk_ids", "required_rule_ids", "expected_category",
                     "expected_risk_floor", "expected_handoff",
                     "required_answer_concepts", "forbidden_answer_claims",
                     "source_refs", "annotation_reason"}
ALLOWED_META_KEYS = {"name", "note", "created_at", "set_nature", "total",
                     "layer_a_retrieval_scope_order", "layer_b_api_contract",
                     "risk_levels_source", "annotation_basis", "cases"}
RULE_LEVELS = {"HR-01": "高", "HR-02": "高", "HR-03": "中", "HR-04": "中",
               "HR-05": "高", "HR-06": "高", "HR-07": "高", "HR-08": "高"}
LEVEL_SCORE = {"低": 0, "中": 1, "高": 2}
REAL_ORDERS = {"202609180001", "202609180002", "202609180003"}
ORDER_PRODUCTS = {"202609180001": "耳机", "202609180002": "键盘", "202609180003": "杯子"}

results = []


def check(idx, name, ok, detail=""):
    results.append((idx, name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {idx:02d} {name}" + (f" —— {detail}" if detail else ""))
    return ok


def normalize(q):
    return PUNCT_RE.sub("", (q or "")).lower()


def zh_segments(s):
    return ZH_RE.findall(s or "")


def zh_joined(s):
    return "".join(zh_segments(normalize(s)))


def ngrams(s, n):
    segs = zh_joined(s)
    return set(segs[i:i + n] for i in range(len(segs) - n + 1)) if len(segs) >= n else set()


def overlap_coeff(a_set, b_set):
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / min(len(a_set), len(b_set))


def longest_common_substring(a, b):
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


# ============ 载入 ============
bs = json.load(open(os.path.join(DATA, "final_blind_set_v3.json"), encoding="utf-8"))
cases = bs["cases"]
blacklist = json.load(open(os.path.join(DATA, "final_blind_v3_query_blacklist.json"), encoding="utf-8"))
bl_norm = {e["normalized_query"] for e in blacklist["entries"]}
bl_nq_list = [e["normalized_query"] for e in blacklist["entries"]]

# 知识库片段文本（供第9项）
kb_texts = []
for line in open(os.path.join(DATA, "knowledge_chunks.jsonl"), encoding="utf-8"):
    d = json.loads(line)
    kb_texts.append((d["chunk_id"], d.get("text") or ""))

# risk_levels.py 正式映射（第17项核对源码常量）
rl_src = open(os.path.join(BASE, "risk_levels.py"), encoding="utf-8").read()
for rid, lv in RULE_LEVELS.items():
    if f'"{rid}"' not in rl_src or lv not in rl_src:
        check(0, "risk_levels.py 含正式映射 " + rid, False)

meta = bs
queries = [c["query"] for c in cases]
norms = [normalize(q) for q in queries]
zh_norms = [zh_joined(q) for q in queries]

# ============ 01 case_id 唯一且连续 ============
ids = [c["case_id"] for c in cases]
expected_ids = [f"BV3-{i:03d}" for i in range(1, 81)]
check(1, "case_id 唯一且连续 BV3-001..080", ids == expected_ids,
      "" if ids == expected_ids else f"首差异位置 {[i for i,(a,b) in enumerate(zip(ids,expected_ids)) if a!=b][:3]}")

# ============ 02 query 唯一 ============
dup = [q for q, n in Counter(queries).items() if n > 1]
check(2, "query 精确唯一", not dup, f"重复: {dup}" if dup else "")

# ============ 03 与黑名单无完全重复 ============
hits = [(c["case_id"], nq) for c, nq in zip(cases, norms) if nq in bl_norm]
check(3, "与历史黑名单无完全重复", not hits, f"{hits[:5]}" if hits else f"（黑名单 {len(bl_norm)} 条规范化查询）")

# ============ 04 集内无规范化重复 ============
d4 = [q for q, n in Counter(norms).items() if n > 1]
check(4, "集内无规范化重复", not d4, f"{d4}" if d4 else "")

# ============ 05 无简单同义改写（包含关系） ============
c5 = []
for i, nq in enumerate(norms):
    if len(nq) < 10:
        continue
    for bl in bl_nq_list:
        if len(bl) >= 10 and (nq in bl or bl in nq):
            c5.append((cases[i]["case_id"], bl[:20]))
            break
d5 = []
for i in range(len(norms)):
    for j in range(len(norms)):
        if i != j and len(norms[i]) >= 10 and len(norms[j]) >= 10 and (norms[i] in norms[j] or norms[j] in norms[i]):
            d5.append((cases[i]["case_id"], cases[j]["case_id"]))
c5 = list(set(c5))
check(5, "无简单同义改写（≥10字包含关系）", not c5 and not d5,
      f"vs黑名单:{c5[:3]} 集内:{d5[:3]}" if (c5 or d5) else "")

# ============ 06 无高 bigram/trigram 重合 ============
bl_bigrams = [ngrams(b, 2) for b in bl_nq_list]
bl_trigrams = [ngrams(b, 3) for b in bl_nq_list]
c6 = []
for i, q in enumerate(queries):
    bg = ngrams(q, 2)
    tg = ngrams(q, 3)
    for j, bbg in enumerate(bl_bigrams):
        oc = overlap_coeff(bg, bbg)
        if oc >= 0.55 and len(bg & bbg) >= 8:
            c6.append((cases[i]["case_id"], "bigram", round(oc, 2), bl_nq_list[j][:24]))
            break
    for j, btg in enumerate(bl_trigrams):
        oc = overlap_coeff(tg, btg)
        if oc >= 0.45 and len(tg & btg) >= 5:
            c6.append((cases[i]["case_id"], "trigram", round(oc, 2), bl_nq_list[j][:24]))
            break
for i in range(len(queries)):
    for j in range(i + 1, len(queries)):
        oc = overlap_coeff(ngrams(queries[i], 2), ngrams(queries[j], 2))
        if oc >= 0.55 and len(ngrams(queries[i], 2) & ngrams(queries[j], 2)) >= 8:
            c6.append((cases[i]["case_id"], "in-set-bigram", round(oc, 2), cases[j]["case_id"]))
c6_unique = list({(x[0], x[1]): x for x in c6}.values())
check(6, "无高 bigram/trigram 重合（中文ngram，系数≥0.55）", not c6_unique,
      f"{c6_unique[:6]}" if c6_unique else "")

# ============ 07 无过长公共子串 ============
c7 = []
for i, zn in enumerate(zh_norms):
    for j, bl in enumerate(bl_nq_list):
        blzh = zh_joined(bl)
        if not blzh:
            continue
        l = longest_common_substring(zn, blzh)
        if l >= 10:
            c7.append((cases[i]["case_id"], l, bl[:24]))
            break
for i in range(len(zh_norms)):
    for j in range(i + 1, len(zh_norms)):
        l = longest_common_substring(zh_norms[i], zh_norms[j])
        if l >= 10:
            c7.append((cases[i]["case_id"] + "/" + cases[j]["case_id"], l, zh_norms[i][:12]))
check(7, "无过长公共子串（中文≥10字）", not c7, f"{c7[:6]}" if c7 else "")

# ============ 08 无简单商品/数字替换（中文骨架精确匹配） ============
c8 = []
bl_skeleton = {}
for b in bl_nq_list:
    sk = ZH_RE.sub("", "") or b
    sk = re.sub(r"[a-z0-9]+", "#", b)
    sk = re.sub(r"#", "", sk)
    bl_skeleton.setdefault(sk, b)
skeletons = {}
for i, nq in enumerate(norms):
    sk = re.sub(r"[a-z0-9]+", "", nq)
    if sk in bl_skeleton:
        c8.append((cases[i]["case_id"], bl_skeleton[sk][:24]))
    if sk in skeletons:
        c8.append((cases[i]["case_id"] + "/" + skeletons[sk], "in-set"))
    skeletons.setdefault(sk, cases[i]["case_id"])
check(8, "无简单商品/数字替换（中文骨架重复）", not c8, f"{c8[:5]}" if c8 else "")

# ============ 09 未复制知识库完整句子 ============
c9 = []
for i, zn in enumerate(zh_norms):
    for cid, text in kb_texts:
        tz = zh_joined(text)
        if longest_common_substring(zn, tz) >= 12:
            c9.append((cases[i]["case_id"], cid))
            break
check(9, "未复制知识库完整句子（中文≥12字）", not c9, f"{c9[:5]}" if c9 else "")

# ============ 10 relevant_chunk_ids 存在 ============
kb_ids = {cid for cid, _ in kb_texts}
c10 = [(c["case_id"], x) for c in cases for x in c["relevant_chunk_ids"] if x not in kb_ids]
check(10, "relevant_chunk_ids 全部存在于知识库", not c10, f"{c10[:5]}" if c10 else "")

# ============ 11 required_rule_ids 存在且为 rule ============
c11 = []
for c in cases:
    for x in c["required_rule_ids"]:
        if x not in kb_ids or not x.startswith("RULE-HR-"):
            c11.append((c["case_id"], x))
check(11, "required_rule_ids 全部存在且为规则片段", not c11, f"{c11[:5]}" if c11 else "")

# ============ 12 scope/route/category 合法 ============
SCOPE = {"supported", "unsupported_business", "irrelevant"}
ROUTE = {"v3_hybrid", "v2_order_structured", "api_deterministic", "local_fallback"}
CAT_A = {"product", "faq", "rule", "multi", "order", "unsupported_business", "irrelevant"}
c12 = []
for c in cases:
    if c["expected_scope"] not in SCOPE or c["expected_route"] not in ROUTE:
        c12.append((c["case_id"], "scope/route"))
    if c["evaluation_layer"] == "api_contract" and c["category"] != "api":
        c12.append((c["case_id"], "B层category"))
    if c["evaluation_layer"] == "retrieval_scope_order" and c["category"] not in CAT_A:
        c12.append((c["case_id"], "A层category"))
    if c["expected_category"] not in {"商品", "订单与支付", "物流", "售后", "其他"}:
        c12.append((c["case_id"], "expected_category"))
    if c["expected_risk_floor"] not in LEVEL_SCORE:
        c12.append((c["case_id"], "risk_floor枚举"))
check(12, "scope/route/category 枚举合法", not c12, f"{c12[:5]}" if c12 else "")

# ============ 13 supported 标注完整 ============
c13 = []
for c in cases:
    if c["expected_scope"] == "supported":
        order_ref = any("模拟订单数据" in r for r in c["source_refs"])
        if not c["relevant_chunk_ids"] and not order_ref:
            c13.append((c["case_id"], "无片段且无订单依据"))
        if not c["required_answer_concepts"]:
            c13.append((c["case_id"], "无概念"))
check(13, "supported 标注完整（片段/订单依据+概念）", not c13, f"{c13[:5]}" if c13 else "")

# ============ 14 unsupported/irrelevant 相关片段为空 ============
c14 = [(c["case_id"], c["relevant_chunk_ids"], c["required_rule_ids"])
       for c in cases if c["expected_scope"] != "supported"
       and (c["relevant_chunk_ids"] or c["required_rule_ids"])]
check(14, "unsupported/irrelevant 相关片段为空", not c14, f"{c14[:5]}" if c14 else "")

# ============ 15 数量和难度分布正确 ============
cat = Counter(c["category"] for c in cases)
diff = Counter(c["difficulty"] for c in cases)
layer = Counter(c["evaluation_layer"] for c in cases)
a_sup = sum(1 for c in cases if c["evaluation_layer"] == "retrieval_scope_order" and c["expected_scope"] == "supported")
b_scope = Counter(c["expected_scope"] for c in cases if c["evaluation_layer"] == "api_contract")
ok15 = (len(cases) == 80
        and cat == Counter({"rule": 16, "faq": 10, "unsupported_business": 10, "irrelevant": 10,
                            "product": 8, "multi": 8, "order": 8, "api": 10})
        and diff == Counter({"medium": 36, "hard": 28, "easy": 16})
        and layer == Counter({"retrieval_scope_order": 70, "api_contract": 10})
        and a_sup == 50
        and b_scope == Counter({"supported": 6, "unsupported_business": 2, "irrelevant": 2})
        and bs["total"] == 80)
check(15, "数量/分类/难度/层分布正确", ok15,
      f"cat={dict(cat)} diff={dict(diff)} A_supported={a_sup} B={dict(b_scope)}")

# ============ 16 HR-01..08 全覆盖 ============
cov = Counter()
for c in cases:
    for r in c["required_rule_ids"]:
        cov[r[5:]] += 1
ok16 = all(cov.get(h, 0) >= 2 for h in RULE_LEVELS) and len(cov) == 8
check(16, "HR-01..08 全部覆盖（各≥2条正例）", ok16, f"{dict(sorted(cov.items()))}")

# ============ 17 风险等级与 risk_levels.py 一致 ============
c17 = []
for c in cases:
    if c["required_rule_ids"]:
        expect = max((LEVEL_SCORE[RULE_LEVELS[r[5:]]] for r in c["required_rule_ids"]))
        if LEVEL_SCORE[c["expected_risk_floor"]] != expect:
            c17.append((c["case_id"], c["expected_risk_floor"], expect))
    else:
        if c["expected_risk_floor"] not in {"低", "中"}:
            c17.append((c["case_id"], c["expected_risk_floor"], "无规则却非低/中"))
        if c["expected_risk_floor"] == "中" and not (c["expected_handoff"] and c["expected_scope"] != "irrelevant"):
            c17.append((c["case_id"], "中风险无handoff"))
check(17, "风险等级与 risk_levels.py 正式映射一致", not c17, f"{c17[:5]}" if c17 else "")

# ============ 18 多风险取最高等级 ============
c18 = []
for c in cases:
    if len(c["required_rule_ids"]) >= 2:
        mx = max(LEVEL_SCORE[RULE_LEVELS[r[5:]]] for r in c["required_rule_ids"])
        if LEVEL_SCORE[c["expected_risk_floor"]] != mx:
            c18.append((c["case_id"], c["expected_risk_floor"]))
check(18, "多风险用例 floor 取最高等级", not c18, f"{c18[:5]}" if c18 else "")

# ============ 19 高风险 handoff=true ============
c19 = [(c["case_id"], c["expected_handoff"]) for c in cases
       if (c["expected_risk_floor"] == "高" or any(RULE_LEVELS.get(r[5:]) == "高" for r in c["required_rule_ids"]))
       and not c["expected_handoff"]]
check(19, "所有高风险规则用例 handoff=true", not c19, f"{c19[:5]}" if c19 else "")

# ============ 20 订单数据合法 ============
c20 = []
for c in cases:
    ids_in_q = set(re.findall(r"2026\d{8}", c["query"]))
    for oid in ids_in_q:
        if oid in REAL_ORDERS:
            if oid[8:] == "0002" and ("杯子" in c["query"] or "保温" in c["query"]):
                c20.append((c["case_id"], f"{oid} 实为键盘订单"))
            if oid[8:] == "0003" and ("键盘" in c["query"] or "耳机" in c["query"] or "台灯" in c["query"]):
                c20.append((c["case_id"], f"{oid} 实为保温杯订单"))
            if oid[8:] == "0001" and ("杯子" in c["query"] or "键盘" in c["query"]):
                c20.append((c["case_id"], f"{oid} 实为耳机订单"))
        else:
            if "不存在" not in c["annotation_reason"]:
                c20.append((c["case_id"], f"{oid} 不存在但未标注"))
    if not ids_in_q and c["category"] == "order":
        if "不完整" not in c["annotation_reason"] and "尾号" not in c["query"]:
            c20.append((c["case_id"], "order类但无订单号且未标注不完整"))
check(20, "订单引用合法且商品一致", not c20, f"{c20[:5]}" if c20 else "")

# ============ 21 label review 覆盖 80 条 ============
lr = open(os.path.join(DATA, "final_blind_set_v3_label_review.md"), encoding="utf-8").read()
lr_ids = set(re.findall(r"BV3-\d{3}", lr))
missing = [i for i in ids if i not in lr_ids]
check(21, "label review 覆盖全部 80 条", not missing, f"缺失: {missing[:5]}" if missing else f"覆盖 {len(lr_ids)} 条")

# ============ 22 无 PII ============
c22 = []
PII_RE = re.compile(r"1[3-9]\d{9}|\d{17}[\dXx]|\d{6,}(?<!2026\d{8})")
for c in cases:
    blob = json.dumps(c, ensure_ascii=False)
    if re.search(r"1[3-9]\d{9}", blob):
        c22.append((c["case_id"], "手机号模式"))
    if re.search(r"\d{17}[\dXx]", blob):
        c22.append((c["case_id"], "身份证模式"))
    for kw in ("api_key", "sk-", "DEEPSEEK_API_KEY"):
        if kw in blob:
            c22.append((c["case_id"], kw))
check(22, "无 API Key/真实手机号/身份证/个人数据", not c22, f"{c22[:5]}" if c22 else "")

# ============ 23 无运行后字段 ============
c23 = []
for c in cases:
    extra = set(c.keys()) - ALLOWED_CASE_KEYS
    if extra:
        c23.append((c["case_id"], sorted(extra)))
extra_meta = set(bs.keys()) - ALLOWED_META_KEYS
for bad in ("retrieved", "scores", "ranking", "actual", "output", "results", "executed_at"):
    if bad in extra_meta or any(bad in k for k in extra_meta):
        c23.append(("meta", bad))
check(23, "无运行后字段（actual/score/ranking等）", not c23 and not extra_meta,
      f"case级:{c23[:3]} meta级:{sorted(extra_meta)}" if (c23 or extra_meta) else "")

# ============ 24 17个候选文件哈希一致 ============
fm = json.load(open(os.path.join(DATA, "v3_2_2_candidate_freeze_manifest.json"), encoding="utf-8"))
c24 = []
for rel, recorded in fm["files_sha256"].items():
    p = os.path.join(BASE, rel.replace("/", os.sep))
    if sha256_file(p) != recorded.lower():
        c24.append(rel)
check(24, "17 个候选文件哈希与 V3.2.2 冻结清单一致", not c24 and fm.get("all_match") is True,
      f"不一致: {c24}" if c24 else f"（{len(fm['files_sha256'])} 文件）")

# ============ 汇总 ============
fails = [r for r in results if r[1] is False or r[1] == 0 or not r[2]]
fails = [(i, n, d) for (i, n, ok, d) in results if not ok]
print("\n==== 汇总 ====")
print(f"检查项: {len(results)}  通过: {len(results) - len(fails)}  失败: {len(fails)}")
for i, n, d in fails:
    print("  FAIL:", i, n, d)
out = {"checked_at": "2026-09-26", "total_checks": len(results),
       "passed": len(results) - len(fails), "failed": len(fails),
       "failures": [{"check": i, "name": n, "detail": d} for i, n, d in fails]}
with open(os.path.join(DATA, "_blindv3_check_result.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
sys.exit(0 if not fails else 1)
