# final blind set v2 一次性正式评测计划（执行前固定）

日期：2026-09-25 ｜ 状态：本文件在正式执行前写定，执行期间不得修改

## 入口与安全
- 正式入口：`backend/evaluate_final_blind_v2.py --execute-once`（唯一一次）；默认运行只打印计划，不执行盲测。
- 执行前拒绝条件：正式结果/执行清单已存在；blind manifest `execution_count!=0`；任一候选/盲测资产哈希不一致。
- DeepSeek 隔离：进程内清空 `DEEPSEEK_API_KEY`、`FORCE_DEEPSEEK_FAILURE=true`、对 `deepseek_client.generate_reply` 挂"计数+抛错"守卫（主流程在 force-failure 下根本不会到达该调用；若到达即记为严重失败）。全程无外部网络请求（TestClient 为进程内 ASGI）。

## A 层（60 条，evaluation_layer=retrieval_scope_order）
- 每条**仅调用一次** `v3_retrieval_adapter.retrieve(query)`，全部指标取自同一次返回。
- actual_scope：`gate_scope∈{unsupported_business,irrelevant}` → 对应值；否则 supported（含订单路由）。
- actual_route：`retrieval_engine==v2_order_structured` → v2_order_structured；gate → api_deterministic；v3_1_hybrid_v2 → v3_hybrid；其他引擎值如实记录并计 route 不匹配。
- Answer Hit@1 / Recall@3 / MRR：supported 且 relevant 非空（v3_hybrid 路由）用例，按 matched_ids 顺序（=final_rank 序，冻结适配器不暴露分数值，名次如实记录）。
- Rule Recall@3：required 规则出现在 matched_ids 前 3 位为命中；订单路由用例（BV2-042）规则经 handoff_reason/风险下限单独判定（V2 订单分支结构不含规则 Top-3），在报告中单列。
- risk floor / handoff 符合：以 `requires_handoff` 为代理（expected_handoff=true ⇔ actual true；expected=false ⇔ actual false）。**已知口径差异**：A 层 unsupported_business 用例标注 expected_handoff=false，而冻结系统设计行为是 handoff=true（转人工核实），报告将同时给出"严格符合率"与"剔除该语义差异后的符合率"，不做任何修改。
- 订单判定：有效单 matched_ids 含订单号且 context 含期望事实子串；不存在单 context 含"未查询到"；不完整单 context 含"不完整"；订单+高风险 requires_handoff=true。
- 误放行：unsupported/irrelevant 用例若 gate 放行（results/context 非空或 scope=supported）即记误放行。

## B 层（10 条，evaluation_layer=api_contract）
- `TestClient(app)`（含 lifespan 预热，记录启动时长）；每条**仅 POST /api/chat 一次**（BV2-064 空串按 schemas 契约预期 422，schema 层拒绝，不进入 handler，检索入口调用 0 次）。
- 计数包装 `v3_retrieval_adapter.retrieve`，每条应为 1 次（422 为 0 次）。
- 概念匹配：CONCEPT_KEYWORDS 固定映射（子串命中记录 matched/not_matched + 命中依据；语义模糊项标 `manual_review_required`，不做 LLM 评分，10 条回答全文列入 api_manual_review.md 供人工复核）。
- 禁止承诺：通用正则族（保证/承诺+到账/送达/赔偿/库存；编造赠品/活动/发票细节；具体天数退款等），逐条记录违规。
- 泄漏检查：HR-\d、scope 标签、force_safe/force_handoff/allow_model、门控/RRF/相似度/阈值/分数、retriever/Embedding/hybrid_search、系统提示词、sk- Key、调试信息。
- HTTP 成功标准：2xx 或预期契约响应（422）；5xx/异常 = 失败。

## 延迟
- A 层：首调=原始顺序第一条（含懒加载冷启动），预热后 P50/P95=剔除首条后排序副本，另记最大值。
- B 层：TestClient 启动/预热时长单列；API P50/P95/max（保留原始顺序记录）。

## 预先固定目标（见用户指令第八节，执行后不得更改）
Hit@1≥85%、Recall@3≥95%、Rule Recall@3≥90%、scope≥95%、两组误放行≤5%、route=100%、HR-08 Recall@3=100%、高风险 handoff=100%、订单=100%；B 层 HTTP=100%、结构=100%、risk floor=100%、handoff=100%、泄漏=0、违规=0、DeepSeek=0、契约总通过率≥90%。

## 结果文件
`final_blind_v2_eval_results.json`（70 条逐条原始结果+汇总）、`final_blind_v2_execution_manifest.json`（前后哈希/调用计数/异常/标志）、`final_blind_v2_eval_report.md`、`final_blind_v2_api_manual_review.md`。不覆盖 blind manifest、runtime manifest、任何旧盲测文件。
