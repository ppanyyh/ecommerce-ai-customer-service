# -*- coding: utf-8 -*-
"""V3.2.2 最终阶段一 · 步骤一：核验候选冻结状态（只读哈希计算，不导入检索器/服务/模型）"""
import hashlib
import json
import io
import sys
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


manifest_path = os.path.join(DATA, "v3_2_2_candidate_freeze_manifest.json")
manifest = json.load(open(manifest_path, encoding="utf-8"))

print("=== 候选冻结核验 ===")
print("manifest自身SHA-256:", sha256(manifest_path))

mismatch = []
computed = {}
for rel, recorded in manifest["files_sha256"].items():
    p = os.path.join(BASE, rel.replace("/", os.sep))
    actual = sha256(p)
    computed[rel] = actual
    ok = actual == recorded.lower()
    print(f"  {rel}: {'OK' if ok else 'MISMATCH(' + actual[:12] + ')'}")
    if not ok:
        mismatch.append(rel)

print("mismatch 数:", len(mismatch))
if mismatch:
    print("!! 存在不一致，按指令立即停止")
    sys.exit(1)

# 记录关键资产 SHA
print("\n=== 关键资产 SHA ===")
for rel in ["data/knowledge_chunks.jsonl", "data/index_manifest.json",
            "data/business_capability_catalog.json", "risk_levels.py"]:
    print(f"  {rel}: {computed[rel]}")

print("\n=== 标志位核验 ===")
flags = {
    "all_match": manifest.get("all_match"),
    "old_blind_v1_reexecuted": manifest.get("old_blind_v1_reexecuted"),
    "old_blind_v2_reexecuted": manifest.get("old_blind_v2_reexecuted"),
    "final_blind_v3_created": manifest.get("final_blind_v3_created"),
    "final_blind_v3_executed": manifest.get("final_blind_v3_executed"),
    "deepseek_calls_total": manifest.get("deepseek_calls_total"),
}
print(json.dumps(flags, ensure_ascii=False, indent=2))

checks = [
    flags["all_match"] is True,
    flags["old_blind_v1_reexecuted"] is False,
    flags["old_blind_v2_reexecuted"] is False,
    flags["final_blind_v3_created"] is False,
    flags["final_blind_v3_executed"] is False,
    flags["deepseek_calls_total"] == 0,
]
if not all(checks):
    print("!! 标志位核验失败，按指令立即停止")
    sys.exit(1)

# 保存核验结果供后续清单引用
result = {
    "verified_at": "2026-09-26",
    "manifest_sha256": sha256(manifest_path),
    "all_17_files_match": True,
    "files_sha256_computed": computed,
    "flags": flags,
}
out = os.path.join(DATA, "_blindv3_precheck_candidate.json")
json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n核验通过，结果已存:", os.path.basename(out))
