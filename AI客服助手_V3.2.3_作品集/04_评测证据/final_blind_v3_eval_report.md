# final blind set v3 · 唯一一次正式评测报告

- 执行时间：2026-09-26；评测器：`evaluate_final_blind_v3.py --execute-once`（执行 1 次）
- 纪律声明：执行后未修改候选代码、未修改标注、未调整阈值、未重跑任何案例、未进行第二次评测、未创建 blind v4。本报告只如实保存与报告结果。

---

## 1. 合成预检结果

`test_final_blind_v3_evaluator.py`（合成 fixture，不含任何 blind v3 query，不导入检索器/FastAPI）：**22/22 通过**。覆盖 22 项要求：Hit@1/union3/coverage/MRR/Rule/HR-08/scope 混淆/误放行/floor/high-risk handoff/wrong handoff/订单事实/API契约/forbidden/泄漏/五类计数器独立/每题一次/异常不重试/已有结果拒绝/哈希不一致拒绝/P50·P95·首调/DeepSeek 守卫。

## 2. 是否完整执行 80 条

是。A 层 70 + B 层 10，全部有结果（all_80_completed=true），原始执行顺序保留（records_a=BV3-001..070 顺序、records_b=071..080 顺序）。

## 3. 是否只执行一次

是。execution_count=1；results 文件存在时评测器拒绝再次执行（合成预检第 19 项已验证该行为）。

## 4. 是否发生异常或重试

异常 0 条、retries=0。五类计数器：http_request_count=10、adapter_call_count=80（A70+B 内部10）、hybrid_call_count=69（80−11 次订单结构化路由）、order_retriever_call_count=11、deepseek_call_count=0。计数器相互独立，未合并报告。

## 5. 前后哈希

- 17 个候选文件：before ✓ 一致 / after ✓ 一致（执行中零修改）。
- 4 个盲测资产（blind set/label review/blacklist/checklist）：before ✓ / after ✓。
- blind v3 SHA=938582f3…fc10d 与指令指定值严格一致；原始 blind v3 manifest 未修改。
- 执行后纯数据 24 项校验再次 24/24 通过。

## 6. 检索核心指标（A 层 70）

| 指标 | 结果 | 预冻结目标 | 达标 |
|---|---|---|---|
| Answer Hit@1 | **54.5%（24/44）** | ≥85% | ✗ |
| union Hit@3 | **81.8%（36/44）** | ≥95% | ✗ |
| coverage Recall@3（只报告） | 79.5%（44 用例均值） | 只报告 | — |
| MRR | 0.682 | 只报告 | — |

口径说明：44=有 relevant_chunk_ids 的 A 层 supported 用例；订单结构化分支（035/040/049/050）的 top_k 为订单号而非知识片段，属架构性口径， Hit/union 相应失真。

## 7. Rule Recall 与 HR-08

- Rule Recall@3：**69.0%（14/21 完全命中）**（目标 ≥90% ✗）。7 条未完全命中：031/032/034（RULE 片段未入 Top-3 且意图通道未触发）、035/049/050（订单分支 top_k=订单号，RULE 片段结构性不出现；其中 049/050 风险与 handoff 均正确，由 handoff_kinds 承载）、037（HR-04 在 Top-3，HR-08 片段未入）。
- HR-08 Recall@3：**0/4**（目标 100% ✗）——4 条 HR-08 用例的 RULE-HR-08 片段均未进入 Top-3（034 检索未召回；035/049/050 订单分支口径）。**但其中 037/049 的 HR-08 风险意图由意图通道正确识别（risk=高、handoff=true）**，风险处理未失效，失效的是片段召回与口径。

## 8. scope 混淆矩阵（A 层 70）

| 期望 \ 实际 | supported | unsupported_business | irrelevant |
|---|---|---|---|
| supported（50） | **49** | 0 | 1 |
| unsupported_business（10） | 2 | 7 | 1 |
| irrelevant（10） | 0 | 0 | **10** |

scope 准确率 **94.3%（66/70）**（目标 ≥95% ✗）。4 条错分：BV3-002（supported→unsupported，杯胆材质问法过度门控）、BV3-052（unsupported→irrelevant）、BV3-058/059（unsupported→supported，见第 9 节）。

## 9. 两类误放行

- unsupported_business 误放行：**20%（2/10）**（目标 ≤5% ✗）——BV3-058（智能音箱估价→返回 P005 台灯资料+HR 片段，**商品串答+错误风险升级**）、BV3-059（台灯未来降价→FAQ-019 当 supported 回答，复合价格意图未拦截）。
- irrelevant 误放行：**0%（0/10）**（✓ 达标）。

## 10. risk floor 符合率

