# -*- coding: utf-8 -*-
"""V3.1 第一阶段调修：保存调修前现状基线清单（只读现有文件，不运行检索）。"""
import hashlib
import json
import os
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


exec_manifest = json.load(open(os.path.join(DATA, "final_blind_execution_manifest.json"), encoding="utf-8"))
results = json.load(open(os.path.join(DATA, "final_blind_eval_results.json"), encoding="utf-8"))

baseline = {
    "created_at": datetime.now().isoformat(timespec="seconds"),
    "purpose": "V3.1 第一阶段调修前的现状基线：记录旧 final blind set 结果与候选文件哈希，调修不得改动这些资产。",
    "old_blind_set_reused_for_tuning": False,
    "old_blind_set_reexecuted": False,
    "old_blind_set_sha256": exec_manifest["blind_set_sha256"],
    "old_evaluated_mode": exec_manifest["evaluated_mode"],
    "old_candidate_files_sha256": exec_manifest["candidate_hashes_after"],
    "old_blind_metrics": {
        "answer_hit1": results["overall"]["answer_hit1"],
        "answer_hit1_pct": results["overall"]["answer_hit1_pct"],
        "answer_recall3": results["overall"]["answer_recall3"],
        "answer_recall3_pct": results["overall"]["answer_recall3_pct"],
        "mrr": results["overall"]["mrr"],
        "rule_recall3": results["overall"]["rule_recall3"],
        "rule_recall3_pct": results["overall"]["rule_recall3_pct"],
        "supported_accuracy": results["overall"]["supported_accuracy"],
        "supported_accuracy_pct": results["overall"]["supported_accuracy_pct"],
        "unanswerable_false_hits": results["overall"]["unanswerable_false_hits"],
        "unanswerable_false_hit_rate_pct": results["overall"]["unanswerable_false_hit_rate_pct"],
    },
    "latency_errata": {
        "reported_in_original_report": {
            "latency_ms_cold_start_first_call": results["overall"]["latency_ms_cold_start_first_call"],
            "latency_ms_p95_overall": results["overall"]["latency_ms_p95_overall"],
        },
        "corrected": {
            "real_cold_start_first_call_ms": 194742.21,
            "warm_p50_ms": 14.44,
            "warm_p95_excluding_first_ms": 31.46,
        },
        "errata_file": "final_blind_eval_errata.md",
        "note": "原脚本先排序后取首元素，误把最小值当成首次调用；勘误详见 final_blind_eval_errata.md。",
    },
}

out = os.path.join(DATA, "v3_1_baseline_manifest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(baseline, f, ensure_ascii=False, indent=2)
print("written:", out)
