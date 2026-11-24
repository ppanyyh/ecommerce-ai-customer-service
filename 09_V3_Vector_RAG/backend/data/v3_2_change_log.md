# V3.2 第一阶段变更日志（v3_2_change_log.md）

日期：2026-09-25 ｜ 范围：仅 09_V3_Vector_RAG（backend 及其 data/），未触碰 V2 / frontend / 05_AI_Demo / 旧盲测资产
本阶段性质：开发 + 回归测试。未创建、未运行任何新最终盲测集（blind v3 不存在）。DeepSeek 调用次数：0。

---

## 1. 评测器修复（需求第二节）

### evaluate_final_blind_v2.py
- 计数体系重构：`new_call_counters()` 返回五个独立计数器（http_request_count / adapter_call_count / hybrid_call_count / order_retriever_call_count / deepseek_call_count），替代原来 POST 计数与内部检索计数混用的共享 `call_counter["calls"]`。修复前 B 层 execution manifest 的 per_case_calls_max 会误记为 2（一次 POST + 一次内部检索被同一体系累计）。
- 指标双口径：新增 `union_hit3()`（并集口径，定为正式达标口径）；`rank_metrics` 输出区分 union 正式口径与 coverage 补充口径；summary 同时输出 `union_hit3` 与兼容旧字段名的 `answer_recall3_coverage`。
- 勘误文档：`final_blind_v2_evaluator_errata.md` 记录了上述计数双计的成因、影响面（仅 manifest 计数展示层，原始结果/清单/哈希均不变）与双口径定稿。

### test_final_blind_v2_evaluator.py
- 适配新计数器 API；新增第 14-15 节纯合成单元测试（五计数器独立性、union/coverage 分离、不读取不运行 blind v2）。**52/52 通过**。
- **未用修复后脚本重跑 blind v2**（原始结果文件与执行清单哈希未变，见 §7）。

## 2. 风险意图重构（risk_intents.py，新建）

七类检测器均改为"小函数 + 结构化条件"（对象/动作/语境/组合/排除/否定/已购状态/正反例），可独立测试：
`detect_complaint`、`detect_amount_dispute`、`detect_refund_urge`、`detect_logistics_stall`、`detect_other_order`、`detect_privacy`、`detect_defect`（含售前守卫 `_DEFECT_PRESALE_GUARD`）、`detect_over_promise`；`detect_risk_intents(q)` 汇总。

调试期补词（均为开发集暴露的口语改写，非对旧盲测逐题硬编码）：
- 金额争议：`说好(全额|全款)`、`实际(只退|少退)`、`货款(多付|重复付)`、`多付(一次|一次钱|了)` 等（DV3-026/028 类改写）。
- 他人订单：对象词补 `件/她名下/他名下` 等（DV3-010"她名下那个件"）。
- 泛化质量咨询守卫：`是不是(质量|品质)(不)?好` 确认疑问式不再触发缺陷（修复自带反例"拉链拉不动了是不是质量不好"误判）。
- 自带正反例自测：**19/19 通过**。

## 3. 风险语义安全网（hybrid_retriever_v2.py）

- `_rule_safety_net(query, vec_rule_hits, analysis)`：独立第二通道。启用条件（证据条件）：`vec_sim >= 0.42`（RULE_NET_VEC_SIM）且存在电商信号，且无 supported_intents、无 covered_attributes、HR-08 非售前守卫语境。
- 启用后的规则片段注入 fused 结果（仅当无 required_rule_ids 时）并并入 required_rule_ids；不抢普通 Top-1；启用原因写入 analysis.reasons，不进入面向用户的 answer。

## 4. 业务范围门控重构（query_analyzer.py + business_capability_catalog.json）

### 能力目录（business_capability_catalog.json，catalog_version 1.1）
- known_products P001–P005：covered_attributes 严格源自 kb attributes 原文 + 类别级通用关键词。
- global_covered_intents / uncovered_business_types（含 invoice_policy，注明用户批准口径）/ out_of_scope_topics。
- 调试期补充词条（全部为类别级表述，非逐题硬编码）：P001/P005 充电的拆字表述（充一次电/充满一次电/插多久/电源——"充电"被子数量词隔开时子串匹配失效）、P004 电脑仓（放下/主袋）、全商品"价格"属性、P002 防水等。

### 门控逻辑
- 门控优先级：风险意图 > out_of_scope（irrelevant）> uncovered_business（unsupported_business）> 已知商品+属性覆盖判断 > 泛化质量咨询 > unknown。
- 新增：**未知商品询问检测**（问某个未收录商品的具体属性 → unsupported_business，而非落 unknown 兜底）；**生活闲聊检测**（无电商信号+生活语境 → irrelevant）。
- uncovered intents 扩充/修正：comparison_or_review 收窄（`(跟|和|与|同)...比` 需排除订单修改语境"换成白色款"）、promo_activity、product_care_method、warranty_extension、price_protect、tech_dev 注入词等。

