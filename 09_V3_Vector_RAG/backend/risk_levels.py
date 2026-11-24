# -*- coding: utf-8 -*-
"""V3.2.2 统一风险等级定义（单一公共来源，禁止各模块自定义顺序）。

背景缺陷：main.py 与 v3_retrieval_adapter.py 各自定义 _RISK_ORDER 且顺序相反
（("低","中","高") 与 ("高","中","低")），均配合 max(..., key=index) 使用，
adapter 的反序会在多风险候选中选择**较低**风险，且 V3 结构化意图识别出的
高风险规则等级（如 HR-07=高）未参与最终风险兜底。

本模块是唯一权威定义：
- RISK_SCORE        显式映射（低=0 < 中=1 < 高=2），杜绝顺序书写歧义；
- normalize_risk()  非法值归一为"低"（不抛异常，兼容模型/外部输入）；
- max_risk()        取多个风险等级中的最高（支持 *args 与可迭代）；
- kinds_risk_level()按转人工类型（HR-01..08）对应规则等级取最高，供
  retrieval 层把规则等级传回 main 的风险兜底链。

规则等级依据（knowledge_chunks.jsonl 原始规则，不得通过修改知识片段降低）：
HR-01=高 HR-02=高 HR-03=中 HR-04=中 HR-05=高 HR-06=高 HR-07=高 HR-08=高
"""

# 风险等级 -> 分数（显式映射，唯一权威来源）
RISK_SCORE = {"低": 0, "中": 1, "高": 2}

_SCORE_TO_RISK = {v: k for k, v in RISK_SCORE.items()}
_LEVELS_DESC = ("高", "中", "低")

# 正式规则等级映射（与 knowledge_chunks.jsonl / knowledge_base.json 一致）
RULE_RISK_LEVELS = {
    "HR-01": "高",  # 投诉赔偿
    "HR-02": "高",  # 金额争议
    "HR-03": "中",  # 退款催促
    "HR-04": "中",  # 物流停滞
    "HR-05": "高",  # 他人订单
    "HR-06": "高",  # 隐私信息
    "HR-07": "高",  # 超范围承诺
    "HR-08": "高",  # 质量缺陷
}


def normalize_risk(level) -> str:
    """非法/缺失风险等级归一为"低"（不抛异常）。"""
    return level if level in RISK_SCORE else "低"


def max_risk(*levels) -> str:
    """取多个风险等级中的最高；支持 max_risk("中", "高") 或传入可迭代。
    None/空值/非法值自动忽略；全部非法时返回"低"。"""
    flat = []
    for lv in levels:
        if lv is None:
            continue
        if isinstance(lv, (list, tuple, set, frozenset)):
            flat.extend(lv)
        else:
            flat.append(lv)
    scores = [RISK_SCORE[normalize_risk(lv)] for lv in flat if lv is not None]
    return _SCORE_TO_RISK[max(scores)] if scores else "低"


def kinds_risk_level(kinds, rule_levels=None) -> str:
    """按转人工类型（HR-01..08）返回最高规则等级；无有效命中返回"低"。
    rule_levels 供调用方注入自定义映射（默认 RULE_RISK_LEVELS）。"""
    mapping = rule_levels or RULE_RISK_LEVELS
    levels = [mapping[k] for k in (kinds or []) if k in mapping]
    return max_risk(levels) if levels else "低"
