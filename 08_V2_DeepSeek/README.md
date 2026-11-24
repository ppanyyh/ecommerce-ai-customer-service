# 电商客服AI助手 V2.0（DeepSeek 方案）

## 版本说明

- **V1.2（稳定版）**：位于 `../05_AI_Demo`，纯 HTML/CSS/JS 的**规则匹配版本**——关键词匹配商品资料/FAQ/SOP/模拟订单，双击 `index.html` 即可本地运行，保持不变，不在原目录开发。
- **V2.0（本目录）**：**本地检索（retriever）＋ DeepSeek 生成 ＋ 规则兜底**。前端由 FastAPI 托管，优先调用 `/api/chat`；**DeepSeek 失败或后端不可用时，前端自动回退 V1.2 本地规则引擎并标记"本地规则回答"**。
- **注意**：V2.0 必须通过 FastAPI 地址（`http://127.0.0.1:8000/`）访问，**不能再直接双击 index.html 作为 V2 正式运行方式**（直接打开时前端会以本地规则模式运行，无 AI 生成能力）。

## 目录结构

```
08_V2_DeepSeek/
├─ frontend/          # 前端（V2.0：优先调用 /api/chat，失败回退本地规则）
│  ├─ index.html      # 版本标记 V2.0 · DeepSeek增强版；顶部后端状态标签
│  ├─ styles.css
│  ├─ app.js          # generateApiAnswer(30s超时) + generateLocalAnswer(本地规则回退)
│  └─ data.js         # 本地规则引擎知识数据（回退用）
├─ backend/           # FastAPI 后端
│  ├─ main.py         # /api/health、/api/chat + 静态托管 frontend（挂载于 API 路由之后）
│  ├─ deepseek_client.py  # DeepSeek OpenAI 兼容客户端
│  ├─ retriever.py    # 本地知识检索：商品/FAQ/SOP/订单
│  ├─ prompts.py      # 系统提示词模板（含 V1.2 回答边界硬约束）
│  ├─ schemas.py      # 请求/响应模型（含 answer_mode / risk_decision）
│  ├─ requirements.txt
│  └─ .env.example    # 复制为 .env 后填写 Key
├─ .gitignore
└─ README.md
```

## 当前状态（阶段六：双层输出——消费者话术与内部依据分离）

- **双层输出原则**：`answer` 只面向消费者（结论 + 需用户提供的信息 + 下一步 + 必要边界说明，自然简洁礼貌）；资料名、FAQ/SOP 规则编号、风险与转人工原因只出现在 `sources` / `risk_level` / `handoff_reason` / `risk_decision` 等内部字段；
- **System Prompt**（prompts.py）明确禁止 answer 出现："根据《……》"、规则编号（HR-xx/FAQ-xxx/SOP）、"知识库"、"现有资料未覆盖"、"AI无法……"、内部字段名等；
- **后端兜底校验**（main.py）：DeepSeek 返回后用 `_internal_leak` 正则检查 answer，命中则重试一次，仍命中则替换为面向消费者的安全模板（保留模型返回的 sources/风险/转人工内部字段）；
- **本地话术同步更新**：无关问题→"抱歉，我目前只能协助处理商品、订单、物流和售后相关问题。"；资料缺失→"目前暂时无法确认该问题，建议联系人工客服进一步核实。"；降级回答不再输出内部资料摘要；
- **页面调整**：分析面板标题改为"内部分析（演示）"并附灰色说明；用户消息气泡中的分析区块不再显示"信息依据"与"命中商品/订单"（仅在右侧内部分析面板保留）；
- **FastAPI 托管前端**：`/` 直接打开 `frontend/index.html`；静态目录在所有 `/api` 路由注册之后挂载（StaticFiles, html=True），API 不会被覆盖；目录基于 `main.py` 文件位置计算，不依赖终端目录；
- **前端调用顺序**：用户发送 → 显示"正在查询资料并生成回复……" → `POST /api/chat`（30 秒超时，AbortController）→ 成功显示后端结果；请求失败/超时/后端不可用 → 调用 `generateLocalAnswer()`（V1.2 本地规则引擎），并明确标记**"本地规则回答"**；
- **防重复提交**：请求进行中禁用发送按钮与输入框，空内容不发送，加载提示在成功/失败/超时后必定消失；
- **回答模式展示**：`deepseek`→AI生成 / `deterministic`→确定性规则 / `fallback`→本地降级 / 本地回退→本地规则回答；
- **顶部状态标签**（GET /api/health）：后端可用且 DeepSeek 已配置→"AI服务已连接"；后端可用但未配置→"规则模式"；后端不可用→"本地模式"；
- **安全**：前端所有动态文本用 textContent/DOM API 渲染（不拼接 innerHTML）；前端不出现、不读取 API Key 与 .env；页面只调用本地 `/api/chat`；
- 集成测试：`backend/test_chat_integration.py`（8 主用例 + 口径回归 + 回退测试 + **answer 内部信息泄露检查**）**309/309 通过**；`test_retriever.py` 12/12 通过；端到端 `test_e2e_frontend.py` **10/10 通过**。

