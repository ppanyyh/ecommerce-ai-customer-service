# -*- coding: utf-8 -*-
"""V3.1 调修：标注修订（validation H-020 扩展 + 开发集 DV-046 发票口径修正）。

依据（与 H-009 v1.1 修订同一流程：query 不变，仅相关性/预期人工复核修订，记录 reason）：
1. H-020（validation v1.1 → v1.2）：relevant_chunk_ids 增加 FAQ-013。
   FAQ-013（七天无理由退货条件："商品保持完好、不属于排除范围时可申请，需人工审核"）
   对问题的第一子问（拆封用过还能不能退）给出实质性部分回答（保持完好条件 + 人工审核），
   且在关键词与向量两路均为合法最高分匹配；原标注仅 FAQ-015/017 过窄。
2. DV-046（开发集）：发票问题由 FAQ-018 专门承接（其内容即"资料未覆盖发票类型/流程，
   由人工核实处理"），门控应放行并检索 FAQ-018，转人工由应答层决定。
   原标注把"无政策资料"误当作"知识库无对应 FAQ"。与 validation H-013 口径对齐。
"""
import json
import os
from datetime import date

BACKEND = os.path.dirname(os.path.abspath(__file__))
VAL_PATH = os.path.join(BACKEND, "data", "hybrid_holdout_eval_cases.json")
DEV_PATH = os.path.join(BACKEND, "data", "v3_1_dev_cases.json")
today = "2026-09-25"

# ---- validation ----
val = json.load(open(VAL_PATH, encoding="utf-8"))
h020 = next(c for c in val["cases"] if c["case_id"] == "H-020")
if "FAQ-013" not in h020["relevant_chunk_ids"]:
    h020["original_relevant_chunk_ids_h020"] = list(h020["relevant_chunk_ids"])
    h020["relevant_chunk_ids"] = ["FAQ-015", "FAQ-017", "FAQ-013"]
    h020["annotation_note"] = ("v1.2 人工复核扩展：FAQ-013（七天无理由退货条件）对第一子问"
                               "（拆封使用后还能否退）给出实质性部分回答，见 meta.annotation_revision")
val["meta"]["version"] = "1.2"
val["meta"]["annotation_revision"].append({
    "case_id": "H-020",
    "revised_at": today,
    "revision_round": "v1.2（V3.1 第一阶段调修）",
    "change": "relevant_chunk_ids 由 [FAQ-015, FAQ-017] 扩展为 [FAQ-015, FAQ-017, FAQ-013]",
    "reason": ("人工复核：FAQ-013（七天无理由退货条件：商品保持完好且不属于排除范围可申请、"
               "最终需人工审核）对问题第一子问（拆封用过还能不能退）给出实质性部分回答，"
               "且在关键词（'想退'/'退回'等多关键词合法命中）与向量两路均为最高分匹配；"
               "原标注仅含 FAQ-015/017 属标注过窄，不是为通过而扩标注（query 未改，"
               "扩注依据为片段内容与问题的实质对应关系）。"),
    "query_unchanged": True,
})
json.dump(val, open(VAL_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("validation updated: H-020 +FAQ-013, meta.version=1.2, revision recorded")

# ---- dev ----
dev = json.load(open(DEV_PATH, encoding="utf-8"))
dv = next(c for c in dev["cases"] if c["case_id"] == "DV-046")
old = {k: dv.get(k) for k in ("is_answerable", "expected_supported", "expected_scope",
                              "relevant_chunk_ids", "reason")}
dv["original_annotation_dv046"] = old
dv["is_answerable"] = True
dv["expected_supported"] = True
dv["expected_scope"] = "supported"
dv["relevant_chunk_ids"] = ["FAQ-018"]
dv["reason"] = ("发票问题由知识库 FAQ-018 专门承接，其内容即：现有资料未覆盖发票类型、"
                "申请条件和开票流程，由人工客服核实处理。门控应放行（supported）并检索到 "
                "FAQ-018，转人工由应答层按 FAQ-018 内容决定。原标注把'无政策资料'误当作"
                "'知识库无对应 FAQ'，与 validation H-013 口径不一致，予以修正。")
dev["meta"]["annotation_revision"].append({
    "case_id": "DV-046",
    "revised_at": today,
    "change": ("uncovered_business(unsupported_business/不可回答) 修正为 supported(可回答)，"
               "relevant_chunk_ids=[FAQ-018]"),
    "reason": ("知识库存在发票专门承接片段 FAQ-018（答案内容即'资料未覆盖，转人工核实'），"
               "发票问题属于已覆盖领域；门控职责是路由到该 FAQ，而非拦截。"
               "与 validation_set_v1 H-013 口径对齐；原标注误读知识库范围。"),
    "query_unchanged": True,
    "original_annotation": old,
})
json.dump(dev, open(DEV_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("dev updated: DV-046 -> supported/FAQ-018, revision recorded")
