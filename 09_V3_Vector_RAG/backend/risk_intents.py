"""V3.2 结构化风险意图识别（替换 V3.1 的"短字符串命中即触发"正则堆叠）。

设计原则（对应 V3.2 第一阶段需求第三节）：
1. 每种风险意图 = 结构化条件：对象(object) + 动作(action) + 状态(state) + 语境(context)
   + 必要触发组合 + 排除条件(exclusion) + 否定/售前守卫(guard)。
2. 普通口语（报错、不舒服、听得清、回到卡里、后悔、换款式、插线、不动…）因缺少
   必要的"对象+动作/状态"组合而不再单独触发风险。
3. 全部实现为可独立测试的小函数；每个检测器附正例与近似反例（本文件 docstring）。
4. 只写类别级通用模式，不写死任何测试句子，不按 case_id 分支。

输出结构（detect_risk_intents）：
    [{"intent": "complaint_compensation", "rule_id": "RULE-HR-01",
      "evidence": {"object": [...], "action": [...], "state": [...], "context": [...]},
      "reason": "人类可读的触发说明（仅内部调试，不展示给用户）"}, ...]
"""

import re

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _hit(q, patterns):
    """返回第一个命中的 re.Match（按模式顺序），无命中返回 None。"""
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            return m
    return None


def _all_hits(q, patterns):
    """返回全部命中文本（去重、保序）。"""
    out = []
    for pat in patterns:
        for m in re.finditer(pat, q):
            t = m.group(0)
            if t not in out:
                out.append(t)
    return out


# ---------------------------------------------------------------------------
# 1. 投诉与赔偿（HR-01）
#    正例：我要投诉你们 / 要求三倍赔偿 / 我要举报到315 / 太坑了这店，给我个说法
#    近似反例：耳机报错灯一直闪 / 戴着不舒服 / 这宝贝有问题吗（无投诉行为）
# ---------------------------------------------------------------------------
_COMPLAINT_EXPLICIT = [
    r"投诉", r"索赔", r"赔偿", r"举报", r"(?<![0-9])315(?![0-9])", r"消协",
    r"曝光", r"维权", r"退一赔三", r"三倍", r"给我?个说法", r"必须赔", r"赔钱",
    r"差评", r"黑店", r"骗人", r"坑人",
]
_COMPLAINT_STRONG_MOOD = [r"太坑", r"什么破", r"垃圾(店|货|东西)", r"气死"]
_COMPLAINT_COMMERCE_CTX = re.compile(
    r"买|卖|订单|下单|发货|商品|东西|货|店|客服|售后|退款|退货|质量|包装|物流|快递|你们|宝贝")

def detect_complaint(q):
    """必须有明确投诉/索赔/举报/升级行为；强烈不满措辞需叠加电商语境。"""
    explicit = _all_hits(q, _COMPLAINT_EXPLICIT)
    if explicit:
        return {"intent": "complaint_compensation", "rule_id": "RULE-HR-01",
                "evidence": {"action": explicit}, "reason": "明确投诉/索赔/举报行为"}
    mood = _all_hits(q, _COMPLAINT_STRONG_MOOD)
    if mood and _COMPLAINT_COMMERCE_CTX.search(q):
        return {"intent": "complaint_compensation", "rule_id": "RULE-HR-01",
                "evidence": {"action": mood, "context": ["电商语境"]},
                "reason": "强烈不满措辞+电商语境"}
    return None


# ---------------------------------------------------------------------------
# 2. 他人订单（HR-05）
#    正例：帮我朋友查下他的包裹 / 我同事的单子到哪了 / 不是我本人的订单
#    近似反例：给我爸买个台灯（购前代买，无订单对象）/ 换个款式 / 这个能送人吗
# ---------------------------------------------------------------------------
_OTHER_RELATION = [
    r"别人", r"他人", r"其他人", r"同事", r"朋友", r"室友", r"家人", r"亲戚",
    r"爸妈", r"父母", r"我妈", r"我爸", r"我弟", r"我妹", r"我姐", r"我哥",
    r"弟弟", r"哥哥", r"姐姐", r"妹妹", r"老板", r"领导", r"女朋友", r"男朋友",
    r"[他她]人", r"代(查|看|问|收)", r"不是(我|本人)", r"帮我.{0,4}(他|她|别人|朋友|同事|爸妈)",
]
_OTHER_ORDER_OBJECT = [r"订单", r"单子", r"单号", r"快递", r"包裹", r"物流", r"快件",
                       r"(那|这)(个)?件", r"(这|那)单",
                       r"(买|下单|拍)(的|来)?(东西|物件|物品|那件)",
                       r"(下|拍)的单"]