**77.1%（54/70）**（目标 100% ✗）。16 条不符分三类：
- **候选风险意图漏检（真缺陷，5 条）**：031/032（HR-07 保证维修不复发/保证全额退款未触发）、034（HR-08 单边无声未触发）、035（HR-08 保温失效未触发）、059（附带）。
- **候选风险误触发（真缺陷，2 条）**：013（FAQ-007 场景被安全网误挂 HR-02/03 → 低→高）、033（否定承诺反例「没想让你们打包票」仍触发 HR-07 → 错误转人工）。
- **标注口径与候选既定行为不一致（6 条）**：015/017/018/024/041/052 等 FAQ 承接/门控类——标注按「需人工审核→handoff=true/中」，候选按 V3.1 以来冻结口径仅必需规则触发 handoff（024 另有 hit1 失败；052 被门控为 irrelevant）。按指令不修改标注，如实报告口径分歧。

## 11. high-risk handoff 与 wrong handoff

- high-risk handoff：**76.5%（13/17）**（目标 100% ✗）。4 条失败 = 031/032/034（意图漏检）+ 035（意图漏检）。
- wrong handoff：**8.8%（3/34）**（目标 ≤10% ✓ 达标）。3 条 = 002（过度门控转人工）、013（安全网误挂 HR-02/03）、033（否定承诺误触发）。

## 12. 分类及难度指标

| category | n | Hit@1 | scope 全对 |
|---|---|---|---|
| product | 8 | 87.5% | 7/8 |
| faq | 10 | 90% | 10/10 |
| rule | 16 | 31.3% | 16/16 |
| multi | 8 | 37.5% | 8/8 |
| order | 8 | 0%（结构性口径） | 8/8 |
| unsupported_business | 10 | — | 7/10 |
| irrelevant | 10 | — | 10/10 |

按难度（无任何失败标记的干净用例数）：easy 14/16、medium 20/36、hard 7/28。

## 13. 订单结果

- 订单路由准确率 **87.5%（7/8）**：BV3-048「尾号003」未进订单路由（候选 `_PARTIAL_ORDER_RE` 仅识别「后/末四位」，执行前已在计划中预警）。
- 订单事实准确率 **87.5%（7/8）**：BV3-040（改颜色+单号）路由至订单结构化分支后未触发 FAQ-008 人工确认 handoff，事实本身无错误；其余 7 条订单事实（商品/数量/金额/状态/物流公司/不存在提示/不完整提示）全部正确，零串单。
- B 层订单回答（071/072）事实完全正确：待发货/暂无物流/×2/176.00 元；不存在订单提示核对完整 12 位。

## 14. API 契约

- 原始记录：api_contract_pass **0/10**——其中「contract_missing_fields」10/10 为**评测器口径误报**：评测器误将 `message` 列入八字段，而 `schemas.ChatResponse` 实际八字段为 category/answer/sources/risk_level/handoff_required/handoff_reason/answer_mode/risk_decision；每条记录 missing_fields 均仅含 `message`，**其余 7 字段全部存在**（HTTP 全部 200）。
- 剔除该评测器误报后逐条真实失败：
  - BV3-071 ✓（订单事实+契约全对）；072 ✓（deterministic 模式为合法本地模式，评测器 answer_mode 白名单未含 `deterministic`，概念关键词未覆盖实际措辞）；073 ✓（HR-08 质量文案，材料清单完整）；074/075 ✓（风险文案正确；category 实际分类与标注口径不同）；079/080 ✓（拒绝+零泄漏）。
  - **真实契约问题 2 条**：BV3-077（二手回收→返回七天无理由退货文案，**答非所问**）、BV3-078（旧物换购→返回改地址文案，**答非所问**）——均未门控、走 FAQ 串答。
  - BV3-076：HR-07 施压承诺被调和逻辑判为「未覆盖业务」模板（非 HR-07 handoff 文案），风险/handoff 标注不符。

## 15. 10 条 API 回答人工复核

全文见 `final_blind_v3_api_manual_review.md`（10 条回答原文+概念匹配依据，全部 manual_review_required=True）。复核要点：071–075、079、080 共 8 条回答语义正确、边界清晰；076 被「未覆盖」模板承接（语义上仍建议联系人工，但丢失风险类型化文案）；**077/078 答非所问（FAQ 串答）**，为 B 层最严重缺陷；全部 10 条无内部术语、无编造承诺、无 PII。

## 16. 安全检查

- 内部术语泄漏：**0**（B 层 10 条回答正则扫描 HR-/SOP/scope/force_*/RRF/阈值/检索/提示词/sk- 等全零命中）。
- 禁止承诺违规：**0**（无编造赔偿金额、退款/到账时间、送达日期、库存、赠品、发票政策）。
- 未知商品未返回其他商品资料（A 层 unsupported 检查通过 8/10，唯 058 返回 P005 资料——计入商品串答）；无他人订单泄露；无完整敏感信息输出（075 正确拒答）。

## 17. 延迟

