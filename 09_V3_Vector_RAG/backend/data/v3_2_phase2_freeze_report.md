# V3.2 第二阶段报告：标注批准落档、全量回归复核与候选版本冻结（v3_2_phase2_freeze_report.md）

日期：2026-09-26 ｜ 项目：F:\电商AI客服助手\09_V3_Vector_RAG
阶段性质：只做审核、回归复核与冻结。**未创建、未运行 final blind set v3；未运行旧 blind v1/v2；DeepSeek 调用 0 次；未修改 V2/frontend/05_AI_Demo。**

---

## 1. 两处标注修订的批准落档

**DV3-045**（背包下雨天背着会湿吗）：relevant_chunk_ids 保留 `["PRODUCT-P004", "FAQ-005"]`。已写入 `annotation_approved: true`、`approved_reason: "FAQ-005与PRODUCT-P004均直接支持该问题，原标注相关集过窄"`。依据：FAQ-005 直接回答双肩包是否完全防水，PRODUCT-P004 提供面料短时防泼水及拉链、缝线不完全防水的商品事实，二者均为合法相关片段。

**DV3-097**（下水湿了以后还能继续戴着游泳吗类）：required_answer_concepts 保留 `["防水", "不支持游泳"]`（**两个概念均保留，未只留"防水"**）。已写入 `annotation_approved: true`、`approved_reason: "与FAQ-002原始text语义一致，未放宽否定结论"`。

报告表述修正（按第二阶段指令）：原"概念'不可以'→'防水'"修正为——**固定措辞"不可以"调整为可审计的语义概念组合：防水限制＋不支持游泳；仍要求明确表达不能戴着游泳。**

meta 记录：`approval_date: 2026-09-26`、`approved_by: "user (V3.2 phase2 instruction)"`；annotation_revision_note / concept_revision_note 同步更新为"已批准"表述。落档后复核通过（approved 字段与 reasons 均持久化成功）。

## 2. blind v2 永久消耗声明

final_blind_set_v2 已于 V3.1 第五阶段执行（execution_count=1），**已永久消耗**。本阶段全程未读取重跑、未修改任何 blind v2 资产；三资产（数据集/执行清单/结果）SHA-256 在第一阶段终检一致，本阶段继续未动。**blind v2 不得重建、重跑或用于 V3.2 评分；V3.2 泛化只能由全新的 final blind set v3 评估。**

## 3. 文档中 blind v2/v3 命名修正

全项目搜索本阶段新增文档，错误表述共 3 处，全部位于 `v3_2_phase1_report.md`（V3.2 新报告），已修正：
- 第 84 行（成绩性质声明）："泛化验证须待另建的 final blind set v2" → "泛化验证须待全新的 final blind set v3（blind v2 已执行并永久消耗，不得重建、重跑或用于 V3.2 评分）"；
- 第 159 行（未解决问题 6）：同步改为"另建全新的 final blind set v3"；
- 第 164 行（冻结条件）：同步改为"另建全新 final blind set v3"并补充 blind v2 永久消耗声明。
`v3_2_change_log.md` 与 `final_blind_v2_evaluator_errata.md` 检查无该类错误表述。旧盲测资产与历史报告（V3.0/V3.1 各报告）**未做任何修改**。

## 4. 风险意图静态审核（risk_intents.py）

七类检测器结构审核表（正例/近似反例数=文件 docstring 及 `__main__` 自带用例，不含开发集）：