_OTHER_POSSESSIVE = [r"[他她]那边", r"[他她]名下", r"[他她的]账号", r"他(的)?单", r"她(的)?单"]

def detect_other_order(q):
    """须同时存在"他人关系"与"订单/物流对象"；购前代买（无订单对象）不触发。"""
    rel = _all_hits(q, _OTHER_RELATION)
    obj = _all_hits(q, _OTHER_ORDER_OBJECT)
    poss = _all_hits(q, _OTHER_POSSESSIVE)
    if rel and obj:
        return {"intent": "other_order", "rule_id": "RULE-HR-05",
                "evidence": {"object": obj, "context": rel},
                "reason": "他人关系+订单/物流对象"}
    if poss and obj:
        return {"intent": "other_order", "rule_id": "RULE-HR-05",
                "evidence": {"object": obj, "context": poss},
                "reason": "他人指代+订单/物流对象"}
    return None


# ---------------------------------------------------------------------------
# 3. 隐私信息（HR-06）
#    正例：把我的收货地址发我一下 / 我手机号是多少你们存了吗 / 能查到收件人电话吗
#    近似反例：这耳机人声听得清吗 / 语音助手能听懂吗（无敏感对象+查看动作）
# ---------------------------------------------------------------------------
_PRIVACY_SENSITIVE = [
    r"收货地址", r"收件地址", r"家庭住址", r"住址", r"详细地址",
    r"手机号", r"电话号码", r"电话", r"收件电话", r"收货电话",
    r"身份证", r"支付密码", r"验证码", r"银行卡号",
    r"收件人(的)?(电话|手机|姓名|信息)", r"(收货|收件)人信息",
]
_PRIVACY_ACTION = [
    r"(查看|查到|查询|查一下|帮我查)", r"(提供|给我|发(给?我)?|报一下|报个?|念)",
    r"告诉我", r"说一下", r"是多少", r"泄露", r"(核对|核实|确认一下)",
    r"(存|登记)了", r"(删|清除|注销)(掉|了?)", r"(什么|啥)(手机|电话|地址)",
]
def detect_privacy(q):
    """须同时存在敏感对象与查看/提供/泄露类动作。"""
    sens = _all_hits(q, _PRIVACY_SENSITIVE)
    if not sens:
        return None
    act = _all_hits(q, _PRIVACY_ACTION)
    if not act:
        return None
    return {"intent": "privacy_info", "rule_id": "RULE-HR-06",
            "evidence": {"object": sens, "action": act},
            "reason": "敏感对象+查看/提供动作"}


# ---------------------------------------------------------------------------
# 4. 退款催促（HR-03）
#    正例：退款都拖三天了还没到账 / 申请的退款怎么还不处理 / 马上给我退款
#    近似反例：钱回到了银行卡里（无退款发生）/ 付款失败怎么办（支付问题，非催促）
# ---------------------------------------------------------------------------
_REFUND_OCCURRED = [r"退款", r"退钱", r"(申请|提交)了?.{0,4}退", r"退(的|了)款", r"退货退款",
                    r"退(回|回去|回来)的?(钱|款)", r"退(回来|回去)"]
