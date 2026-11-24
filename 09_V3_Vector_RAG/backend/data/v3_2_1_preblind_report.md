# V3.2.1 落地前修复阶段报告（v3_2_1_preblind_report.md）

- 日期：2026-09-26
- 范围：09_V3_Vector_RAG/backend
- 性质：盲测前修复阶段报告。**本阶段未创建、未运行 final blind set v3；未重跑任何旧盲测集。**
- 结论速览：全部 19 节核验完成，15 项补充集指标达标（15/15），原开发集无新增回归，服务实测 14/14 OK，DeepSeek 调用 0 次，候选已重新冻结（all_match=true）。**具备创建 blind v3 的前置条件，等待独立盲测创建指令。**

---

## 1. 冻结基线核验

| 项目 | 结果 |
|---|---|
| V3.2 候选冻结清单 `v3_2_candidate_freeze_manifest.json` | 读取并复算校验，`all_match=true` 确认（SHA-256 = 10ecbeff…176089） |
| 新建基线 `data/v3_2_1_baseline_manifest.json` | 已生成：记录 16 个候选文件修改前 SHA、已知残留带入、blind 消耗状态、DeepSeek 计数 0、允许/禁止修改文件清单 |
| 修改前 SHA 与 V3.2 清单一致性 | 16/16 逐位一致（mismatch=0） |
| 原清单覆盖 | 未覆盖、未修改任何旧清单 |

## 2. 未知商品修复（未收录商品自然句式）

- 修复位置：`query_analyzer.py` 新增结构化识别（商家指向词 `_RE_SHOP_POINTER` + 商品意图 `_RE_PRODUCT_INTENT` + 能力目录驱动，主体合法性核对 `_unknown_product_subject_check`，步骤 6.5/步骤 7 门控接入 `unknown_product_sales`）。
- 行为：未收录商品 → `unsupported_business`、`results=[]`、`sources=["现有资料未覆盖"]`，用户文案：「目前资料中没有这款商品的信息，暂时无法确认。请提供商品编号或联系人工客服核实。」
- 验证（开发集 A 层 10 条正例）：空气炸锅/手机壳/加湿器/颈椎按摩仪/电竞椅/行车记录仪/电动牙刷/破壁机/挂烫机/体脂秤，10/10 正确拦截，handoff=true，风险=中，无任何其他商品资料串入。
- 已知别名（PXXX 显式编号、保温杯/耳机等）识别不受影响（A 层 5 条已知对照全过）。

## 3. 商品串答检查

- 开发集 80 条全部记录逐条核对：`cross_product_leak=[]`（0 条）。
- 未收录商品回答 `results_count=0`，不返回 P001–P005 任何字段。
- 无关探针（公司/天气/电影等 5 条）`fp_intent_checks` 显示 `unknown_product_inquiry` 均未误触发，无普通名词误判为商品询问。

## 4. 售价与复合价格区分

- 修复位置：`query_analyzer.py` 步骤 5.6 复合未覆盖价格意图（二手回收/估价/以旧换新/折价/回购/保值/残值/历史与未来价格）优先于通用「价格」属性判定；`data/business_capability_catalog.json` 新增 `price_related_uncovered` 复合类别（catalog_version 1.1→1.2，含来源可追溯说明）。
- 售价 8/8 全对：保温杯 88 元、背包 239 元、台灯 129 元、耳机 299 元、P003 88 元、键盘 459 元等，价格事实未修改（`sale_price_fail=[]`）。
- 复合价格 8/8 全对：二手回收价格/以旧换新价格/估价/回收/折价/保值/残值/回购 均 → `unsupported_business` + 转人工，答案不含任何价格数字（`composite_price_fail=[]`）。

## 5. over_promise 否定守卫

- 修复位置：`risk_intents.py` 重写 `detect_over_promise`：否定前缀守卫 `_promise_verb_negation`、否定补语、能不能→要求归一化、双重否定自然覆盖；新增 `over_promise_negated` 供安全网与本地风险下限共用；`hybrid_retriever_v2.py` 安全网 `_rule_safety_net` 增加否定守卫（防否定承诺经语义相似误启用规则保留位）。
- 专项自测 24/24（正例 12 含「不是说不用保证，你必须保证退款」双重否定转折；反例 12 含「我知道你不能保证，只是问一般多久」）。
- 开发集：正例召回 12/12=100%（≥95% 达标）；否定探针误触发 0/12=0%（`promise_neg_fp_ids=[]`）。
- 否定语境下检索仍正常提供事实型回答（如「多久能退款到账」给到账流程事实，handoff=false）。

