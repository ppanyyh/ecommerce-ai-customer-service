# -*- coding: utf-8 -*-
"""V3.2.3 热修复全量回归（不含任何 blind；专项测试单独跑）。"""
import io
import json
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

JOBS = [
    ("hotfix_specialized", ["test_v3_2_3_audio_defect_hotfix.py"]),
    ("hotfix_api", ["test_v3_2_3_api_hotfix.py"]),
    ("risk_levels_unit", ["test_v3_2_2_risk_levels.py"]),
    ("risk_selftest", ["risk_intents.py"]),
    ("v321_dev", ["evaluate_v3_2_1_dev.py"]),
    ("v32_dev", ["evaluate_v3_2_dev.py"]),
    ("v31_dev", ["evaluate_v3_1_dev.py"]),
    ("validation_v1_1_frozen", ["evaluate_hybrid_v2.py", "--cases", "hybrid_holdout_eval_cases_v1_1_frozen.json"]),
    ("validation_v1_2_reviewed", ["evaluate_hybrid_v2.py", "--cases", "hybrid_holdout_eval_cases_v1_2_reviewed.json"]),
    ("api_integration", ["test_v3_1_api_integration.py"]),
    ("test_retriever", ["test_retriever.py"]),
    ("latency_order", ["test_latency_order.py"]),
    ("leakage", ["check_leakage.py"]),
    ("chat_integration", ["test_chat_integration.py"]),
]

raw = {}
for name, args in JOBS:
    print("[RUN]", name, flush=True)
    try:
        p = subprocess.run([PY] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600)
        rc, tail, err = p.returncode, (p.stdout or "")[-12000:], (p.stderr or "")[-1500:]
    except subprocess.TimeoutExpired:
        rc, tail, err = -9, "", "timeout"
    raw[name] = {"rc": rc, "stdout_tail": tail, "stderr_tail": err}
    print("   rc =", rc, flush=True)

with open("data/_v323_regress_raw.json", "w", encoding="utf-8") as f:
    json.dump(raw, f, ensure_ascii=False, indent=1)
print("DONE", {k: v["rc"] for k, v in raw.items()})
