# -*- coding: utf-8 -*-
"""V3.1 第二阶段：标注口径定稿的数据文件变更（用户批准后执行）。

1. DV-046 恢复为 unsupported_business（用户不批准发票改 supported 的标注修订）。
2. validation 双版本拆分（不再使用无版本文件继续修订）：
   - hybrid_holdout_eval_cases_v1_1_frozen.json   — 依据 original_relevant_chunk_ids_h020
     反向恢复的 v1.1 等效版本（重建版），冻结不可修改；
   - hybrid_holdout_eval_cases_v1_2_reviewed.json — 保留 H-020 修订的审查版，
     明确标记为 annotation-corrected exploratory evaluation。
3. 开发集 meta 补充独立性声明（开发集、已迭代、非盲测集）。

不修改无版本的 hybrid_holdout_eval_cases.json（保留现状，此后以版本文件为准）。
输出：各文件 SHA-256。
"""
import copy
import hashlib
import json
import os

BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BACKEND, "data")


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print("written:", os.path.basename(path), "sha256:", sha256(path))


# ---------- 1. DV-046 恢复 ----------
dev_path = os.path.join(DATA, "v3_1_dev_cases.json")
dev = json.load(open(dev_path, encoding="utf-8"))
dv46 = next(c for c in dev["cases"] if c["case_id"] == "DV-046")
before = {k: dv46.get(k) for k in ("expected_supported", "expected_scope", "relevant_chunk_ids", "is_answerable")}
dv46["is_answerable"] = False
dv46["expected_supported"] = False
dv46["expected_scope"] = "unsupported_business"
dv46["relevant_chunk_ids"] = []
if dv46.get("required_rule_ids") is None:
    dv46["required_rule_ids"] = []
assert dv46["category"] == "uncovered_business", "DV-046 category 应保持 uncovered_business"
dev["meta"].setdefault("annotation_revision", []).append({
    "case_id": "DV-046",
    "revised_at": "2026-09-25 (V3.1 Phase 2)",
    "change": "恢复为 is_answerable=false / expected_supported=false / expected_scope=unsupported_business / relevant_chunk_ids=[]（撤销阶段一将发票改 supported 的修订）",
    "reason": "用户审核不批准：FAQ-018 仅说明现有资料未覆盖发票类型/条件/流程并给出转人工步骤，不构成发票政策答案；按 V3.1 三分类属业务相关但资料未覆盖。发票口径为 V3.1 有意进行的业务语义变更。",
    "before_phase2_revert": before,
    "approved_by": "user (V3.1 Phase 2 指令 第二节)",
})
dev["meta"]["set_nature"] = (
    "本集合是开发集（development set）：允许用于调试、阈值校准与失败迭代，"
    "在多轮评测中根据失败结果修订过标注（见 annotation_revision）并据此调整过实现；"
    "其结果只证明开发集拟合通过，不能作为最终泛化成绩，不得称为盲测集。"
    "最终泛化评估须另建独立 final blind set（本阶段未创建、未运行）。"
)
dump(dev_path, dev)

# ---------- 2. validation 双版本 ----------
cur_path = os.path.join(DATA, "hybrid_holdout_eval_cases.json")
cur = json.load(open(cur_path, encoding="utf-8"))

# v1.2 reviewed（保留 H-020 修订）
v12 = copy.deepcopy(cur)
v12["meta"]["version"] = "1.2"
v12["meta"]["evaluation_status"] = (
    "annotation-corrected exploratory evaluation：H-020 的 relevant_chunk_ids 修订"
    "（+FAQ-013，部分相关性）发生在看到检索结果之后，本版本结果仅作探索性参考，"
    "不参与最终盲测成绩；H-013（发票）保持原始标注不变，其在新业务口径下的偏差"
    "作为 V3.1 有意进行的业务语义变更单独报告，不改标注。"
)
v12["meta"]["note_v1_1_preserved"] = "原始 v1.1 标注经 original_relevant_chunk_ids_h020 恢复至 hybrid_holdout_eval_cases_v1_1_frozen.json（冻结不可修改）。"
v12_path = os.path.join(DATA, "hybrid_holdout_eval_cases_v1_2_reviewed.json")
dump(v12_path, v12)

# v1.1 frozen（反向恢复，冻结）
v11 = copy.deepcopy(cur)
h020 = next(c for c in v11["cases"] if c["case_id"] == "H-020")
orig_ids = h020.get("original_relevant_chunk_ids_h020")
assert orig_ids, "缺少 original_relevant_chunk_ids_h020，无法恢复 v1.1"
h020["relevant_chunk_ids"] = list(orig_ids)
del h020["original_relevant_chunk_ids_h020"]
v11["meta"]["annotation_revision"] = [
    r for r in v11["meta"].get("annotation_revision", []) if r.get("case_id") != "H-020"
]
v11["meta"]["version"] = "1.1"
v11["meta"]["evaluation_status"] = (
    "原始 v1.1 口径（H-020 = ['FAQ-015','FAQ-017']）。本文件是由 v1.2 依据"
    " original_relevant_chunk_ids_h020 字段反向恢复的重建版（非原始字节文件），"
    "恢复后冻结：此后任何情况下不得修改本文件。"
)
v11_path = os.path.join(DATA, "hybrid_holdout_eval_cases_v1_1_frozen.json")
dump(v11_path, v11)

# ---------- 3. 汇总 ----------
print("\n无版本文件保留现状（未修改）:", os.path.basename(cur_path), "sha256:", sha256(cur_path))
print("\n=== 双口径文件 SHA-256（写入冻结清单与报告） ===")
print("v1_1_frozen   :", sha256(v11_path))
print("v1_2_reviewed :", sha256(v12_path))
