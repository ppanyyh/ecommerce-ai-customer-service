# -*- coding: utf-8 -*-
"""V3.2 第二阶段全量回归批量执行器（不运行任何 final blind set）。"""
import subprocess, sys, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PY = sys.executable
RUNS = [
    ("risk_intents_selftest", ["risk_intents.py"]),
    ("check_v3_2_dev_set", ["check_v3_2_dev_set.py"]),
    ("evaluator_52", ["test_final_blind_v2_evaluator.py"]),
    ("test_retriever", ["test_retriever.py"]),
    ("hybrid_unit", ["test_hybrid_retriever_unit.py"]),
    ("latency_order", ["test_latency_order.py"]),
    ("check_leakage", ["check_leakage.py"]),
    ("validation_v1_1_frozen", ["evaluate_hybrid_v2.py", "--cases", "hybrid_holdout_eval_cases_v1_1_frozen.json"]),
    ("validation_v1_2_reviewed", ["evaluate_hybrid_v2.py", "--cases", "hybrid_holdout_eval_cases_v1_2_reviewed.json"]),
    ("v3_1_dev_eval", ["evaluate_v3_1_dev.py"]),
    ("v3_2_dev_eval", ["evaluate_v3_2_dev.py"]),
    ("api_integration", ["test_v3_1_api_integration.py"]),
    ("chat_integration", ["test_chat_integration.py"]),
]

results = {}
for name, args in RUNS:
    t0 = time.time()
    r = subprocess.run([PY] + args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
    dt = time.time() - t0
    results[name] = {"rc": r.returncode, "secs": round(dt, 1),
                     "stdout_tail": (r.stdout or '')[-3000:], "stderr_tail": (r.stderr or '')[-800:]}
    print("%-28s rc=%-3s %6.1fs" % (name, r.returncode, dt), flush=True)

import json
with open("data/_v32_phase2_regress_raw.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("ALL DONE")