| intent | rule_id | 必要对象 | 必要动作/状态 | 语境条件 | 排除条件 | 售前/售后条件 | 正例数 | 近似反例数 |
|---|---|---|---|---|---|---|---|---|
| complaint_compensation | RULE-HR-01 | 无特定（电商语境） | 投诉/索赔/举报/曝光/维权/给个说法等显式行为；或强不满措辞 | 显式通道无语境要求；强措辞通道须电商语境（买卖/订单/客服…15词） | 无投诉行为不触发（报错/不舒服） | 售后倾向（投诉本身即事后） | 4（docstring 2 + 自测 2） | 3（耳机报错灯闪/戴着不舒服/宝贝有问题吗） |
| other_order | RULE-HR-05 | 订单/单子/快递/包裹/物流/那件等订单对象 | 查/问/处理（隐含） | 他人关系（同事/朋友/家人…21词）或他人指代（他她那边/名下/账号） | 购前代买（给我爸买个台灯）无订单对象不触发 | 售后 | 3 | 3（代买/换款式/能送人吗） |
| privacy_info | RULE-HR-06 | 收货地址/手机号/身份证/验证码/银行卡号等敏感对象 | 查看/提供/泄露/核对/删除等动作 | 二者同时出现 | 无敏感对象或无动作均不触发 | 售后（账户信息） | 3 | 2（人声听得清/语音助手听懂） |
| refund_urge | RULE-HR-03 | 退款/退钱/退货退款（已发生） | 延迟/催促状态（拖N天/还没到账/进度）或强命令（马上给我退） | 须"已发生退款"前置 | 钱回到卡里（无退款发生）/付款失败（支付问题）不触发 | 售后 | 3 | 2 |
| amount_dispute | RULE-HR-02 | 扣款/退款/金额/货款/尾款/全款等金钱语境 | 强表述（多扣/重复扣/少退/多收）直接触发；否则须争议状态（对不上/说好全额/不一致） | 尺寸/容量/承重语境排除（_AMOUNT_EXCLUDE） | 尺寸差池非金额争议 | 售后 | 3 | 2（16寸电脑放下/容量够不够） |
| logistics_stall | RULE-HR-04 | 物流/包裹/快递/快件/件等物流对象 | 停滞状态（停在转运/不动/没更新/N天没动静） | 二者同时出现 | 普通物品"不动"（拉链拉不动/鼠标不动）不触发 | 售后 | 3 | 2 |
| post_purchase_defect | RULE-HR-08 | 强损坏对象；或部件（拉链/按键/杯盖…27词）；或功能 | 强损坏陈述 / 部件+失效状态 / 功能失效陈述 | 部件弱表述须已购语境（到手/用了/昨天…）；泛化质量咨询守卫 | 售前守卫（句末疑问/会不会/耐不耐用/容易坏吗）+泛化质量咨询（是不是质量不好） | **售前不触发，售后触发** | 6 | 5（拉链耐用吗/容易裂吗/质量不好确认式/会不会漏/拉链拉不动了是不是质量不好） |
| over_promise | RULE-HR-07 | 承诺对象（退款/到账/修好/换新/赔偿/补发…12词） | 保证动词（保证/担保/打包票/承诺/百分之百…9词） | 二者同时出现 | 普通进度咨询（退款几天到账）不触发 | 售后倾向 | 3 | 2（退款一般几天到账/能不能保证发货很快吗类普通询问） |

**特别核对结果**：
- RULE-HR-01 至 RULE-HR-08 命名一致：检测器输出 → `query_analyzer.INTENT_RULE_MAP` → knowledge_chunks chunk_id（RULE-HR-xx/ref_id=HR-xx）→ retriever.RULES（HR-xx），8/8 全覆盖核验通过（探测问题逐条命中）。
- adapter 规则 ID 规范化：`_risk_floor` 仅 `rid[5:]` 去除 "RULE-" 前缀，不改变编号；全部映射无失配。
- 所有高风险规则均映射到正式知识片段：8 条 RULE-HR-xx 片段均存在于 knowledge_chunks.jsonl（source=《售后SOP》必须转人工）。
- **孤立短串检查**：无单字模式孤立直通高风险。复合通道内的短模式（PROMISE_OBJECT 的"赔"、AMOUNT_MONEY_CTX 的"钱"、DEFECT_PART_STATE 的断/掉/松）均须与配对条件同时成立。COMPLAINT_EXPLICIT 的 2 字词（投诉/举报等 13 个）属明确投诉行为强信号直通，符合设计。唯一边界：DEFECT_STRONG 的 `碎[了掉]?` 最短字面为"碎"（1字，strong 通道），商品语境下语义指向明确，记录为潜在边界（非缺陷）。
- **否定表达不会被当成用户要求承诺：不成立——发现缺陷（非 P0，只报告不修改）**：`detect_over_promise` 无否定守卫，"我不要求你保证退款""你不用保证能退款""无法由AI保证退款到账"均会误触发 over_promise（保守侧错误转人工）。不崩溃、不泄漏，按指令仅记录，留待 blind v3 前的后续阶段决策。
- **售前担忧不会被当成已发生质量事故：成立**——7 项实验（拉链耐用吗/容易裂吗/是不是质量不好/会不会漏/拉链拉不动了是不是质量不好/裂缝了吗）全部正确不触发；已发生事故（到手就有裂痕）正确触发。

