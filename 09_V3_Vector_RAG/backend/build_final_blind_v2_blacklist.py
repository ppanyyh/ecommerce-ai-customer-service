# -*- coding: utf-8 -*-
"""V3.1 第四阶段：汇总全部历史开发/验证/测试问题，生成
final_blind_v2_query_blacklist.json（final blind set v2 泄漏检查专用依据）。

来源（全部只读，不导入任何检索模块、不运行检索）：
A. 旧黑名单 eval_query_blacklist.json（V3.0 已汇总：vector_eval_cases、
   validation_set_v1 原始版、单元/集成/e2e 测试问题）——逐条继承并标注来源；
B. 旧最终盲测集 final_blind_set_v1.json；
C. V3.1 开发集 v3_1_dev_cases.json；
D. validation 双版本 hybrid_holdout_eval_cases_v1_1_frozen.json /
   hybrid_holdout_eval_cases_v1_2_reviewed.json；
E. V3.1 新增测试脚本中的问题字面量：test_v3_1_api_integration.py、
   test_retriever.py、test_latency_order.py、debug_v3_1_failures.py、
   debug_v3_1_natural.py、debug_v3_1_dev_natural.py、test_vector_retrieval.py、
   test_vector_stack.py；
F. 历史评测结果 JSON 中的 query/message 字段（final_blind_eval_results、
   hybrid_v2_validation_results*、v3_1_dev_eval_results、vector_eval_baseline、
   vector_eval_after_rule_optimization、retrieval_mode_comparison、
   retrieval_failure_diagnosis）。

规范化：去首尾空白、去除全部标点/空白、转小写。
黑名单只用于泄漏检查，不得交给任何检索器。
"""

import hashlib
import json
import os
import re

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")

PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）\"'“”‘’…—\-~～]")
ZH_RE = re.compile(r"[\u4e00-\u9fff]")


def normalize(q):
    return PUNCT_RE.sub("", (q or "")).lower()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def from_json_eval(path, label, query_keys=("query",)):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for c in d.get("cases", []):
        for k in query_keys:
            q = (c.get(k) or "").strip() if isinstance(c, dict) else ""
            if q:
                out.append({"query": q, "source": f"{label}:{c.get('case_id','')}"})
                break
    return out


def from_json_recursive(path, label, keys=("query", "message")):
    """递归提取结果类 JSON 中所有 query/message 字段。"""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in keys and isinstance(v, str) and v.strip() and ZH_RE.search(v):
                    out.append({"query": v.strip(), "source": f"{label}"})
                else:
                    walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)

    walk(d)
    return out


def from_py_literals(path, label):
    """提取 .py 文件中含中文的字符串字面量（长度>=6），作为历史问题候选。"""
    if not os.path.exists(path):
        return []
    src = open(path, encoding="utf-8").read()
    out = []
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.strip()
            if len(s) >= 6 and ZH_RE.search(s) and not s.startswith(("《", "#")):
                if re.search(r"预期|期望|说明:|实际=|通过|泄露|失败项|不可出现|禁止", s):
                    continue
                out.append({"query": s, "source": label})
    return out


def main():
    entries = []

    # A. 旧黑名单逐条继承
    old_path = os.path.join(DATA, "eval_query_blacklist.json")
    if os.path.exists(old_path):
        old = json.load(open(old_path, encoding="utf-8"))
        for e in old.get("entries", []):
            entries.append({"query": e["query"], "source": f"inherit:{e.get('source','old_blacklist')}"})

    # B-F. 追加来源
    entries += from_json_eval(os.path.join(DATA, "final_blind_set_v1.json"), "final_blind_set_v1")
    entries += from_json_eval(os.path.join(DATA, "v3_1_dev_cases.json"), "v3_1_dev_cases")
    entries += from_json_eval(os.path.join(DATA, "hybrid_holdout_eval_cases_v1_1_frozen.json"), "validation_v1_1_frozen")
    entries += from_json_eval(os.path.join(DATA, "hybrid_holdout_eval_cases_v1_2_reviewed.json"), "validation_v1_2_reviewed")

    py_sources = [
        ("test_v3_1_api_integration.py", "v3_1_api_integration_test"),
        ("test_retriever.py", "v2_retriever_test"),
        ("test_latency_order.py", "latency_test"),
        ("debug_v3_1_failures.py", "v3_1_debug"),
        ("debug_v3_1_natural.py", "v3_1_debug"),
        ("debug_v3_1_dev_natural.py", "v3_1_debug"),
        ("test_vector_retrieval.py", "vector_retrieval_test"),
        ("test_vector_stack.py", "vector_stack_test"),
    ]
    for fname, label in py_sources:
        entries += from_py_literals(os.path.join(BACKEND, fname), label)

    result_files = [
        "final_blind_eval_results.json",
        "hybrid_v2_validation_results.json",
        "hybrid_v2_validation_results_v1_1_frozen.json",
        "hybrid_v2_validation_results_v1_2_reviewed.json",
        "v3_1_dev_eval_results.json",
        "vector_eval_baseline.json",
        "vector_eval_after_rule_optimization.json",
        "retrieval_mode_comparison.json",
        "retrieval_failure_diagnosis.json",
    ]
    for fn in result_files:
        entries += from_json_recursive(os.path.join(DATA, fn), f"results:{fn}")

    # 去重（按规范化 query），保留全部来源标签
    seen = {}
    for e in entries:
        nq = normalize(e["query"])
        if not nq:
            continue
        if nq in seen:
            if e["source"] not in seen[nq]["sources"]:
                seen[nq]["sources"].append(e["source"])
        else:
            seen[nq] = {
                "query": e["query"],
                "normalized_query": nq,
                "sha256": sha256_text(e["query"]),
                "sources": [e["source"]],
            }

    out = {
        "meta": {
            "name": "V3.1 final blind set v2 泄漏检查用历史查询黑名单",
            "created_at": "2026-09-25",
            "purpose": "仅用于 final_blind_set_v2 泄漏检查，不得交给任何检索器",
            "normalization": "去首尾空白与全部标点/空白、转小写",
            "sources": [
                "eval_query_blacklist.json（V3.0 旧黑名单：dev20/validation_set_v1/单元/V2集成与e2e测试）",
                "final_blind_set_v1.json",
                "v3_1_dev_cases.json",
                "hybrid_holdout_eval_cases_v1_1_frozen.json / v1_2_reviewed.json",
                "test_v3_1_api_integration.py / test_retriever.py / debug_v3_1_* 等 V3.1 测试与调试脚本",
                "历史评测结果 JSON 中的 query/message 字段",
            ],
            "total_collected": len(entries),
            "total_unique": len(seen),
        },
        "entries": list(seen.values()),
    }
    out_path = os.path.join(DATA, "final_blind_v2_query_blacklist.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("collected:", len(entries), "unique:", len(seen))
    print("saved:", out_path)


if __name__ == "__main__":
    main()
