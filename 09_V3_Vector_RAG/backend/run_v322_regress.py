# -*- coding: utf-8 -*-
"""V3.2.2 全量回归批量执行（不含任何 final blind set、不含旧 blind）。"""
import io
import json
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

JOBS = [
    ("risk_levels_unit", ["test_v3_2_2_risk_levels.py"]),
    ("risk_selftest", ["risk_intents.py"]),
    ("check_v32_dev", ["check_v3_2_dev_set.py"]),
    ("check_v321_dev", ["check_v3_2_1_dev_set.py"]),
    ("v321_dev", ["evaluate_v3_2_1_dev.py"]),
    ("evaluator_unit", ["test_final_blind_v2_evaluator.py"]),
    ("validation_v1_1_frozen", ["evaluate_hybrid_v2.py", "--cases", "hybrid_holdout_eval_cases_v1_1_frozen.json"]),
    ("validation_v1_2_reviewed", ["evaluate_hybrid_v2.py", "--cases", "hybrid_holdout_eval_cases_v1_2_reviewed.json"]),
    ("v31_dev", ["evaluate_v3_1_dev.py"]),
    ("v32_dev", ["evaluate_v3_2_dev.py"]),
    ("test_retriever", ["test_retriever.py"]),
    ("hybrid_unit", ["test_hybrid_retriever_unit.py"]),
    ("api_integration", ["test_v3_1_api_integration.py"]),
    ("chat_integration", ["test_chat_integration.py"]),
    ("latency_order", ["test_latency_order.py"]),
    ("leakage", ["check_leakage.py"]),
]

raw = {}
for name, args in JOBS:
    print("[RUN]", name, flush=True)
    p = subprocess.run([PY] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=3600)
    tail = (p.stdout or "")[-12000:]
    raw[name] = {"rc": p.returncode, "stdout_tail": tail,
                 "stderr_tail": (p.stderr or "")[-1500:]}
    print("   rc =", p.returncode, flush=True)

with open("data/_v322_regress_raw.json", "w", encoding="utf-8") as f:
    json.dump(raw, f, ensure_ascii=False, indent=1)
print("DONE", {k: v["rc"] for k, v in raw.items()})
