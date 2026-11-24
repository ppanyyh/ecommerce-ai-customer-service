# 评测执行计划（final blind set v3 · 唯一一次正式评测）

## 1. 执行入口与门控

- 评测器：`backend/evaluate_final_blind_v3.py`
- 默认不执行任何评测；只有显式 `--execute-once` 才进入正式执行。
- 正式执行前自动重跑执行前检查（manifest 状态、blind v3 SHA、17 候选文件 SHA、4 资产 SHA、结果文件不存在），任一失败立即拒绝执行。
- 检测到 `final_blind_v3_eval_results.json` 已存在 → 拒绝再次执行（不重跑、不二评）。

## 2. 调用与计数（五类独立计数器）

| 计数器 | 挂点 | 说明 |
|---|---|---|
| http_request_count | B 层每条 POST /api/chat 调用点 | 仅统计用户级 HTTP 请求 |
| adapter_call_count | 包装 v3_retrieval_adapter.retrieve | A 层直接入口 + B 层 API 内部调用分别计入同一独立计数器 |
| hybrid_call_count | 包装 v3_retrieval_adapter.hybrid_search_v2 | 混合检索内核调用 |
| order_retriever_call_count | 包装 retriever.retrieve | V2 结构化订单检索调用 |
| deepseek_call_count | deepseek_client.generate_reply 守卫 | 任何尝试均记为严重失败 |

- 禁止把 HTTP 计数与内部检索计数相加；五类计数器相互独立、分别保存。
- 每条 A 层用例仅调用 `v3_retrieval_adapter.retrieve(query)` 一次；每条 B 层用例仅 POST 一次；无自动重试（异常→记录→继续下一题）。
- 正式计时前执行一次预热调用（query="你好"，非盲测题），随后计数器归零；预热调用不计入 80 条执行统计。

## 3. actual 字段判定口径（A 层）

- actual_scope：结果含 gate_scope → 取该值；否则 supported（订单分支与命中均属支持域）。
- actual_route：gate → local_fallback；订单分支且 order_local.found=True → v2_order_structured；订单分支且 found=False（不存在/不完整）→ api_deterministic；其余 → v3_hybrid。
- actual_risk：risk_floor_level 存在则取之；gate unsupported_business → 中；gate irrelevant → 低。
- actual_handoff：requires_handoff。
- Top-K = matched_ids（final_rank 顺序，K=5）；全部指标（Hit@1/union Hit@3/coverage Recall@3/MRR/Rule Recall@3/HR-08 Recall@3）从同一次结果计算。

## 4. B 层（10 条）

- FastAPI TestClient + lifespan（不启动长期后台服务，测毕关闭）。
- DeepSeek 守卫：进程内清除 DEEPSEEK_API_KEY、FORCE_DEEPSEEK_FAILURE=true、generate_reply 换装为记录并抛错的守卫；意外调用=严重失败，不重试。
- 概念检查不用 LLM：每条 required_answer_concept 用预定义关键词匹配，matched/not_matched/匹配依据/manual_review_required 逐条记录，10 条原始回答存入 api_manual_review。

## 5. 目标

直接读取 `final_blind_set_v3_manifest.json` 的 pre_frozen_targets（运行前已冻结），评测器不重新定义、不得修改。

## 6. 已知风险点（执行前如实记录，不作任何规避）

- BV3-048（尾号003）：候选 `_PARTIAL_ORDER_RE` 仅识别「后/末四位」，「尾号」句式可能不进订单路由——如实报告。
- BV3-040/041 等 FAQ 驱动 handoff 用例：adapter 仅必需规则触发 handoff——如实报告。
