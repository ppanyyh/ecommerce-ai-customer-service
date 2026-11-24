"""Pydantic 数据模型（与 V1.2 回复六要素口径一致，字段名按 V2.0 联调约定统一）。

六要素映射：
- category        -> 问题分类（商品 / 订单与支付 / 物流 / 售后 / 其他）
- answer          -> 建议回复
- sources         -> 信息依据（引用的知识来源列表）
- risk_level      -> 风险等级（低 / 中 / 高，独立维度）
- handoff_required-> 是否转人工
- handoff_reason  -> 转人工原因
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """前端发送的对话请求。"""
    message: str = Field(min_length=1, max_length=500, description="用户问题")
    order_id: str | None = Field(default=None, description="可选：已识别的12位模拟订单号")
    history: list[dict] = Field(default_factory=list, description="可选：多轮上下文 [{role, content}]")


class ChatResponse(BaseModel):
    """统一回复结构（六要素）。"""
    category: str = Field(description="问题分类：商品 / 订单与支付 / 物流 / 售后 / 其他")
    answer: str = Field(description="建议回复")
    sources: list[str] = Field(default_factory=list, description="信息依据（知识来源列表）")
    risk_level: str = Field(default="低", description="风险等级：低 / 中 / 高（独立维度）")
    handoff_required: bool = Field(default=False, description="是否建议转人工")
    handoff_reason: str = Field(default="", description="转人工原因")
    answer_mode: str = Field(default="deepseek",
                             description="回答来源：deepseek=模型生成 / deterministic=本地确定性回答 / fallback=本地降级回答（前端可忽略，测试用）")
    risk_decision: str = Field(default="allow_model",
                               description="风险决策模式：force_safe=本地确认安全查询（模型不得升级风险） / force_handoff=本地确认必须转人工（模型不得降低风险） / allow_model=本地规则不确定，参考模型判断")
