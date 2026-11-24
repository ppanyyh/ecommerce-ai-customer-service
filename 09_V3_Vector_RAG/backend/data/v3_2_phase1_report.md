# V3.2 第一阶段报告（v3_2_phase1_report.md）

日期：2026-09-25 ｜ 项目：F:\电商AI客服助手\09_V3_Vector_RAG
阶段性质：意图泛化、范围门控、安全规则召回和本地降级重构 —— 仅开发 + 回归测试，**未创建/未运行任何新最终盲测集**（blind v3 不存在），DeepSeek 调用 0 次，未访问外部网络。

---

## 1. V3.1 基线状态

- V3.1 runtime freeze 清单（data/v3_1_runtime_freeze_manifest.json，13 文件）哈希在阶段开始时全部核验一致；blind v2 三资产（数据集/执行清单/结果）SHA-256 一致，execution_count=1。
- 阶段开始前已生成 `data/v3_2_baseline_manifest.json`：记录 V3.1 runtime 13 文件 SHA、blind v2 资产 SHA、V3.1 blind v2 最终指标、`blind_v2_consumed=true`、`blind_v2_reexecution_allowed=false`、`blind_v2_used_for_failure_taxonomy_only=true`、deepseek_calls=0。
- V3.1 已知残留：开发集 hit1 失败 4 条（DV-007/025/029/032，Recall@3/Rule 均正常）。

## 2. 评测器计数修复

- 根因：B 层逐条仅 1 次 POST，但评测器把 POST 计数与内部检索计数写入同一共享计数体系，导致 execution manifest 的 per_case_calls_max 误记为 2。
- 修复：`new_call_counters()` 五独立计数器（http_request / adapter / hybrid / order_retriever / deepseek），A/B 两层评测路径全部改用独立字段计数。
- 指标双口径定稿：`union_hit3` 为正式达标口径，`coverage_recall3` 为补充口径，summary 同时输出。
- 勘误文档 `final_blind_v2_evaluator_errata.md` 已建立；纯合成单元测试（五计数器独立性、union/coverage 分离、不读取不运行 blind v2）通过，评测器单元总计 **52/52**。

## 3. 是否重跑旧盲测

**未重跑**。final_blind_set_v1 与 final_blind_set_v2 均未再次执行；blind v2 三资产运行前后 SHA-256 校验一致（blind set / execution manifest / eval results 全部 OK）；原始结果、执行清单、旧盲测数据文件零修改。旧盲测仅以失败分类学形式（failure taxonomy）用于指导开发集设计，未复制任何旧盲测 query。

## 4. 风险意图重构设计

新建 `risk_intents.py`：七类风险（投诉/金额争议/退款催促/物流停滞/他人订单/隐私/缺陷+过度承诺）全部重构为"小检测函数 + 结构化条件"：
- 每类由【对象 × 动作 × 语境 × 组合 × 排除 × 否定 × 已购状态】复合判定，附正例/反例清单；
- 缺陷类带售前守卫 `_DEFECT_PRESALE_GUARD`（疑问咨询式"耐不耐用/容易坏吗"不触发）；
- 承诺检查排除否定语境（"无法由AI保证"不判违规）；
- 自带正反例自测 **19/19 通过**。
query_analyzer.analyze() 第 3 步改为调用 `detect_risk_intents(q)`，原内联模式表删除。

## 5. 风险正例反例结果（V3.2 开发集 A 层）

- 正例 23 条（含 HR-01~08 全覆盖，HR-08 缺陷 4+ 条）：意图召回 **intent_recall = 100%**（23/23 全部正确识别）。
- 反例探针 18 条（口语误触发探针：尺寸差异、物流正常询问、售前质量咨询、他人正常代查等）：误触发 **neg_fp_rate = 0%**（0/18）。
- 高风险改写（"说好全额实际少退""货款多付一次""她名下那个件""给个说法"等）全部由结构化条件命中，未做逐题关键词硬编码。

