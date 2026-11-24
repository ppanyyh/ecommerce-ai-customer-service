# V3.1 第二阶段报告：标注口径定稿、回归复核与候选版本冻结

生成时间：2026-09-25 17:5x
范围：`09_V3_Vector_RAG/backend`。本阶段**未创建/未生成/未运行 final blind set v2，未运行旧 final_blind_set_v1，DeepSeek 调用 0 次，未修改 V2 / frontend / 05_AI_Demo。**

---

## 1. H-020 最终处理方式

**采用用户批准的双口径方案**：

- **原始 v1.1 标注保留并恢复为冻结文件** `data/hybrid_holdout_eval_cases_v1_1_frozen.json`
  （H-020 relevant = `["FAQ-015","FAQ-017"]`）。该文件是由 v1.2 依据
  `original_relevant_chunk_ids_h020` 字段反向恢复的**重建版**（原 v1.1 字节文件已被阶段一覆盖），
  恢复后冻结不可修改。SHA-256：`1a4192741fe848231b272932e8bd5af3e7896ab62ce77829b20b551f8af9fed8`
- **修订版另存为** `data/hybrid_holdout_eval_cases_v1_2_reviewed.json`（H-020 +FAQ-013 部分相关性），
  meta 中明确标记为 **annotation-corrected exploratory evaluation**（修订发生在看到检索结果之后，
  不参与最终盲测成绩）。SHA-256：`a126a126e4e189a6752f01677d712f5400cc0f959b133832064f2e0693d90ba6`
- FAQ-013 对 H-020 第一子问的"部分相关性"判断**被接受并保留**，但仅体现在 v1.2 口径。
- 无版本文件 `hybrid_holdout_eval_cases.json` 不再修订（保留阶段一现状），此后一律使用版本文件。

## 2. Validation v1.1 原始指标（旧检索兼容口径，冻结文件）

| 指标 | 结果 |
|---|---|
| Answer Hit@1 | 22/24 = **91.7%** |
| Answer Recall@3 | 23/24 = 95.8% |
| MRR | 0.9375 |
| Rule Recall@3 | 8/8 = 100% |

失败明细（共 2 条，均有明确归因，非检索缺陷）：
- **H-013**（发票）：V3.1 新业务口径判 `unsupported_business`（results=[]），旧口径下计 hit1/recall3 失败 → **有意业务语义变更**（见第 4 节）。
- **H-020**：hit1 miss——实际 Top-3 = `[FAQ-013, FAQ-015, FAQ-017]` 全部为 v1.2 相关集；按 v1.1 相关集计 Top-1（FAQ-013）不命中 → **部分相关性排序差异**，v1.2 口径已批准保留（v1.2 下该条 PASS）。

结果文件：`data/hybrid_v2_validation_results_v1_1_frozen.json`

## 3. Validation v1.2 修订指标（annotation-corrected exploratory）

| 指标 | 结果 |
|---|---|
| Answer Hit@1 | 23/24 = **95.8%** |
| Answer Recall@3 | 23/24 = 95.8% |
| MRR | 0.9583 |
| Rule Recall@3 | 8/8 = 100% |

**唯一失败为 H-013**（发票业务语义变更，同上）。除 H-013 外全部通过。
按用户要求：**不以 v1.2 的 23/24 宣称"完全零回归"**——旧检索兼容口径（v1.1）下存在
H-013（业务语义变更）与 H-020（部分相关性排序差异）两处已知偏差，均已如实列示。

结果文件：`data/hybrid_v2_validation_results_v1_2_reviewed.json`

## 4. DV-046：已恢复为 unsupported_business（用户裁定执行）

- `is_answerable=false`、`expected_supported=false`、`expected_scope=unsupported_business`、
  `relevant_chunk_ids=[]`（category 保持 uncovered_business）。
- 代码侧：`query_analyzer.py` 将发票从 supported 意图恢复为未覆盖意图
  `invoice_policy`（发票/开票/电子发票/专票/增值税/报销票据），删除对应改写。
- 依据：FAQ-018 只说明"资料未覆盖发票类型、条件和流程"并给出转人工步骤，
  **不构成发票政策答案**；存在兜底片段 ≠ 资料足够回答。