_REFUND_URGE_STATE = [
    r"(拖|等|交上去?|提交|申请)(了)?\s*[0-9一二两三四五六七八九十几]+\s*(天|日|礼拜|星期|周)",
    r"(还没|还没有|未|没)到?账", r"没到账", r"迟迟不", r"怎么还不", r"为什么还不",
    r"(多久|什么时候|啥时候|几天)(能|会|才)?(到账|退回|回来|到)", r"(进度|进展)",
    r"催(一下|催)", r"好几天了", r"卡(在|住)", r"还没(退|处理|到)",
    r"没有?(消息|动静|音讯|下文|进展)",
    r"一点(动静|消息|反应|音讯|进展)都没有?",   # "一点动静没有"（倒装，V3.2.1）
    r"这么久", r"那么久",
]
_REFUND_STRONG_DEMAND = [r"(立即|马上|赶紧|赶快|现在就).{0,4}退", r"给我退", r"(必须|要求)退[款回]"]

def detect_refund_urge(q):
    """须同时存在"已发生退款"与"延迟/催促状态"；强命令式要求退款可直接触发。"""
    occurred = _all_hits(q, _REFUND_OCCURRED)
    if not occurred:
        return None
    state = _all_hits(q, _REFUND_URGE_STATE)
    if state:
        return {"intent": "refund_urge", "rule_id": "RULE-HR-03",
                "evidence": {"object": occurred, "state": state},
                "reason": "已发生退款+延迟/催促状态"}
    demand = _all_hits(q, _REFUND_STRONG_DEMAND)
    if demand:
        return {"intent": "refund_urge", "rule_id": "RULE-HR-03",
                "evidence": {"object": occurred, "action": demand},
                "reason": "强命令式要求退款"}
    return None


# ---------------------------------------------------------------------------
# 5. 重复扣款与金额争议（HR-02）
#    正例：这个月被扣了两次款 / 退款金额和说好的对不上 / 少退了我十块钱
#    近似反例：16寸电脑能不能放下（尺寸语境）/ 容量够不够用（容量语境）
# ---------------------------------------------------------------------------
_AMOUNT_STRONG = [
    r"多扣", r"重复扣(款|费)?", r"扣了\s*(两|2|二|多)\s*(次|笔|回)", r"扣了两笔",
    r"少退", r"多收", r"重复(扣|付|收)款?", r"扣(重|多了?|了两次|了两次款)",
]
# 金额语境：支付/退款动作 + 数字（"退三十""付了五十"）也是金额语境；
# "货款/尾款/全款"等名词化款项（V3.2 补充，覆盖"货款多付了一次"类表述）
_AMOUNT_MONEY_CTX = [
    r"扣款", r"扣了", r"退款", r"付款", r"金额", r"钱", r"支付", r"到账", r"收款",
    r"货款", r"尾款", r"全款",
    r"(退|付|扣|收)\s*[0-9一二两三四五六七八九十百]+",
]
_AMOUNT_DISPUTE_STATE = [
    r"(不对|有误|异常|不一致|对不上|不一样|不符)",
    r"(说好|讲好|答应|承诺).{0,12}(退|全额|数目|金额)",
    r"(退|到账|退回|扣).{0,8}(和|跟|与).{0,8}(说好|应该|实际)",
    r"(比|和|跟)(原来|之前|当时).{0,8}(多|少|差)",
    r"(多|少)(扣|收|付|给)了?", r"(多|少)了?\s*(一|两|二|双)?\s*(次|笔)\s*钱",
]
_AMOUNT_EXCLUDE = re.compile(r"尺寸|容量|装(得|不)下|放(得|不)下|重量|承重|大小合适|尺码")

def detect_amount_dispute(q):
    """强金钱争议表述直接触发；其余须"金钱语境+争议状态"同时成立；尺寸/容量语境排除。"""
    strong = _all_hits(q, _AMOUNT_STRONG)
    if strong:
        return {"intent": "amount_dispute", "rule_id": "RULE-HR-02",
                "evidence": {"state": strong}, "reason": "重复扣款/金额差池表述"}
    money = _all_hits(q, _AMOUNT_MONEY_CTX)
    dispute = _all_hits(q, _AMOUNT_DISPUTE_STATE)
    if money and dispute and not _AMOUNT_EXCLUDE.search(q):
        return {"intent": "amount_dispute", "rule_id": "RULE-HR-02",
                "evidence": {"object": money, "state": dispute},
                "reason": "金钱语境+金额争议状态"}
    return None


