"""V3.0 混合检索失败/边界案例诊断数据采集（只读，不做任何修改，不调用 DeepSeek）。

目标案例：H-004 / H-007 / H-009 / H-021 / H-022 / H-025。

对每个案例采集：
1. 完整 query / is_answerable / relevant_chunk_ids / required_rule_ids；
2. keyword_only Top-5（chunk_id/rank/keyword_score/matched_terms/doc_type/title/source）；
3. vector_only Top-5（chunk_id/rank/similarity/doc_type/title/source）；
4. hybrid Top-5（chunk_id/final_rank/keyword_rank/vector_rank/两个RRF分项/rrf_score）；
5. 预期片段（relevant + required）在三种模式 Top-10 中的排名（不在则标记 NOT_IN_TOP10）；
6. query 词项识别（商品编号/商品名称或别名/FAQ关键词/风险关键词/泛化词/多意图）；
7. 冻结文件哈希核验结果。

本脚本只读取数据并输出诊断 JSON，不修改任何检索代码、知识片段、关键词、测试集或参数。

运行方式（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\diagnose_failures.py
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
HOLDOUT_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_holdout_eval_cases.json")
COMPARISON_PATH = os.path.join(BACKEND_DIR, "data", "retrieval_mode_comparison.json")
FREEZE_PATH = os.path.join(BACKEND_DIR, "data", "hybrid_code_freeze_manifest.json")
KB_PATH = os.path.join(BACKEND_DIR, "knowledge_base.json")

sys.path.insert(0, BACKEND_DIR)
from keyword_retriever_v3 import keyword_search  # noqa: E402
from vector_retriever import vector_search  # noqa: E402
from hybrid_retriever import hybrid_search, RRF_K, KEYWORD_WEIGHT, VECTOR_WEIGHT  # noqa: E402

TARGET_CASES = ["H-004", "H-007", "H-009", "H-021", "H-022", "H-025"]
TOP_K_VIEW = 5
TOP_K_POOL = 10

RE_PRODUCT_ID = re.compile(r"P\d{3}", re.IGNORECASE)
RE_RULE_ID = re.compile(r"HR-?\d{2}", re.IGNORECASE)
GENERIC_WORDS = ["东西", "货", "你们", "这边", "问题", "处理", "这个", "那个", "还是",
                 "到底", "马上", "直接", "顺便", "一般", "应该", "能不能", "是不是",
                 "怎么", "怎么办", "多久", "多少", "为什么", "一样"]


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def title_of(chunks_by_id, cid):
    c = chunks_by_id.get(cid, {})
    return c.get("title", ""), c.get("source", "")


def main():
    holdout = json.load(open(HOLDOUT_PATH, encoding="utf-8"))["cases"]
    kb = json.load(open(KB_PATH, encoding="utf-8"))
    chunks_by_id = {}
    with open(os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunks_by_id[c["chunk_id"]] = c

    faq_kw = {f["id"]: f.get("keywords", []) for f in kb.get("faqs", [])}
    rule_kw = {r["id"]: r.get("keywords", []) for r in kb.get("handoff_rules", [])}
    product_terms = {}
    for p in kb.get("products", []):
        product_terms[p["id"]] = [p.get("name", "")] + list(p.get("aliases", []))

    diagnosis = []
    for case in holdout:
        if case["case_id"] not in TARGET_CASES:
            continue
        q = case["query"]

        kw = keyword_search(q, top_k=TOP_K_POOL)
        vec = vector_search(q, top_k=TOP_K_POOL)
        hyb = hybrid_search(q, top_k=TOP_K_POOL)

        kw_rank = {r["chunk_id"]: r["rank"] for r in kw}
        vec_rank = {r["chunk_id"]: r["rank"] for r in vec}
        hyb_rank = {r["chunk_id"]: r["final_rank"] for r in hyb}
        kw_score = {r["chunk_id"]: r["keyword_score"] for r in kw}
        vec_sim = {r["chunk_id"]: r["similarity"] for r in vec}

        # ---- 词项识别 ----
        ids_p = sorted({m.group(0).upper() for m in RE_PRODUCT_ID.finditer(q)})
        ids_hr = sorted({m.group(0).upper() for m in RE_RULE_ID.finditer(q)})
        alias_hits = []
        for pid, terms in product_terms.items():
            for t in terms:
                if t and t.lower() in q.lower():
                    alias_hits.append({"product": pid, "term": t})
        faq_kw_hits = [{"faq": fid, "term": t}
                       for fid, kws in faq_kw.items() for t in kws if t.lower() in q.lower()]
        rule_kw_hits = [{"rule": rid, "term": t}
                        for rid, kws in rule_kw.items() for t in kws if t.lower() in q.lower()]
        generic_hits = [w for w in GENERIC_WORDS if w in q]

        def rank_or_marker(d, cid):
            r = d.get(cid)
            return r if r is not None else "NOT_IN_TOP10"

        expected = []
        for cid in list(dict.fromkeys(case["relevant_chunk_ids"] + case["required_rule_ids"])):
            expected.append({
                "chunk_id": cid,
                "keyword_rank_top10": rank_or_marker(kw_rank, cid),
                "vector_rank_top10": rank_or_marker(vec_rank, cid),
                "hybrid_rank_top10": rank_or_marker(hyb_rank, cid),
                "keyword_score": kw_score.get(cid),
                "vector_similarity": vec_sim.get(cid),
            })

        entry = {
            "case_id": case["case_id"],
            "category": case["category"],
            "query": q,
            "is_answerable": case["is_answerable"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "required_rule_ids": case["required_rule_ids"],
            "keyword_only_top5": [
                {"chunk_id": r["chunk_id"], "rank": r["rank"],
                 "keyword_score": r["keyword_score"], "matched_terms": r["matched_terms"],
                 "doc_type": r["doc_type"],
                 "title": chunks_by_id.get(r["chunk_id"], {}).get("title", ""),
                 "source": r["source"]}
                for r in kw[:TOP_K_VIEW]
            ],
            "vector_only_top5": [
                {"chunk_id": r["chunk_id"], "rank": r["rank"],
                 "similarity": r["similarity"], "doc_type": r["doc_type"],
                 "title": chunks_by_id.get(r["chunk_id"], {}).get("title", ""),
                 "source": r["source"]}
                for r in vec[:TOP_K_VIEW]
            ],
            "hybrid_top5": [
                {"chunk_id": r["chunk_id"], "final_rank": r["final_rank"],
                 "keyword_rank": r["keyword_rank"], "vector_rank": r["vector_rank"],
                 "rrf_keyword_component": round(KEYWORD_WEIGHT / (RRF_K + r["keyword_rank"]), 6)
                 if r["keyword_rank"] is not None else 0.0,
                 "rrf_vector_component": round(VECTOR_WEIGHT / (RRF_K + r["vector_rank"]), 6)
                 if r["vector_rank"] is not None else 0.0,
                 "rrf_score": r["rrf_score"], "doc_type": r["doc_type"]}
                for r in hyb[:TOP_K_VIEW]
            ],
            "expected_chunk_ranks": expected,
            "term_analysis": {
                "product_ids": ids_p,
                "rule_ids": ids_hr,
                "product_name_or_alias_hits": alias_hits,
                "faq_keyword_hits": faq_kw_hits,
                "risk_keyword_hits": rule_kw_hits,
                "generic_word_hits": generic_hits,
                "multi_intent_marked": case["category"] == "multi",
            },
        }
        diagnosis.append(entry)

    freeze = json.load(open(FREEZE_PATH, encoding="utf-8"))
    freeze_now = {f: sha256(os.path.join(BACKEND_DIR, f)) for f in freeze["files_sha256"]}

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "失败/边界案例诊断（只读采集，未修改任何检索代码/知识片段/关键词/测试集/参数）",
        "validation_set_designation": {
            "set": "hybrid_holdout_eval_cases.json",
            "formal_name": "validation_set_v1",
            "meaning": "该测试集后续可用于调试，但不再作为最终无偏测试集；算法修改完成后必须重新创建一套全新的 final blind set",
            "sha256": sha256(HOLDOUT_PATH),
        },
        "comparison_file_saved": os.path.exists(COMPARISON_PATH),
        "comparison_generated_at": json.load(open(COMPARISON_PATH, encoding="utf-8"))["generated_at"]
        if os.path.exists(COMPARISON_PATH) else None,
        "rrf_params": {"RRF_K": RRF_K, "KEYWORD_WEIGHT": KEYWORD_WEIGHT, "VECTOR_WEIGHT": VECTOR_WEIGHT},
        "freeze_hashes_verified": freeze_now == freeze["files_sha256"],
        "cases": diagnosis,
    }
    out_path = os.path.join(BACKEND_DIR, "data", "retrieval_failure_diagnosis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"诊断数据已写入: {out_path}")
    print(f"cases={len(diagnosis)} freeze_hashes_verified={out['freeze_hashes_verified']} "
          f"comparison_saved={out['comparison_file_saved']}")


if __name__ == "__main__":
    main()