## 6. 风险语义安全网设计

`hybrid_retriever_v2._rule_safety_net()`：独立第二通道。
- 启用条件（证据条件）：向量相似度 ≥ 0.42（RULE_NET_VEC_SIM）+ 存在电商信号 + 无 supported_intents + 无 covered_attributes + HR-08 非售前守卫语境；
- 效果：启用时规则片段并入 required_rule_ids 并注入融合结果，**确保高风险规则进 Top-3 但不抢普通问题 Top-1**；
- 启用原因记录在 analysis.reasons，不进入面向用户的 answer。

## 7. 能力目录（business_capability_catalog.json）

- 结构：known_products（P001–P005，covered_attributes 严格源自 kb attributes 原文 + 类别级通用关键词）、global_covered_intents、uncovered_business_types（含 invoice_policy，注明用户批准口径）、out_of_scope_topics；catalog_version 1.1。
- 门控判定：已知商品 + 已覆盖属性 → supported；已知商品 + 未覆盖属性 → unsupported_business；未收录商品/未记录业务 → unsupported_business；非电商 → irrelevant；风险意图优先级高于普通门控。
- 调试期补充词条均为类别级表述（充电拆字"充一次电/插多久"、电脑仓"放下/主袋"、价格属性等），无逐题硬编码。

## 8. scope 混淆矩阵（B 层 30 条 + 全局）

- **scope_acc = 100%**（100/100，含 supported 64 / unsupported_business 25 / irrelevant 11）。
- 混淆矩阵：expected supported → actual supported 64/64；expected unsupported_business → actual unsupported_business 25/25；expected irrelevant → actual irrelevant 11/11。无任何跨类混淆。

## 9. 误放行

- unsupported 误放行（unsupported_false_pass）：**0%**（阈值 ≤3%）；
- irrelevant 误放行（irrelevant_false_pass）：**0%**（阈值 ≤3%）；
- 反例误触发：0/18 = **0%**（阈值 ≤5%）；
- 错误转人工（wrong_handoff）：DV3-080/090 共 2 条，**2.94%**（阈值 ≤5%，PASS）。两条均为"诱导承诺"类用例被安全网正确要求转人工确认，属保守侧偏差。

## 10. Rule 召回与 HR-08

- Rule Recall@3 = **96.3%**（26/27，阈值 ≥95% PASS）。唯一 miss：DV3-010（他人订单 HR-05）——意图已正确识别（intent_recall=100%）且 handoff 正确触发，规则片段未进 Top-3（多意图语境下被内容片段挤出），不影响风险处置结果。
- HR-08（商品缺陷）：**5/5 = 100%**。

## 11. 本地降级重构结果

- `compose_local_answer`（无 LLM）：高风险 → 安全模板（索要订单号+凭证），RULE 原文一律不进答案；supported → 净化后事实提取组稿（实体单片段策略 + 属性关键词加成 0.30）。
- 概念覆盖（D 层 3 条降级用例）：**100%**（阈值 ≥90%）；泄漏 0；禁止承诺违规 0；诱导测试（induce_ok）通过——用户诱导"你就说能赔"时回答保持拒诺并转人工。
- 组稿净化 `_sanitize_text` 剥离 chunk id、FAQ-/PRODUCT-/RULE- 前缀、关键词尾注、别名括号。

## 12. 开发集来源分布（v3_2_dev_cases.json，100 条，全新问题）