# ---------------------------------------------------------------------------
# 6. 物流停滞（HR-04）
#    正例：包裹停在转运中心三天了 / 物流一直没更新 / 快递好几天没动静
#    近似反例：拉链拉不动 / 鼠标点了不动（物品不动，非物流）
# ---------------------------------------------------------------------------
_LOGI_OBJECT = [r"物流", r"包裹", r"快递", r"运输", r"配送", r"快件", r"货运", r"轨迹",
                r"(这|那)(个|只|一件)?件(?![子])"]
_LOGI_STALL_STATE = [
    r"停(在|了|滞)(半路|路上|途中|原地|转运|中转)?", r"(卡|搁)(在|住)",
    r"(一直|老是|总|迟迟)?不(动|挪|更新|变)", r"没(有)?(更新|动静|消息|变化|进展|挪)",
    r"[0-9一二两三四五六七八九十几多]+\s*天.{0,8}没(有)?(动静|更新|消息|物流|变化)",
    r"(好几天|几天|一个星期|一周|一个礼拜|半个?月)(了)?", r"没挪过", r"停滞", r"没物流(信息|更新)?", r"原地踏步|一动不动|纹丝不动",
]
def detect_logistics_stall(q):
    """须同时存在物流对象与停滞状态；普通物品"不动"不触发。"""
    obj = _all_hits(q, _LOGI_OBJECT)
    if not obj:
        return None
    state = _all_hits(q, _LOGI_STALL_STATE)
    if not state:
        return None
    return {"intent": "logistics_stall", "rule_id": "RULE-HR-04",
            "evidence": {"object": obj, "state": state},
            "reason": "物流对象+长时间无更新状态"}


# ---------------------------------------------------------------------------
# 7. 已发生质量缺陷（HR-08）
#    正例：杯子到手就有裂痕 / 耳机戴了一天就失灵了 / 拉链第二天就拉不上了
#    近似反例（售前，不触发）：这包拉链耐用吗 / 容不容易裂 / 质量怎么样
# ---------------------------------------------------------------------------
# 售前守卫：疑问式/耐久咨询式表述表明损坏尚未发生
_DEFECT_PRESALE_GUARD = re.compile(
    r"(吗|么|嘛|呢)\s*[?？!！。]?\s*$"          # 句末疑问
    r"|(会不会|容易不容易|容不容易|耐不耐用|结不结实|好不好用|灵不灵|好不好)"
    r"|(质量|品质)(怎么样|如何|好吗|好不好)"
    r"|(容易|容易坏|怕不怕)(摔|坏|裂|漏|进水)")
# A. 强损坏陈述：语言上已表明损坏发生
_DEFECT_STRONG = [
    r"破损", r"裂痕", r"裂缝", r"开裂", r"裂了", r"摔(坏|裂|了)", r"坏[了掉]",
    r"损坏", r"故障", r"漏液", r"进水[了了]?", r"开线", r"脱线", r"散线", r"掉漆",
    r"没法用", r"用不了", r"无法使用", r"(不能|无法)正常(工作|使用|运行)",
    r"渗水", r"漏水", r"密封.{0,6}(失效|不行了|坏了)", r"变形", r"发霉", r"断裂",
    r"裂开", r"碎[了掉]?", r"瘪了", r"塌陷",
]
# B. 部件失效（部件对象 + 失效状态同时出现）
_DEFECT_PART = [
    r"拉链", r"拉锁", r"拉头", r"按键", r"按钮", r"开关", r"旋钮", r"接口", r"插口",
    r"插头", r"充电口", r"耳机孔", r"转轴", r"铰链", r"合页", r"杯盖", r"瓶盖",
    r"密封圈", r"盖子", r"仓盖", r"上盖", r"盒盖", r"缝线", r"背带", r"肩带", r"拉杆", r"滚轮", r"脚架",
]
_DEFECT_PART_STATE = [
    r"拉不动", r"拉不上", r"拉不拢", r"卡住", r"卡死", r"断[了掉]?", r"掉[了]?",
    r"坏[了掉]?", r"失灵", r"不灵", r"没反应", r"按不动", r"松[了掉]?",
    r"接触不良", r"拧不紧", r"拧不开", r"关不严", r"漏水", r"渗水", r"合不上",
    r"收不回", r"回弹", r"异响",
]
# C. 功能失效陈述
_DEFECT_FUNC = [
    r"(充不进|充不上)电?", r"开不了机", r"无法开机", r"连不上", r"无法连接",
    r"没(有)?声(音)?了?", r"不亮了", r"灯不亮", r"接触不良", r"异响", r"有杂音",
    r"(听筒|麦克风|话筒).{0,8}(没声|失灵|坏)", r"失灵", r"没反应", r"花屏", r"死机",
    r"不(响|发声|震动|振动)了?", r"(左|右|一边|另一边)(耳|边)?不(响|出声)",
]
# D. 已购语境（部件/功能弱表述时需要）
_DEFECT_PURCHASE_CTX = re.compile(
    r"(收到|到手|到货|签收|买来|买回来|买回|刚买|寄到|用了|使用(了|后|几天|一段时间)?|"
    r"昨天|昨儿|今天早|刚拿|拆开|开箱|第一次(用|使)|过保|刚过保修|前几天|上礼拜|前两天|"
    r"戴(了|着|了一会儿|几天)?|背(了|着|了一会儿)?|穿(了|着|了一会儿)?|第二次|又坏)")