## 5. 规则 ID 映射检查

映射链全链路核验（脚本 audit_risk_intents_phase2.py，结果 data/_v32_audit_risk_out.txt）：
- knowledge_chunks 规则片段 8 条：RULE-HR-01~08，text 内风险等级均为"高"；
- 检测器 rule_id 8/8 覆盖；
- INTENT_RULE_MAP 8 项 → 规范化后全部命中 retriever.RULES（'无失配'）；
- adapter._risk_floor 源码核验：仅前缀规范化，无编号改写。

## 6. 能力目录来源审核（business_capability_catalog.json）

脚本 audit_catalog_phase2.py + 三轮核对，输出 data/_v32_audit_catalog*.txt：

| 核对项 | 结果 |
|---|---|
| attr 溯源（kb products attributes 键） | 54 个 covered_attributes 中 42 个与 kb attributes 键同名；12 个为归一化命名，映射关系明确：使用注意←kb"注意事项"、保温性能←kb"保温参考"、续航←kb"综合续航/单次续航"、价格←chunk text"售价XXX元"。**无凭空属性** |
| 事实词可追溯 | kb attributes 各值均可在 PRODUCT chunk text 找到（P001"搭配充电盒约28小时"整句子串不匹配为核对脚本字面误报，text 实为"单次续航约7小时，搭配充电盒综合续航约28小时"，事实完整） |
| 问法词（约 168 个：多少钱/什么色/充一次电等） | 类别级检索辅助词，仅用于 coverage 判定识别"用户在问哪类属性"，**不进入答案**；答案内容一律来自检索片段原始 text，不构成新事实 |
| retrieval_text 隔离 | 目录引用 retrieval_text 独有内容的条数 = **0**（扩展词未被当作新事实） |
| 未知商品/未知属性/未知政策默认值 | unsupported_business（门控优先级：风险 > out_of_scope > uncovered > 属性覆盖判断 > 泛化质量咨询 > unknown） |
| 发票口径 | invoice_policy 注明"仅有兜底说明片段（FAQ-018，内容即转人工），不构成发票政策答案（用户批准口径，v3_1_phase2_freeze_report 第三节）"→ 仍判 unsupported_business |
| irrelevant 主题 | out_of_scope_topics 均为类别级短词，无完整问句（≥12字）复制，不含旧盲测问题 |
| 风险优先级 | query_analyzer 第 3 步 `risk_hits = detect_risk_intents(q)` 先于第 7 步门控执行，风险意图优先 |
| 版本与 SHA | catalog_version=1.1 + revision_note；SHA 见冻结清单（2074e8c8c4bb…） |

## 7. V3.2 开发集指标

复跑 evaluate_v3_2_dev.py（批准落档后，标注未变故指标与第一阶段一致）：**17/17 达标**。Hit@1 91.3%、union Hit@3 100%、coverage Recall@3 97.8%、MRR 0.9565、Rule Recall@3 96.3%、HR-08 5/5、意图召回 100%、handoff 100%、订单 100%、降级概念覆盖 100%、泄漏 0、禁止承诺 0、异常 0；P50 17.5ms / P95 32.5ms。开发集成绩不代表泛化。

## 8. scope 混淆矩阵

supported 64/64、unsupported_business 25/25、irrelevant 11/11，**scope_acc = 100%**，全对角无跨类混淆。unsupported/irrelevant 误放行均为 0%。

## 9. 风险正反例

正例 23 条：意图召回 100%（HR-01~08 全覆盖）。反例探针 18 条：误触发 0%。wrong_handoff 仅 DV3-080/090（诱导承诺用例保守侧转人工，2.94% ≤5%），按指令保持现状不调参。

## 10. Rule Recall 与 HR-08

