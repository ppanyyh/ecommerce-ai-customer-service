# final_blind_set_v3 创建·审核·冻结报告（V3.2.2 最终阶段一）

- 日期：2026-09-26
- 性质：本项目**最后一套**最终盲测集（no_future_blind_set_planned=true），创建后冻结，等待唯一一次评测指令。
- 本阶段边界：只创建和检查盲测数据。**未调用任何关键词/向量/混合检索器、未调用 v3_retrieval_adapter、未调用 /api/chat、未启动 FastAPI、未查询 Chroma、未调用 DeepSeek、未修改任何候选文件。**

---

## 1. V3.2.2 候选哈希核验

- 脚本：`verify_candidate_for_blindv3.py`（只读 hashlib）
- `v3_2_2_candidate_freeze_manifest.json` 自身 SHA-256：`29d417d42bdb914a09e27a5c6ad6fbb6609227ceb9aee60bc41736cf582381cd`
- 17 个候选文件逐一重算：**17/17 一致，mismatch=0**
- 关键资产：
  - `knowledge_chunks.jsonl`：`f97e84992073721bcfd554efd2eff865c9c975a8d4162f47b72bcb26869d681d`
  - `index_manifest.json`：`cc0da3fe74433c1a8a782a9165e71806b2ddbd3a4744537f57cdf8a1c4c44602`
  - `business_capability_catalog.json`：`921fe8299678b48dc47d086ded84be11edabcb73e278023791dc4bbb1c0c635a`
  - `risk_levels.py`：`18767229344d2a343dc0e6af880ae8189a9afd4176cc2aff7f8c6124c603ca16`
- 标志位：all_match=true；old_blind_v1_reexecuted=false；old_blind_v2_reexecuted=false；final_blind_v3_created=false（创建前）；final_blind_v3_executed=false；deepseek_calls_total=0。**全部一致，未触发停止条件。**

## 2. blind v3 SHA（冻结后）

| 资产 | SHA-256 |
|---|---|
| final_blind_set_v3.json | 见 `final_blind_set_v3_manifest.json`（生成时复算 OK） |
| final_blind_set_v3_label_review.md | 同上 |
| final_blind_v3_query_blacklist.json | `4267713cffd63b527e643ab1067fbf1fc7c9e53bc0bee21afd12bf1c578bfe89` |
| final_blind_set_v3_review_checklist.md | 同 manifest 记录 |
| final_blind_set_v3_manifest.json 自身 | `6f694fc4edbe2dbeac5ef0642b73058c8a31d4d1b5c42098604196cda9e3966d` |

## 3. 总数和分类分布

总计 **80 条** = A 层 70（retrieval_scope_order）+ B 层 10（api_contract）。

| category | A 层 | B 层 | 合计 |
|---|---|---|---|
| product | 8 | — | 8 |
| faq | 10 | — | 10 |
| rule | 16 | — | 16 |
| multi | 8 | — | 8 |
| order | 8 | — | 8 |
| unsupported_business | 10 | — | 10 |
| irrelevant | 10 | — | 10 |
| api | — | 10 | 10 |

A 层 supported = 8+10+16+8+8 = **50**（含 BV3-033 否定承诺近似反例，由 FAQ-016 承接）；A 层不可回答 = unsupported_business 10 + irrelevant 10。

## 4. 难度分布

easy **16** / medium **36** / hard **28**（product 4/4/0、faq 2/7/1、rule 3/7/6、multi 0/4/4、order 4/2/2、unsupported 0/5/5、irrelevant 3/4/3、api 0/3/7）。

## 5. scope 分布

supported **56**（A50 + B6）/ unsupported_business **12**（A10 + B2）/ irrelevant **12**（A10 + B2）。

## 6. 风险规则分布（required_rule_ids 正例）

HR-01×2、HR-02×4、HR-03×3、HR-04×3、HR-05×4、HR-06×4、HR-07×4、HR-08×4 —— **每条正式规则 ≥2 条全新表达，HR-01..08 全覆盖**。

- HR-07 四形态：真正要求承诺（BV3-031 保证维修半年不复发）、带施压承诺（BV3-072/B7 层 073「办不到你试试」）、双重否定后仍要求承诺（BV3-032、BV3-076）、否定承诺近似反例（BV3-033，不触发、FAQ-016 承接）。
- HR-08 四种部件/功能故障：耳机单边无声（034）、保温杯不保温（035）、背包外膜磕裂（037）、键盘按键失灵（049）。
- HR-05/06：他人订单查询/代退/代改（027/028/038/074）+ 验证码/索要地址身份证/索要手机号（029/030/038/075）。
- HR-03/04 保持正式**中**风险且 handoff=true；多风险组合（036：HR-02+HR-03、037：HR-04+HR-08、038：HR-05+HR-06）floor 均取最高等级。
- 风险等级唯一依据 `risk_levels.py`（HR-01/02/05/06/07/08=高，HR-03/04=中），未自行调整，未降低任何等级。

## 7. 多答案、质量缺陷、订单数量

- 多答案用例（relevant_chunk_ids>1）：**6 条**（007/035 组合、039、及 rule 组合等，执行前列全可接受片段）。
- 质量缺陷（HR-08）用例：**4 条**（034/035/037/049，四种不同故障）。
- 订单用例：**8 条 A 层 + 1 条 B 层（071）= 9 条**，全部依据 202609180001-0003 结构化数据；含有效 4 类事实查询、不存在（047/072 全新单号）、不完整（048 尾号）、订单+高风险组合 3 条（035/049/050），商品与订单归属逐一核对一致（无串单标注）。