# 泛化质量咨询（不算缺陷）；"质量不好/不行/有问题"是确认疑问式判断请求，
# 不是已发生缺陷陈述（V3.2 补充：修复"拉链拉不动了是不是质量不好"类售前反例）
_DEFECT_GENERIC_QUALITY = re.compile(
    r"(质量|品质)(这|方面)?(怎么样|如何|好吗|好不好|行不行|靠谱吗)|靠谱(吗|不|么)"
    r"|(质量|品质)(有没有|有)(差(别|异)|区(别|分))"
    r"|是不是.{0,4}(质量|品质)(不?好|不行|有问题|有毛病|差)"
    r"|(质量|品质)(不?好|不行|有问题|有毛病|差)(吗|么|吧)?\s*[?？]\s*$")


# ---------------------------------------------------------------------------
# 7b. 单边音频失效（HR-08 专项，V3.2.3 归档后安全热修复）
#     用户实测漏判："昨天刚收到的耳机，今天早上右边就不出声了"
#     根因：旧模式 (左|右|一边|另一边)(耳|边)?不(响|出声) 要求方位词与失效词
#     紧邻，"就/突然/完全"等自然连接词隔断后整体漏判。
#     设计为独立小函数（可单测），不再扩大不可维护的大正则。
# ---------------------------------------------------------------------------
# 方位/对象表达
_RE_AUDIO_SIDE = re.compile(
    r"左耳|右耳|左声道|右声道|左边|右边|一边|另一边|另一只|另一个|另一耳|"
    r"单边|单耳|一只|一个耳朵|一只耳朵|一个耳")
# 声音失效状态
_RE_AUDIO_LOSS = re.compile(
    r"没(有)?声(音)?了?|不出声|不响了?|无声|失声|声音没了|不发声")
# 方位词与失效词之间允许出现的少量自然连接词（+中性助词/量词/标点）
_AUDIO_CONNECTOR_CHARS = "就突然完全现在开始已经怎么又后来的一直都还也早晚那这只个渐渐机耳，, "
# 不对称表达：只有一边有声 / 一只响另一只不响
_RE_AUDIO_ONE_SIDE_ONLY = re.compile(
    r"(只有|仅|就)(一|另一|单)?[边只个耳].{0,6}(有声|有声音|能响|响)"
    r"|一[边只个耳].{0,4}(能响|有声|有声音|响).{0,10}另.{0,4}"
    r"(没声|没声音|不出声|不响|无声|声音没了|没有声)")
# 状态变化表达：开始时有声音，后来不出声了
_RE_AUDIO_CHANGE_STATE = re.compile(
    r"(开始|一开始|之前|先前|原先).{0,4}(有声音|有声|能响|正常|是好的)"
    r".{0,12}(后来|现在|今天|刚才|这两天)(就|突然|又)?"
    r"(不出声|不响|没声|没声音|无声|声音没了|没有声)")
