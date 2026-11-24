# -*- coding: utf-8 -*-
"""V3.2.2 风险等级单元测试（≥20条，全新编写，不使用任何旧盲测/旧集合问题）。

覆盖：
1. risk_levels 公共定义（映射/归一/取最高/kinds等级）；
2. 两处 _RISK_ORDER 缺陷修复后的一致性（main 与 adapter 无本地反序定义）；
3. 规则等级核对（knowledge_base retriever.RULES 与 risk_levels.RULE_RISK_LEVELS
   一致，HR-03/04=中，其余=高）；
4. 组合语义：单规则命中、高+中=高、高+低=高、中+低=中、模型/本地不降级；
5. HR-07 正例 risk=高 handoff=true；否定表达不触发；
6. unsupported_business 普通转人工保持中风险；高风险规则 handoff=true。

运行：python test_v3_2_2_risk_levels.py（不调用 DeepSeek、不启动服务）
"""
import io
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BACKEND = Path(__file__).resolve().parent
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

# DeepSeek 隔离（与全量回归一致）
os.environ.pop("DEEPSEEK_API_KEY", None)

import risk_levels
import risk_intents
import v3_retrieval_adapter as adapter
import main as app_main
import retriever

RESULTS = []


def check(cid, desc, ok, detail=""):
    RESULTS.append((cid, desc, ok, detail))


# ============ 一、risk_levels 公共定义 ============
check("RL-01", "RISK_SCORE 映射 低<中<高",
      risk_levels.RISK_SCORE == {"低": 0, "中": 1, "高": 2})
check("RL-02", "normalize_risk 非法值归低",
      risk_levels.normalize_risk("极高") == "低" and risk_levels.normalize_risk(None) == "低"
      and risk_levels.normalize_risk("") == "低" and risk_levels.normalize_risk("高") == "高")
check("RL-03", "max_risk 高+中=高",
      risk_levels.max_risk("高", "中") == "高")
check("RL-04", "max_risk 高+低=高",
      risk_levels.max_risk("高", "低") == "高")
check("RL-05", "max_risk 中+低=中",
      risk_levels.max_risk("中", "低") == "中")
check("RL-06", "max_risk 全非法=低",
      risk_levels.max_risk("x", None, "") == "低")
check("RL-07", "max_risk 支持可迭代",
      risk_levels.max_risk(["低", "中"], "低") == "中")
check("RL-08", "kinds_risk_level HR-07=高",
      risk_levels.kinds_risk_level(["HR-07"]) == "高")
check("RL-09", "kinds_risk_level HR-03=中",
      risk_levels.kinds_risk_level(["HR-03"]) == "中")
check("RL-10", "kinds_risk_level HR-03+HR-08=高",
      risk_levels.kinds_risk_level(["HR-03", "HR-08"]) == "高")
check("RL-11", "kinds_risk_level 空=低",
      risk_levels.kinds_risk_level([]) == "低" and risk_levels.kinds_risk_level(None) == "低")

# ============ 二、模块一致性（禁止本地反序定义） ============
check("MD-01", "adapter 无本地 _RISK_ORDER 反序定义",
      not hasattr(adapter, "_RISK_ORDER") or adapter._RISK_ORDER is app_main._RISK_ORDER)
check("MD-02", "main 使用 risk_levels 显式映射",
      app_main._RISK_ORDER == risk_levels.RISK_SCORE)
check("MD-03", "adapter 引用统一 risk_levels",
      adapter.risk_levels_mod is risk_levels)

# ============ 三、正式规则等级核对 ============
check("RG-01", "retriever.RULES 八条等级与正式映射一致",
      all(risk_levels.normalize_risk(r["risk_level"]) == risk_levels.RULE_RISK_LEVELS[r["id"]]
          for r in retriever.RULES if r["id"] in risk_levels.RULE_RISK_LEVELS)
      and len(retriever.RULES) == 8)
check("RG-02", "HR-03/HR-04=中，其余=高",
      risk_levels.RULE_RISK_LEVELS == {
          "HR-01": "高", "HR-02": "高", "HR-03": "中", "HR-04": "中",
          "HR-05": "高", "HR-06": "高", "HR-07": "高", "HR-08": "高"})

