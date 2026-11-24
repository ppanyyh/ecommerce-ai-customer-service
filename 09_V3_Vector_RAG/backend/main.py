# V2.0 阶段四：/api/chat 全链路集成（retriever 检索 -> DeepSeek 生成 -> 本地校验兜底 -> 失败降级）
# 阶段四修订：引入三种风险决策模式 force_safe / force_handoff / allow_model，
# 修正退款进度查询、无关问题与业务规则缺失、投诉赔偿分类三处业务口径。
# V3.1 第三阶段：知识检索主流程切换为 v3_retrieval_adapter（V3.1 冻结混合检索内核
#   hybrid_retriever_v2；订单号精确查询仍走 V2 retriever 结构化逻辑）。
#   检索算法、阈值、关键词均未改动；门控三分类（supported/unsupported_business/
#   irrelevant）由适配器返回结构承载，unsupported/irrelevant 在确定性分支本地回复。

# --- 标准库 ---
import os
import re
import time
from contextlib import asynccontextmanager

# --- 第三方 ---
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# --- 本项目模块 ---
import schemas
import retriever
import v3_retrieval_adapter
import deepseek_client
import risk_intents

# 加载 backend/.env（真实 Key 只保存在该文件，不进入版本库、不进入日志）
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_VERSION = "3.2.3"

VALID_CATEGORIES = ("商品", "订单与支付", "物流", "售后", "其他")
# V3.2.2：统一风险等级定义（单一公共来源 risk_levels.py；原本地 _RISK_ORDER
# 与 adapter 的定义顺序不一致，已废弃本地副本，全部改用显式映射）
import risk_levels
_RISK_ORDER = risk_levels.RISK_SCORE  # 兼容旧引用（"低"/"中"/"高" 成员检查）

# 回答红线：不得承诺退款时间、审核结果或赔偿金额。
# 注意排除否定表述（如"无法承诺退款"），避免把合规回答误判为违规承诺。
_PROMISE_TRIGGER_RE = re.compile(
    r"(保证|承诺|一定|必定|肯定)[^。？！?!]{0,12}(退款|到账|赔付|赔偿|退回)"
    r"|(退款|赔偿|到账|退回)[^。？！?!]{0,12}\d+\s*(个?工作日|天|小时|分钟)"
)
_PROMISE_NEGATIONS = ("无法", "不能", "不得", "不会", "不作", "不做", "并非", "拒绝", "没", "未", "不")
# 订单数据越界检查：回答中出现的 12 位数字必须是资料内的订单号或单号
_ORDER_NUM_RE = re.compile(r"\d{12}")

# 双层输出原则：answer 面向消费者，禁止出现内部检索/决策信息（sources 等内部字段不受限）
_INTERNAL_LEAK_RE = re.compile(
    r"根据《|依据《|《[^》]{1,24}》"                      # 资料引用（书名号）
    r"|根据[^。？！]{0,8}资料|依据[^。？！]{0,8}资料"      # 根据商品资料/依据知识资料等
    r"|HR-\d|FAQ-\d|SOP|知识库|现有资料未覆盖|资料未覆盖"   # 规则/资料编号与口径用语
    r"|AI无法|AI不|模型判断|模型返回|风险决策|risk_level|handoff_required|answer_mode"
    r"|force_safe|force_handoff|allow_model|retriever|DeepSeek|API|命中|检索|模拟数据"
)

# answer 泄露内部信息时的安全模板（保留模型返回的内部字段，仅替换用户可见文本）
_SAFE_TEMPLATES = [
    # (匹配条件关键词, 模板)
    (("投诉", "赔偿"),
     "很抱歉给你带来不好的体验。你的问题涉及投诉和赔偿，我无法直接确认赔偿方案，将为你转接人工客服进一步处理。"),
    (("质量",), "很抱歉给你带来不好的体验。请提供：订单号、商品问题描述、商品照片或视频、包装及配件情况，将由人工客服核实处理。"),
    (("金额", "少退", "多扣", "重复扣款"),
     "你反馈的金额问题需要人工核对订单及支付记录。请提供订单号，我将为你转接人工客服跟进处理，具体处理结果以实际核实为准。"),
    (("还不", "立即", "马上", "尽快", "赶紧", "催", "退款", "到账"),
     "退款进度需要结合订单状态进一步核实。请提供订单号，我将为你转接人工客服跟进处理，具体审核结果和到账时间以实际处理进度为准。"),
]
_SAFE_TEMPLATE_DEFAULT = "目前暂时无法确认该问题，建议联系人工客服进一步核实。"