# 售前担忧/参数咨询守卫：尚未发生的担忧或普通功能咨询不判缺陷
_AUDIO_PRESALE_GUARD = re.compile(
    r"(会不会|容易|怕不怕)(没声|没声音|不出声|不响|无声|坏|失灵)"
    r"|(支不支持|能不能用|可以单(独|耳)|单耳(模式|使用|通话)|声道|音量|降噪|隔音|"
    r"延迟|防不防水|音质|佩戴|佩戴方式|左右耳(能|可)不?可以?)")


def _audio_loss_hit(q):
    return {"intent": "post_purchase_defect", "rule_id": "RULE-HR-08",
            "evidence": {"state": ["单边音频失效"]}, "reason": "单边音频失效陈述"}


def detect_single_side_audio_loss(q):
    """单边音频失效检测（HR-08 专项，V3.2.3）。

    触发条件（均需先通过售前守卫）：
    1. 不对称表达：只有一边有声 / 一只响另一只不响；
    2. 状态变化：开始时有声音，后来不出声了；
    3. 方位词 + 声音失效词，中间仅隔少量自然连接词（就/突然/完全/现在/
       开始/已经/怎么/又/后来等）。
    售前担忧（会不会没声音/容易没声吗）与参数咨询（左右声道/音量/降噪/
    单耳模式）不触发。
    """
    if _AUDIO_PRESALE_GUARD.search(q):
        return None
    if _RE_AUDIO_ONE_SIDE_ONLY.search(q) or _RE_AUDIO_CHANGE_STATE.search(q):
        return _audio_loss_hit(q)
    for m_side in _RE_AUDIO_SIDE.finditer(q):
        for m_loss in _RE_AUDIO_LOSS.finditer(q):
            if m_loss.start() < m_side.end():
                continue
            gap = q[m_side.end():m_loss.start()]
            if len(gap) <= 8 and all(c in _AUDIO_CONNECTOR_CHARS for c in gap):
                return _audio_loss_hit(q)
    return None


def detect_defect(q):
    """已发生质量缺陷：强损坏陈述 / 部件+失效状态 / 功能失效，均需排除售前疑问式。"""
    if _DEFECT_GENERIC_QUALITY.search(q) and not re.search(r"(坏|裂|漏|断|失灵|损)", q):
        return None
    presale = bool(_DEFECT_PRESALE_GUARD.search(q))
    if presale:
        return None
    # V3.2.3：单边音频失效专项检测（含自然连接词/不对称/状态变化表达）
    single = detect_single_side_audio_loss(q)
    if single:
        return single
    strong = _all_hits(q, _DEFECT_STRONG)
    if strong:
        return {"intent": "post_purchase_defect", "rule_id": "RULE-HR-08",
                "evidence": {"state": strong}, "reason": "强损坏陈述"}
    part = _all_hits(q, _DEFECT_PART)
    part_state = _all_hits(q, _DEFECT_PART_STATE)
    if part and part_state:
        ctx = _all_hits(q, [_DEFECT_PURCHASE_CTX.pattern])
        ev = {"object": part, "state": part_state}
        if ctx:
            ev["context"] = ctx
        return {"intent": "post_purchase_defect", "rule_id": "RULE-HR-08",
                "evidence": ev, "reason": "部件失效陈述（失效状态即已发生）"}
    func = _all_hits(q, _DEFECT_FUNC)
    if func:
        return {"intent": "post_purchase_defect", "rule_id": "RULE-HR-08",
                "evidence": {"state": func}, "reason": "功能失效陈述"}
    # 弱表述 + 已购语境兜底
    if part_state and _DEFECT_PURCHASE_CTX.search(q):
        return {"intent": "post_purchase_defect", "rule_id": "RULE-HR-08",
                "evidence": {"state": part_state, "context": ["已购语境"]},
                "reason": "失效状态+已购语境"}
    return None


