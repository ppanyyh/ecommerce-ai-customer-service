# V2.0 阶段四：/api/chat 全链路集成（retriever 检索 -> DeepSeek 生成 -> 本地校验兜底 -> 失败降级）
# 阶段四修订：引入三种风险决策模式 force_safe / force_handoff / allow_model，
# 修正退款进度查询、无关问题与业务规则缺失、投诉赔偿分类三处业务口径。

# --- 标准库 ---
import os
import re

# --- 第三方 ---
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# --- 本项目模块 ---
import schemas
import retriever
import deepseek_client

# 加载 backend/.env（真实 Key 只保存在该文件，不进入版本库、不进入日志）
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_VERSION = "2.0.0"

VALID_CATEGORIES = ("商品", "订单与支付", "物流", "售后", "其他")
_RISK_ORDER = ("低", "中", "高")

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

app = FastAPI(title="电商客服AI助手 V2.0", version=APP_VERSION)

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
    """本地风险规则：返回 (风险等级, 是否需转人工, 原因)。"""
    hits = [r for r in _ALL_RISK_RULES if any(k in t for k in r["keywords"])]
    if not hits:
        return "低", False, ""
    top = max(hits, key=lambda r: _RISK_ORDER.index(r["risk_level"]))
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
        top = max(hits, key=lambda r: _RISK_ORDER.index(r["risk_level"]))
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


def _fallback_reply(retrieval: dict, message: str = "",
                    prefix_note: str = "AI生成服务暂时不可用") -> schemas.ChatResponse:
    """本地降级回答：用户可见文本用消费者话术（不泄露内部资料与规则），
    内部字段（sources/风险/转人工）保留完整判断。"""
    local_risk, local_handoff, _ = _local_risk(_clean(message)) if message else ("低", False, "")
    handoff = retrieval["requires_handoff"] or local_handoff
    reason = retrieval["handoff_reason"]
    # 风险兜底：本地降级回答的风险不得低于本地规则判定
    floor = "中" if handoff else "低"
    risk = max(local_risk, floor, key=_RISK_ORDER.index)
    if handoff:
        answer = ("抱歉，AI服务暂时繁忙，无法完成本次查询。"
                  "建议你联系人工客服进一步处理，或稍后重新提问。")
    else:
        answer = "抱歉，AI服务暂时繁忙。你可以稍后重新提问，或联系人工客服进一步核实。"
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

    # 3) 不完整订单号（6-11位独立数字，且不含完整12位）
    m12 = retriever._DIGIT12_RE.search(t)
    m611 = retriever._DIGIT611_RE.search(t)
    if not m12 and m611:
        STATS["deterministic"] += 1
        return _reply(
            category="订单与支付",
            answer="你输入的订单号可能不完整，请提供完整的12位订单号后再查询。",
            sources=["《模拟订单数据》"], risk="低", handoff=False, reason="",
            mode="deterministic", risk_decision="force_safe",
        )

    # 4) 不存在的完整订单号
    if m12 and m12.group(1) not in retriever.ORDERS:
        STATS["deterministic"] += 1
        return _reply(
            category="订单与支付",
            answer="未查询到该模拟订单，请核对完整订单号。",
            sources=["《模拟订单数据》"], risk="低", handoff=False, reason="",
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
    model_risk = reply["risk_level"] if reply["risk_level"] in _RISK_ORDER else "低"
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
        "mode": "deepseek_with_retrieval",
        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
    }


@app.post("/api/chat")
def chat(req: schemas.ChatRequest):
    """对话接口（V2.0 全链路）。

    流程：retriever 检索 -> 确定性场景判断 -> 风险决策模式判定 -> DeepSeek 生成
    （只发送当前问题 + context + 格式规则）-> 六字段校验 + sources 过滤 + 按模式兜底
    -> 失败时本地降级，保证不返回 500。
    注意：按安全约定，req.history 不发送给模型（模型输入只含当前问题与 context）。
    """
    try:
        message = req.message
        retrieval = retriever.retrieve(message)
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
            final_risk = max(model_risk, decision["risk"], key=_RISK_ORDER.index)
            handoff = True
            reason = model_reason or decision["reason"]
            risk_decision = "force_handoff"
        else:
            # allow_model：本地规则不确定，参考模型判断，仍受本地风险下限兜底
            # 需转人工的场景（本地或检索判定）风险不低于"中"，避免模型把风险降级
            category = reply["category"]
            local_risk, local_handoff, local_reason = _local_risk(t)
            floor_handoff = local_handoff or retrieval["requires_handoff"]
            floor_risk = "中" if floor_handoff else local_risk
            final_risk = max(model_risk, floor_risk, key=_RISK_ORDER.index)
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