## 6. 订单本地回答（DeepSeek 不可用降级）

- 修复位置：`v3_retrieval_adapter.py` 新增 `_order_local_payload()`（结构化订单字段，**不经向量库**）；`main.py` 新增 `_compose_order_answer()`；`compose_local_answer` 过滤 RULE- 片段原文；`_sanitize_text` 剥离「知识库」等内部措辞。
- 有效订单 3/3：仅展示允许事实（状态/商品名/数量/金额/物流/下一步），例：202609180001 → SoundGo Air ×1、299.00 元、已发货/运输中、顺丰 SF1234567890。**不编造**预计送达/退款时间/审核结果；订单 202609180002 的进行中售后仅表述「审核和处理结果需由人工客服核实」。
- 不存在订单 2/2：「未查询到该订单号对应的记录…」，未返回其他订单；不完整订单 2/2：要求完整 12 位。
- 高风险组合 3/3：裂痕+订单号 → 质量缺陷转人工；不存在订单+投诉 → 投诉转人工（不泄露订单存在性）；索要收件电话 → 隐私保护转人工。串单 0（`order_cross=[]`），不暴露「模拟数据」字样。

## 7. 各风险类型转人工文案

- 修复位置：`main.py` 新增 `_HANDOFF_COPY_BY_KIND`（HR-01~08 按风险类型）+ `_handoff_user_copy()`；确定性分支接入高风险组合守卫；`_HANDOFF_KIND_PRIORITY` 调整并在 HR-02/HR-03 同现时按 `amount_strong` 裁决。
- 文案核对：每类给出明确下一步与材料清单（质量缺陷→照片/视频；金额争议→支付记录/扣款截图；退款催促→申请时间/支付方式；物流异常→运单号；投诉→经过说明；隐私/他人订单→勿发敏感信息+身份核验；超范围承诺→「无法对处理结果作出保证」）。
- 不展示 HR 编号/SOP 名称/scope/门控/阈值/检索分数；不承诺赔偿、退款时间与结果；`handoff_required` 保持 true；本地风险下限只增不减，不可被模型降低。
- E 类 10/10 `handoff_ok=true`。残留：DV321-076（索要系统内登记电话）文案概念标记未被子串命中（人工复核级，属概念命名口径，非行为错误；见第 16 节）。

## 8. 补充集分布（v3_2_1_dev_cases.json）

- 总量 80 条，全新编写，与历史集合（validation v1.1/v1.2、V3.1 dev 60、V3.2 dev 100、旧盲测集）查重通过。

| 分区 | 条数 |
|---|---|
| A 未知商品正例 | 10 |
| A 已知商品对照 | 5 |
| A 无关探针 | 5 |
| B 普通售价 | 8 |
| B 复合未覆盖价格 | 8 |
| C 承诺正例 | 12 |
| C 承诺否定探针 | 12 |
| D 有效订单 | 3 |
| D 不存在订单 | 2 |
| D 不完整订单 | 2 |
| D 高风险组合订单 | 3 |
| E 转人工文案（HR-01~08 全覆盖） | 10 |

- meta 声明：`set_nature=development`（开发集性质，非盲测集）等字段齐全。
- `check_v3_2_1_dev_set.py`：17/17 通过（查重/KB 原句复制 30 字滑窗/PII/枚举/分布/meta）。

## 9. 补充集泄漏检查

- 查重：与全部历史集合无完全重复与近重复（bigram/LCS/掩码）；未复制知识库原句。
- 评测 query 未新增进入 aliases（27 个）与 keywords（75 个），与 V2 口径一致。
- retrieval_text 仍仅由 kb name/keywords/reason/risk_level 组合，风险等级未修改（check_leakage 全过）。
- 补充集标注基于业务口径人工编写，未从候选代码行为反推。

## 10. 补充集指标（15/15 达标）