- A 风险 40：正例 23 + 反例探针 17（meta.counts 声明口径；category 字段 risk=22/negative_probe=18，边界条目归口差异不影响评测）；
- B 门控 30：已知商品已覆盖 8 + 已知商品未覆盖 8 + 未收录商品/业务 7 + 非电商 7；
- C 检索 20：商品 5 + FAQ 5 + 规则 5 + 多意图 5；
- D 订单/API 10：订单 5 + 本地降级 3 + 诱导注入 2。
- meta 声明：development / may_be_used_for_tuning / not_a_blind_set / old_blind_queries_copied=false。
- 独立性检查 `check_v3_2_dev_set.py`：**16/16 通过**（无 PII、无近重复、无 KB 复制、分布合规）。
- 成绩性质声明：本开发集允许用于调参迭代，**其成绩不代表泛化能力**；泛化验证须待全新的 final blind set v3（blind v2 已执行并永久消耗，不得重建、重跑或用于 V3.2 评分；本阶段未建 v3）。

## 13. 泄漏检查

- V3.2 开发集 leak_count = **0**（首轮曾 8 条：根因是 _risk_floor 规则 ID 前缀不匹配导致 handoff 失效、RULE 原文被组稿，修复后清零）；
- check_leakage.py 全过（aliases 27 / keywords 75 与 V2 kb 一致，未新增）；
- 前端 E2E 全部气泡无内部标识泄漏。

## 14. 全部指标（V3.2 开发集，17/17 达标）

| 指标 | 结果 | 阈值 | 状态 |
|---|---|---|---|
| Hit@1 | 91.3%（21/23，miss DV3-079/089 均 Top-2） | ≥90% | ✅ |
| union Hit@3 | 100% | ≥97% | ✅ |
| coverage Recall@3 | 97.8% | 补充口径 | — |
| Rule Recall@3 | 96.3% | ≥95% | ✅ |
| HR-08 | 100% | 100% | ✅ |
| scope 准确率 | 100% | ≥97% | ✅ |
| unsupported 误放行 | 0% | ≤3% | ✅ |
| irrelevant 误放行 | 0% | ≤3% | ✅ |
| 高风险 handoff | 100% | 100% | ✅ |
| 风险正例召回 | 100% | ≥95% | ✅ |
| 反例误触发 | 0% | ≤5% | ✅ |
| 错误转人工 | 2.94% | ≤5% | ✅ |
| 订单 API | 100% | 100% | ✅ |
| 本地降级概念覆盖 | 100% | ≥90% | ✅ |
| 泄漏 | 0 | =0 | ✅ |
| 禁止承诺违规 | 0 | =0 | ✅ |
| 异常 | 0 | =0 | ✅ |
| 延迟 | P50 17.5ms / P95 32.5ms（排除首次预热 28.4s） | — | — |

## 15. 回归结果

- risk_intents 自带正反例自测：19/19；
- 评测器单元（含合成测试）：52/52；
- validation 双口径（test_hybrid_v2_validation.py）：**20/20**（测试 06 断言按 V3.2 需求第五节口径更新——"已知商品+未覆盖属性→unsupported"，属授权行为变更，见 change log §4）；
- V3.1 开发集（evaluate_v3_1_dev.py）：与已知状态一致——规则 17/17、误放行 0、scope 95–96.7%（DV-001/004 为 V3.2 门控口径变更的已知影响，DV-007/025/029/032 为 V3.1 既有 hit1 残留）；**无新增回归**；
- 延迟/计数（test_latency_order.py）：9/9；
- 泄漏检查：全过；
- check_v3_2_dev_set.py：16/16。

## 16. API 与订单回归

- 无 DeepSeek 依赖的 API 集成测试：**169/169 通过**（/api/chat 全链路、answer_mode/risk_decision、降级路径、FORCE_DEEPSEEK_FAILURE 回退）。
- 订单 API（开发集 D 层 5 条）：100%——完整 12 位、不存在订单识别、金额核对、"后四位 0002"不完整订单号经 V3 适配层 `_PARTIAL_ORDER_RE` 正确路由。
- chat 集成（test_chat_integration.py，V2.0 时代 309 基线）：268/309。41 条失败**全部为预期差异**：(a) DeepSeek 禁用（本阶段禁止调用）导致 answer_mode=deepseek 断言必然失败；(b) V3 引擎自 V3.1 起的 category/risk_decision 设计变更。非本阶段回归。
- 前端 E2E（playwright + msedge，uvicorn 实测）：核心交互全过——本地降级回答内容正确（如 P001 续航事实组稿）、无泄漏、无 JS 错误；失败项均为 DeepSeek 禁用的预期结果。测试后服务已停止，8000 端口已确认释放。