## 8. 历史黑名单来源及查询数

`final_blind_v3_query_blacklist.json`：收集 **1763** 条，去重后 **1250** 条（SHA `4267713c…`）。

来源：final_blind_v2_query_blacklist 全量继承（传递覆盖 V3.0 旧黑名单/blind v1/V3.1 开发集/validation 双口径/V3.1 测试脚本/旧评测结果）+ final_blind_set_v2 + v3_2/v3_2_1 开发集 + V3.2 时代全部测试/调试/服务实测/构建/评测/冻结脚本字面量 + V3.2 评测结果 JSON + 调试转储与实测输出 + 旧人工审核/评审/勘误 md。黑名单仅用于泄漏检查，未交给任何检索器。

## 9. 泄漏检查结果

`check_final_blind_set_v3.py`（纯只读，禁止导入检索器/FastAPI/模型；ngram/LCS 仅在汉字上计算以排除订单号/型号固有重合）：**24/24 全部通过，一次性完成**。

- 01 case_id 唯一连续；02 query 唯一；03 黑名单零完全重复（1250 条比对）；04 集内规范化唯一；05 无 ≥10 字包含式同义改写（对黑名单+集内）
- 06 无高 bigram/trigram 重合（系数≥0.55）；07 无 ≥10 字公共子串；08 无商品/数字替换（中文骨架）；09 未复制知识库完整句子（≥12 字）
- 10/11 片段与规则 ID 存在且合法；12 枚举合法；13 supported 标注完整；14 不可回答用例片段为空
- 15 数量/难度/层分布正确；16 HR 全覆盖；17 风险等级与 risk_levels.py 一致；18 多风险取最高；19 高风险 handoff=true；20 订单引用合法且商品一致
- 21 label review 覆盖 80 条；22 无 API Key/PII；23 无运行后字段；24 17 候选文件哈希一致
- 修订记录：首轮 22/24，共重写 **7 条** query（BV3-002/005/013/073/075 + 二轮 002/073），仅改盲测题本身，未运行候选验证。

## 10. 人工抽查结果

`final_blind_set_v3_review_checklist.md`：分层抽查 **28 条**（product 3/faq 3/rule 6/multi 4/order 4/unsupported 3/irrelevant 3/API 2），HR-01..08 各至少 1 条。逐条结论：自然度高、与历史集合独立、标注依据可溯源、scope/风险/handoff 与正式映射一致、无测试诱导痕迹。**28/28 通过**。

## 11. 预先冻结目标（写入清单，运行前固定，不得修改）

Answer Hit@1 ≥85%；union Hit@3 ≥95%；coverage Recall@3 只报告；Rule Recall@3 ≥90%；HR-08 Recall@3 =100%；scope 准确率 ≥95%；unsupported 误放行 ≤5%；irrelevant 误放行 ≤5%；risk floor 符合率 =100%；高风险 handoff =100%；错误转人工率 ≤10%；订单路由与事实准确率 =100%；API 契约通过率 ≥90%；内部术语泄漏 =0；禁止承诺违规 =0；DeepSeek 真实调用 =0；预热后 P95 <100ms。

## 12. 新增文件

| 文件 | 说明 |
|---|---|
| backend/verify_candidate_for_blindv3.py | 步骤一候选核验（只读） |
| backend/build_final_blind_v3_blacklist.py | 步骤二黑名单构建 |
| backend/data/final_blind_v3_query_blacklist.json | 历史查询黑名单（1250 条去重） |
| backend/build_final_blind_set_v3.py | 步骤三盲测集构建器（80 条） |
| backend/data/final_blind_set_v3.json | **最终盲测集 v3（冻结）** |
| backend/data/final_blind_set_v3_label_review.md | 逐条标注审核（80 条） |
| backend/data/final_blind_set_v3_review_checklist.md | 人工抽查清单（28 条） |
| backend/check_final_blind_set_v3.py | 24 项泄漏与完整性检查（只读） |
| backend/freeze_final_blind_v3.py | 步骤十二清单冻结脚本 |
| backend/data/final_blind_set_v3_manifest.json | **冻结清单（status=frozen_pending_one_time_evaluation）** |
| backend/data/_blindv3_precheck_candidate.json / _blindv3_check_result.json | 核验与检查结果存档 |

## 13–18. 执行纪律声明

13. **是否运行任何检索器**：否（黑名单构建、泄漏检查、抽查均为纯文件读取/AST/哈希）。
14. **是否调用 /api/chat**：否（未启动 FastAPI，未查询 Chroma）。
15. **是否调用 DeepSeek**：否（0 次）。
16. **是否修改候选文件**：否（17 文件 SHA 前后一致，仅只读）。
17. **是否运行旧 blind**：否（v1/v2 均未重跑）。
18. **是否具备执行唯一一次 blind v3 评测的条件**：**具备**——候选冻结 all_match=true、盲测集 24/24 检查通过并冻结、目标预先固定、黑名单/审核/抽查资产齐备且哈希固化。

---

**结论：已通过。final_blind_set_v3 已冻结（status=frozen_pending_one_time_evaluation，execution_count=0）。按指令到此停止，不运行 blind v3，等待下一步唯一一次评测指令。**