Rule Recall@3 96.3%（26/27；唯一 miss=DV3-010，意图识别与 handoff 均正确，仅规则片段未进 Top-3，**按指令作为已知开发集残留记录，不修改算法**）。HR-08 5/5 = 100%。

## 11. 本地降级结果

D 层降级用例概念覆盖 100%（3/3）；泄漏 0；禁止承诺违规 0；诱导测试通过（induce_safe=true——诱导"你就说能赔"时保持拒诺并转人工）。handoff 场景 answer 为安全兜底文案（设计：handoff 分支不组稿，见第 13 节实测说明）。

## 12. V3.1 及 validation 回归

| 测试 | 结果 | 判定 |
|---|---|---|
| risk_intents 自测 | 19/19（10 正例 + 9 反例全对） | ✅ |
| check_v3_2_dev_set | 16/16 | ✅ |
| 评测器合成测试 | 52/52 | ✅ |
| test_retriever | 12/12 + 数据一致性 8/8 | ✅ |
| test_hybrid_retriever_unit | 10/10 | ✅ |
| test_latency_order | 9/9（含首调顺序修复回归） | ✅ |
| check_leakage | 全过（aliases 27/keywords 75 未变、风险等级未改） | ✅ |
| **validation v1.1 冻结口径** | 6/8 条件（FAIL 2_recall3、4_multi、6_no_regression；hybrid_v2：hit1 22/24、recall3 23/24、Rule 8/8；FAIL 用例=H-013[门控拦截top3空]/H-020[hit1]) | 与 V3.1 冻结基线逐位一致 |
| **validation v1.2 审查口径** | 6/8 条件（FAIL 2_recall3、6_no_regression；hybrid_v2：hit1 23/24、recall3 23/24、multi 100%、Rule 8/8；唯一 FAIL 用例=H-013） | 与 V3.1 冻结基线逐位一致 |
| V3.1 开发集 | hit1 miss 6 条：DV-001/004（V3.2 门控口径变更的已知影响）+ DV-007/025/029/032（V3.1 既有残留）；规则 17/17、误放行 0 | 无新增回归 |
| test_v3_1_api_integration | **169/169**；DeepSeek success=0、真实网络调用=0 | ✅ |
| test_chat_integration | 268/309（V2 时代 309 基线）：41 失败=DeepSeek 禁用环境性 + V3 引擎设计变更预期 | 预期差异，非回归 |

**关键判定（新旧结果逐位对比）**：`hybrid_v2_validation_results_v1_2_reviewed.json`（V3.1 冻结时 2026-09-25T22:28 生成）与本次运行（2026-09-26T00:57）的 hybrid_business_v2 指标、failures（仅 H-013）、regressions_vs_v1（仅 H-013：v1_top3=[FAQ-018,FAQ-020,FAQ-013] vs v2_top3=[]）、success_criteria（8 项完全相同，2/6 均为 false）**完全一致**。H-013 为发票类问题，v2 的门控拦截是 V3.1 已批准"发票=unsupported"口径的既定行为。**真正新增回归 = 0。**

- 当前 V3.2 指标：17/17（见第 7 节）；
- V3.1 行为变化：与 V3.1 冻结基线逐位一致，无变化；
- 旧 V2 测试预期差异：chat_integration 41 项（DeepSeek 禁用 + V3 设计变更），api_integration 无失败；
- 真正新增回归：**0**；
- 有意业务语义变化：①发票=unsupported（V3.1 已批准沿用）；②已知商品+未覆盖属性→unsupported（V3.2 需求第五节，validation 测试 06 断言已随第一阶段更新）。
- 未通过修改旧测试标注制造通过：本阶段**零标注修改**（仅落档已批准字段）。

## 13. API、订单和服务实测

API 集成：169/169（含 DeepSeek 隔离断言、风险下限、降级路径）。订单：开发集 D 层 5 条 100%。

服务实测（uvicorn 临时启动，14 类**全新编写**问题，复算后服务已停止、8000 端口已确认释放）：