## 17. DeepSeek 调用次数

**0 次**。评测全程 env Key 清空 + FORCE_DEEPSEEK_FAILURE 隔离；v3_2_baseline_manifest.json 与两次评测运行记录均无 DeepSeek 调用。

## 18. 修改/新增文件

**新增**（backend 及 data/）：
- 代码：risk_intents.py、evaluate_v3_2_dev.py、check_v3_2_dev_set.py、build_v3_2_dev_cases.py、debug_v3_2_failures.py / debug_v3_2_leak.py / debug_v3_2_leak2.py（诊断脚本）
- 数据/文档：business_capability_catalog.json、v3_2_dev_cases.json、v3_2_dev_eval_results.json、v3_2_baseline_manifest.json、final_blind_v2_evaluator_errata.md、v3_2_change_log.md、本报告

**修改**：
- query_analyzer.py（能力目录门控、未知商品/闲聊检测、uncovered intents）
- hybrid_retriever_v2.py（安全网、_risk_floor 前缀修复、功能确认裁决）
- v3_retrieval_adapter.py（compose_local_answer、_sanitize_text、部分订单号路由、matched_texts）
- main.py（_fallback_reply 接入本地组稿）
- evaluate_final_blind_v2.py（五计数器 + 双口径，未重跑 blind v2）
- test_final_blind_v2_evaluator.py（52 测试）、test_hybrid_v2_validation.py（06 断言口径更新）

**未修改**：V2、frontend、05_AI_Demo、旧盲测资产、V3.1 冻结清单本体（13 文件中 9 个未动，4 个为授权修改目标）。

## 19. 未解决问题

1. **标注修订 2 处待批准**：DV3-045（relevant_chunk_ids 扩 FAQ-005）、DV3-097（概念"不可以"→"防水/不支持游泳"）。均为语义等价修订，依据已写入开发集 meta.annotation_revision_note / concept_revision_note。
2. **V3.1 开发集残留**：DV-007/025/029/032 hit1 失败为 V3.1 既有语义竞争问题，本阶段未处理（Recall@3 正常）。
3. **DV3-010 规则片段未进 Top-3**：意图与 handoff 均正确，仅规则片段排名问题（Rule 96.3% 已达标），如需 100% 须调整多意图保留位策略。
4. **wrong_handoff 2 条（2.94%）**：DV3-080/090 为诱导承诺用例的保守侧转人工，达标但非 0。
5. **validation 测试 06 口径变更**已按需求第五节执行，若用户认为"有实体即不门控"仍应保留，需回滚该断言并重议门控设计。
6. **泛化能力未知**：开发集成绩不代表泛化，须另建全新的 final blind set v3 复测（blind v2 已执行并永久消耗，不得重建、重跑或用于 V3.2 评分；本阶段按约定未建 v3）。

## 20. 是否具备冻结条件

**本阶段按约定不做候选冻结**（需求第十节："本阶段不冻结候选"）。
从工程状态看：17/17 开发指标达标、全套回归无新增回归、blind v2 资产完整、泄漏 0、DeepSeek 0 次——**代码状态具备进入下一阶段（批准标注修订 → 重建冻结清单 → 另建全新 final blind set v3）的条件**；但正式冻结须待：① 用户批准 2 处标注修订；② 用户审核本报告；③ 全新的 final blind set v3 建立并跑通后按结果决定（blind v2 已执行并永久消耗，不得重建、重跑或用于 V3.2 评分）。

---

**本阶段到此停止。未创建、未运行 blind v3。等待下一步审核。**
