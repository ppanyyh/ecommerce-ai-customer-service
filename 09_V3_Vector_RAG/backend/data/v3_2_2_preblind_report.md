# V3.2.2 最终盲测前 P0 修复报告（v3_2_2_preblind_report.md）

- 日期：2026-09-26
- 范围：09_V3_Vector_RAG/backend
- 性质：盲测前 P0 修复阶段报告。**本阶段未创建、未运行 final blind set v3；未重跑旧 blind v1/v2；DeepSeek 全程 0 次调用；检索参数（RRF/EPSILON/RULE_NET_VEC_SIM/关键词/向量阈值/排序权重）未做任何调整。**
- 结论速览：风险排序缺陷已根除（统一 risk_levels.py 显式映射），8 条规则等级核对一致，43/43 风险单元测试、15/15 V3.2.1 指标（risk floor 80/80）、17/17 V3.2 目标、validation 双口径与基线一致、API 169/169、服务实测 11/11，候选已重新冻结（all_match=true）。**具备创建 final blind set v3 的前置条件。**

---

## 1. 风险排序缺陷根因

**缺陷确认（与指令描述一致）：**

| 位置 | 修复前定义 | 配合用法 | 后果 |
|---|---|---|---|
| `main.py` | `_RISK_ORDER = ("低","中","高")` | `max(..., key=index)` | 正确（取最高） |
| `v3_retrieval_adapter.py` | `_RISK_ORDER = ("高","中","低")` | `max(..., key=index)` | **反序：多风险候选取最低风险** |

**第二层根因（本阶段新发现）：** adapter 的 `_risk_floor` 只返回 (是否转人工, 原因)，**不返回规则风险等级**——V3 结构化意图识别出的高风险规则（如 HR-07=高）等级在 retrieval 层被丢弃，`_fallback_reply` 的 floor 只到「中」。这正是 V3.2.1 阶段 C 类 9 条 HR-07 正例实际风险为「中」的根本原因（当时误归为"分级口径"，实为缺陷）。

## 2. 统一风险等级实现

- 新增 `backend/risk_levels.py`（唯一权威定义）：
  - `RISK_SCORE = {"低":0, "中":1, "高":2}`（显式映射，杜绝顺序书写歧义）；
  - `normalize_risk()`（非法值归「低」，不抛异常）；
  - `max_risk(*levels)`（取最高，支持可迭代/忽略非法值）；
  - `kinds_risk_level(kinds)`（按 HR-01..08 类型返回最高规则等级，供 retrieval 层向 main 传递规则等级下限）；
  - `RULE_RISK_LEVELS`（正式等级映射常量）。
- `main.py`：删除本地 `_RISK_ORDER` 元组，全部 6 处 `max(..., key=index)` 与成员检查改为 `risk_levels` 调用；`_fallback_reply` 与 allow_model/force_handoff 分支的风险兜底并入 `retrieval["risk_floor_level"]`。
- `v3_retrieval_adapter.py`：删除反序 `_RISK_ORDER`；`_risk_floor` 返回值增加风险等级（多规则取最高）；`_from_v3` 与订单路由返回增加 `risk_floor_level` 内部字段（不进入用户可见 answer，不破坏八字段响应）。
- 传播链：规则等级（HR-07=高）→ required_rule_ids → `risk_floor_level` → main 风险兜底（`max_risk(model_risk, local/floor, retrieval_floor)`）——**模型或本地结果均不能低于该下限**。

## 3. 8 条规则等级核对

依据 `knowledge_chunks.jsonl` 原始规则与 `knowledge_base.json` retriever.RULES 逐条核对，**未通过修改知识片段降低任何等级**：

| 规则 | 正式等级 | retriever.RULES | risk_levels 映射 | 一致 |
|---|---|---|---|---|
| HR-01 投诉赔偿 | 高 | 高 | 高 | ✅ |
| HR-02 金额争议 | 高 | 高 | 高 | ✅ |
| HR-03 退款催促 | 中 | 中 | 中 | ✅ |
| HR-04 物流停滞 | 中 | 中 | 中 | ✅ |
| HR-05 他人订单 | 高 | 高 | 高 | ✅ |
| HR-06 隐私信息 | 高 | 高 | 高 | ✅ |
| HR-07 超范围承诺 | 高 | 高 | 高 | ✅ |
| HR-08 质量缺陷 | 高 | 高 | 高 | ✅ |

## 4. 单规则及多规则组合测试（43/43，全新问题，不用旧 blind 原句）

`test_v3_2_2_risk_levels.py`（rc=0）四组覆盖：