# ---------------------------------------------------------------------------
# 8. 超范围承诺要求（HR-07）：用户要求AI/商家作出保证性承诺
#    正例：你保证今天必须退款到账 / 跟我担保一定办成 / 承诺赔我钱
#    近似反例：退款一般几天到账（普通进度咨询，无保证要求）
# ---------------------------------------------------------------------------
_PROMISE_VERB = [r"保证", r"担保", r"打包票", r"承诺", r"立字据", r"写保证书",
                 r"百分之百", r"一定(要|得)?(退|赔|办|到)"]
_PROMISE_OBJECT = [r"退款", r"到账", r"修好", r"换新", r"办成", r"成功", r"退成",
                   r"赔偿", r"赔", r"补(发|寄)", r"全额退", r"如数退",
                   r"送达", r"送到", r"发货",
                   # V3.2.2：保证"结果不再发生"类对象（保证不会再出现这种问题/
                   # 保证不再坏/保证不会再犯）——属保证结果诉求，须触发 HR-07
                   r"不会再(出现|发生|坏|犯|漏发|错发)", r"不再(出现|发生|坏|犯)"]

# 否定前缀（直接修饰承诺动词时该动词出现视为否定形态）：不要求保证/不用承诺/
# 无法保证/不需要打包票/没法担保…（V3.2.1 否定守卫）
_PROMISE_NEG_PREFIX = [
    "无法", "不能", "不能够", "不可以", "不可", "没能", "没有", "没",
    "不用", "无需", "无须", "用不着", "没法", "没办法", "难以", "别", "勿", "莫",
    "不要求", "不求", "不指望", "不奢望", "不奢求", "不强求",
]
# "能不能/可不可以/能否 + 承诺动词"：询问并请求作出承诺（真承诺要求），非否定。
# 先归一化为"要求"，避免"能不能保证"被窗口误判为否定（其尾部同样含"不能"二字）。
_RE_CAN_QUESTION = re.compile(
    r"(?:能不能|可不可以|能否)(?=(?:[^，。；！？?!]{0,4})?(?:保证|担保|打包票|承诺|立字据|写保证书|拍胸脯|许诺))")
# 动词后接否定补语：保证不了/承诺不成/担保不上…
_PROMISE_NEG_SUFFIX = ("不了", "不成", "不上", "不着", "不到")


def _promise_verb_negation(q):
    """返回 (非否定动词列表, 全部动词出现数)。否定判定规则见 detect_over_promise。"""
    q2 = _RE_CAN_QUESTION.sub("要求", q)
    occurrences = []
    for pat in _PROMISE_VERB:
        for m in re.finditer(pat, q2):
            occurrences.append((m.start(), m.end(), m.group(0)))
    active = []
    for s, e, txt in occurrences:
        tail = q2[max(0, s - 6):s]
        if any(tail.endswith(tok) for tok in _PROMISE_NEG_PREFIX):
            continue
        if q2[e:e + 2] in _PROMISE_NEG_SUFFIX:
            continue
        active.append(txt)
    return active, len(occurrences)


def over_promise_negated(q):
    """V3.2.1：句中出现了承诺动词、但全部为否定形态（不能保证/保证不了/不用承诺…）。
    用于安全网/本地风险下限的否定守卫：此时不应因"保证"类宽松信号转人工。"""
    active, total = _promise_verb_negation(q)
    return total > 0 and not active


def amount_strong(q):
    """是否存在强金额争议表述（多扣/重复扣款/少退…），供文案类型裁决。"""
    return bool(_all_hits(q, _AMOUNT_STRONG))


def detect_over_promise(q):
    """须同时存在"要求保证"动词与承诺对象；普通进度咨询不触发。

    V3.2.1 否定守卫：
    - 否定词直接修饰承诺动词（不能保证/无法承诺/不用担保/不要求保证/保证不了）
      时，该动词出现视为否定形态，不参与触发；
    - "能不能/可不可以/能否+承诺动词"是请求承诺（真承诺要求），不算否定；
    - 仅当存在至少一个非否定形态的承诺动词、且存在承诺对象时才触发；
    - 双重否定/转折自然覆盖：同一句中只要有一个非否定的动词出现即触发
      （"不是说不用保证，你必须保证"→"必须保证"非否定 → 触发）。
    """
    active_verbs, _total = _promise_verb_negation(q)
    if not active_verbs:
        return None
    obj = _all_hits(q, _PROMISE_OBJECT)
    if not obj:
        return None
    return {"intent": "over_promise", "rule_id": "RULE-HR-07",
            "evidence": {"action": active_verbs, "object": obj},
            "reason": "要求作出保证性承诺"}