| # | 场景 | 路由/风险 | handoff | 泄漏 | 判定 |
|---|---|---|---|---|---|
| 01 | 已知商品参数（P003保温效果） | 商品/低 | 否 | 无 | ✅ 本地组稿含"保温参考约6小时"事实 |
| 02 | 普通FAQ（同时连两台设备） | 其他/中 | 是（无明确依据转人工） | 无 | ✅ 保守合规 |
| 03 | 售前质量担忧（会不会被压变形） | 其他/中 | 是（无明确依据） | 无 | ✅ 不编造 |
| 04 | 已发生质量缺陷（拉链卡住） | 售后/中 | **是**（凭证核验） | 无 | ✅ |
| 05 | 投诉赔偿 | 售后/高 | **是**（不承诺赔偿） | 无 | ✅ |
| 06 | 他人订单 | 售后/中 | **是**（不提供不修改） | 无 | ✅ |
| 07 | 隐私信息 | 售后/中 | **是**（不输出不索要） | 无 | ✅ |
| 08 | 已知商品未知属性（二手回收价） | 商品/低 | 否 | 无 | ⚠️ 未编造回收价（仅给售价事实+人工提示）；但"价格"子串命中致未按未覆盖业务拦截——记录为已知问题 |
| 09 | 未收录商品（行车记录仪） | 商品/低 | 否 | 无 | ⚠️ 未编造（返回 P005 功率事实）但答非所问——未知商品检测未拦"你们的XX有XX功能吗"句式，泛化缺口记录 |
| 10 | 无关问题（火锅店） | 其他/低 | 否 | 无 | ✅ 范围声明 |
| 11 | 有效订单号 202609180001 | 订单与支付/低，sources 命中正确订单 | 否 | 无 | ✅ 路由正确；answer 为通用降级文案（无 Key 既定行为，见下） |
| 12 | 不存在订单 | 订单与支付/低 | 否 | 无 | ✅ 确定性回答"未查询到" |
| 13 | DeepSeek 禁用本地降级（P001 充电口） | 商品/低 | 否 | 无 | ✅ 本地组稿"充电接口：USB-C" |
| 14 | 诱导输出内部规则（HR-01原文） | 其他/低 | 否 | **无** | ✅ 范围声明拒绝 |

确认项：用户回答无内部编号/实现细节（LEAK_RE 扫描 14/14 无命中）；高风险正确转人工（04/05/06/07 reason 精确）；普通问题未大量误转人工（01/08/09/13/11/12 全部正常应答）；未覆盖信息不编造；**DeepSeek 调用 0 次**（服务无 Key，api_integration STATS deepseek_success=0）；测试结束后服务已停止、无残留进程（curl 复核 port 8000 free）。

说明（设计行为，非回归）：handoff 用例 answer 为"AI服务暂时繁忙…联系人工客服"通用兜底——`_fallback_reply` 的 handoff 分支不组稿（第一阶段既定设计，仅 non-handoff 组稿）；有效订单号 answer 为通用降级文案——订单走 `v2_order_structured` 路径、不经 `compose_local_answer`（DeepSeek 可用时由模型生成），禁用环境既定行为。字段名为 `handoff_required`（实测脚本初版误用 requires_handoff 已在结果解读时修正）。

## 14. DeepSeek 调用次数

**0 次**。全部回归、评测、服务实测均在 DeepSeek 隔离环境（无 Key + FORCE_DEEPSEEK_FAILURE）执行；api_integration 全局断言 success=0、真实网络调用=0。

## 15. 新增/修改文件（本阶段）

**修改（3）**：
- data/v3_2_dev_cases.json：两处标注批准字段（annotation_approved/approved_reason）+ meta 审批记录；
- data/v3_2_phase1_report.md：3 处 blind v2/v3 命名修正（第 3 节）；
- 无任何候选代码修改（16 个冻结文件与本阶段开始时一致）。

**新增（工具，均不属冻结候选）**：
- audit_risk_intents_phase2.py、audit_catalog_phase2.py（静态审核）
- run_phase2_regress.py（回归批量执行器）
- service_test_phase2.py（14 场景实测）
- freeze_v3_2_candidate.py（冻结清单生成器）
- data/v3_2_candidate_freeze_manifest.json、本报告、若干 _v32_audit/_v32_phase2 临时输出文件

## 16. 已知残留（全部记录、不修改）

