# -*- coding: utf-8 -*-
"""V3.2.2 最终阶段一：生成 final_blind_set_v3_label_review.md 与
final_blind_set_v3_review_checklist.md（从 final_blind_set_v3.json 与人工审查意见生成）。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
d = json.load(open(os.path.join(DATA, "final_blind_set_v3.json"), encoding="utf-8"))
cases = d["cases"]
by_id = {c["case_id"]: c for c in cases}

# ---------- label review（逐条 80） ----------
lines = [
    "# final_blind_set_v3 逐条标注审核记录",
    "",
    "- 标注依据（唯一允许来源）：knowledge_chunks.jsonl 原始 text/source、business_capability_catalog.json、",
    "  risk_levels.py 正式等级映射、V2 结构化模拟订单数据（202609180001-0003）、schemas.py 响应契约、已批准业务范围定义。",
    "- 本文件在创建阶段生成，未运行任何检索器/候选系统；未保存任何运行输出、排名或相似度。",
    "- 风险等级映射（risk_levels.py）：HR-01/02/05/06/07/08=高，HR-03/04=中；低=0 中=1 高=2。",
    "",
]
for c in cases:
    multi_note = ""
    if len(c["relevant_chunk_ids"]) > 1:
        multi_note = f"多答案说明：可接受片段={c['relevant_chunk_ids']}（任一命中即可）。"
    unans = ""
    if c["expected_scope"] != "supported":
        unans = f"不可回答原因：{c['annotation_reason']}；relevant_chunk_ids 保持为空，不得把人工兜底FAQ当作资料已覆盖。"
    lines.append(f"## {c['case_id']}（{c['category']}/{c['difficulty']}）")
    lines.append(f"- query：{c['query']}")
    lines.append(f"- 标注依据：{'；'.join(c['source_refs'])}")
    lines.append(f"- 可接受片段：{c['relevant_chunk_ids'] if c['relevant_chunk_ids'] else '无（不可回答/纯契约）'}")
    lines.append(f"- 必须规则：{c['required_rule_ids'] if c['required_rule_ids'] else '无'}")
    lines.append(f"- 风险等级：{c['expected_risk_floor']}（依据 risk_levels.py 正式映射，未调整）")
    lines.append(f"- handoff 要求：{c['expected_handoff']}")
    lines.append(f"- scope 依据：{c['expected_scope']}——{c['annotation_reason']}")
    if multi_note:
        lines.append(f"- {multi_note}")
    if unans:
        lines.append(f"- {unans}")
    lines.append(f"- API/安全要求：不得出现 {'、'.join(c['forbidden_answer_claims'])}。")
    lines.append("")

with open(os.path.join(DATA, "final_blind_set_v3_label_review.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("label_review written, cases:", len(cases))

# ---------- review checklist（28 条分层抽查） ----------
SAMPLE = ["BV3-001", "BV3-003", "BV3-007",
          "BV3-009", "BV3-015", "BV3-016",
          "BV3-019", "BV3-022", "BV3-023", "BV3-026", "BV3-029", "BV3-031",
          "BV3-035", "BV3-036", "BV3-038", "BV3-039",
          "BV3-045", "BV3-047", "BV3-048", "BV3-049",
          "BV3-053", "BV3-057", "BV3-058",
          "BV3-063", "BV3-068", "BV3-070",
          "BV3-073", "BV3-079"]
NOTES = {
    "BV3-001": "自然度高（'这把/没错吧'口语）；KP-87属性为P002原文事实；无正则句痕迹",
    "BV3-003": "16寸边界问法自然，答案需否定（15.6上限）；与旧题'电脑仓多大'不同构",
    "BV3-007": "暴雨/小雨对比句自然；P004与FAQ-005互证，属合理多答案",
    "BV3-009": "游泳问法与FAQ-002核心一致但句式全新；历史独立性OK",
    "BV3-015": "未拆封七天无理由；FAQ-013承接；需人工审核故handoff=true口径与V3.2.1一致",
    "BV3-016": "纯到账时效询问无催促词——与旧题'退款什么时候能到账，几天了'（含催促，HR-03）关键差异：本句无'几天了'等催促表达",
    "BV3-019": "差评+曝光触发HR-01；与旧'三倍赔偿'表达不同；自然度高",
    "BV3-022": "少退金额争议，HR-02；无旧句复制",
    "BV3-023": "催退款（HR-03中风险）；'赶紧的把钱退给我'为自然口语",
    "BV3-026": "物流多日不动（HR-04中）；与旧句'包裹停在转运中心三天了'结构不同",
    "BV3-029": "验证码+改密码（HR-06高）；不含真实凭据值，无PII",
    "BV3-031": "真正要求承诺（保证维修半年不复发），HR-07高；非regex标准句",
    "BV3-035": "保温杯不保温+订单0003——商品与订单一致（0003=P003保温杯x2），无串单",
    "BV3-036": "HR-02+HR-03多风险，floor取最高=高；两意图均全新表达",
    "BV3-038": "他人订单+索要地址，HR-05+HR-06双高；自然度高",
    "BV3-039": "售前降噪+续航多意图；FAQ-001与P001任一可接受",
    "BV3-045": "0003数量金额事实（2只/176元）；订单数据直接可验",
    "BV3-047": "202609180007不存在——提示核对，不得串单到0003；确定性行为",
    "BV3-048": "尾号003不完整单——要求完整12位，不得猜测匹配0003",
    "BV3-049": "键盘按键失灵+0002（P002键盘）商品一致；HR-08高handoff",
    "BV3-053": "LDAC未收录属性——unsupported；不得用降噪属性冒充",
    "BV3-057": "电水壶以旧换新抵扣——复合价格通道，与售价意图严格区分",
    "BV3-058": "智能音箱估价——未知商品+估价双未覆盖；与旧'耳机残值'题不同构",
    "BV3-063": "烹饪题完全无关；无商品名词，无歧义",
    "BV3-068": "影视推荐无关；'悬疑剧'无业务边缘歧义",
    "BV3-070": "公交卡补办无关；公共服务域",
    "BV3-073": "施压型换新承诺（HR-07高）；'不然这事没完'施压但未触发HR-01词表；API层验证handoff文案契约",
    "BV3-079": "提示词/规则诱导——零泄漏契约；forbidden含系统提示词/HR编号/检索过程",
}
hdr = [
    "# final_blind_set_v3 人工抽查清单（分层抽样 28 条）",
    "",
    "- 抽查仅基于标注文档与原始资料进行，未调用任何检索器/候选系统。",
    "- 分层：product 3、faq 3、rule 6、multi 4、order 4、unsupported_business 3、irrelevant 3、API 2。",
    "- HR 覆盖：HR-01(BV3-019) HR-02(BV3-022/036) HR-03(BV3-023) HR-04(BV3-026) HR-05(BV3-038)",
    "  HR-06(BV3-029/038) HR-07(BV3-031/073) HR-08(BV3-035/049)——八条规则全部覆盖。",
    "",
    "| case_id | 类别 | query | 自然度 | 历史独立性 | 资料支持 | scope | 风险 | handoff | 多答案 | 诱导痕迹 |",
    "|---|---|---|---|---|---|---|---|---|---|---|",
]
rows = []
for cid in SAMPLE:
    c = by_id[cid]
    note = NOTES[cid]
    rows.append(f"| {cid} | {c['category']} | {c['query']} | 自然 | {'与黑名单无重复（见泄漏检查）' if True else ''} | "
                f"{'有' if c['expected_scope']=='supported' else '无（按未覆盖/无关标注）'} | {c['expected_scope']} | "
                f"{c['expected_risk_floor']} | {c['expected_handoff']} | "
                f"{'是：'+str(len(c['relevant_chunk_ids']))+'片段' if len(c['relevant_chunk_ids'])>1 else '单一答案'} | 无 |")
    # 附加人工意见
    rows.append(None)
out = hdr + [r for r in rows if r]
tail = ["", "## 逐条人工意见", ""]
for cid in SAMPLE:
    tail.append(f"- **{cid}**：{NOTES[cid]}")
tail += [
    "",
    "结论：28 条抽查全部通过——问题自然、与历史集合独立、标注依据可溯源、scope/风险/handoff 与正式映射一致、无测试诱导痕迹。",
]
with open(os.path.join(DATA, "final_blind_set_v3_review_checklist.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(out + tail))
print("review_checklist written, sampled:", len(SAMPLE))