# ---------------------------------------------------------------------------
# 汇总入口
# ---------------------------------------------------------------------------
_DETECTORS = [
    detect_complaint,
    detect_amount_dispute,
    detect_refund_urge,
    detect_logistics_stall,
    detect_other_order,
    detect_privacy,
    detect_defect,
    detect_over_promise,
]


def detect_risk_intents(q):
    """运行全部风险检测器，返回命中列表（去重，按检测器固定顺序）。"""
    hits = []
    seen = set()
    for det in _DETECTORS:
        r = det(q)
        if r and r["intent"] not in seen:
            seen.add(r["intent"])
            hits.append(r)
    return hits


if __name__ == "__main__":
    pos = [
        "我要投诉你们店，必须给我一个说法",
        "这个月被扣了两次款了",
        "退款都拖三天了还没到账",
        "包裹停在转运中心三天了",
        "帮我朋友查下他的包裹",
        "把我的收货地址发我一下",
        "杯子到手就有裂痕了",
        "耳机戴了一天按键就失灵了",
        "充不进电，昨天刚买的",
    ]
    neg = [
        "耳机报错灯一直闪",            # 无投诉行为（报错≠投诉）
        "戴着不舒服",                  # 无投诉行为
        "给我爸买个台灯",              # 购前代买，无订单对象
        "换个款式行吗",                # 无他人关系
        "这耳机人声听得清吗",          # 无敏感对象
        "钱回到了银行卡里",            # 无退款发生
        "16寸电脑能不能放下",          # 尺寸语境
        "拉链拉不动了是不是质量不好",  # 售前担忧式
        "这包拉链耐用吗",              # 售前耐久咨询
        "鼠标点了不动",                # 物品不动，非物流
    ]
    for s in pos:
        rs = detect_risk_intents(s)
        print("POS", "OK " if rs else "MISS", s, "->", [r["intent"] for r in rs])
    for s in neg:
        rs = detect_risk_intents(s)
        print("NEG", "LEAK" if rs else "OK ", s, "->", [r["intent"] for r in rs])
    print()
    # over_promise 否定守卫专项（V3.2.1）
    op_pos = [
        "你保证今天必须退款到账",
        "跟我担保一定全额退款",
        "承诺三天内修好",
        "你们能不能保证三天到账",
        "给我保证明天送达，否则投诉",
        "必须保证赔偿我的损失",
        "不是说不用保证，你必须保证退款",
        "别跟我废话，承诺换新",
        "你给我打包票一定办成",
        "我要你保证补发新件",
        "今晚必须到账，给我个准话保证",
        "你们得保证这次修好，不能再坏了",
    ]
    op_neg = [
        "我不要求保证，只是问问",
        "不用承诺什么，正常处理就行",
        "你们无法保证的话我就等消息",
        "不需要打包票，告诉我流程就好",
        "我知道你不能保证，只是问一般多久",
        "谁也没法保证一定修好，我理解",
        "不用保证全额退，按流程来",
        "保证不了也没关系，先帮我看看",
        "我没有让你们保证什么",
        "别向我承诺时间，尽快就行",
        "你们担保不了的话直接说",
        "不求你们保证，只希望尽快处理",
    ]
    ok = 0
    for s in op_pos:
        rs = [r for r in detect_risk_intents(s) if r["intent"] == "over_promise"]
        good = bool(rs)
        ok += good
        print("OP-POS", "OK " if good else "MISS", s)
    for s in op_neg:
        rs = [r for r in detect_risk_intents(s) if r["intent"] == "over_promise"]
        good = not rs
        ok += good
        print("OP-NEG", "OK " if good else "LEAK", s)
    print("over_promise guard: %d/%d" % (ok, len(op_pos) + len(op_neg)))
