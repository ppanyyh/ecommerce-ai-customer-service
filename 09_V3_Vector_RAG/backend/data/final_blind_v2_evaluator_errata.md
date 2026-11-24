# final blind v2 评测器勘误（V3.2 开始时补记）

> 本文件仅作勘误记录。原始结果 `final_blind_v2_eval_results.json`、执行清单
> `final_blind_v2_execution_manifest.json` 及全部哈希**保持原样不变**。
> 本问题不通过重跑 blind v2 修正（blind v2 已消耗，execution_count=1，禁止重跑）。

## 勘误 1：B 层调用计数双计

**事实**：B 层 10 条用例实际每条只有 **1 次 HTTP POST**（评测代码每条仅调用一次
`client.post`，且有异常不重试逻辑；BV2-064 空输入为 422，POST 发生 1 次）。

**缺陷**：评测器把「POST 计数」和「内部检索调用计数」写入了同一个计数 dict
（`call_counter`），导致：

- 逐条记录中出现 `calls`（≈2）与 `post_calls`、`retrieval_calls` 并存；
- `execution_manifest.per_case_calls_max=2`，与实际"每条 1 次 POST"不符。

**影响范围**：仅计数记账错误。不影响任何检索结果、scope/route 判定、风险判定、
概念命中、泄漏检查或延迟记录。A 层（adapter 单调用）不受影响。

**处置**：不重跑、不改原始文件。V3.2 评测器改为彼此独立的五个计数器：

- `http_request_count`
- `adapter_call_count`
- `hybrid_call_count`
- `order_retriever_call_count`
- `deepseek_call_count`

## 勘误 2：Recall@3 双口径混称

**事实**：V3.1 评测报告中的 `answer_recall3` 实为 **coverage 口径**
（|Top-3 ∩ relevant| / |relevant| 的宏平均），而失败归因时另算的
"union Hit@3"（任一合法相关片段进 Top-3）为 91.7%，两者未在正式结果中并列。

**口径定稿（V3.2 起执行）**：

- **union Hit@3**：Top-3 中存在至少一个合法相关片段即命中。作为正式达标口径；
- **coverage Recall@3**：相关片段覆盖率。仅作补充指标报告；
- 两者不得混称，报告与结果文件必须分开命名。

## 勘误 3：B 层 scope 行为映射过严

**事实**：B 层 `scope_behavior_ok` 判定对订单/隐私类确定性路由过严（把
V2 结构化订单路由的合理行为误判为与 expected_scope 不一致），拉低了
`B_contract_pass`（原始 20% / 修正映射口径 40%）。该判定逻辑在 V3.2 评测器中
按路由类型分别校验。原始结果文件不变。

## 评测器修复范围与限制

- 允许修复 `evaluate_final_blind_v2.py` 的**通用计数与指标函数**供未来复用；
- **禁止**使用修复后的脚本重跑 blind v2；
- 新增纯合成单元测试验证计数与双口径指标（不读取、不运行 blind v2）。
