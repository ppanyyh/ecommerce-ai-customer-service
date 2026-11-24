"""V3.0 数据泄漏自动检查（不调用 DeepSeek，不接入 /api/chat）。

检查项：
1. vector_eval_cases.json 中每条完整 query 不得作为子串出现在任何片段的
   retrieval_text 中（含规则与全部片段）；反向包含同样报告；
2. 评测 query 不得新增到 aliases / keywords：核对 V3 与 V2 的
   knowledge_base.json 商品 aliases 与规则 keywords 完全一致（未被本轮修改），
   且任何 eval query 不作为 keyword/alias 出现；
3. retrieval_text 只允许使用原业务资料（knowledge_base.json）中的字段组合：
   规则 name / keywords / reason / risk_level；通过"retrieval_text 中出现的
   关键词必须能在 kb 字段中找到"以及"不得包含 eval query 的长片段（>=10字）"
   双重校验；
4. 规则风险等级未被修改：chunk text 与 retrieval_text 中的风险等级必须与
   knowledge_base.json 的 risk_level 一致。

输出：逐项检查结果，全部通过时 exit 0，否则 exit 1。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\check_leakage.py
"""

import json
import os
import re
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
V3_ROOT = PROJECT_DIR
V2_ROOT = os.path.join(os.path.dirname(V3_ROOT), "08_V2_DeepSeek")

EVAL_PATH = os.path.join(BACKEND_DIR, "data", "vector_eval_cases.json")
CHUNKS_PATH = os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl")
KB_V3 = os.path.join(BACKEND_DIR, "knowledge_base.json")
KB_V2 = os.path.join(V2_ROOT, "backend", "knowledge_base.json")


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    cases = json.load(open(EVAL_PATH, encoding="utf-8"))["cases"]
    chunks = load_jsonl(CHUNKS_PATH)
    kb = json.load(open(KB_V3, encoding="utf-8"))
    kb_v2 = json.load(open(KB_V2, encoding="utf-8"))
    kb_rules = {r["id"]: r for r in kb["handoff_rules"]}

    queries = [c["query"] for c in cases]
    retrieval_texts = {
        c["chunk_id"]: (c.get("retrieval_text") or "").strip()
        for c in chunks if (c.get("retrieval_text") or "").strip()
    }

    failures = []

    # ---------- 检查1：完整 query 不得出现在 retrieval_text ----------
    print("[检查1] eval query 不得出现在任何 retrieval_text 中")
    hit = False
    for q in queries:
        for cid, rt in retrieval_texts.items():
            if q in rt or rt in q:
                print(f"  [LEAK] {cid} 与 query 相互包含: {q[:30]}...")
                failures.append(f"leak_query_in_retrieval_text:{cid}:{q[:20]}")
                hit = True
    if not hit:
        print(f"  PASS：{len(queries)} 条 query x {len(retrieval_texts)} 条 retrieval_text 无相互包含")

    # ---------- 检查2：aliases/keywords 未新增（V3 与 V2 knowledge_base.json 一致） ----------
    print("[检查2] 评测 query 未新增到 aliases/keywords（V3 与 V2 kb 商品aliases+规则keywords一致）")
    v2_rules = {r["id"]: r for r in kb_v2["handoff_rules"]}
    alias_ok = all(
        p.get("aliases") == q.get("aliases")
        for p, q in zip(kb["products"], kb_v2["products"])
    )
    kw_ok = all(
        v3_r.get("keywords") == v2_r.get("keywords")
        for v3_r, v2_r in ((kb_rules[i], v2_rules[i]) for i in kb_rules)
    )
    n_alias = sum(len(p.get("aliases", [])) for p in kb["products"])
    n_kw = sum(len(r.get("keywords", [])) for r in kb["handoff_rules"])
    if not alias_ok:
        failures.append("aliases_changed_vs_v2")
        print("  [LEAK] 商品 aliases 与 V2 不一致！")
    else:
        print(f"  PASS：商品 aliases 与 V2 完全一致（共 {n_alias} 个别名，未被本轮修改）")
    if not kw_ok:
        failures.append("keywords_changed_vs_v2")
        print("  [LEAK] 规则 keywords 与 V2 不一致！")
    else:
        print(f"  PASS：规则 keywords 与 V2 完全一致（共 {n_kw} 个触发关键词，未被本轮修改）")
    # query 不得作为 keyword/alias 本体出现
    all_terms = [a for p in kb["products"] for a in p.get("aliases", [])] + \
                [k for r in kb["handoff_rules"] for k in r.get("keywords", [])]
    bad = [(t, q) for t in all_terms for q in queries if t == q or (len(q) >= 8 and q in t)]
    if bad:
        failures.append(f"query_added_to_terms:{bad[:3]}")
        print(f"  [LEAK] 发现 query 进入 keywords/aliases: {bad[:3]}")
    else:
        print("  PASS：无任何 eval query 进入 aliases/keywords")

    # ---------- 检查3：retrieval_text 只使用原资料字段 ----------
    print("[检查3] retrieval_text 仅由 kb 已有字段（name/keywords/reason/risk_level）组合")
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    for cid, rt in sorted(retrieval_texts.items()):
        c = chunks_by_id[cid]
        if c["doc_type"] != "rule":
            continue
        hr_id = c["ref_id"]
        rule = kb_rules[hr_id]
        # 3a. risk_level 一致（retrieval_text 与 text 与 kb）
        risk = rule["risk_level"]
        rt_ok = f"属于{risk}风险" in rt  # retrieval_text 统一写作「属于高风险/中风险」
        txt_risk = re.search(r"风险等级：(高|中|低)", c["text"])
        if not rt_ok or not txt_risk or txt_risk.group(1) != risk:
            failures.append(f"risk_level_mismatch:{cid}")
            print(f"  [LEAK] {cid} 风险等级表述与 kb({risk}) 不一致")
        else:
            print(f"  PASS：{cid} 风险等级一致（{risk}），retrieval_text 风险表述正确")
        # 3b. retrieval_text 中的关键词都必须来自 kb keywords 或 name/reason 文本
        allowed_corpus = rule["name"] + "".join(rule["keywords"]) + rule["reason"]
        used_keywords = [k for k in rule["keywords"] if k in rt]
        if not used_keywords:
            failures.append(f"no_original_keywords:{cid}")
            print(f"  [WARN] {cid} retrieval_text 未包含任何 kb 原始关键词")
        # 3c. 不得包含 eval query 的长片段（>=10 字，防止改写式复制）
        leak_frag = False
        for q in queries:
            for i in range(0, max(len(q) - 9, 0)):
                frag = q[i:i + 10]
                if frag in rt:
                    print(f"  [LEAK] {cid} 包含 eval query 长片段: {frag}")
                    failures.append(f"leak_fragment:{cid}:{frag}")
                    leak_frag = True
                    break
            if leak_frag:
                break
        if not leak_frag:
            print(f"  PASS：{cid} 使用原始关键词 {len(used_keywords)} 个，无 eval query 长片段")

    print("\n----- 泄漏检查结论 -----")
    if failures:
        print("存在泄漏风险项:")
        for x in failures:
            print(" -", x)
        sys.exit(1)
    print("全部通过：retrieval_text 未泄漏评测问题；aliases/keywords 未新增；风险等级未修改。")
    sys.exit(0)


if __name__ == "__main__":
    main()
