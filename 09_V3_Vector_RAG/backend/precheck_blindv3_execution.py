# -*- coding: utf-8 -*-
"""final blind v3 唯一一次评测 · 步骤一：执行前检查（只读）。任何一项失败立即停止。"""
import hashlib
import json
import os
import sys

try:
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


fail = []

# 1) blind v3 manifest 状态
m = json.load(open(os.path.join(DATA, "final_blind_set_v3_manifest.json"), encoding="utf-8"))
required = {
    "status": "frozen_pending_one_time_evaluation",
    "no_future_blind_set_planned": True,
}
for k, v in required.items():
    ok = m.get(k) == v
    print(f"manifest.{k} = {m.get(k)} {'OK' if ok else 'FAIL'}")
    if not ok:
        fail.append(k)
for k in ("retrieval_executed", "api_chat_called", "deepseek_called",
          "final_blind_v3_executed"):
    ok = m.get(k) is False
    print(f"manifest.{k} = {m.get(k)} {'OK' if ok else 'FAIL'}")
    if not ok:
        fail.append(k)
ok = m.get("execution_count") == 0
print(f"manifest.execution_count = {m.get('execution_count')} {'OK' if ok else 'FAIL'}")
if not ok:
    fail.append("execution_count")

# 2) blind v3 SHA 严格等于指定值
EXPECTED_BLIND_SHA = "938582f31a5506c52c0beafdb0f395dd19e7d7fada04ef9697af8bbe2a9fc10d"
blind_sha = sha256_file(os.path.join(DATA, "final_blind_set_v3.json"))
print(f"blind v3 SHA = {blind_sha}")
if blind_sha != EXPECTED_BLIND_SHA:
    fail.append("blind_sha")
else:
    print("blind v3 SHA 严格匹配指定值 OK")

# 3) 4 资产哈希与清单一致
assets = {
    "final_blind_set_v3_sha256": "final_blind_set_v3.json",
    "label_review_sha256": "final_blind_set_v3_label_review.md",
    "query_blacklist_sha256": "final_blind_v3_query_blacklist.json",
    "review_checklist_sha256": "final_blind_set_v3_review_checklist.md",
}
for field, fname in assets.items():
    actual = sha256_file(os.path.join(DATA, fname))
    ok = actual == m.get(field)
    print(f"asset {fname}: {'OK' if ok else 'MISMATCH'}")
    if not ok:
        fail.append(fname)

# 4) 17 候选文件哈希
fm = json.load(open(os.path.join(DATA, "v3_2_2_candidate_freeze_manifest.json"), encoding="utf-8"))
mm = 0
for rel, recorded in fm["files_sha256"].items():
    if sha256_file(os.path.join(BASE, rel.replace("/", os.sep))) != recorded.lower():
        mm += 1
        fail.append(rel)
print(f"candidate files: {len(fm['files_sha256']) - mm}/{len(fm['files_sha256'])} match")

# 5) 结果文件不得已存在
for fname in ("final_blind_v3_eval_results.json", "final_blind_v3_execution_manifest.json"):
    exists = os.path.exists(os.path.join(DATA, fname))
    print(f"pre-existing {fname}: {'YES -> STOP' if exists else 'no'}")
    if exists:
        fail.append("pre_existing:" + fname)

if fail:
    print("\n!! 执行前检查失败，立即停止:", fail)
    sys.exit(1)

# 存档执行前哈希
pre = {
    "checked_at": "2026-09-26",
    "blind_v3_sha": blind_sha,
    "blind_v3_manifest_sha": sha256_file(os.path.join(DATA, "final_blind_set_v3_manifest.json")),
    "candidate_freeze_manifest_sha": sha256_file(os.path.join(DATA, "v3_2_2_candidate_freeze_manifest.json")),
    "candidate_files_sha": {rel: sha256_file(os.path.join(BASE, rel.replace("/", os.sep)))
                            for rel in fm["files_sha256"]},
    "blind_assets_sha": {fname: sha256_file(os.path.join(DATA, fname)) for fname in assets.values()},
    "evaluator_sha_before": None,
}
print("\n执行前检查全部通过。")
json.dump(pre, open(os.path.join(DATA, "_blindv3_exec_pre_hashes.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