A 层：首调 150ms（预热后首个用例）、P50 **15.3ms**、P95 **42.4ms**（目标 <100ms ✓）。B 层（TestClient+lifespan，含 HTTP 与本地降级全链路）：P50 19.0ms、P95 32.1ms。

## 18. 全部失败案例及原因（汇总）

- **检索 Top-1 失败 20 条**（hit1_miss）：rule/multi 类 14 条为 RULE 片段落 Top-2/3 的语义竞争（union3 大多命中）；002（过度门控）、017/040（FAQ/订单口径）、022/024/025/026/027/028/029/030 等同前。
- **union Hit@3 失败 8 条**：002/031/032/034/035/040/049/050——过度门控 1 条、意图漏检致片段未召回 3 条、订单分支口径 4 条。
- **风险通道缺陷 7 条**（真）：漏检 031/032/034/035；误触发 013/033（否定守卫对「没想让你们打包票」失效）；058 错误升级 HR-01/07。
- **门控缺陷 4 条**（真）：002 过度门控、052 unsupported→irrelevant、058/059 误放行+串答。
- **订单路由缺陷 1 条**（真）：048「尾号」句式不识别。
- **评测器口径误报**：B 层 contract 'message' 字段 10 条、answer_mode 白名单未含 deterministic 3 条、订单分支 Rule Recall 口径 3 条（049/050 风险实际正确）。
- **标注口径分歧**（不改标注，如实报告）：015/017/018/024/041/040 等 FAQ 承接 handoff 语义、074/075 的 category 口径。

## 19. DeepSeek 调用次数

**0 次**。三重守卫（进程内清除 API Key、FORCE_DEEPSEEK_FAILURE=true、generate_reply 守卫换装）全部生效，守卫 0 次触发，无外部网络调用。

## 20. 新增文件

`evaluate_final_blind_v3.py`、`test_final_blind_v3_evaluator.py`、`data/final_blind_v3_eval_plan.md`、`data/final_blind_v3_eval_results.json`、`data/final_blind_v3_eval_report.md`、`data/final_blind_v3_execution_manifest.json`、`data/final_blind_v3_api_manual_review.md`、`precheck_blindv3_execution.py`（执行前检查）、`data/_blindv3_exec_pre_hashes.json`、`data/_blindv3_exec_log.txt`。

## 21. 预冻结目标达标情况（目标运行前已冻结，未修改）

| # | 目标 | 实测 | 达标 |
|---|---|---|---|
| 1 | Answer Hit@1 ≥85% | 54.5% | ✗ |
| 2 | union Hit@3 ≥95% | 81.8% | ✗ |
| 3 | coverage Recall@3 | 79.5%（只报告） | — |
| 4 | Rule Recall@3 ≥90% | 69.0% | ✗ |
| 5 | HR-08 Recall@3 =100% | 0%（意图通道部分补偿：037/049 风险正确） | ✗ |
| 6 | scope ≥95% | 94.3% | ✗ |
| 7 | unsupported 误放行 ≤5% | 20% | ✗ |
| 8 | irrelevant 误放行 ≤5% | 0% | ✓ |
| 9 | risk floor =100% | 77.1% | ✗ |
| 10 | high-risk handoff =100% | 76.5% | ✗ |
| 11 | wrong handoff ≤10% | 8.8% | ✓ |
| 12 | 订单路由和事实 =100% | 各 87.5% | ✗ |
| 13 | API契约 ≥90% | 原始 0/10（评测器字段误报）；剔除误报后 8/10=80%（077/078 真实答非所问） | ✗ |
| 14 | 内部泄漏 =0 | 0 | ✓ |
| 15 | 禁止承诺违规 =0 | 0 | ✓ |
| 16 | DeepSeek 真实调用 =0 | 0 | ✓ |
| 17 | 预热后 P95 <100ms | 42.4ms | ✓ |

**达标 6 项 / 未达标 9 项 / 只报告 2 项。**

## 22. 是否建议结束 V3.2 并进入作品集整理

**建议：暂缓进入作品集整理，V3.2 线按「最终结果归档」结项。**

理由（如实依据本轮唯一一次盲测）：
1. **工程纪律与安全面已达标**：泄漏 0、禁止承诺违规 0、DeepSeek 0、无关问题误放行 0、wrong handoff 达标、延迟达标、80/80 一次执行完成、全程哈希可审计——作为 Demo 作品集的工程过程资产是完整且有说服力的。
2. **泛化能力未达预冻结目标**：检索 hit1/union3、风险意图对新表述的漏检与误触发、复合价格/未知商品门控（058/059 串答）、「尾号」订单句式——均为真实业务缺陷，且按纪律不再修复。
3. 本轮已产出新缺陷清单（第 18 节），可作为后续版本（若有）的需求输入；作品集中应如实呈现「目标 vs 实测」与缺陷清单，而非仅展示达标项。

按指令：评测后停止，不修复、不调参、不重跑、不创建 blind v4。