- 实测 DV-046 判定：`unsupported_business` ✓（scope 三分类 60/60 全对）。
- **H-013 与新口径的冲突处理**：未篡改旧验证集，v1.1/v1.2 中 H-013 均保持原始标注；
  其在新口径下的失败单独记录为 **V3.1 有意进行的业务语义变更**
  （旧检索兼容指标 vs V3.1 新业务口径指标已在第 2/3 节分别报告）。

## 5. 三分类门控定义（统一后）

| scope | 定义 | 行为 |
|---|---|---|
| `supported` | 知识库有足够事实/政策回答 | 正常检索作答 |
| `unsupported_business` | 属本店商品/订单/售后业务，但资料未覆盖具体政策/承诺/事实 | `results=[]`，面向用户给出下一步人工核实方式（"现有资料没有覆盖这项信息，建议联系人工客服确认。"） |
| `irrelevant` | 非电商客服业务 | `results=[]`，简洁说明仅协助商品/订单/售后 |

- 按用户裁定，以下类型一律 `unsupported_business`（除非知识库未来加入明确政策）：
  **发票类型和流程、未记录的促销活动、直播赠品、实时库存、未记录的配送时效承诺、未记录的新商品**。
- 门控实现位置：`query_analyzer.py`（三分类判定，优先级：风险意图 > 范围外 > 未覆盖业务 > 商品实体/已覆盖意图 > 泛化质量咨询 > unknown 兜底）+ `hybrid_retriever_v2.py`（拒答返回与 unknown 检索证据兜底，`KEYWORD_GATE_THRESHOLD=3.0 / VECTOR_GATE_THRESHOLD=0.40`）。
- `main.py` 核查结论：V3 混合检索**尚未接入** /api/chat（main.py 仍走 V2 `retriever.retrieve`，无冲突的门控语义）；三分类语义集中在 analyzer/retriever_v2，接入时按本定义执行。面向用户文案不含 HR 编号/SOP/门控/相似度/阈值。
- 高风险场景（HR-01~08）继续走风险意图 → 转人工，门控不拦截。

## 6. 开发集修正后指标（v3_1_dev_cases.json，60 条）

| 指标 | 目标 | 结果 |
|---|---|---|
| Answer Hit@1 | ≥85% | 36/40 = **90.0%** ✓ |
| Answer Recall@3 | ≥95% | 40/40 = **100%** ✓ |
| MRR | — | 0.95 |
| Rule Recall@3 | =100% | 17/17 = **100%** ✓ |
| supported 准确率 | ≥95% | 60/60 = **100%** ✓ |
| scope 三分类准确率 | ≥90% | 60/60 = **100%** ✓ |
| 不可回答误放行率 | ≤5% | 0/20 = **0%** ✓ |
| 质量缺陷 HR-08 进 Top-3 | 100% | 7/7 = **100%** ✓ |
| DV-046 判 unsupported_business | 必须 | **正确** ✓ |

剩余 4 条 hit1 miss（Recall@3/Rule 均通过）：DV-007（无实体 hard）、DV-025、DV-029、DV-032（FAQ 语义竞争类，相关内容在 Top-3 内）。

## 7. Scope 混淆矩阵（开发集）

| expected \ predicted | supported | unsupported_business | irrelevant |
|---|---|---|---|
| supported | **40** | 0 | 0 |
| unsupported_business | 0 | **10** | 0 |
| irrelevant | 0 | 0 | **10** |

全对角；误放行 0、误拦截 0。

## 8. HR-08（质量缺陷）结果

7 条缺陷用例（部件破损/渗漏密封/接触不良/拉链失效等，含已购语境约束）**全部**在 Top-3 命中 `RULE-HR-08`（7/7 = 100%）。

## 9. Validation 双口径回归汇总

- v1.1（旧检索兼容）：Hit@1 91.7%、Recall@3 95.8%、Rule 100%；偏差 = H-013（业务语义变更）+ H-020（部分相关性排序差异）。
- v1.2（annotation-corrected exploratory）：Hit@1 95.8%、Recall@3 95.8%、Rule 100%；唯一偏差 = H-013（业务语义变更）。
- 两口径均**未通过原"完全零回归"宣称**，偏差全部归因于已批准的业务语义/标注变更，无未解释回归。
- 延迟（validation，预热后）：v2 P50 13.4–15.7ms、P95 16.7–19.6ms；开发集 P50 14.87ms、P95(excl first) 20.83ms。