### 已知行为口径变更（与 V3.1 断言冲突，属需求第五节授权）
- V3.1 validation 测试 06 断言"有实体→不门控"；V3.2 需求第五节明确"已知商品+属性询问+目录未覆盖属性→unsupported"。已按 V3.2 口径更新该断言（test_hybrid_v2_validation.py），更新后 **20/20 通过**。这是**有意的行为变更**，非回归。

## 5. 本地降级重构（v3_retrieval_adapter.py + main.py）

- `_from_v3` 返回增加 `matched_texts`（原始片段 text/source/doc_type）、`v3_entity_pids`、`v3_attr_keywords`。
- `compose_local_answer(message, retrieval)`：无 LLM 组稿。
  - 高风险（handoff）：安全模板（索要订单号+凭证），**RULE 片段原文一律不进用户答案**（修复了此前 handoff 场景把"HR-01（投诉与赔偿）：触发条件…"组稿给用户的泄漏）。
  - supported：净化后事实提取组稿——实体单片段策略 + 属性关键词加成（ATTR_BONUS=0.30）；`_sanitize_text` 剥离 chunk id、FAQ-/PRODUCT-/RULE- 前缀、关键词尾注、别名括号。
- main.py `_fallback_reply` non-handoff 分支接入 compose_local_answer（仅 v3 引擎），composed 为 None 时回退通用致歉。

## 6. 检索裁决修复（hybrid_retriever_v2.py）

- **_risk_floor 规则 ID 前缀不匹配 bug（本阶段最关键修复）**：`INTENT_RULE_MAP` 传入 `RULE-HR-01` 带前缀格式，而 `retriever.RULES` 的 id 是 `HR-01`，集合求交恒空 → **所有风险用例 handoff 全部失效**，RULE 原文被组稿进答案（8 条泄漏的共同根因）。修复为两侧统一去前缀。
- 适配器风险下限改为仅"必需规则"（意图通道或安全网启用）触发转人工；Top-K 中偶发规则片段不再单独触发（DV3-035 类误 handoff）。
- 新增**功能确认裁决** `_FUNCTION_CONFIRM_RE`（好使吗/能用吗/灵不灵等）：该场景下不启用实体优先与显式证据裁决，解答型 FAQ 优先（修复 DV3-076 与 PRODUCT-P002 的 epsilon 并列误裁决）。
- 部分订单号识别（适配层，不动冻结的 V2）：`_PARTIAL_ORDER_RE` 识别"后/末四位是 XXXX"（3-5 位口述片段），路由至 V2 结构化订单查询并附带 `v3_scope` 字段（修复 DV3-094 order_route）。

## 7. 评测器（evaluate_v3_2_dev.py）修正

- `_PROMISE_RE` 判定增加否定语境排除（回溯窗口内含"无法由AI保证/不能保证/不承诺"等拒诺表达不记违规，修复 DV3-080/084 拒诺被误判为承诺）。
- rec 初始化补 `required_rule_ids / relevant_chunk_ids / expected_handoff`（KeyError 修复）。

## 8. 开发集标注修订（均语义等价、已记录于 meta，**待用户批准**）

- **DV3-045**：relevant_chunk_ids 由 `["PRODUCT-P004"]` 扩为 `["PRODUCT-P004", "FAQ-005"]`。依据：「背包下雨天背着会湿吗」的 Top-1 FAQ-005（双肩包完全防水吗）与 PRODUCT-P004 同为该问题直接回答，担忧式问法下 FAQ 解答优先是既定裁决设计，原标注过窄。
- **DV3-097**：required_answer_concepts 由 `["不可以", ...]` 修正为 `["防水", "不支持游泳"]`。本地降级回答以「不支持游泳或长时间浸水」表述拒绝，语义等价，原概念"不可以"无法字面验证。

## 9. 冻结与禁改资产状态

- blind v2 三资产（blind set / execution manifest / eval results）SHA-256 **未变**；execution_count=1；v3_2_baseline_manifest.json 记录 blind_v2_consumed=true。
- V3.1 runtime freeze 13 文件中 4 个变更（main.py、v3_retrieval_adapter.py、query_analyzer.py、hybrid_retriever_v2.py），全部为 V3.2 需求授权的修改目标；其余 9 个未变。
- V2 / frontend / 05_AI_Demo：未修改。
- 本阶段未做候选冻结（按需求第十节）。

## 10. 文件清单

新增：risk_intents.py、business_capability_catalog.json、v3_2_dev_cases.json、check_v3_2_dev_set.py、evaluate_v3_2_dev.py、build_v3_2_dev_cases.py、v3_2_baseline_manifest.json、final_blind_v2_evaluator_errata.md、debug_v3_2_failures.py / debug_v3_2_leak.py / debug_v3_2_leak2.py（诊断脚本）。
修改：query_analyzer.py、hybrid_retriever_v2.py、v3_retrieval_adapter.py、main.py、evaluate_final_blind_v2.py、test_final_blind_v2_evaluator.py、test_hybrid_v2_validation.py。