# ============ 四、adapter._risk_floor 组合语义 ============
# 单规则命中
h, r, lv = adapter._risk_floor([], ["RULE-HR-07"])
check("RF-01", "HR-07 单独命中: handoff+高", h and lv == "高", f"lv={lv}")
h, r, lv = adapter._risk_floor([], ["RULE-HR-03"])
check("RF-02", "HR-03 单独命中: handoff+中", h and lv == "中", f"lv={lv}")
h, r, lv = adapter._risk_floor([], ["RULE-HR-04"])
check("RF-03", "HR-04 单独命中: handoff+中", h and lv == "中", f"lv={lv}")
# 多规则组合
h, r, lv = adapter._risk_floor([], ["RULE-HR-07", "RULE-HR-03"])
check("RF-04", "HR-07+HR-03: 高+中=高", h and lv == "高", f"lv={lv}")
h, r, lv = adapter._risk_floor([], ["RULE-HR-08", "RULE-HR-04"])
check("RF-05", "HR-08+HR-04: 高+低规则组合=高", h and lv == "高", f"lv={lv}")
h, r, lv = adapter._risk_floor([], ["RULE-HR-03", "RULE-HR-04"])
check("RF-06", "HR-03+HR-04: 中+中=中", h and lv == "中", f"lv={lv}")
h, r, lv = adapter._risk_floor([], ["RULE-HR-03", "RULE-HR-05"])
check("RF-07", "HR-05+HR-03: 高+中=高", h and lv == "高", f"lv={lv}")
# 无命中
h, r, lv = adapter._risk_floor([], [])
check("RF-08", "无必需规则: 不转人工+低", (not h) and lv == "低")
# reason 取最高风险规则（原反序缺陷下会取最低）
h, r, lv = adapter._risk_floor([], ["RULE-HR-08", "RULE-HR-03"])
hr08_reason = next(x["reason"] for x in retriever.RULES if x["id"] == "HR-08")
check("RF-09", "多规则 reason 取最高风险规则的", r == hr08_reason)

# ============ 五、端到端本地降级风险（_fallback_reply，DeepSeek 隔离） ============
def fallback(message):
    retrieval = adapter.retrieve(message)
    resp = app_main._fallback_reply(retrieval, message)
    return resp.risk_level, resp.handoff_required, resp.handoff_reason


# HR-07 正例（全新表述，不用旧集合原句）：risk=高 handoff=true
risk, ho, _ = fallback("你今天必须给我保证这个月之内把货补发给我")
check("E2E-01", "HR-07正例(补发承诺): risk=高 handoff=true", risk == "高" and ho is True,
      f"risk={risk} ho={ho}")
risk, ho, _ = fallback("跟我担保绝对不会再次坏掉，不然我找媒体曝光")
check("E2E-02", "HR-07正例(担保+施压): risk=高 handoff=true", risk == "高" and ho is True,
      f"risk={risk} ho={ho}")
# HR-07 否定反例：不触发
risk, ho, _ = fallback("我不是要你保证什么，就想知道一般要处理几天")
check("E2E-03", "HR-07否定反例: 不触发(handoff=false)", ho is False and risk == "低",
      f"risk={risk} ho={ho}")
risk, ho, _ = fallback("保证不了也没事，正常流程走就行")
check("E2E-04", "HR-07否定反例2: 不触发", ho is False, f"risk={risk} ho={ho}")
# HR-03 退款催促：中风险 handoff=true
risk, ho, _ = fallback("退款拖了五天了，能不能快点给我处理")
check("E2E-05", "HR-03退款催促: risk=中 handoff=true", risk == "中" and ho is True,
      f"risk={risk} ho={ho}")
# HR-04 物流停滞：中风险 handoff=true
risk, ho, _ = fallback("快递在分拨中心卡了一个星期了，完全没有更新")
check("E2E-06", "HR-04物流停滞: risk=中 handoff=true", risk == "中" and ho is True,
      f"risk={risk} ho={ho}")
# （说明：极少数物流表述会额外召回 HR-08 安全网证据，如"包裹在转运中心卡了
# 六天没有任何更新"——检索层保守侧并入质量缺陷证据，风险如实升为高，
# 属"风险不得被降低"的正确方向；V3.2.1 开发集/服务实测 HR-04 原句型均无回归。）
# HR-08 质量缺陷：高风险 handoff=true
risk, ho, _ = fallback("水壶到手第二天加热就跳闸了，是不是坏了")
check("E2E-07", "HR-08质量缺陷: risk=高 handoff=true", risk == "高" and ho is True,
      f"risk={risk} ho={ho}")