## 快速开始（本机已验证，Python 3.13.14）

```bash
# 1. 在 08_V2_DeepSeek 根目录创建虚拟环境（要求 Python >= 3.10）
python -m venv .venv
.venv\Scripts\python.exe --version

# 2. 用虚拟环境中的 Python 安装依赖（不要全局安装）
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 3. 启动后端（从根目录启动时用 --app-dir 指定 backend；或先 cd backend 再运行）
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

## 接口测试方法

1. **健康检查**：浏览器打开 `http://127.0.0.1:8000/api/health`，预期返回：
   `{"status":"ok","version":"2.0.0","mode":"deepseek_with_retrieval","deepseek_configured":true}`
2. **页面访问**：浏览器打开 `http://127.0.0.1:8000/`，应直接显示 V2.0 前端页面，顶部状态标签为"AI服务已连接"（已配置 Key 时）。
3. **Swagger**：浏览器打开 `http://127.0.0.1:8000/docs`，对 `POST /api/chat` 传 `{"message": "你好"}` 执行，
   预期返回 HTTP 200 与统一结构化 JSON（category / answer / sources / risk_level / handoff_required / handoff_reason / answer_mode / risk_decision）。
4. **Pydantic 校验**：空 `message` 或缺少 `message` 字段会返回 HTTP 422。

## 跨域（CORS）说明

开发阶段 `allow_origins=["*"]`：前端可能通过 `file://` 直接打开（Origin 为 `null`）或运行在任意本地端口。
**生产环境必须收紧为明确的允许来源列表**（如 `["http://127.0.0.1:5500", "http://localhost:8080"]`），禁止带 `*` 上线。

## DeepSeek 客户端（已接入）

- `backend/deepseek_client.py`：OpenAI 兼容 SDK + `response_format={"type":"json_object"}`，六字段 JSON 输出校验，异常分层（配置/网络/空响应/JSON/字段）；
- `backend/prompts.py`：System Prompt 含回答边界硬约束与 JSON 输出示例；
- `backend/test_deepseek.py`：连通性与输出校验脚本（投诉赔偿用例，预期转人工）；
- Key 配置于 `backend/.env`（不进入版本库）。

### 配置与运行 DeepSeek 测试（需手工执行）

```bash
# 1. 复制 .env.example 为 .env（在 backend/ 目录内）
copy backend\.env.example backend\.env

# 2. 用文本编辑器打开 backend\.env，手工填写：
#    DEEPSEEK_API_KEY=sk-你的真实Key
#    （DEEPSEEK_MODEL / DEEPSEEK_BASE_URL 已有默认值，可不改）

# 3. 运行测试脚本（使用虚拟环境）
.venv\Scripts\python.exe backend\test_deepseek.py
```

脚本输出：是否调用成功、模型名称、六字段 JSON、校验结果、Token 用量、错误类型。**不会输出 API Key。**

### Key 安全（重要）

- **不得上传、提交或向任何人展示 `.env` 文件内容**（已被 `.gitignore` 排除：`.env`、`backend/.env`）；
- **Key 一旦泄露，必须立即在 DeepSeek 控制台删除该 Key 并重新创建**，同时更换本地 `.env`；
- Key 只保存在 `backend/.env`，禁止写入前端（frontend/）、README、测试记录或任何作品集文件；
- 客户端所有日志与异常信息均不携带 Key 内容。

## V2.0 计划流程

用户提问 → 输入校验/订单号识别 → 问题分类 → retriever 检索知识（商品/FAQ/SOP/订单）→ prompts 组装上下文 → deepseek_client 生成建议回复 → 风险判断与转人工 → 返回统一六要素结构 → 前端展示。
