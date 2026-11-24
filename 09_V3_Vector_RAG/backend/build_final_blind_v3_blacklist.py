# -*- coding: utf-8 -*-
"""V3.2.2 最终阶段一 · 步骤二：final_blind_v3_query_blacklist.json

在 final_blind_v2_query_blacklist.json（382 条，已传递覆盖 eval_query_blacklist、
blind v1、V3.1 开发集、validation 双口径、V3.1 测试脚本、旧评测结果）基础上，
追加 V3.2 / V3.2.1 / V3.2.2 阶段全部新来源。

只读文件 + AST 提取字面量，不导入任何检索器/FastAPI/模型。黑名单只用于泄漏检查。
"""
import ast
import hashlib
import json
import os
import re

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")
PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）\"'“”‘’…—\-~～·]")
ZH_RE = re.compile(r"[\u4e00-\u9fff]")


def normalize(q):
    return PUNCT_RE.sub("", (q or "")).lower()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def from_json_eval(path, label):
    out = []
    if not os.path.exists(path):
        return out
    d = json.load(open(path, encoding="utf-8"))
    cases = d.get("cases", d if isinstance(d, list) else [])
    for c in cases:
        if isinstance(c, dict):
            q = (c.get("query") or "").strip()
            if q:
                out.append({"query": q, "source": f"{label}:{c.get('case_id','')}"})
    return out