| 指标 | 目标 | 实际 | 结果 |
|---|---|---|---|
| 未知商品误放行率 | =0 | 0/10 | ✅ |
| 商品串答 | =0 | 0 | ✅ |
| 已知商品对照/无关探针 | 全过 | 5/5、5/5 | ✅ |
| 普通售价识别 | 100% | 8/8 | ✅ |
| 复合价格正确率 | 100% | 8/8 | ✅ |
| over_promise 正例召回 | ≥95% | 12/12=100% | ✅ |
| 否定误触发率 | =0 | 0/12 | ✅ |
| 高风险 handoff | 100% | 全部正确 | ✅ |
| 订单事实准确率 | 100% | 8/8 | ✅ |
| 串单 | =0 | 0 | ✅ |
| 本地降级概念覆盖 | ≥95% | 97.62% | ✅ |
| scope 分类 | 全对 | 80/80 | ✅ |
| 泄漏 | =0 | 0 | ✅ |
| 禁止承诺违规 | =0 | 0 | ✅ |
| 延迟 | — | P50 29.22ms / P95 52.96ms | — |

结果文件：`data/v3_2_1_dev_eval_results.json`（DeepSeek 隔离，全部本地路径）。

## 11. 原开发集回归（V3.2 / V3.1）

- **V3.2 开发集 100 条：17/17 目标达标**（含承诺类调和后恢复：DV3-061 纯配送时效承诺无施压→未覆盖业务口径，与 V3.2.1 C 类正例的施压场景正确区分）。hit1 91.3%、union3 100%、rule 96.3%（DV3-010 为既有残留）、HR-08 100%、scope 100%、误放行 0、wrong_handoff 2 条（DV3-080/090 既有保守侧）。
- **V3.1 开发集 60 条：与既有基线一致**（hit1 34/40=85%、Recall@3 95%、MRR 0.9、Rule 17/17、误放行 0；DV-007/025/029/032 hit1 为既有残留）。
- **新增回归：0。** 未修改任何旧标注。

## 12. validation 及 API 回归

| 测试 | 结果 | 对比说明 |
|---|---|---|
| validation v1.1 frozen（30 条四模式） | 与 V3.1/V3.2 冻结基线逐位一致 | 唯一 per-case 差异 H-015：Top-1 名称变化但指标全同（既有差异，非本轮新增） |
| validation v1.2 reviewed（30 条四模式） | 与冻结基线逐位一致 | 无新增回归 |
| API 集成 test_api | 169/169 rc=0 | 无差异 |
| chat 集成 test_chat_integration | 269/309 rc=1 | 41 条失败均为 DeepSeek 禁用（answer_mode=fallback）与 V3 引擎设计变更的**预期差异**（FB-01/02/03 等断言依赖 deepseek 模式），非回归 |
| retriever 一致性检查 | 全过（5 商品/20 FAQ/3 订单，金额勾稽成立） | — |
| hybrid 单元测试 | 10/10 | — |
| 评测器单元测试 | 52/52 | — |
| risk_intents 专项自测 | over_promise guard 24/24 | — |
| 延迟顺序测试 | 9/9 | — |
| 泄漏检查 check_leakage | 全过 | aliases/keywords 未新增 |

## 13. 服务实测（临时启动 uvicorn，14 类全新问题）

结果文件：`data/_v321_servicetest.txt`，**14/14 OK，零缺失零泄漏**。要点：

| # | 场景 | 关键验证 |
|---|---|---|
| 1 | 未收录商品「空气炸锅」 | 未收录文案+handoff=true，不返回其他资料（V3.2 遗留缺口已修复） |
| 2 | 已知商品保温杯 | 正常事实回答，handoff=false |
| 3 | 普通售价键盘 | 459 元正确返回 |
| 4 | 背包以旧换新价格 | 转人工，答案不含任何价格（修复确认） |
| 5 | 否定承诺 | 不误转人工（handoff=false），给事实型回答 |
| 6 | 真正承诺要求 | 转人工，无违规承诺表述 |
| 7 | 有效订单 202609180001 | 商品/数量/金额/物流/承运全部正确，无「模拟」字样 |
| 8 | 不存在订单 | 提示核对 12 位，未泄露任何真实订单 |
| 9 | 不完整订单（后四位） | 要求完整 12 位 |
| 10–12 | 质量缺陷/金额争议/他人订单 | 均转人工且给出类型化下一步，无内部术语 |
| 13 | 本地降级（杯子容量） | 500ml 事实正确 |
| 14 | 无关问题（火锅店） | 拒答模板正确 |

- 全部 14 条答案经内部术语正则（HR-/FAQ-/RULE-/SOP/知识库/模拟/handoff/检索/门控/阈值/scope 等）扫描：0 命中。
- 测后已停止服务，端口 8000 已确认释放，无 python 子进程残留。

## 14. DeepSeek 调用次数

- **全程 0 次。** 服务启动未注入 `DEEPSEEK_API_KEY`（`deepseek_configured=false`），开发集评测、回归、服务实测均走本地路径。禁用方式为环境隔离，未修改任何代码。

