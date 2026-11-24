"""DeepSeek API 客户端（OpenAI 兼容协议，JSON Output 模式）。

约定：
- 真实 API Key 只保存在 backend/.env，通过 python-dotenv 加载到环境变量后读取；
- 严禁把 Key 写入日志、异常信息、返回结果或任何提交到作品集的文件；
- base_url=https://api.deepseek.com，模型从 DEEPSEEK_MODEL 读取（默认 deepseek-flash）；
- 使用 response_format={"type": "json_object"}（JSON Output），Prompt 中同时明确要求输出 JSON。

异常体系（调用方按类型区分处理，均不携带 Key 内容）：
- DeepSeekConfigError      API Key 未配置 / 配置错误
- DeepSeekRequestError     网络请求失败 / API 返回错误
- DeepSeekEmptyResponseError API 返回空内容
- DeepSeekJSONError        JSON 解析失败
- DeepSeekFieldError       缺少必要字段或字段类型不合法
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

import schemas

# 加载 backend/.env（文件不存在时静默跳过，由 get_api_key() 给出配置错误）
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

# 六字段中 sources 为数组、handoff_required 为布尔，其余为字符串（schemas.ChatResponse 已定义）
REQUIRED_FIELDS = ("category", "answer", "sources", "risk_level", "handoff_required", "handoff_reason")
VALID_RISK_LEVELS = ("低", "中", "高")


class DeepSeekConfigError(RuntimeError):
    """API Key 未配置或配置不合法。"""


class DeepSeekRequestError(RuntimeError):
    """网络请求失败或 API 返回错误。"""


class DeepSeekEmptyResponseError(RuntimeError):
    """API 返回空内容。"""


class DeepSeekJSONError(ValueError):
    """返回内容不是合法 JSON。"""


class DeepSeekFieldError(ValueError):
    """JSON 缺少必要字段或字段类型不合法。"""


def get_api_key() -> str:
    """读取 API Key；未配置时抛出明确的配置错误（不含任何 Key 内容）。"""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise DeepSeekConfigError(
            "DEEPSEEK_API_KEY 未配置：请复制 backend/.env.example 为 backend/.env 并填写。"
        )
    return key


def get_model() -> str:
    return os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def get_base_url() -> str:
    """允许通过 DEEPSEEK_BASE_URL 覆盖（.env.example 提供该项），默认官方地址。"""
    return os.getenv("DEEPSEEK_BASE_URL", BASE_URL).strip() or BASE_URL


def build_client() -> OpenAI:
    """创建 OpenAI 兼容客户端。Key 缺失时抛 DeepSeekConfigError。"""
    return OpenAI(api_key=get_api_key(), base_url=get_base_url())


def generate_reply(message: str, context: str, history: list[dict] | None = None,
                   temperature: float = 0.3) -> dict:
    """调用 DeepSeek 生成六字段建议回复。

    参数：
    - message: 用户当前问题（不发送历史对话、不发送完整知识库）
    - context: 检索到的知识资料片段（由调用方 retriever 提供）
    - history: 可选多轮上下文 [{role, content}]（当前 /api/chat 按安全约定不发送）

    返回：六字段 dict（经 schemas.ChatResponse Pydantic 校验）。
    失败：抛出 DeepSeek*Error 系列异常（均不含 Key 内容）。
    """
    # 1) 配置检查：Key 缺失 → DeepSeekConfigError（在任何网络动作之前）
    api_key = get_api_key()
    model = get_model()

    # 2) 组装消息：System Prompt（含 JSON 输出硬约束）+ 历史 + 本轮问题
    from prompts import build_system_prompt
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(context)}]
    if history:
        messages.extend({"role": h.get("role", "user"), "content": h.get("content", "")}
                        for h in history if isinstance(h, dict))
    messages.append({"role": "user", "content": message})

    # 3) 请求（JSON Output 模式）
    try:
        client = OpenAI(api_key=api_key, base_url=get_base_url())
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except DeepSeekConfigError:
        raise
    except Exception as exc:  # 网络失败、鉴权失败、限流等 → 统一请求错误（只带原因，不带 Key）
        raise DeepSeekRequestError(f"DeepSeek 请求失败：{type(exc).__name__}") from exc

    # 4) 空内容检查
    content = (resp.choices[0].message.content if resp.choices else None) or ""
    content = content.strip()
    if not content:
        raise DeepSeekEmptyResponseError("DeepSeek 返回内容为空。")

    usage = getattr(resp, "usage", None)
    usage_dict = None
    if usage is not None:
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }

    # 5) JSON 解析（模型偶发在 ```json 围栏内输出，做一次剥离重试）
    data = _parse_json(content)

    # 6) 字段完整性 + 类型校验（缺字段/类型错 → DeepSeekFieldError；校验通过 → 六字段 dict）
    return _validate_fields(data)


def _parse_json(content: str) -> dict:
    """解析模型输出为 dict；解析失败抛 DeepSeekJSONError。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeepSeekJSONError("DeepSeek 返回内容不是合法 JSON。") from exc
    if not isinstance(data, dict):
        raise DeepSeekJSONError("DeepSeek 返回的 JSON 不是对象。")
    return data


def _validate_fields(data: dict) -> dict:
    """校验六字段存在性与类型，并归一为统一结构。"""
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise DeepSeekFieldError(f"DeepSeek 返回 JSON 缺少必要字段：{', '.join(missing)}")

    # sources 必须是字符串数组（单个字符串时宽容归一，其余类型报错）
    sources = data["sources"]
    if isinstance(sources, str):
        sources = [sources] if sources else []
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise DeepSeekFieldError("sources 必须是字符串数组。")
    # 至少包含一个非空字符串：模型无依据时应返回 ["现有资料未覆盖"]，不允许空数组
    sources = [s for s in sources if s.strip()]
    if not sources:
        raise DeepSeekFieldError(
            "sources 不得为空：使用了资料须引用其来源标签，无可用依据时应返回 [\"现有资料未覆盖\"]。"
        )

    # handoff_required 必须是布尔值（字符串 "true"/"false" 宽容归一）
    handoff = data["handoff_required"]
    if isinstance(handoff, str):
        if handoff.lower() in ("true", "1", "yes"):
            handoff = True
        elif handoff.lower() in ("false", "0", "no", ""):
            handoff = False
    if not isinstance(handoff, bool):
        raise DeepSeekFieldError("handoff_required 必须是布尔值。")

    payload = {
        "category": str(data["category"]),
        "answer": str(data["answer"]),
        "sources": sources,
        "risk_level": str(data["risk_level"]),
        "handoff_required": handoff,
        "handoff_reason": str(data["handoff_reason"]),
    }

    # Pydantic 结构校验（models 层面再兜底一次）
    resp = schemas.ChatResponse.model_validate(payload)

    # risk_level 取值约束
    if resp.risk_level not in VALID_RISK_LEVELS:
        raise DeepSeekFieldError(
            f"risk_level 必须是 {'/'.join(VALID_RISK_LEVELS)} 之一，实际为：{resp.risk_level}"
        )
    return resp.model_dump()