## 10. 数据泄漏检查

- **开发集 vs 旧 final blind set**（新脚本 `check_v3_1_dev_set.py`，规范化完全比对 + 字符 bigram Jaccard≥0.6 疑似改写筛查）：**exact=0，near=0，通过**。结果：`data/v3_1_dev_set_leakage_check.json`。
- 知识库泄漏检查 `check_leakage.py`：全部通过（retrieval_text 未泄漏评测问题、aliases/keywords 未新增、风险等级未修改）。
- 开发集独立性声明（已写入 `v3_1_dev_cases.json` meta.set_nature）：**本集合是开发集，允许调试迭代，曾依据失败结果修订标注并调整实现；其 100% 门控结果只证明开发集拟合通过，不能作为最终泛化成绩，不得称为盲测集。**

## 11. 修改和新增文件

**修改：**
- `query_analyzer.py`：发票恢复为未覆盖意图 `invoice_policy`（含口径注释），删除 invoice supported 意图与改写。
- `evaluate_hybrid_v2.py`：新增 `--cases` / `--out` 参数支持双口径评测；结果记录实际用例文件名。
- `data/v3_1_dev_cases.json`：DV-046 恢复 + meta（annotation_revision 追加用户批准记录、set_nature 独立性声明）。SHA-256：`5d0643bdc1bf084fea8e4205b505b57069d2aa24b88c999d9f76ba1522744c70`

**新增：**
- `data/hybrid_holdout_eval_cases_v1_1_frozen.json`（冻结，SHA `1a419274…`）
- `data/hybrid_holdout_eval_cases_v1_2_reviewed.json`（SHA `a126a126…`）
- `check_v3_1_dev_set.py` + `data/v3_1_dev_set_leakage_check.json`
- `apply_v3_1_phase2_annotations.py`（标注定稿执行脚本，留档）
- `data/hybrid_v2_validation_results_v1_1_frozen.json` / `…_v1_2_reviewed.json`
- `data/v3_1_candidate_freeze_manifest.json`
- 本报告

**未修改：** main.py、hybrid_retriever_v2.py、keyword_retriever_v3.py、vector_retriever.py、build_vector_index.py、schemas.py、prompts.py、knowledge_chunks.jsonl、无版本 `hybrid_holdout_eval_cases.json`、全部 final_blind_* 资产。

## 12. 候选冻结清单及 SHA 校验

`data/v3_1_candidate_freeze_manifest.json`（生成后立即全量重算哈希，**all_match=true**），冻结 10 个候选文件：

query_analyzer.py、keyword_retriever_v3.py、vector_retriever.py、hybrid_retriever_v2.py、build_vector_index.py、main.py、schemas.py、prompts.py、data/knowledge_chunks.jsonl、data/index_manifest.json

同时记录：Python 3.12.0 / chromadb 1.5.9 / sentence-transformers 6.1.0 / BAAI/bge-small-zh-v1.5 / 512 维 / collection `ecommerce_kb_v1` / data_version 1.2；RRF_K=60、双路权重 1.0/1.0、Top-N 10/10、EPSILON=0.0003、ALIAS_BOOST=0.0002、门控阈值 3.0/0.40（无独立门控配置文件，参数为模块常量随文件冻结）；风险规则映射 = V2 kb 口径 8 条 HR 规则未新增。

## 13. 是否运行过旧 final blind set

**否。** 仅以只读方式读取 `final_blind_set_v1.json` 的 query 字段做泄漏比对（第 10 节），未执行任何检索评测。`old_final_blind_reexecuted=false`。

## 14. DeepSeek 调用次数

**0 次**（本阶段全部为本地检索/评测/检查）。

## 15. 是否具备创建独立 final blind set v2 的条件

**具备**：候选代码与索引已冻结且 all_match=true；门控三分类口径经用户裁定定稿；开发集独立性/泄漏检查通过；双口径 validation 结果与偏差归因清晰；评测工具链（延迟统计、防泄漏检查）就绪。**但按本阶段指令，暂不创建、不生成、不运行 final blind set v2**，等待下一步独立生成新盲测集的指令。

---

### 冻结后限制（已生效）

不再修改候选代码 / knowledge_chunks / 阈值；不依据旧盲测结果增加关键词；暂不创建 final blind set v2；暂不接入 /api/chat 正式评测。
