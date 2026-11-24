# V3.1 第三阶段报告：V3.1 混合检索接入 /api/chat 与运行版本冻结

生成时间：2026-09-25 18:2x
范围：`09_V3_Vector_RAG/backend`。本阶段**未创建/未运行 final blind set v2，未运行旧 final_blind_set_v1，DeepSeek 真实调用 0 次，未修改 V2 / frontend / 05_AI_Demo。**

---

## 1. /api/chat 此前是否仍使用 V2 检索

**是。** 接入前 main.py 的 /api/chat 直接调用 `retriever.retrieve(message)`（V2 关键词/规则检索）；V3.1 检索此前仅以评测脚本方式存在，未接入服务（第二阶段报告已记录）。

## 2. 最终接入架构

```
POST /api/chat
  └─ v3_retrieval_adapter.retrieve(message)          ← 新增适配器（唯一接入点）
       ├─ 订单号（完整12位/疑似6-11位）→ retriever.retrieve  （V2 结构化订单查询，原样保留）
       └─ 其余问题 → hybrid_retriever_v2.hybrid_search_v2   （V3.1 冻结检索内核）
            ├─ gate: unsupported_business / irrelevant → 空结果结构（gate_scope 标记）
            │                                            → main.py 确定性分支本地回复
            └─ supported → Top-K 原始片段 → context/sources/风险下限
                            → 确定性场景 → 风险决策(force_safe/force_handoff/allow_model)
                            → DeepSeek 生成 → 六字段校验 → 失败本地降级
```

- 检索算法零改动：`query_analyzer.py / keyword_retriever_v3.py / vector_retriever.py / hybrid_retriever_v2.py / build_vector_index.py / knowledge_chunks.jsonl / index_manifest.json` 与检索内核冻结基线逐字节一致（哈希核验通过）。
- 阈值/关键词/别名/规则映射零改动。
- main.py 改动仅 3 处：import 适配器、chat() 检索调用切换、`_deterministic_reply` 新增门控分支（unsupported/irrelevant 本地回复）。三种风险决策模式、双层输出泄露检查、承诺红线、订单越界检查、FORCE_DEEPSEEK_FAILURE 回退开关全部原样保留。
- 适配器内置异常兜底：V3 检索异常时回退 V2 检索路径，不阻断服务。

## 3. V3 检索结果如何适配现有响应

- **context**：按 final_rank 排序，`[来源：{source}]片段 {chunk_id}：{text}` 逐片段拼接；一律使用**原始 text**（retrieval_text 仅用于索引，不作为事实输出）。
- **sources**：结果片段的 source 去重（如《商品资料》P003、《售后SOP》质量问题处理）。
- **matched/match_type/matched_ids**：与 V2 `_empty` 结构同构；match_type 映射 product→"商品"、faq→FAQ 分类、含规则命中→"risk"（售后），兼容 `_fallback_category`。
- **风险下限**：结果中的 RULE-HR-* 片段 ∪ analyzer `required_rule_ids` → 对应 V2 本地规则 → `requires_handoff=True` + 最高风险级规则原因。
- **不向用户暴露**：HR 编号、SOP 名称、scope 内部标签、门控逻辑、相似度、关键词/RRF 分数、阈值——这些仅存在于 context/sources/handoff_reason 等内部字段；answer 受 `main._INTERNAL_LEAK_RE`（既有）+ 集成测试 `_USER_LEAK_RE`（新增，含门控/scope/分数等扩展词）双重校验。
- **schemas.py / prompts.py 未修改**（现有响应字段与提示模板完全够用，符合"仅在确有需要时修改"）。

## 4. 结构化订单如何保留

- 适配器第一步即检测 `retriever._DIGIT12_RE / _DIGIT611_RE`：命中即整体委托 `retriever.retrieve(message)`——完整保留 V2 订单存在性、状态、金额、物流、不完整订单号、不存在订单的确定性处理与风险标注。
- 订单数据不写入向量库（index_manifest `contains_orders=false` 未变）。
- **订单号 + 高风险表达**：V2 订单分支自带 `_risk_flag`，且 main.py `_risk_decision(t)` 在模型调用前独立运行——投诉/赔偿/催促等命中即 force_handoff，模型不得降低风险或取消转人工（集成测试 C06b 验证：handoff=True、risk≥中）。
- 无回归证明：集成测试 C06/C07 + 旧测试订单类用例（TC-01/02/03 中订单事实断言外的失败均为无Key环境性）+ 实测 `订单202609180001` 返回《模拟订单数据》来源。

