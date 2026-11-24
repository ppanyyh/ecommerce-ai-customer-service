# -*- coding: utf-8 -*-
"""V3.1 第二阶段：开发集独立性检查（对旧 final blind set 的原句/改写泄漏比对）。

- 比对 v3_1_dev_cases.json 与 final_blind_set_v1.json 的全部 query：
  1) 规范化（小写、去空白与标点）后完全一致 → 原句泄漏；
  2) 字符 bigram Jaccard >= 0.6 → 疑似简单改写，列出于人工复核。
- 同时记录开发集性质声明（开发集、已迭代、非盲测集）。
- 只读两个数据文件，不运行任何检索，不调用 DeepSeek。

输出：backend/data/v3_1_dev_set_leakage_check.json
"""
import json
import os
import re
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DEV_PATH = os.path.join(BACKEND, "data", "v3_1_dev_cases.json")
BLIND_PATH = os.path.join(BACKEND, "data", "final_blind_set_v1.json")
OUT_PATH = os.path.join(BACKEND, "data", "v3_1_dev_set_leakage_check.json")

_JAC_THRESHOLD = 0.6


def norm(q):
    return re.sub(r"[\s，。？！、：；\"'“”‘’（）()\[\]{}.,?!:;]", "", (q or "").lower())


def bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


def jac(a, b):
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def main():
    dev = json.load(open(DEV_PATH, encoding="utf-8"))
    blind = json.load(open(BLIND_PATH, encoding="utf-8"))
    dev_cases = dev["cases"]
    blind_cases = blind["cases"]

    blind_norm = [(c.get("case_id"), norm(c.get("query", "")), c.get("query", "")) for c in blind_cases]
    blind_norm_map = {b: cid for cid, b, _ in blind_norm}

    exact, near = [], []
    for c in dev_cases:
        qn = norm(c.get("query", ""))
        if qn in blind_norm_map:
            exact.append({"dev_case_id": c["case_id"], "blind_case_id": blind_norm_map[qn],
                          "query": c["query"]})
            continue
        for b_cid, b_norm, b_raw in blind_norm:
            j = jac(qn, b_norm)
            if j >= _JAC_THRESHOLD:
                near.append({"dev_case_id": c["case_id"], "blind_case_id": b_cid,
                             "jaccard": round(j, 4),
                             "dev_query": c["query"], "blind_query": b_raw})

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dev_set": {"file": "v3_1_dev_cases.json", "n_cases": len(dev_cases),
                    "sha256": __import__("hashlib").sha256(open(DEV_PATH, "rb").read()).hexdigest(),
                    "nature": dev["meta"].get("set_nature")},
        "blind_set": {"file": "final_blind_set_v1.json", "n_cases": len(blind_cases),
                      "note": "只读取做比对，未运行、未修改。"},
        "method": {"normalization": "小写、去空白与标点", "exact_match": "规范化后完全一致",
                   "near_match": f"字符 bigram Jaccard >= {_JAC_THRESHOLD}（疑似简单改写，人工复核）"},
        "exact_leaks": exact,
        "near_matches": near,
        "conclusion": ("通过：无原句泄漏、无疑似改写" if not exact and not near
                       else f"发现疑似泄漏：exact={len(exact)}, near={len(near)}，须人工复核"),
    }
    json.dump(result, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("exact_leaks:", len(exact))
    print("near_matches:", len(near))
    for n in near:
        print("  NEAR", n["dev_case_id"], "vs", n["blind_case_id"], n["jaccard"], "|", n["dev_query"][:24])
    print("conclusion:", result["conclusion"])
    print("written:", OUT_PATH)


if __name__ == "__main__":
    main()