def from_json_recursive(path, label, keys=("query", "message")):
    out = []
    if not os.path.exists(path):
        return out
    d = json.load(open(path, encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in keys and isinstance(v, str) and v.strip() and ZH_RE.search(v):
                    out.append({"query": v.strip(), "source": label})
                else:
                    walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)

    walk(d)
    return out


def from_py_literals(path, label):
    if not os.path.exists(path):
        return []
    out = []
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.strip()
            if len(s) >= 6 and ZH_RE.search(s) and not s.startswith(("《", "#")):
                if re.search(r"预期|期望|说明:|实际=|通过|泄露|失败项|不可出现|禁止|断言|检查:", s):
                    continue
                out.append({"query": s, "source": label})
    return out


def from_txt_question_lines(path, label):
    """调试转储/服务实测输出中的问题行（含？或 query= 标记）。"""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        m = re.search(r"query[=：:]\s*(.+)", line)
        cand = m.group(1) if m else (line if ("？" in line or "?" in line) else "")
        cand = cand.strip().strip('"\'`')
        if len(cand) >= 6 and ZH_RE.search(cand) and len(cand) <= 120:
            out.append({"query": cand, "source": label})
    return out


def main():
    entries = []

    # A. v2 黑名单整体继承（传递覆盖 V3.0/V3.1 全部来源）
    v2 = json.load(open(os.path.join(DATA, "final_blind_v2_query_blacklist.json"), encoding="utf-8"))
    for e in v2.get("entries", []):
        entries.append({"query": e["query"], "source": "inherit:" + (e["sources"][0] if e.get("sources") else "v2_blacklist")})

    # B. blind v2 用例
    entries += from_json_eval(os.path.join(DATA, "final_blind_set_v2.json"), "final_blind_set_v2")

    # C. V3.2 / V3.2.1 开发集
    entries += from_json_eval(os.path.join(DATA, "v3_2_dev_cases.json"), "v3_2_dev_cases")
    entries += from_json_eval(os.path.join(DATA, "v3_2_1_dev_cases.json"), "v3_2_1_dev_cases")

    # D. 新增测试/调试/服务实测/构建脚本字面量
    py_sources = [
        ("test_v3_2_2_risk_levels.py", "v322_risk_levels_test"),
        ("test_final_blind_v2_evaluator.py", "blind_v2_evaluator_test"),
        ("service_test_phase2.py", "phase2_service_test"),
        ("service_test_v321.py", "v321_service_test"),
        ("service_test_v322.py", "v322_service_test"),
        ("test_e2e_frontend.py", "e2e_frontend_test"),
        ("test_deepseek.py", "deepseek_test"),
        ("test_chat_integration.py", "v2_chat_integration_test"),
        ("test_hybrid_retriever_unit.py", "hybrid_unit_test"),
        ("test_hybrid_v2_validation.py", "hybrid_v2_validation_test"),
        ("debug_v3_2_failures.py", "v32_debug"),
        ("debug_v3_2_leak.py", "v32_debug"),
        ("debug_v3_2_leak2.py", "v32_debug"),
        ("build_v3_2_dev_cases.py", "v32_dev_builder"),
        ("build_v3_2_1_dev_cases.py", "v321_dev_builder"),
        ("evaluate_v3_2_dev.py", "v32_evaluator"),
        ("evaluate_v3_2_1_dev.py", "v321_evaluator"),
        ("run_v321_regress.py", "v321_regress_runner"),
        ("run_v322_regress.py", "v322_regress_runner"),
        ("freeze_v3_2_1_candidate.py", "v321_freeze"),
        ("freeze_v3_2_2_candidate.py", "v322_freeze"),
        ("verify_candidate_for_blindv3.py", "blindv3_precheck"),
    ]
    for fname, label in py_sources:
        entries += from_py_literals(os.path.join(BACKEND, fname), label)

    # E. V3.2 时代评测结果 JSON
    result_files = [
        "v3_2_dev_eval_results.json",
        "v3_2_1_dev_eval_results.json",
        "final_blind_v2_eval_results.json",
        "_v321_regress_raw.json",
        "_v322_regress_raw.json",
        "_v32_phase2_regress_raw.json",
        "_v321_val11.json", "_v321_val11b.json",
        "_v321_val12.json", "_v321_val12b.json",
    ]
    for fn in result_files:
        entries += from_json_recursive(os.path.join(DATA, fn), f"results:{fn}")

    # F. 调试转储 / 服务实测输出
    txt_files = [
        "_v321_servicetest.txt", "_v322_servicetest.txt",
        "v3_1_debug_dump.txt", "v3_1_debug_dump2.txt", "v3_1_debug_dump3.txt",
    ]
    for fn in txt_files:
        entries += from_txt_question_lines(os.path.join(DATA, fn), f"txt:{fn}")

    # G. 旧人工审核文件中的问题行
    md_files = [
        "final_blind_set_label_review.md", "final_blind_set_v2_label_review.md",
        "final_blind_set_v2_review_checklist.md", "final_blind_v2_api_manual_review.md",
        "final_blind_eval_errata.md", "final_blind_v2_evaluator_errata.md",
    ]
    for fn in md_files:
        entries += from_txt_question_lines(os.path.join(DATA, fn), f"md:{fn}")

    # 去重合并
    seen = {}
    for e in entries:
        nq = normalize(e["query"])
        if not nq:
            continue
        if nq in seen:
            if e["source"] not in seen[nq]["sources"]:
                seen[nq]["sources"].append(e["source"])
        else:
            seen[nq] = {"query": e["query"], "normalized_query": nq,
                        "sha256": sha256_text(e["query"]), "sources": [e["source"]]}

    out = {
        "meta": {
            "name": "V3.2.2 final blind set v3 泄漏检查用历史查询黑名单（本项目最后一套）",
            "created_at": "2026-09-26",
            "purpose": "仅用于 final_blind_set_v3 泄漏检查，不得交给任何检索器",
            "normalization": "去首尾空白与全部标点/空白、转小写",
            "inheritance": "final_blind_v2_query_blacklist.json 全量继承（传递覆盖 eval_query_blacklist / blind v1 / V3.1 dev / validation / V3.1 测试脚本 / 旧评测结果）",
            "new_sources": [
                "final_blind_set_v2.json",
                "v3_2_dev_cases.json / v3_2_1_dev_cases.json",
                "V3.2 时代全部测试/调试/服务实测/构建/评测/冻结脚本字面量",
                "V3.2 时代评测结果 JSON 的 query/message 字段",
                "调试转储与服务实测输出中的问题行",
                "旧人工审核/评审/勘误 md 文件中的问题行",
            ],
            "total_collected": len(entries),
            "total_unique": len(seen),
        },
        "entries": list(seen.values()),
    }
    out_path = os.path.join(DATA, "final_blind_v3_query_blacklist.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("collected:", len(entries), "unique:", len(seen))
    print("blacklist_sha256:", sha256_text(json.dumps(out, ensure_ascii=False, sort_keys=True)))
    print("saved:", out_path)


if __name__ == "__main__":
    main()