## 5. supported / unsupported_business / irrelevant 的 API 行为

| scope | DeepSeek | context/来源 | 行为 |
|---|---|---|---|
| supported | 有 Key 时调用（本阶段测试环境无 Key → answer_mode=fallback 本地降级） | Top-K 原始片段 | 正常作答流程；高风险强制转人工 |
| unsupported_business | **不调用** | results/context 为空 | 确定性回复："现有资料没有覆盖这项信息，建议联系人工客服确认。"（中风险、转人工，sources=["现有资料未覆盖"] 不伪造） |
| irrelevant | **不调用** | results/context 为空 | 确定性回复："抱歉，我只能协助处理本店商品、订单和售后相关问题。"（低风险、不转人工、不携带知识片段） |

## 6. 高风险转人工结果

- 质量缺陷（HR-08）：集成测试 C04 → handoff=True、risk=高 ✓
- 投诉赔偿（HR-01）：C05 → handoff=True、risk=高 ✓
- 订单号+高风险：C06b → handoff=True、risk≥中 ✓
- 本地风险下限：`_risk_decision` 与检索规则片段双通道，均不受模型影响（本阶段模型未参与，降级路径也保留 handoff）。

## 7. 端到端测试结果（test_v3_1_api_integration.py，新增）

**169/169 全部通过**，覆盖全部 16 类：商品参数、已覆盖FAQ、普通退货、质量缺陷、投诉赔偿、已知订单、不存在订单、发票未覆盖、促销赠品未覆盖、未知商品、完全无关、空输入（空串 422 校验拒绝 + 纯空白确定性回复）、连续重复请求（3 次 200 且行为一致）、DeepSeek 不可用降级（无 Key → fallback；FORCE_DEEPSEEK_FAILURE → HTTP 仍 200）、/api/health、/api/ready，另含前端静态兼容（根路径 HTML）。

关键校验：八字段结构（category/answer/sources/risk_level/handoff_required/handoff_reason/answer_mode/risk_decision）与 V2 完全一致（前端兼容）；answer 无内部术语；门控结果 sources=["现有资料未覆盖"] 不携带知识片段；订单查询无回归；全局 `deepseek_success=0`、无 Key 时仅配置异常（`deepseek_attempts == deepseek_failed`，无真实网络调用）。

测试表达全部为本阶段重新编写，未复制旧盲测题目。

## 8. V3.1 开发集回归

与第二阶段**完全一致**（检索内核未动）：Hit@1 36/40=90.0%、Recall@3 40/40=100%、Rule 17/17、门控 60/60（混淆矩阵全对角）、误放行 0/20、HR-08 7/7、DV-046 判 unsupported_business ✓。

## 9. Validation 双口径回归

与第二阶段**完全一致**：
- **v1.1 冻结口径**：v2 Hit@1 22/24 (91.7%)、Recall@3 23/24、Rule 8/8；v2 失败 = H-013（发票业务语义变更）+ H-020（v1.2 已批准的部分相关性排序差异）。
- **v1.2 审查口径**（annotation-corrected exploratory）：v2 Hit@1 23/24 (95.8%)、Recall@3 23/24、Rule 8/8；v2 失败 = 仅 H-013。
- 成功条件逐项与第二阶段相同，无新增回归。

## 10. 旧 chat 测试结果（test_chat_integration.py，无 Key 环境运行）

**269/309 通过，40 项失败，已逐一归因（未篡改旧测试）：**

| 归因类别 | 失败项 | 说明 |
|---|---|---|
| A. 无 Key 环境性（与接入无关） | 各用例 `answer_mode 期望 deepseek 实际 fallback`、`answer 包含关键信息`（模型生成内容）、`risk_decision 期望 force_safe/force_handoff 实际 allow_model`（fallback 路径不设置 risk_decision） | V2 原代码在无 Key 环境下同样如此；本环境无 DeepSeek Key，模型用例按设计降级 |
| B. V3 多源 sources 预期变化 | `sources 均在 retriever 来源内`（单来源白名单断言） | V3 Top-K 检索天然返回多片段来源（如商品+SOP 组合）；V2 为单一主来源。**接入后的预期行为变化**，前端多来源展示本就支持 |
| C. 有意业务语义变更 | TC-08/RG-04 无关问题文案（V2 5c"商品、订单、物流和售后" → V3.1 门控"本店商品、订单和售后"，按第三阶段指令第四节指定文案）；RG-05"可以开发票吗"（V2 命中 FAQ-018 交模型 → V3.1 按第二阶段裁定判 unsupported_business 确定性转人工） | 按指令"分别报告，不篡改旧测试制造通过" |

