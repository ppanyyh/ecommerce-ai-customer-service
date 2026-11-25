# 电商客服 AI 助手

> 个人主导、AI 辅助完成的电商售后客服原型（作品集原型，模拟数据，非生产系统）。

## 一句话定位

用 FastAPI + ChromaDB + BGE 中文向量 + DeepSeek 构建的电商售后客服后端：混合检索找对资料、结构化订单直查查准数据、风险下限守安全边界、本地降级保证永远有回应，并以「一次性盲测 + SHA-256 留痕」的评测纪律完成验收归档。

## 核心能力

| 能力 | 解决的问题 |
|---|---|
| 混合检索（关键词 RRF + BGE 向量） | 规则类语义召回弱、纯向量 Top1 被口语 FAQ 抢占 |
| 结构化订单直查（12 位单号不入向量库） | 向量相似度查精确订单必然「串单」 |
| 风险下限机制（8 条规则，模型只能抬高不能降低） | 客服不能自由发挥、不能许下无法兑现的承诺 |
| 本地降级（LLM 不可用照样回应） | 服务必须永远可用 |
| 一次性盲测验收（候选冻结 + 泄漏检查 + `--execute-once`） | 盲测反复跑就退化成开发集 |

## 关键成果（V3.2.2 盲测，已归档）

- **工程与安全面全达标**：80/80 一次执行、内部泄漏 0、禁止承诺违规 0、P95 42.4ms
- **检索强项**：商品 Hit@1 87.5%、FAQ Hit@1 90%、scope 准确率 94.3%
- **如实披露未达标**：总体 Hit@1 54.5%（目标 85%）、high-risk handoff 76.5% 等

## 目录导航

| 目录 | 内容 |
|---|---|
| `01_需求分析` | 产品与用户需求分析 |
| `02_知识库资料` | 商品资料 / 客服 FAQ / 售后 SOP / 模拟订单数据 |
| `03_PRD` | PRD + 业务流程图 |
| `04_Axure原型` | Axure 源文件 + 原型截图 |
| `05_AI_Demo` | 纯前端可运行 Demo |
| `06_测试记录` | 测试 / 迭代 / 回归记录 |
| `07_案例集` | 作品集案例（PPT/PDF）+ 项目复盘 |
| `08_V2_DeepSeek` | DeepSeek 接入版（V2） |
| `09_V3_Vector_RAG` | 最终版：向量 RAG + 混合检索 + 风险控制（含 PORTFOLIO / 面试稿 / 评测证据） |

## 本地运行

```powershell
cd 09_V3_Vector_RAG
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

- 前端：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/api/health`
- 就绪检查：`http://127.0.0.1:8000/api/ready`

## 版本边界（重要）

- **V3.2.2**：完成 80 条 final blind set v3 一次性评测，原始结果完整保留。
- **V3.2.3**：针对「耳机单边无声」漏判的安全热修复，通过 30/30 专项测试与既有回归，**未重跑盲测**。
- 因此盲测指标属于 V3.2.2；V3.2.3 只能表述为「专项修复并通过回归」。

## 诚实边界

- 这是「个人主导、AI 辅助完成」的**作品集原型**，不是完全独立手写，也不是已上线的生产系统。
- `production_ready=false`：模拟数据、无鉴权、CORS 全开，未经真实业务数据、并发压测、权限体系与线上监控验证。
- 同时陈述成果与不足：工程安全指标良好，但盲测 Hit@1、Rule Recall 等泛化指标未达预设目标。

## 简历与面试入口

- 简历项目描述：[`简历项目描述.md`](简历项目描述.md)
- 完整项目叙事：[`09_V3_Vector_RAG/PORTFOLIO.md`](09_V3_Vector_RAG/PORTFOLIO.md)
- 面试准备（30 秒 / 2 分钟 / 5 分钟）：[`09_V3_Vector_RAG/INTERVIEW_GUIDE.md`](09_V3_Vector_RAG/INTERVIEW_GUIDE.md)
- 本地演示步骤：[`09_V3_Vector_RAG/DEMO_GUIDE.md`](09_V3_Vector_RAG/DEMO_GUIDE.md)
- 盲测原始报告：[`09_V3_Vector_RAG/backend/data/final_blind_v3_eval_report.md`](09_V3_Vector_RAG/backend/data/final_blind_v3_eval_report.md)