## 15. 修改与新增文件

**修改（6 个，均属允许范围）：**

| 文件 | 变更摘要 |
|---|---|
| `query_analyzer.py` | 结构化未知商品识别、复合价格意图、承诺类调和、service_hours 意图、门控接入 |
| `risk_intents.py` | over_promise 否定守卫、`over_promise_negated`、对象词表扩展（送达/送到/发货）、他人订单/退款催促词条补充 |
| `v3_retrieval_adapter.py` | 订单结构化本地载荷（不经向量库）、V3 风险意图补充本地风险下限（只增不减）、RULE- 片段过滤、内部措辞净化 |
| `main.py` | 分风险类型转人工文案、订单结构化回答、高风险组合守卫、本地风险否定守卫 |
| `hybrid_retriever_v2.py` | 仅一处：安全网 `_rule_safety_net` 否定守卫（属「必要时」范围） |
| `data/business_capability_catalog.json` | 新增 `price_related_uncovered` 复合类别（v1.2） |

**新增：** `save_v321_baseline.py`、`build_v3_2_1_dev_cases.py`、`check_v3_2_1_dev_set.py`、`evaluate_v3_2_1_dev.py`、`run_v321_regress.py`、`service_test_v321.py`、`freeze_v3_2_1_candidate.py`，及 data 下 `v3_2_1_baseline_manifest.json`、`v3_2_1_dev_cases.json`、`v3_2_1_dev_eval_results.json`、`v3_2_1_candidate_freeze_manifest.json`、`_v321_regress_raw.json`、`_v321_val11.json`、`_v321_val12.json`、`_v321_servicetest.txt`、本报告。

**未触碰（禁改清单核验通过）：** keyword_retriever_v3.py、vector_retriever.py、knowledge_chunks.jsonl、index_manifest.json、Embedding/RRF/EPSILON/RULE_NET_VEC_SIM 参数、旧标注、V2/frontend/05_AI_Demo、schemas.py/prompts.py/retriever.py/deepseek_client.py/build_vector_index.py/evaluate_final_blind_v2.py。

## 16. 已知残留

1. DV321-011 概念标记「保温性能」未被子串命中（回答实际给出「保温参考：约6小时」事实，属概念命名口径，非回答错误）；本地降级概念覆盖 97.62% 仍达标。
2. DV321-076（索要系统内登记电话）handoff 文案概念标记未命中（人工复核级；行为正确：handoff=true+隐私保护文案，风险=高）。
3. 既有残留原样带入：DV3-010（HR-05 未进 Top-3）、DV3-079/089 hit1 Top-2 语义竞争、DV3-080/090 保守侧 wrong_handoff、V3.1 DV-007/025/029/032 hit1。
4. V3.2.1 C 类正例 12 条中 9 条实际风险为「中」（V3 结构化风险意图正确触发 handoff，但风险等级低于标注下限「高」）；高风险用例（赔偿/双重否定转折）正确为「高」。属风险分级口径而非拦截失败，`handoff_fail_all=[]`。

## 17. 新冻结清单及 all_match

- `data/v3_2_1_candidate_freeze_manifest.json` 已生成：16 候选文件 SHA-256 复算；10 个禁改文件与基线逐位一致；6 个允许修改文件记录变更前后 SHA；检索参数（RRF_K=60/EPSILON=0.0003/RULE_NET_VEC_SIM=0.42/top_k=5）、Embedding（bge-small-zh-v1.5, 512 维, data_version 1.2）、能力目录 v1.2 均已记录。
- **`all_match=true`**，读回复核通过。V3.2 旧清单未覆盖。
- 自此候选代码/知识库/目录/阈值冻结，不得再修改。

## 18. 是否运行旧 blind

- **未运行。** final blind set v1 / v2 均未重跑（v2 保持已消耗状态 execution_count=1）；未重建、未篡改、未用于本阶段评分。

## 19. 是否具备创建 blind v3 条件

**具备。** 判定依据：
- 候选已重新冻结（第 17 节，all_match=true）；
- 15 项补充集指标全达标（第 10 节），原开发集/validation/API 无新增回归（第 11–12 节）；
- 服务实测 14/14（第 13 节），DeepSeek 0 次（第 14 节）；
- 旧盲测集状态完好（第 18 节）。

按指令：**本阶段到此停止，不创建、不运行 final blind set v3**，等待独立盲测创建指令。