- **公共定义（11 条）**：RISK_SCORE 映射、normalize_risk、max_risk 高+中/高+低/中+低、kinds 等级、空值处理；
- **模块一致性（3 条）**：adapter 无本地反序定义、main/adapter 均引用统一 risk_levels；
- **规则等级核对（2 条）**：八条等级与正式映射一致、HR-03/04=中其余=高；
- **组合语义（9 条）**：单规则命中（HR-07→高、HR-03→中、HR-04→中）、高+中=高、高+低=高、中+中=中、无命中=低、多规则 reason 取最高风险规则；
- **端到端降级（14 条）**：HR-07 正例 risk=高 handoff=true、否定反例不触发、HR-03/04=中、HR-08/05/06=高、多风险取最高、unsupported=中、最终风险≥risk_floor_level；
- **风险决策+意图检测（4 条）**：force_handoff 决策风险=命中规则最高等级、V3 新表述经 allow_model 由 retrieval floor 兜底、HR-07 正例全触发/否定全不触发。

## 5. HR-07 正反例

- **正例 12/12 全部 risk=高、handoff=true**（V3.2.1 的 9 条中风险缺陷已根除）：补发承诺、担保绝对不坏、承诺换新、担保赔偿、双重否定转折（"不是说不用保证，你必须保证"）等；
- **否定反例 12/12 全部不触发**（risk=低、handoff=false）："我不是要你保证什么""保证不了也没事""我知道你不能保证，只是问一般多久"等；
- 修复中新增承诺对象词表（「保证**不会再出现/不再坏/不再犯**」类保证结果诉求），此前「你给我保证永远不会再出现这种问题」因对象词缺口漏检——属触发面补充，非否定守卫改动。

## 6. V3.2.1 开发集风险指标（重跑）

| 指标 | 结果 |
|---|---|
| 15 项目标 | **15/15 达标** |
| risk floor 符合率 | **80/80 = 100%** |
| HR-07 正例 | 12/12 全部 risk=高、handoff=true |
| HR-07 否定反例 | 12/12 全部不触发 |
| handoff 正确率 | 80/80 = 100% |
| 泄漏/违规 | 0 / 0 |

**标注修正披露（1 处，非放宽）**：E 类 DV321-073（HR-03）/DV321-074（HR-04）的 `expected_risk_floor` 由「高」修正为「中」——原生成器对 E 类 10 条一刀切标「高」，与指令二正式等级映射（HR-03/04=中）直接冲突，属标注错误纠正；HR-07 正例 12 条「高」标注未动。生成器 `build_v3_2_1_dev_cases.py` 已同步按 `risk_levels.RULE_RISK_LEVELS` 取值，`check_v3_2_1_dev_set` 重建后 17/17。

## 7. 原开发集与 validation 回归

| 测试 | 结果 | 说明 |
|---|---|---|
| V3.2 原开发集（100 条） | **17/17 目标达标** | 无新增回归 |
| V3.1 开发集（60 条） | 与既有基线一致 | hit1 34/40 等不变（DV-007/025/029/032 既有残留） |
| validation v1.1 frozen | hybrid Hit@1=22/24、MRR=0.9375、Rule 8/8 | 与冻结基线一致（H-013 既有） |
| validation v1.2 reviewed | hybrid Hit@1=23/24、MRR=0.9583、Rule 8/8 | 与冻结基线一致 |
| API 集成 | **169/169**（rc=0） | 无差异 |
| chat 集成 | 268/309（rc=1） | **失败 41 条与 V3.2.1 失败集合逐位相同**（DeepSeek 禁用+V2 时代断言预期差异），零新增回归。注：V3.2.1 报告中"269/309"系笔误，上轮实际同为 268/309（已用上轮 raw 复核） |
| 订单测试 | test_retriever 订单 TC 全过 + v32_dev 订单 5/5 + v321_dev 订单 10/10 | 全过 |
| 本地降级 | v32_dev 概念覆盖 100% + v321_dev 97.62% | 达标 |
| 泄漏检查 | 全过 | aliases/keywords 未新增 |
| 延迟顺序测试 | 9/9 | — |

## 8. API 版本标识

| 项 | 修复前 | 修复后 |
|---|---|---|
| `APP_VERSION` | "2.0.0" | **"3.2.2"** |
| FastAPI title | 电商客服AI助手 V2.0 | **电商客服AI助手 V3.2.2** |
| health/ready version | 2.0.0 | 3.2.2 |
| health mode | deepseek_with_retrieval | **hybrid_rag_with_structured_orders** |
| /api/ready | 正常（version=3.2.2） | ✅ |

- 前端依赖检查：`app.js`/`index.html` 中的 mode 引用均为 chat 响应的 `answer_mode` 字段（非 health 的 mode），对 version/新 mode 无功能性依赖；仅 4 处注释与 1 处装饰 badge 文案含"V2.0"（不影响运行，未改动前端）。`deepseek_configured` 字段保留。
- 八字段 chat 响应结构未破坏（API 169/169 佐证）。
- `test_chat_integration.py` HC-01 的 mode/version 断言同步更新为新版本（旧断言因版本更新必然失效，属指令四的必要跟进）。

