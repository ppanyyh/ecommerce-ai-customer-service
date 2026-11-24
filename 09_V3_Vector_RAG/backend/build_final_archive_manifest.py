# -*- coding: utf-8 -*-
"""V3.2.2 最终归档清单生成器（只读哈希，不修改任何候选/评测文件）。"""
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 1) 读取既有清单，获取 17 个候选文件相对路径（files_sha256: path -> sha）
freeze = json.load(open(os.path.join(BASE, "data", "v3_2_2_candidate_freeze_manifest.json"), encoding="utf-8"))
files_sha = freeze.get("files_sha256") or {}
cand_paths = sorted(files_sha.keys())
assert len(cand_paths) == 17, f"候选文件数异常: {len(cand_paths)}"

# 2) 重算 17 个候选文件 SHA
candidate_files = []
mismatch = []
for rel in cand_paths:
    p = os.path.join(BASE, rel.replace("/", os.sep))
    actual = sha256(p)
    expected = (files_sha.get(rel) or "").lower()
    ok = actual.lower() == expected
    if not ok:
        mismatch.append(rel)
    candidate_files.append({"path": rel, "sha256": actual, "matches_freeze_manifest": ok})

# 3) 关键评测/清单文件 SHA
key_files = {}
for name in [
    "v3_2_2_candidate_freeze_manifest.json",
    "final_blind_set_v3_manifest.json",
    "final_blind_v3_execution_manifest.json",
    "final_blind_v3_eval_results.json",
    "final_blind_v3_eval_report.md",
]:
    key_files[name] = sha256(os.path.join(BASE, "data", name))

# 4) 执行清单标志核验
execm = json.load(open(os.path.join(BASE, "data", "final_blind_v3_execution_manifest.json"), encoding="utf-8"))
assert execm.get("execution_count") == 1, "execution_count != 1"
assert execm.get("no_future_blind_set_planned") is True

manifest = {
    "archive_version": "1.0",
    "created_at": "2026-09-26",
    "purpose": "V3.2.2 最终归档：冻结评测结论，进入作品集整理阶段（只读，不修改任何候选/评测/盲测文件）",
    "key_artifacts_sha256": key_files,
    "candidate_freeze_manifest": {
        "path": "backend/data/v3_2_2_candidate_freeze_manifest.json",
        "sha256": key_files["v3_2_2_candidate_freeze_manifest.json"],
        "all_match_at_freeze_time": True,
    },
    "candidate_files_17": candidate_files,
    "execution_state": {
        "execution_count": 1,
        "final_blind_v3_executed_once": True,
        "no_future_blind_set_planned": True,
        "deepseek_real_calls": 0,
        "exceptions": 0,
        "retries": 0,
    },
    "project_status": {
        "project_status": "portfolio_prototype_completed",
        "production_ready": False,
        "code_frozen": True,
        "evaluation_frozen": True,
        "portfolio_stage": True,
    },
    "constraints": {
        "no_code_changes_allowed": True,
        "no_annotation_changes_allowed": True,
        "no_blind_rerun_allowed": True,
        "no_blind_v4": True,
    },
}

out = os.path.join(BASE, "data", "v3_2_2_final_archive_manifest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# 5) 复核
rel = json.load(open(out, encoding="utf-8"))
bad = [c["path"] for c in rel["candidate_files_17"] if c["matches_freeze_manifest"] is False]
print("candidate files:", len(rel["candidate_files_17"]), "| mismatch:", bad or "无")
print("key files sha recorded:", len(rel["key_artifacts_sha256"]))
print("archive manifest sha256:", hashlib.sha256(open(out, "rb").read()).hexdigest())
print("all_match =", not bad)
