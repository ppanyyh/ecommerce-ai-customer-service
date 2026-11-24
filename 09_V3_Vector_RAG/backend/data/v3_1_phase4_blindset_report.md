# V3.1 第四阶段报告 — final blind set v2 创建、审核与冻结

日期：2026-09-25 ｜ 状态：候选冻结，等待一次性评测指令

## 1. 候选运行版本哈希是否一致
一致。开工前重算 `v3_1_runtime_freeze_manifest.json` 的 13 个文件 SHA-256，**全部 OK（13/13）**；收尾时第 16 项校验再次复核，仍全部一致，本阶段未修改任何候选代码/知识库/索引/阈值/规则映射。

关键文件 SHA-256：
- `v3_1_runtime_freeze_manifest.json`：`b6f867838775a0b6…c8721ab`
- `v3_1_candidate_freeze_manifest.json`：`a0c6f070b74cdff0…9b20aa`
- `knowledge_chunks.jsonl`：`f97e8499207372…6869d681d`
- `index_manifest.json`：`cc0da3fe74433c1a…c4c44602`

## 2. 新盲测集 SHA-256
`final_blind_set_v2.json`：`06bf27e4eb50a3cf5921f82a1b0306a53f3cc1b53fa815b1eb5d3786f3ed18b5`

## 3. 总数与分类分布
总数 **70**。A 层（retrieval_scope_order）60 条：product 8 / faq 10 / rule 10 / multi 8 / order 6 / unsupported_business 10 / irrelevant 8；B 层（api_contract）10 条。

## 4. 难度分布
easy 14 / medium 32 / hard 24（符合要求）。

## 5. 三种 scope 分布
supported 42（=8+10+10+8+6，全部 answerable）/ unsupported_business 10 / irrelevant 8（含空输入 BV2-064、内部诱导 BV2-070 两个 API 契约用例）。

## 6. 两个评测子集分布
A 检索/门控/订单路由 60 条；B API 行为与安全契约 10 条（supported 本地降级、unsupported/irrelevant 确定性回复、高风险转人工、隐私、空输入、不完整订单号、不存在订单、赔偿承诺要求、内部信息诱导）。

## 7. 多答案、风险、质量缺陷、订单数量
- 多答案（relevant≥2）：**17 条**（≥12 ✓）
- 风险用例（含 required_rule_ids）：**17 条**（≥16 ✓），覆盖 HR-01~HR-08 全部 8 条规则
- 已发生质量缺陷（HR-08 已购故障）：**8 条**（≥6 ✓）
- 订单用例：**6 条** ✓（有效完整号×3——含状态×2、金额×1；不存在完整号×1；不完整号×1；订单号+高风险组合×1）

## 8. 历史黑名单来源和查询数量
`final_blind_v2_query_blacklist.json`：采集 **729** 条原始记录，去重后 **382** 条唯一查询，逐条含来源文件/原始 query/规范化 query/SHA-256。来源覆盖：旧黑名单继承（vector_eval_cases、validation_set_v1 原始版、V2 单元/集成/e2e 测试）、final_blind_set_v1、v3_1_dev_cases、validation v1_1_frozen / v1_2_reviewed 双版本、V3.1 全部测试与调试脚本字面量、9 个历史评测结果 JSON 的 query/message 字段。黑名单仅用于泄漏检查，未交给任何检索器。

## 9. 泄漏检查结果
`check_final_blind_set_v2.py` 16 项纯数据校验 **16/16 通过**（一次通过，无需回改）：case_id 唯一连续、query 唯一、与黑名单无完全重复、无简单改写（bigram Jaccard≥0.6 / LCS≥75% 检测）、未复制知识库完整句子（30 字滑窗）、relevant/required 引用全部合法、supported 结构完整、不可回答用例 relevant 为空、scope/route/category 组合合法、数量与难度分布、多答案/风险/缺陷/订单达标、无 API Key 与 PII、无运行后字段、label review 全覆盖、runtime 冻结哈希一致。

## 10. 人工抽查结果
`final_blind_set_v2_review_checklist.md`：分层配额抽样 **23 条**（≥20 ✓：普通 supported 4、风险规则 4、多意图 3、订单 3、unsupported 3、irrelevant 3、API 安全 3），全部通过——自然度/独立性/资料可支持性/scope/风险要求 5 项均无回改条目。已记录 1 处边界判断（BV2-049 风险下限定为"中"）及其依据，供评测后复核。

## 11. 新增文件
- `backend/data/final_blind_set_v2.json`（70 条盲测集，候选冻结）
- `backend/data/final_blind_set_v2_label_review.md`（逐条标注评审）
- `backend/data/final_blind_set_v2_review_checklist.md`（人工抽查清单）
- `backend/data/final_blind_v2_query_blacklist.json`（历史查询黑名单）
- `backend/data/final_blind_set_v2_manifest.json`（冻结清单，all_match=true）
- `backend/build_final_blind_v2_blacklist.py`、`backend/check_final_blind_set_v2.py`、`backend/freeze_final_blind_v2.py`（三个纯数据脚本，均不导入检索模块）

## 12. 是否运行任何检索器
**否。** 未调用 hybrid_search_v2、关键词/向量检索器、query_analyzer；三个新脚本与校验均只做文件读取与字符串比对。

## 13. 是否调用 /api/chat
**否。** 未启动 FastAPI，未发起任何 HTTP 请求。

## 14. 是否调用 DeepSeek
**否。** 全程 0 次。

## 15. 是否修改候选代码、知识库或索引
**否。** runtime 冻结 13 文件哈希前后两次核验一致；旧盲测资产未覆盖未运行；validation 双版本文件未动。

## 16. 是否具备执行一次性 final blind v2 评测的条件
**具备。** 盲测集已冻结（manifest all_match=true、execution_count=0、final_blind_v2_executed=false）、泄漏检查与人工抽查通过、运行版本冻结一致。等待审核并另行下达**一次性**评测指令；在此之前不运行、不修改、不扩写本集。

---
**提醒**：本集创建过程未运行任何检索，标注仅依据原始资料与已批准口径；按约定，评测执行必须一次完成（每条一次调用、不重试、不据结果回改标注）。