## 9. 服务实测（11 场景全新问题，结果 data/_v322_servicetest.txt）

| # | 场景 | risk | handoff | 结果 |
|---|---|---|---|---|
| 1 | HR-07 真正承诺（保证补发） | 高 | true | ✅ |
| 2 | HR-07 否定承诺（不是要你保证） | 低 | false（不触发） | ✅ |
| 3 | HR-03 退款催促 | 中 | true | ✅ |
| 4 | HR-04 物流停滞 | 中 | true | ✅ |
| 5 | HR-08 质量缺陷 | 高 | true | ✅ |
| 6 | HR-06 隐私索要 | 高 | true | ✅ |
| 7 | HR-05 他人订单 | 高 | true | ✅ |
| 8 | 多风险同现（质量缺陷+退款催促） | 高（取最高） | true | ✅ |
| 9 | HR-01 投诉赔偿 | 高 | true | ✅ |
| 10 | HR-02 金额争议 | 高 | true | ✅ |
| 11 | 低风险商品咨询 | 低 | false | ✅ |

- `/api/health` → `version=3.2.2`、`mode=hybrid_rag_with_structured_orders`、`deepseek_configured=false` ✅
- `/api/ready` → `ready=true, vector_warmed=true, version=3.2.2`（预热 18.9s）✅
- 全部答案内部术语正则（HR-/RULE-/SOP/知识库/模拟/handoff/检索/门控/阈值/scope 等）扫描 0 命中。
- 测后停服，端口 8000 已确认释放、无残留进程。

## 10. DeepSeek 次数

- **全程 0 次。** 服务启动未注入 `DEEPSEEK_API_KEY`（环境隔离），单测/回归/服务实测全部走本地路径。chat 回退测试显示 attempts=11 全部为隔离异常，无真实调用、无费用。

## 11. 修改文件

| 文件 | 变更 |
|---|---|
| `risk_levels.py` | **新增**：统一风险等级定义（RISK_SCORE/normalize_risk/max_risk/kinds_risk_level/正式等级映射） |
| `main.py` | APP_VERSION/title/mode 更新；删除本地 _RISK_ORDER；6 处风险比较改用 risk_levels；风险兜底链并入 retrieval.risk_floor_level |
| `v3_retrieval_adapter.py` | 删除反序 _RISK_ORDER；_risk_floor 返回规则等级；_from_v3/订单路由增加 risk_floor_level |
| `risk_intents.py` | _PROMISE_OBJECT 增加"保证结果不再发生"类对象词（不会再出现/不再坏/不再犯） |
| `build_v3_2_1_dev_cases.py` | E 类 expected_risk_floor 按正式等级映射生成（修正 DV321-073/074 标注） |
| `test_chat_integration.py` | HC-01 断言同步 3.2.2（mode/version） |

**新增**：`risk_levels.py`、`test_v3_2_2_risk_levels.py`（43 条）、`run_v322_regress.py`、`service_test_v322.py`、`freeze_v3_2_2_candidate.py`、本报告、`v3_2_2_candidate_freeze_manifest.json` 及 `data/_v322_*` 结果文件。

**未触碰**：检索参数、关键词/别名表、knowledge_chunks.jsonl、index_manifest.json、Embedding、hybrid_retriever_v2.py（本轮零修改）、vector_retriever/keyword_retriever_v3/query_analyzer、V2/frontend/05_AI_Demo、旧标注与旧盲测集。

## 12. 新冻结清单及 all_match

- `data/v3_2_2_candidate_freeze_manifest.json`：17 文件（原 16 + risk_levels.py）SHA-256 复算，4 个有意变更文件记录修改前后 SHA，13 个禁改文件与 V3.2.1 冻结值逐位一致；记录正式风险等级映射、全量回归结果、DeepSeek=0、old blind 未重跑、final blind v3 未创建/未执行。
- **`all_match=true`**，读回复核通过；未覆盖任何旧冻结清单。
- 自此 V3.2.2 候选冻结，不得再修改。

## 13. 是否具备创建 final blind set v3 的条件

**具备。** 依据：
- P0 缺陷（风险排序反序 + 规则等级未传播）已修复并验证（43/43 单测、V3.2.1 risk floor 80/80、HR-07 12/12 全高）；
- 全量回归零新增回归（15/16 rc=0，chat 41 条失败与上轮逐位相同属预期差异）；
- 服务实测 11/11、health/ready 新版本标识正常、DeepSeek 0 次；
- 候选已重新冻结（all_match=true）、旧盲测集未触碰。

按指令：**本阶段到此停止，不创建、不运行 final blind set v3**，等待独立盲测创建指令。