def _internal_leak(answer: str):
    """answer 命中内部信息泄露模式时返回首个命中片段，否则返回 None。"""
    m = _INTERNAL_LEAK_RE.search(answer)
    return m.group(0) if m else None


def _safe_answer(message: str, t: str) -> str:
    """按场景选择面向消费者的安全模板。"""
    for keys, tpl in _SAFE_TEMPLATES:
        if any(k in t for k in keys):
            return tpl
    return _SAFE_TEMPLATE_DEFAULT

# 调用统计（仅供测试观察，不含任何敏感信息；单进程内有效）
STATS = {
    "deepseek_attempts": 0,   # 实际发起的 DeepSeek API 调用次数
    "deepseek_success": 0,    # 模型返回并通过本地校验的次数
    "deepseek_failed": 0,     # 调用失败或校验不通过转降级的次数
    "deterministic": 0,       # 确定性场景（未调用模型）次数
    "fallback": 0,            # 本地降级回答次数
}

# 服务就绪状态（V3.1 调修：Embedding 启动预热；不涉及任何 DeepSeek 调用）
_READY = {
    "ready": False,
    "vector_warmed": False,
    "warmup_ms": None,
    "warmup_error": None,
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动预热：在服务开始接收请求前完成本地 Embedding 模型加载与首次向量检索，
    避免（服务器启动后的）首个用户请求承担约 18s 的模型冷启动。
    预热只涉及本地模型与向量库，不调用 DeepSeek、不产生任何 API 费用。"""
    try:
        from vector_retriever import vector_search
        t0 = time.perf_counter()
        vector_search("服务启动预热查询", top_k=1)
        _READY["vector_warmed"] = True
        _READY["warmup_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    except Exception as e:  # 预热失败不阻断启动；/api/ready 会如实上报
        _READY["warmup_error"] = f"{type(e).__name__}: {e}"
    _READY["ready"] = True
    yield


app = FastAPI(title="电商客服AI助手 V3.2.3", version=APP_VERSION, lifespan=lifespan)

# 跨域配置（开发阶段）：生产环境必须改为明确的允许来源列表（见 README 安全说明）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段放开；生产必须收紧
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 本地规则工具（风险为独立维度；口径与 retriever 一致，均来自 knowledge_base.json）
# --------------------------------------------------------------------------
def _clean(text: str) -> str:
    return retriever._clean(text)


# 补充本地规则：knowledge_base.json 的 HR 规则未覆盖“询问到账时间”类催促表达
_EXTRA_HANDOFF_RULES = [
    {
        "id": "MR-01", "name": "催促退款或询问到账",
        "keywords": ["什么时候到账", "何时到账", "多久到账", "到账时间", "几天到账",
                     "几天能到账", "什么时候退款", "何时退款", "什么时候退我"],
        "risk_level": "中",
        "reason": "催促退款或询问到账时间，需人工跟进，AI不承诺具体退款时间或到账时间",
        "source": "《售后SOP》退款处理",
    },
]
# 全部本地风险规则 = retriever 的 HR 规则 + 补充规则（全部为“必须转人工”级规则）
_ALL_RISK_RULES = list(retriever.RULES) + _EXTRA_HANDOFF_RULES


def _local_risk(t: str):
    """本地风险规则：返回 (风险等级, 是否需转人工, 原因)。

    V3.2.1 否定守卫：命中仅限退款催促/超范围承诺类规则、V3 结构化检测无任何
    风险意图、且承诺动词均为否定形态（保证不了/不用承诺…）时，宽松关键词
    （如"尽快处理"）不作为本地风险下限——否定承诺不构成风险诉求。"""
    hits = [r for r in _ALL_RISK_RULES if any(k in t for k in r["keywords"])]
    if not hits:
        return "低", False, ""
    if ({r["id"] for r in hits} <= {"HR-03", "HR-07"}
            and not risk_intents.detect_risk_intents(t)
            and risk_intents.over_promise_negated(t)):
        return "低", False, ""
    top = max(hits, key=lambda r: risk_levels.RISK_SCORE[risk_levels.normalize_risk(r["risk_level"])])
    return top["risk_level"], True, top["reason"]


def _privacy_rule(t: str):
    """命中隐私信息或他人订单规则时返回该规则（确定性处理，不调用模型）。"""
    for r in _ALL_RISK_RULES:
        if r["name"] in ("他人订单", "隐私信息") and any(k in t for k in r["keywords"]):
            return r
    return None


# --------------------------------------------------------------------------
# 三种风险决策模式：force_safe / force_handoff / allow_model
# --------------------------------------------------------------------------
# 单纯退款/售后进度查询意图（不含催促、金额争议、投诉时按 force_safe 处理）
_REFUND_PROGRESS_PHRASES = (
    "退款到哪", "退款进度", "退款状态", "售后审核状态", "审核状态",
    "查询退款", "退款申请到哪", "退款处理到哪", "退款哪一步", "售后进度",
)
# 排除词：出现即不属于“单纯进度查询”
_URGE_DISPUTE_KEYWORDS = (
    "还不", "立即", "马上", "尽快", "赶紧", "催", "到账", "金额", "少退", "多扣",
    "重复扣款", "扣了两次", "投诉", "赔偿", "举报", "差评", "曝光", "维权", "骗", "几天",
)
# 售后相关词：force_handoff 且命中这些词时，分类覆盖为“售后”
_AFTER_SALE_WORDS = ("退款", "退货", "换货", "质量", "售后", "赔偿", "投诉", "审核")
# 业务相关词：用于区分“完全无关问题”与“业务相关但资料缺失”
_BUSINESS_KEYWORDS = frozenset(set(retriever.PRODUCT_ALIASES) | {
    "订单", "退款", "退货", "换货", "物流", "发货", "快递", "包裹", "签收", "收货",
    "售后", "发票", "开票", "报销", "运费", "邮费", "差价", "价保", "保价", "支付",
    "付款", "扣款", "待付款", "优惠", "折扣", "保修", "质量", "坏了", "故障", "损坏",
    "客服", "人工", "商品", "购买", "下单", "投诉", "赔偿", "举报", "收件", "地址",
})


def _refund_progress_query(t: str) -> bool:
    """是否为单纯退款/售后进度查询（不含催促、金额争议或投诉表达）。"""
    if not any(p in t for p in _REFUND_PROGRESS_PHRASES):
        return False
    if any(k in t for k in _URGE_DISPUTE_KEYWORDS):
        return False
    return True


def _risk_decision(t: str) -> dict:
    """判定风险决策模式（在调用模型前确定，模型结果按模式接受/覆盖）。

    返回 {decision, category, risk, handoff, reason}：
    - force_handoff：任一本地风险规则命中（全部为必须转人工级规则），模型不得降低风险；
      涉及投诉赔偿（HR-01）统一 售后/高；命中售后相关词时分类覆盖为 售后。
    - force_safe：单纯退款/售后进度查询，本地确认为普通安全查询，模型不得升级风险。
    - allow_model：本地规则未命中，允许参考模型判断（仍受本地风险下限兜底）。
    """
    hits = [r for r in _ALL_RISK_RULES if any(k in t for k in r["keywords"])]
    if hits:
        complaint = any(r["name"] == "投诉与赔偿" for r in hits)
        top = max(hits, key=lambda r: risk_levels.RISK_SCORE[risk_levels.normalize_risk(r["risk_level"])])
        category = "售后" if (complaint or any(w in t for w in _AFTER_SALE_WORDS)) else ""
        return {"decision": "force_handoff", "category": category, "risk": top["risk_level"],
                "handoff": True, "reason": top["reason"]}
    if _refund_progress_query(t):
        return {"decision": "force_safe", "category": "售后", "risk": "低",
                "handoff": False, "reason": ""}
    return {"decision": "allow_model", "category": "", "risk": "",
            "handoff": None, "reason": ""}


def _reply(category: str, answer: str, sources: list, risk: str,
           handoff: bool, reason: str, mode: str,
           risk_decision: str = "allow_model") -> schemas.ChatResponse:
    return schemas.ChatResponse(
        category=category, answer=answer, sources=sources, risk_level=risk,
        handoff_required=handoff, handoff_reason=reason, answer_mode=mode,
        risk_decision=risk_decision,
    )


def _context_summary(context: str, limit: int = 160) -> str:
    """取检索 context 的内容摘要（去掉来源标签行），用于降级回答。"""
    lines = [ln.strip() for ln in context.splitlines()
             if ln.strip() and not ln.startswith("[来源：")]
    text = "；".join(lines)
    return text[:limit] + ("…" if len(text) > limit else "")


def _fallback_category(retrieval: dict) -> str:
    mt = retrieval["match_type"]
    if mt == "product":
        return "商品"
    if mt == "order":
        return "订单与支付"
    if mt == "faq":
        for fid in retrieval["matched_ids"]:
            for f in retriever.FAQS:
                if f["id"] == fid:
                    return f["category"]
        return "其他"
    if mt == "risk":
        return "售后"
    return "其他"


# --------------------------------------------------------------------------
# V3.2.1 本地降级组稿：结构化订单回答 + 按风险类型的转人工文案
# （无 LLM；只展示该订单允许展示的事实；不暴露 HR 编号/SOP/scope/阈值/分数；
#   不承诺赔偿、退款时间或处理结果；handoff_required 不变，本地风险下限不降）
# --------------------------------------------------------------------------
_HANDOFF_COPY_BY_KIND = {
    # 质量缺陷
    "HR-08": ("这个问题涉及商品质量核实，需要由人工客服为你处理。请准备好："
              "订单号、问题的具体描述、商品及问题部位的照片或视频，"
              "以及包装和配件情况。处理结果以人工核实为准。"),
    # 金额争议/重复扣款
    "HR-02": ("你反馈的金额问题需要人工核对。请准备好：订单号、支付记录和扣款截图，"
              "由人工客服为你核实处理，处理结果以人工核实为准。"),
    # 退款催促
    "HR-03": ("退款进度需要由人工客服为你核实。请准备好：订单号、退款申请时间和"
              "支付方式，人工客服会为你跟进处理，到账时间以实际处理进度为准。"),
    # 物流异常
    "HR-04": ("物流问题需要由人工客服为你核实。请准备好：订单号和运单号或最新的"
              "物流节点信息，人工客服会为你跟进处理。"),
    # 投诉或赔偿
    "HR-01": ("你的投诉需要由人工客服处理。请准备好：订单号、问题经过说明和"
              "相关凭证，人工客服会为你登记跟进，处理结果以人工核实为准。"),
    # 隐私或他人订单：不要求用户公开发送敏感信息
    "HR-05": ("这涉及订单归属核验。为保护信息安全，请不要在对话中发送手机号、"
              "验证码、完整地址等敏感信息，由人工客服核验身份后为你处理。"),
    "HR-06": ("这涉及个人隐私信息核验。为保护信息安全，请不要在对话中发送"
              "证件号、完整地址等敏感信息，由人工客服核验身份后为你处理。"),
    # 超范围承诺：说明AI不能保证结果
    "HR-07": ("AI助手无法对处理结果作出保证。你的诉求会转由人工客服核实，"
              "请提供订单号和相关凭证，处理结果以人工核实为准。"),
}
_HANDOFF_KIND_PRIORITY = ("HR-07", "HR-08", "HR-02", "HR-03", "HR-04", "HR-01", "HR-05", "HR-06")
_HANDOFF_COPY_DEFAULT = ("这个问题需要由人工客服为你核实处理。请准备好订单号和相关凭证，"
                         "人工客服会为你跟进，处理结果以人工核实为准。")


def _local_risk_kinds(t: str) -> list:
    """V3.2.1：消息文本的本地风险意图类型（HR-01..08），供确定性分支守卫。"""
    try:
        return sorted({r["rule_id"][5:] for r in risk_intents.detect_risk_intents(t)})
    except Exception:
        return []


def _handoff_user_copy(retrieval: dict, message: str = "") -> str:
    """按风险类型返回带明确下一步的转人工文案（不出现内部编号与实现细节）。"""
    kinds = [k for k in (retrieval.get("handoff_kinds") or [])
             if k in _HANDOFF_COPY_BY_KIND]
    if not kinds and message:
        try:
            kinds = [r["rule_id"][5:] for r in risk_intents.detect_risk_intents(_clean(message))]
        except Exception:
            kinds = []
    # 金额争议与退款催促同时命中时按证据裁决：强金额表述（多扣/重复扣款/少退）
    # → 金额文案；仅退款进度催促 → 退款文案（V3.2.1）
    if "HR-02" in kinds and "HR-03" in kinds and message:
        kind = "HR-02" if risk_intents.amount_strong(_clean(message)) else "HR-03"
        return _HANDOFF_COPY_BY_KIND[kind]
    for kind in _HANDOFF_KIND_PRIORITY:
        if kind in kinds:
            return _HANDOFF_COPY_BY_KIND[kind]
    return _HANDOFF_COPY_DEFAULT


def _compose_order_answer(ol: dict) -> str:
    """有效订单的结构化本地回答：仅展示该订单允许展示的事实与可执行下一步。
    不编造预计送达/退款时间/审核结果；不出现"模拟数据"等实现说明。"""
    if ol.get("found"):
        lines = [
            "查询到订单 {} 的当前记录：".format(ol["order_id"]),
            "商品：{} ×{}，合计 {:.2f} 元。".format(
                ol.get("product_name", ""), ol.get("quantity", ""),
                float(ol.get("amount") or 0.0)),
            "订单状态：{}；物流状态：{}。".format(
                ol.get("order_status", ""), ol.get("logistics_status", "")),
        ]
        if ol.get("tracking_number"):
            lines.append("承运信息：{}（运单号 {}）。".format(
                ol.get("logistics_company", ""), ol["tracking_number"]))
        if ol.get("aftersales_status") and ol["aftersales_status"] != "无":
            lines.append("该订单有进行中的售后申请，审核和处理结果需由人工客服核实。")
        lines.append("如需修改订单或有其他问题，可联系人工客服处理。以上为当前系统可查询到的订单记录。")
        return "\n".join(lines)
    if ol.get("incomplete"):
        return ("你提供的订单号可能不完整。为避免匹配到错误订单，"
                "请提供完整的12位订单号后再查询。")
    return ("未查询到该订单号对应的记录。请核对订单号是否为完整的12位数字后再试，"
            "或联系人工客服核实。")


def _fallback_reply(retrieval: dict, message: str = "",
                    prefix_note: str = "AI生成服务暂时不可用") -> schemas.ChatResponse:
    """本地降级回答：用户可见文本用消费者话术（不泄露内部资料与规则），
    内部字段（sources/风险/转人工）保留完整判断。"""
    local_risk, local_handoff, _ = _local_risk(_clean(message)) if message else ("低", False, "")
    handoff = retrieval["requires_handoff"] or local_handoff
    reason = retrieval["handoff_reason"]
    # 风险兜底：本地降级回答的风险不得低于本地规则判定，也不得低于
    # 检索层必需规则的最高等级（V3.2.2：handoff_kinds 对应规则等级，如 HR-07=高）
    floor = "中" if handoff else "低"
    retrieval_floor = risk_levels.normalize_risk(retrieval.get("risk_floor_level"))
    risk = risk_levels.max_risk(local_risk, floor, retrieval_floor)
    if handoff:
        # V3.2.1：按风险类型给出明确下一步（不展示内部编号；不承诺结果）
        answer = _handoff_user_copy(retrieval, message)
    else:
        # V3.2.1 结构化订单本地回答：有效订单直接用订单数据组稿（不经向量库）
        ol = retrieval.get("order_local")
        if (str(retrieval.get("retrieval_engine", "")) == "v2_order_structured"
                and ol):
            answer = _compose_order_answer(ol)
        else:
            # V3.2 本地降级改进：supported 问题基于检索结果原始 text 组稿
            # （无 LLM、不使用 retrieval_text、不泄露内部信息），不再只返回通用致歉。
            composed = None
            if str(retrieval.get("retrieval_engine", "")).startswith("v3"):
                try:
                    composed = v3_retrieval_adapter.compose_local_answer(message, retrieval)
                except Exception:
                    composed = None
            answer = composed or ("抱歉，AI服务暂时繁忙。你可以稍后重新提问，或联系人工客服进一步核实。")
    return _reply(
        category=_fallback_category(retrieval),
        answer=answer,
        sources=list(retrieval["sources"]) or ["现有资料未覆盖"],
        risk=risk,
        handoff=handoff,
        reason=reason,
        mode="fallback",
    )


# --------------------------------------------------------------------------
# 确定性场景：直接由本地程序回答，节省费用并防止幻觉
# --------------------------------------------------------------------------
def _deterministic_reply(message: str, retrieval: dict):
    t = _clean(message)

    # 1) 空输入
    if not t:
        STATS["deterministic"] += 1
        return _reply(
            category="其他",
            answer="请输入你需要咨询的问题，例如商品参数、订单进度或售后规则。",
            sources=["现有资料未覆盖"], risk="低", handoff=False, reason="",
            mode="deterministic", risk_decision="force_safe",
        )

    # 2) 明显的隐私或查询他人订单请求（高风险，本地直接回答）
    pr = _privacy_rule(t)
    if pr:
        STATS["deterministic"] += 1
        return _reply(
            category="其他",
            answer="为保护你的信息安全，他人订单和隐私信息需要人工核实后才能处理，请勿在对话中发送手机号、验证码、完整地址等敏感信息。如需核实，请联系人工客服。",
            sources=[pr["source"]], risk=pr["risk_level"], handoff=True,
            reason=pr["reason"], mode="deterministic", risk_decision="force_handoff",
        )

    # 3) 不完整订单号（6-11位独立数字，或"后四位 XXXX"式部分号码；不含完整12位）
    m12 = retriever._DIGIT12_RE.search(t)
    m611 = retriever._DIGIT611_RE.search(t)
    partial_incomplete = bool((retrieval.get("order_local") or {}).get("incomplete")) \
        if isinstance(retrieval.get("order_local"), dict) else False
    if not m12 and (m611 or partial_incomplete):
        STATS["deterministic"] += 1
        # V3.2.1：不完整订单号 + 高风险表达 → 本地风险下限，转人工
        if _local_risk_kinds(t):
            return _reply(
                category="售后",
                answer=_handoff_user_copy(retrieval, message),
                sources=["现有资料未覆盖"], risk="高", handoff=True,
                reason="订单号不完整且存在高风险表达，必须转人工核实",
                mode="deterministic", risk_decision="force_handoff",
            )
        return _reply(
            category="订单与支付",
            answer="你提供的订单号可能不完整。为避免匹配到错误订单，请提供完整的12位订单号后再查询。",
            sources=["《模拟订单数据》"], risk="低", handoff=False, reason="",
            mode="deterministic", risk_decision="force_safe",
        )

    # 4) 不存在的完整订单号（V3.2.1：用户可见文案不出现"模拟"实现说明）
    if m12 and m12.group(1) not in retriever.ORDERS:
        STATS["deterministic"] += 1
        # V3.2.1：不存在订单 + 高风险表达 → 本地风险下限，转人工
        if _local_risk_kinds(t):
            return _reply(
                category="售后",
                answer=_handoff_user_copy(retrieval, message),
                sources=["现有资料未覆盖"], risk="高", handoff=True,
                reason="订单未查询到且存在高风险表达，必须转人工核实",
                mode="deterministic", risk_decision="force_handoff",
            )
        return _reply(
            category="订单与支付",
            answer="未查询到该订单号对应的记录。请核对订单号是否为完整的12位数字后再试，或联系人工客服核实。",
            sources=["《模拟订单数据》"], risk="低", handoff=False, reason="",
            mode="deterministic", risk_decision="force_safe",
        )

    # 4b) V3.1 门控三分类：unsupported_business / irrelevant 本地直接回答，
    #     不调用 DeepSeek、不把任何知识片段传给回答生成（results/context 为空）。
    #     文案面向用户：说明资料无法确认 + 下一步，不暴露门控/编号/分数等内部信息。
    gate_scope = retrieval.get("gate_scope")
    if gate_scope == "unsupported_business":
        STATS["deterministic"] += 1
        return _reply(
            category="其他",
            answer=retrieval.get("gate_user_answer") or "现有资料没有覆盖这项信息，建议联系人工客服确认。",
            sources=list(retrieval["sources"]) or ["现有资料未覆盖"],
            risk="中", handoff=True, reason=retrieval["handoff_reason"],
            mode="deterministic", risk_decision="force_handoff",
        )
    if gate_scope == "irrelevant":
        STATS["deterministic"] += 1
        return _reply(
            category="其他",
            answer=retrieval.get("gate_user_answer") or "抱歉，我只能协助处理本店商品、订单和售后相关问题。",
            sources=["现有资料未覆盖"],
            risk="低", handoff=False, reason="",
            mode="deterministic", risk_decision="force_safe",
        )

    # 5) 与资料无关且没有任何命中
    if not retrieval["matched"]:
        # 5a) 单纯退款/售后进度查询但未提供订单号 → 引导提供订单号（force_safe）
        if _refund_progress_query(t):
            STATS["deterministic"] += 1
            return _reply(
                category="售后",
                answer="请提供完整的12位订单号，我来帮你查询退款进度。",
                sources=["《模拟订单数据》"], risk="低", handoff=False, reason="",
                mode="deterministic", risk_decision="force_safe",
            )
        # 5b) 业务相关但资料缺少政策（如发票、议价等未命中FAQ的诉求）→ 建议转人工，不编造
        if any(k in t for k in _BUSINESS_KEYWORDS):
            STATS["deterministic"] += 1
            return _reply(
                category="其他",
                answer="目前暂时无法确认该问题，建议联系人工客服进一步核实。",
                sources=["现有资料未覆盖"], risk="中", handoff=True,
                reason="知识库没有明确依据，必须转人工（《售后SOP》必须转人工）",
                mode="deterministic", risk_decision="force_handoff",
            )
        # 5c) 完全无关的问题（如天气、写诗、股票）→ 本地确认安全，不转人工、不调模型
        STATS["deterministic"] += 1
        return _reply(
            category="其他",
            answer="抱歉，我目前只能协助处理商品、订单、物流和售后相关问题。",
            sources=["现有资料未覆盖"], risk="低", handoff=False, reason="",
            mode="deterministic", risk_decision="force_safe",
        )

    return None  # 非确定性场景，交给模型生成


# --------------------------------------------------------------------------
# 模型输出校验 + 本地规则兜底
# --------------------------------------------------------------------------
def _final_from_model(reply: dict, retrieval: dict):
    """对 DeepSeek 六字段返回执行本地校验；通过时返回 (answer, sources, model_risk, model_handoff, model_reason)，不通过返回 None。"""
    # 1) category 合法性
    if reply["category"] not in VALID_CATEGORIES:
        return None

    # 2) answer 非空
    answer = (reply["answer"] or "").strip()
    if not answer:
        return None

    # 3) answer 红线：不得承诺退款时间、审核结果或赔偿金额（否定表述不算违规）
    if _promise_violation(answer):
        return None

    # 4) answer 不得包含知识资料之外的订单数据（12位数字须在资料或 context 中出现过）
    known_nums = set(retriever.ORDERS)
    for o in retriever.ORDERS.values():
        if o.get("tracking_number"):
            known_nums.add(o["tracking_number"])
    known_nums |= set(re.findall(r"\d{6,}", retrieval["context"]))
    for num in _ORDER_NUM_RE.findall(answer):
        if num not in known_nums:
            return None

    # 5) sources 校验：只保留 retriever 来源内的条目，编造的删除；删空则回退 retrieval sources
    allowed = set(retrieval["sources"])
    sources = [s for s in reply["sources"] if s in allowed]
    if not sources:
        sources = list(retrieval["sources"])
    if not sources:
        return None

    # 6) 风险等级合法性（最终风险兜底由 chat() 按 risk_decision 模式执行）
    model_risk = reply["risk_level"] if reply["risk_level"] in risk_levels.RISK_SCORE else "低"
    return answer, sources, model_risk, reply["handoff_required"], reply["handoff_reason"]


def _promise_violation(text: str):
    """命中违规承诺时返回命中片段；否定语境（如'无法承诺'）不算违规。

    判定方式：向前回溯最多12个字符寻找否定词，若否定词与触发词之间
    同句（无标点）且间隔不超过8个字符，视为否定语境。
    """
    for m in _PROMISE_TRIGGER_RE.finditer(text):
        seg = text[max(0, m.start() - 12):m.start()]
        negated = False
        for neg in _PROMISE_NEGATIONS:
            p = seg.rfind(neg)
            if p == -1:
                continue
            between = seg[p + len(neg):]
            if len(between) <= 8 and not any(ch in between for ch in "，。？！?!；;、"):
                negated = True
                break
        if not negated:
            return m.group(0)
    return None


# --------------------------------------------------------------------------
# /api/chat 主流程
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """健康检查：只报告是否已配置 Key，不返回 Key 内容或长度。"""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "mode": "hybrid_rag_with_structured_orders",
        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
    }


@app.get("/api/ready")
def ready():
    """就绪检查（V3.1 调修）：报告 Embedding 预热是否完成。

    与 /api/health 的区别：health 只表明进程存活；ready 表明本地向量检索
    （Embedding 模型 + Chroma）已完成预热，首个正式请求不会再承担模型冷启动延迟。
    不返回任何 Key 信息，不调用 DeepSeek。"""
    return {
        "ready": bool(_READY["ready"]),
        "vector_warmed": bool(_READY["vector_warmed"]),
        "warmup_ms": _READY["warmup_ms"],
        "warmup_error": _READY["warmup_error"],
        "version": APP_VERSION,
    }


@app.post("/api/chat")
def chat(req: schemas.ChatRequest):
    """对话接口（V3.1 全链路）。

    流程：v3_retrieval_adapter 检索（订单号 → V2 结构化订单查询；其余 → V3.1 混合检索，
    门控 unsupported/irrelevant 直接确定性回复）-> 确定性场景判断 -> 风险决策模式判定
    -> DeepSeek 生成（只发送当前问题 + context + 格式规则）-> 六字段校验 + sources 过滤
    + 按模式兜底 -> 失败时本地降级，保证不返回 500。
    注意：按安全约定，req.history 不发送给模型（模型输入只含当前问题与 context）。
    """
    try:
        message = req.message
        retrieval = v3_retrieval_adapter.retrieve(message)
        t = _clean(message)

        # ---- 1) 确定性场景：本地直接回答，不调用 DeepSeek ----
        det = _deterministic_reply(message, retrieval)
        if det is not None:
            return det

        # ---- 2) 风险决策模式（调用模型前确定） ----
        decision = _risk_decision(t)

        # ---- 3) 回退开关（模拟 DeepSeek 失败，不发起真实调用、不泄露 Key） ----
        if os.getenv("FORCE_DEEPSEEK_FAILURE", "").strip().lower() == "true":
            STATS["fallback"] += 1
            return _fallback_reply(retrieval, message, prefix_note="AI生成服务暂时不可用（模拟失败）")

        # ---- 4) 需要模型生成：只发送当前问题 + retriever context + 格式规则 ----
        # 输出校验失败或 answer 泄露内部信息时重试一次；API 异常仍直接降级
        base = None
        leaked = None  # 结构合法但 answer 含内部信息的候选（保留内部字段，文本换安全模板）
        for _try in range(2):
            STATS["deepseek_attempts"] += 1
            try:
                reply = deepseek_client.generate_reply(message=message, context=retrieval["context"])
            except deepseek_client.DeepSeekConfigError:
                STATS["deepseek_failed"] += 1
                STATS["fallback"] += 1
                return _fallback_reply(retrieval, message, prefix_note="AI服务未正确配置")
            except Exception:  # 超时 / 余额 / 网络 / 空内容 / JSON / 字段校验失败 → 本地降级，不返回500
                STATS["deepseek_failed"] += 1
                STATS["fallback"] += 1
                return _fallback_reply(retrieval, message)
            cand = _final_from_model(reply, retrieval)
            if cand is not None and _internal_leak(cand[0]) is None:
                base = cand
                break
            STATS["deepseek_failed"] += 1
            if cand is not None and leaked is None:
                leaked = cand  # 首次泄露候选：结构/来源/风险可用，仅文本违规

        if base is None and leaked is not None:
            # 两次生成均泄露内部信息 → 使用面向消费者的安全模板，保留模型内部字段
            answer, sources, model_risk, model_handoff, model_reason = leaked
            base = (_safe_answer(message, t), sources, model_risk, model_handoff, model_reason)
        if base is None:
            STATS["fallback"] += 1
            return _fallback_reply(retrieval, message, prefix_note="AI生成内容未通过校验")

        answer, sources, model_risk, model_handoff, model_reason = base
        model_reason = (model_reason or "").strip()

        if decision["decision"] == "force_safe":
            # 本地确认安全查询：覆盖模型的分类/风险/转人工判断
            category, final_risk = decision["category"], decision["risk"]
            handoff, reason, risk_decision = False, "", "force_safe"
        elif decision["decision"] == "force_handoff":
            # 本地确认必须转人工：模型不得降低风险；投诉/售后相关统一“售后”
            category = decision["category"] or reply["category"]
            final_risk = risk_levels.max_risk(model_risk, decision["risk"],
                                              retrieval.get("risk_floor_level"))
            handoff = True
            reason = model_reason or decision["reason"]
            risk_decision = "force_handoff"
        else:
            # allow_model：本地规则不确定，参考模型判断，仍受本地风险下限兜底
            # 需转人工的场景（本地或检索判定）风险不低于"中"，且不得低于
            # 检索层必需规则的最高等级（V3.2.2：模型不得降低规则风险）
            category = reply["category"]
            local_risk, local_handoff, local_reason = _local_risk(t)
            floor_handoff = local_handoff or retrieval["requires_handoff"]
            floor_risk = risk_levels.max_risk(
                "中" if floor_handoff else local_risk,
                retrieval.get("risk_floor_level"))
            final_risk = risk_levels.max_risk(model_risk, floor_risk)
            handoff = bool(model_handoff) or floor_handoff
            reason = model_reason or (retrieval["handoff_reason"] or local_reason)
            risk_decision = "allow_model"
        if not handoff:
            reason = ""

        STATS["deepseek_success"] += 1
        return _reply(
            category=category, answer=answer, sources=sources,
            risk=final_risk, handoff=handoff, reason=reason, mode="deepseek",
            risk_decision=risk_decision,
        )
    except Exception:  # 任何未预期异常都不得让 /api/chat 返回 500
        STATS["fallback"] += 1
        return _reply(
            category="其他",
            answer="【本地降级回答】系统暂时出现异常，基于本地资料无法完成本次回答，请稍后重试或转人工客服处理。",
            sources=["现有资料未覆盖"], risk="中", handoff=True,
            reason="系统异常，为保障体验转人工处理",
            mode="fallback",
        )


# --------------------------------------------------------------------------
# 前端静态托管：必须在 /api 路由全部注册之后挂载（FastAPI 按注册顺序匹配，
# 先注册的 /api/health、/api/chat 优先于根路径静态目录，不会被覆盖）。
# 目录基于本文件位置计算，不依赖终端当前目录。
# --------------------------------------------------------------------------
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