完整原始输出留存：`data/v3_1_old_chat_regression_output.txt`。

## 11. health/ready 实测（uvicorn 临时启动）

- `GET /api/health` → `{"status":"ok","version":"2.0.0","mode":"deepseek_with_retrieval","deepseek_configured":false}`
- `GET /api/ready` → `{"ready":true,"vector_warmed":true,"warmup_ms":17393.7,"warmup_error":null}`——启动时仅预热本地 Embedding + 向量库（约 17.4s），**不调用 DeepSeek**；预热完成后 ready=true。
- `POST /api/chat` 实测四类：supported（无Key → fallback、多源 sources）、发票（门控确定性转人工）、无关（门控确定性范围说明）、已知订单（V2 结构化、《模拟订单数据》来源）——全部符合第 5 节定义。
- 测试后服务已停止，**端口 8000 已释放、无残留进程**。

## 12. DeepSeek 调用次数

**0 次真实调用**。集成测试通过环境变量清空 Key 隔离并验证 `DeepSeekConfigError` 仅在配置层抛出（`deepseek_attempts == deepseek_failed`、`deepseek_success=0`）；全流程门控/订单/空输入确定性路径根本不进入模型分支。正式 DeepSeek 客户端语义未修改。

## 13. 修改及新增文件

**修改（1 个）**：`main.py`（import 适配器、chat() 检索切换、确定性门控分支、头部注释——均在接入允许范围）。
**新增（4 个）**：`v3_retrieval_adapter.py`、`test_v3_1_api_integration.py`、`freeze_v3_1_runtime.py`、`data/v3_1_runtime_freeze_manifest.json`；另留存 `data/v3_1_old_chat_regression_output.txt`。
**未修改**：schemas.py、prompts.py、全部检索内核文件、knowledge_chunks.jsonl、index_manifest.json、全部冻结评测集、全部旧 final blind 资产。

## 14. 检索内核冻结文件是否发生变化

**未变化**。`v3_1_candidate_freeze_manifest.json`（基线，SHA-256 `a0c6f070b74cdff0b58bd1daf7e91f964589edfcb9bc77a89c24eae6ad9b20aa`）保留未覆盖；开工前与收尾后两轮核验：10 文件中除允许修改的 main.py 外（schemas.py/prompts.py 实际也未改）全部逐字节一致（`kernel_unchanged_except_allowed=true`）。

## 15. 新运行版本冻结清单及哈希验证

`data/v3_1_runtime_freeze_manifest.json`：冻结 **13 个文件**（main.py、schemas.py、prompts.py、v3_retrieval_adapter.py、retriever.py、query_analyzer.py、keyword_retriever_v3.py、vector_retriever.py、hybrid_retriever_v2.py、deepseek_client.py、build_vector_index.py、data/knowledge_chunks.jsonl、data/index_manifest.json）+ 原 candidate manifest SHA + 内核一致性核验 + 环境（Python 3.12.0 / chromadb 1.5.9 / sentence-transformers 6.1.0 / bge-small-zh-v1.5 / 512 维 / data_version 1.2）+ API 路由/订单路由/门控三分类行为 + 全部测试结果。生成后重算全部哈希：**all_match=true**。

## 16. 是否运行旧 final blind set

**否**（`old_final_blind_reexecuted=false`）。

## 17. 是否具备独立创建 final blind set v2 的条件

**具备**：运行版本已冻结（all_match=true）、检索内核基线一致、/api/chat 全链路集成并通过 169 项端到端测试、双口径 validation 与开发集指标与第二阶段一致、DeepSeek 隔离机制验证有效、health/ready/chat 实测通过。**按指令暂不创建、不运行 final blind set v2**，等待下一步独立生成新盲测集的指令。