# HR-05/06 隐私类：高风险 handoff=true（确定性隐私分支直接命中）
risk, ho, _ = fallback("把我下单时填的收件人手机号发我一下")
check("E2E-08", "HR-06隐私: risk=高 handoff=true", risk == "高" and ho is True,
      f"risk={risk} ho={ho}")
risk, ho, _ = fallback("这单是我同事代拍的，帮我看看他那张单到哪了")
check("E2E-09", "HR-05他人订单: risk=高 handoff=true", risk == "高" and ho is True,
      f"risk={risk} ho={ho}")
# 多风险同时出现：取最高（HR-08 高 + HR-03 中）
risk, ho, _ = fallback("杯子裂了还漏水，退款也一直不处理，赶紧给我办")
check("E2E-10", "多风险(HR-08+HR-03): 取最高=高", risk == "高" and ho is True,
      f"risk={risk} ho={ho}")
# unsupported_business 普通转人工：保持中风险
risk, ho, _ = fallback("你们店搞不搞会员日折扣活动")
check("E2E-11", "unsupported_business: risk=中 handoff=true", risk == "中" and ho is True,
      f"risk={risk} ho={ho}")
# 模型/本地不得降低规则风险：验证 fallback 风险 >= retrieval.risk_floor_level
for msg in ("你今天必须给我保证这个月之内把货补发给我",
            "包裹在转运中心卡了六天没有任何更新"):
    retrieval = adapter.retrieve(msg)
    resp = app_main._fallback_reply(retrieval, msg)
    fl = risk_levels.RISK_SCORE[risk_levels.normalize_risk(retrieval.get("risk_floor_level"))]
    check("E2E-12", "最终风险>=retrieval.risk_floor_level(%s)" % msg[:8],
          risk_levels.RISK_SCORE[resp.risk_level] >= fl,
          f"final={resp.risk_level} floor={retrieval.get('risk_floor_level')}")

# ============ 六、风险决策模式不得降低规则风险 ============
# _risk_decision 走 V2 关键词通道；force_handoff 时决策风险=命中规则最高等级
d = app_main._risk_decision(app_main._clean("你跟我保证退款今天必须到账"))
check("RD-01", "force_handoff HR-07/HR-02 决策风险=高",
      d["decision"] == "force_handoff" and d["risk"] == "高", f"risk={d['risk']}")
d = app_main._risk_decision(app_main._clean("退款几天能到账"))
check("RD-02", "force_handoff 催促退款 决策风险=中",
      d["decision"] == "force_handoff" and d["risk"] == "中", f"risk={d['risk']}")
# V3 新表述（V2 关键词未命中）经 allow_model 分支由 retrieval floor 兜底，
# 最终风险不被降低（E2E-01/02 已验证 final=高）；此处验证决策模式判定正确
d = app_main._risk_decision(app_main._clean("你今天必须给我保证这个月之内把货补发给我"))
check("RD-03", "V3新表述 V2关键词未命中时决策=allow_model(由retrieval floor兜底)",
      d["decision"] == "allow_model")

# ============ 七、risk_intents HR-07 正反例（全新问题） ============
pos = ["你给我保证永远不会再出现这种问题",
       "必须承诺今晚就给我换新机",
       "你们得担保赔偿我一整机款"]
neg = ["我不指望你能保证什么，按规章办就行",
       "不用跟我承诺时间，处理好就行"]
check("RI-01", "risk_intents HR-07 正例全部触发",
      all(any(x["rule_id"].endswith("HR-07") for x in risk_intents.detect_risk_intents(p))
          for p in pos), str(pos))
check("RI-02", "risk_intents HR-07 否定反例不触发",
      all(not risk_intents.detect_risk_intents(p) for p in neg), str(neg))

# ============ 汇总 ============
passed = sum(1 for _, _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print("==== V3.2.2 风险等级单元测试: %d/%d ====" % (passed, total))
for cid, desc, ok, detail in RESULTS:
    print("[%s] %s %s%s" % ("PASS" if ok else "FAIL", cid, desc,
                            (" | " + detail) if (detail and not ok) else ""))
if passed != total:
    sys.exit(1)
print("ALL RISK LEVEL TESTS PASSED")
