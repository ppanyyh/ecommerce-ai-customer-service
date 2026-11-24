# -*- coding: utf-8 -*-
"""汇总历史评测/测试问题，生成规范化黑名单 eval_query_blacklist.json。

来源（只读）：
1. backend/data/vector_eval_cases.json（原20条开发集）；
2. backend/data/hybrid_holdout_eval_cases.json（validation_set_v1，30条）；
3. backend/test_hybrid_retriever_unit.py / test_hybrid_v2_validation.py /
   test_chat_integration.py / test_deepseek.py / test_e2e_frontend.py
   中的自然语言问题字符串（含中文的字符串字面量）。

规范化：去首尾空白、去除全部标点/空白、转小写。
本脚本不导入任何检索模块，不运行检索。
"""

import json
import os
import re

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）\"'“”‘’…—\-~～]")


def normalize(q):
    return PUNCT_RE.sub("", (q or "")).lower()


def from_json_eval(path, label):
    out = []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for c in d.get("cases", []):
        q = (c.get("query") or "").strip()
        if q:
            out.append({"query": q, "source": f"{label}:{c.get('case_id','')}"})
    return out


ZH_RE = re.compile(r"[\u4e00-\u9fff]")


def from_py_literals(path, label):
    """提取 .py 文件中含中文的字符串字面量（长度>=6），作为历史问题候选。"""
    src = open(path, encoding="utf-8").read()
    out = []
    # 用 ast 收集字符串常量，避免误匹配注释/正则
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.strip()
            if len(s) >= 6 and ZH_RE.search(s) and not s.startswith(("《", "#")):
                # 排除明显是期望断言/说明的长句（含“必须”“预期”等评测说明词的短注释式字符串）
                if re.search(r"预期|期望|说明:|实际=|通过|泄露|失败项", s):
                    continue
                out.append({"query": s, "source": label})
    return out


def main():
    entries = []
    entries += from_json_eval(os.path.join(DATA, "vector_eval_cases.json"), "dev20")
    entries += from_json_eval(os.path.join(DATA, "hybrid_holdout_eval_cases.json"), "validation_set_v1")

    py_sources = [
        ("test_hybrid_retriever_unit.py", "unit_test_hybrid_v1"),
        ("test_hybrid_v2_validation.py", "unit_test_hybrid_v2"),
        ("test_chat_integration.py", "v2_integration_test"),
        ("test_deepseek.py", "v2_deepseek_test"),
        ("test_e2e_frontend.py", "v2_e2e_test"),
    ]
    for fname, label in py_sources:
        p = os.path.join(BACKEND, fname)
        if os.path.exists(p):
            entries += from_py_literals(p, label)

    # 规范化去重
    seen = {}
    for e in entries:
        n = normalize(e["query"])
        if not n:
            continue
        if n not in seen:
            seen[n] = {"normalized": n, "original": e["query"], "sources": [e["source"]]}
        else:
            if e["source"] not in seen[n]["sources"]:
                seen[n]["sources"].append(e["source"])

    result = {
        "meta": {
            "name": "历史评测/测试问题黑名单（最终盲测集查重依据）",
            "created_at": "2026-09-25",
            "normalization": "去首尾空白与全部标点/空白、转小写",
            "sources": [
                "vector_eval_cases.json（原20条开发集）",
                "hybrid_holdout_eval_cases.json（validation_set_v1，30条）",
                "test_hybrid_retriever_unit.py / test_hybrid_v2_validation.py（单元测试问题）",
                "test_chat_integration.py / test_deepseek.py / test_e2e_frontend.py（V2测试问题）",
            ],
            "total_unique": len(seen),
        },
        "queries": sorted(seen.values(), key=lambda x: x["normalized"]),
    }
    out = os.path.join(DATA, "eval_query_blacklist.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("blacklist unique queries:", len(seen))


if __name__ == "__main__":
    main()