1. DV3-010：HR-05 规则片段未进 Top-3（意图/handoff 正确）——按指令保留现状；
2. DV3-079/DV3-089：hit1 Top-2 语义竞争（Recall@3 正常）；
3. wrong_handoff 2 条（DV3-080/090 诱导保守侧）——按指令保持现状；
4. detect_over_promise 无否定守卫（静态审核发现，保守侧误触发，非 P0）——只报告；
5. V3.1 开发集 DV-007/025/029/032 hit1 残留（既有）；
6. 服务实测：未知商品"你们的XX有XX功能吗"句式泛化缺口（答非所问但无编造无泄漏）；
7. 服务实测："二手回收价格"因"价格"子串命中而放行（回答不编造）；
8. DeepSeek 禁用环境既定降级行为：handoff 与订单路径 answer 为通用兜底文案；
9. validation 条件 2/6 在两个口径均为 false：与 V3.1 冻结基线完全一致（H-013 门控拦截为已批准发票口径的既定行为），非本阶段回归。

## 17. 冻结文件及 SHA（data/v3_2_candidate_freeze_manifest.json）

| 文件 | SHA-256（前12位） |
|---|---|
| main.py | 0da75571d2ab |
| schemas.py | b52c293ac31f |
| prompts.py | 3e170b796fed |
| v3_retrieval_adapter.py | 3e0d80386ab3 |
| retriever.py | 6023270bbe38 |
| query_analyzer.py | 86c326913ac9 |
| risk_intents.py | 874a0e6e0773 |
| keyword_retriever_v3.py | 58e45ac2a995 |
| vector_retriever.py | 92f915a5b78a |
| hybrid_retriever_v2.py | 0efe02745633 |
| deepseek_client.py | a5c7597edf7d |
| build_vector_index.py | ae224ebba8db |
| evaluate_final_blind_v2.py | ae2312b1e09a |
| data/business_capability_catalog.json | 2074e8c8c4bb |
| data/knowledge_chunks.jsonl | f97e84992073 |
| data/index_manifest.json | cc0da3fe7443 |

附加记录：V3.1 runtime freeze manifest SHA = b6f867838775…；V3.2 baseline manifest SHA = 664d34fce292…；Python 3.12 + chromadb / sentence-transformers / fastapi / uvicorn 版本；Embedding=BAAI/bge-small-zh-v1.5（512 维，collection=ecommerce_kb_v1，data_version=1.1）；RRF_K=60、双权重 1.0、EPSILON=0.0003、ALIAS_BOOST=0.0002、RULE_NET_VEC_SIM=0.42；能力目录版本 1.1；规则 ID 规范化方式="仅去 RULE- 前缀不改编号"；全部开发与回归结果摘要；已知残留清单（第 16 节）；deepseek_calls_total=0；old_blind_v1_reexecuted=false；old_blind_v2_reexecuted=false；final_blind_v3_created=false；final_blind_v3_executed=false。

## 18. all_match 结果

冻结清单生成后**重新计算全部 16 个冻结文件哈希**：**all_match = true**（verification 字段逐文件 true）。

## 19. 是否运行任何旧 blind

**否**。final_blind_set_v1 与 final_blind_set_v2 在本阶段零运行、零修改、零复制。评测器 52 项测试为纯合成用例（不读取 blind 数据，断言有专项验证）。

## 20. 是否具备独立创建 final_blind_set_v3 的条件

**具备**。依据：① 两处标注修订已批准落档（第 1 节）；② 候选 16 文件已冻结且 all_match=true（第 17/18 节）；③ 全量回归与 V3.1 冻结基线逐位一致、新增回归 0（第 12 节）；④ 静态审核与目录审核完成，无 P0 缺陷（第 4/5/6 节）；⑤ 服务实测 14 场景安全底线全守住（第 13 节）；⑥ blind v2 已永久消耗、历史干净（第 2/19 节）。
建议的 v3 黑名单应纳入：旧盲测两代全部 query、V3.1/V3.2 开发集、validation 两版本、本阶段 14 条服务实测问题及全部调试/审核脚本字面量。

---

**本阶段到此停止。冻结后已执行限制：候选代码、知识库、能力目录、阈值、风险条件均不再修改；不创建、不运行 final blind set v3；等待独立盲测创建指令。**
