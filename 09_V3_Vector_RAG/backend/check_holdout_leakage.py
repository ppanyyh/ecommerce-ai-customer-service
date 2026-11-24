"""V3.0 混合检索阶段防泄漏复查（不调用 DeepSeek，不接入 /api/chat）。

检查项：
1. 留出集 query 未出现在 knowledge_chunks.jsonl（原始 text 与 retrieval_text）中
   （双向包含 + >=10 字长片段防改写式复制）；
2. 留出 query 未新增到 keywords / aliases：V3 与 V2 knowledge_base.json 的
   商品 aliases 与规则 keywords 完全一致，且无留出 query 进入词条；
3. 代码冻结后 5 个文件哈希与 hybrid_code_freeze_manifest.json 一致；
4. 留出集文件创建后哈希未改变（与创建时记录的 SHA-256 比对）；
5. 上述全部通过即表明未因失败结果修改预期答案（留出集文件未被改动）。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\check_holdout_leakage.py
"""

import hashlib
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
HOLDOUT_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_holdout_eval_cases.json")
CHUNKS_PATH = os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl")
FREEZE_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_code_freeze_manifest.json")
KB_V3 = os.path.join(BACKEND_DIR, "knowledge_base.json")
KB_V2 = os.path.join(os.path.dirname(os.path.dirname(BACKEND_DIR)), "08_V2_DeepSeek", "backend", "knowledge_base.json")

HOLDOUT_SHA256_EXPECTED = "26ee720d21c486a5d9829a3fd390db9b173360f251a41a6f1523c74759616948"

failures = []


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    holdout = json.load(open(HOLDOUT_PATH, encoding="utf-8"))["cases"]
    queries = [c["query"] for c in holdout]
    chunks = [json.loads(s) for s in open(CHUNKS_PATH, encoding="utf-8") if s.strip()]

    # ---------- 检查1 ----------
    print("[检查1] 留出 query 未出现在 knowledge_chunks（text / retrieval_text）")
    leak = False
    bodies = []
    for c in chunks:
        bodies.append((c["chunk_id"], c["text"], "text"))
        if (c.get("retrieval_text") or "").strip():
            bodies.append((c["chunk_id"], c["retrieval_text"], "retrieval_text"))
    for q in queries:
        for cid, body, kind in bodies:
            if q in body or body in q:
                print(f"  [LEAK] {cid}({kind}) 与 query 相互包含: {q[:24]}...")
                failures.append(f"leak:{cid}:{kind}")
                leak = True
    if not leak:
        print(f"  PASS：{len(queries)} 条 query x {len(bodies)} 段文本无相互包含")
    frag_leak = False
    for q in queries:
        for cid, body, kind in bodies:
            for i in range(0, max(len(q) - 9, 0)):
                if q[i:i + 10] in body:
                    print(f"  [LEAK] {cid}({kind}) 含留出 query 长片段: {q[i:i + 10]}")
                    failures.append(f"frag_leak:{cid}:{kind}")
                    frag_leak = True
                    break
            if frag_leak:
                break
        if frag_leak:
            break
    if not frag_leak:
        print("  PASS：无 >=10 字长片段复制")

    # ---------- 检查2 ----------
    print("[检查2] 留出 query 未新增到 keywords / aliases（V3 与 V2 kb 一致）")
    kb3 = json.load(open(KB_V3, encoding="utf-8"))
    kb2 = json.load(open(KB_V2, encoding="utf-8"))
    alias_ok = all(p.get("aliases") == q.get("aliases") for p, q in zip(kb3["products"], kb2["products"]))
    r2 = {x["id"]: x for x in kb2["handoff_rules"]}
    kw_ok = all(r.get("keywords") == r2[r["id"]].get("keywords") for r in kb3["handoff_rules"])
    if alias_ok and kw_ok:
        print("  PASS：商品 aliases 与规则 keywords 与 V2 完全一致（未被本轮修改）")
    else:
        failures.append("kb_terms_changed")
        print("  [LEAK] kb 词条被修改！")
    terms = [a for p in kb3["products"] for a in p.get("aliases", [])] + \
            [k for r in kb3["handoff_rules"] for k in r.get("keywords", [])]
    bad = [(t, q) for t in terms for q in queries if t == q or (len(q) >= 8 and q in t)]
    if bad:
        failures.append(f"holdout_query_in_terms:{bad[:3]}")
        print(f"  [LEAK] 留出 query 进入词条: {bad[:3]}")
    else:
        print("  PASS：无留出 query 进入 keywords/aliases")

    # ---------- 检查3 ----------
    print("[检查3] 冻结文件哈希保持")
    freeze = json.load(open(FREEZE_PATH, encoding="utf-8"))
    ok3 = True
    for f, expected in freeze["files_sha256"].items():
        now = sha256(os.path.join(BACKEND_DIR, f))
        if now != expected:
            ok3 = False
            failures.append(f"freeze_changed:{f}")
            print(f"  [CHANGED] {f}")
    if ok3:
        print(f"  PASS：{len(freeze['files_sha256'])} 个冻结文件哈希均未改变")

    # ---------- 检查4/5 ----------
    print("[检查4/5] 留出集文件哈希保持（未因失败结果修改预期答案）")
    holdout_now = sha256(HOLDOUT_PATH)
    if holdout_now == HOLDOUT_SHA256_EXPECTED:
        print(f"  PASS：留出集 SHA-256 保持一致（{holdout_now[:16]}...）")
    else:
        failures.append("holdout_changed")
        print(f"  [CHANGED] 留出集被修改！now={holdout_now[:16]}...")

    print("\n----- 防泄漏复查结论 -----")
    if failures:
        for x in failures:
            print(" -", x)
        sys.exit(1)
    print("全部通过：无数据泄漏；冻结哈希与留出集哈希均保持。")
    sys.exit(0)


if __name__ == "__main__":
    main()
