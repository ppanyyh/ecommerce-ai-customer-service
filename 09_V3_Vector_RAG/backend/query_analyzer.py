"""V3.2 查询分析器（结构化风险意图 + 业务能力目录驱动的三分类门控）。

V3.2 变化（第一阶段重构）：
1. 风险意图识别迁移到 risk_intents.py 的结构化检测器（对象+动作+状态+语境+
   排除/售前守卫的小函数组合），替换 V3.1 的"短字符串命中即触发"正则堆叠，
   大幅降低普通口语误触发（报错/听得清/回到卡里/不动…不再单独触发风险）。
2. 门控引入业务能力目录（data/business_capability_catalog.json）：
   - 已知商品 + 已覆盖属性 → supported；
   - 已知商品 + 属性询问 + 未覆盖属性 → unsupported_business；
   - 未知电商政策/未覆盖业务类型 → unsupported_business；
   - 范围外主题 → irrelevant；
   - 风险意图优先级最高（真正投诉/隐私请求不被当成普通未知问题）。
3. 业务范围三分类 scope 与 V3.1 一致：supported / unsupported_business /
   irrelevant / unknown（unknown 交由检索层证据判定）。
4. 面向用户的门控原因 gate_reason 不出现规则编号、门控、阈值、检索分数等细节。

防过拟合约束（不变）：
- 只写类别级通用模式（正则/关键词类别），不写死任何完整测试句子；
- 不根据 case_id 做条件分支；
- 同义词扩展只允许单个合理通用商品词（当前仅"书包"→P004）。
"""

import json
import os
import re

import risk_intents
from risk_intents import detect_risk_intents  # noqa: F401  （供外部复用）

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(BACKEND_DIR, "knowledge_base.json")
CATALOG_PATH = os.path.join(BACKEND_DIR, "data", "business_capability_catalog.json")

# ---------------------------------------------------------------------------
# 产品同义词扩展（仅 V3 检索层；不修改 V2 原始 knowledge_base.json 的 aliases）。
# 只收录"必须映射到已有商品"的合理通用商品词，不收录完整测试句子。
# 记录为：产品同义词扩展（product synonym extension）。
# ---------------------------------------------------------------------------
EXTENDED_SYNONYMS = {
    "书包": "P004",  # 通用口语词，映射到 CityPack 通勤双肩包
}

RE_PRODUCT_ID = re.compile(r"(?<![A-Za-z0-9])P\d{3}(?![0-9])", re.IGNORECASE)
RE_ORDER_ID = re.compile(r"(?<!\d)20\d{10}(?!\d)")

# 意图 -> 对应必需规则片段（chunk_id 与 knowledge_chunks.jsonl 一致）。
# 风险意图的具体检测条件在 risk_intents.py（结构化：对象+动作+状态+语境+守卫）。
INTENT_RULE_MAP = {
    "complaint_compensation": "RULE-HR-01",   # 投诉赔偿
    "amount_dispute": "RULE-HR-02",           # 金额争议（多扣/重复扣款）
    "refund_urge": "RULE-HR-03",              # 退款催促/要求人工
    "logistics_stall": "RULE-HR-04",          # 物流停滞
    "other_order": "RULE-HR-05",              # 他人订单
    "privacy_info": "RULE-HR-06",             # 隐私信息
    "over_promise": "RULE-HR-07",             # 超范围承诺
    "post_purchase_defect": "RULE-HR-08",     # 售后质量缺陷（凭证核验）
}

# ---------------------------------------------------------------------------
# 风险/售后意图模式：V3.2 起全部迁移至 risk_intents.py 的结构化检测器
# （detect_complaint / detect_amount_dispute / detect_refund_urge /
#   detect_logistics_stall / detect_other_order / detect_privacy / detect_defect）。
# 每个检测器含对象/动作/状态/语境组合条件、排除条件与售前守卫，可独立测试。
# ---------------------------------------------------------------------------
_GENERIC_QUALITY_PATTERNS = [
    r"(质量|品质)(这|方面)?(怎么样|如何|好吗|好不好|行不行|靠谱吗)",
    r"(质量|品质)(是)?(一样|相同|一致)",
    r"(质量|品质)(有没有|有)(差(别|异)|区(别|分))",
    r"靠谱(吗|不|么)",
]

# 担忧/风险疑问式表述（用户在担心某个场景会不会出问题，而非询问商品属性）；
# 用于别名并列时的裁决：担忧式优先 FAQ/规则等解答型内容，中性属性询问优先商品片段。
_CONCERN_SCENARIO_PATTERNS = [
    r"会不会", r"有没有(问题|影响|危险|风险)", r"没(什么)?(事|问题|影响)(吧|吗|的?)?",
    r"正常吗", r"安全吗", r"可靠(吗|不|么)", r"不管用|不灵|失灵|有毛病",
    r"怕不怕", r"要紧吗", r"碍事吗",
    r"(坏|损|漏|炸|裂|短路|漏电|进水)",
    r"会(湿|坏|漏|裂|进水|短路)",
    # "这属于质量问题吧 / 是不是质量问题" 类确认式担忧问法（请求判定商品质量是否出了
    # 问题）。必须显式含"质量/售后"字样：泛化的"是不是出问题了"多为物流/订单担忧，
    # 不应触发担忧场景裁决（V3.1 调修：收窄避免误伤物流类用例）。
    r"(属于|是不是).{0,6}(质量|售后)问题",
]

# 常见日用/数码商品类属名词（类别级通用词，非任何测试句）：
# 用于"范围外词仅作场景描述"的判别——天气等词 + 商品名词 + 担忧式表述组合出现时，
# 问题实际指向商品使用场景（如雨天背包是否淋湿），不应按范围外话题拦截。
_GENERAL_PRODUCT_NOUNS = [
    "耳机", "键盘", "鼠标", "音箱", "台灯", "灯", "电脑", "笔记本", "平板", "手机",
    "充电器", "电池", "屏幕", "摄像头", "路由器", "杯子", "保温杯", "水杯", "壶",
    "包", "背包", "双肩包", "书包", "行李箱", "伞", "手表", "衣服", "鞋",
]

# ---------------------------------------------------------------------------
# 已覆盖业务意图（supported，非风险类；用于门控与意图归一化）
# ---------------------------------------------------------------------------
_SUPPORTED_INTENT_PATTERNS = {
    "order_status_query": [
        r"订单.{0,8}(状态|进度|到哪|走到哪|环节|哪一步|处理到|怎么样了)",
        r"(订单|单子|单号).{0,8}(到哪|走到哪|走到哪个|怎么样了)",
        r"[我这那]{0,2}单.{0,12}(出货|发货|到哪|进度|处理|状态|怎么样)",
        r"(查|看|看看|查询|帮我查|帮我瞅瞅|瞅瞅).{0,10}(订单|单号|单子|快递|包裹|物流)",
        r"发货了吗|发货没有|发货没|什么时候发货|几号发货|安排发货|多久.{0,6}发货|啥时候发货",
        r"配送进度|物流到哪|包裹到哪",
        r"(有没有|是否)(发货|出库)",
    ],
    "order_modify_query": [
        r"(换|改|修改|更换).{0,10}(型号|商品|颜色|尺码|数量|地址)",
        r"(型号|商品|颜色|尺码).{0,4}(换|改|更换)",
        r"(把|将).{0,14}换成?.{0,8}(款|色|型号|尺码)",
        r"换成?.{0,6}(白|黑|蓝|灰|红|粉|绿)?色?款",
    ],
    "address_change_query": [
        r"(地址|收件|收货).{0,8}(填错|写错|填岔|错了|改|更改)",
        r"改.{0,6}(地址|寄送|收件|收货|地点)",
    ],
    "return_exchange_query": [
        r"(七天|7天)(无理由)?", r"无理由退", r"换货", r"退货运费",
        r"(想|要|能|可以|怎么).{0,6}退(货|了|掉)", r"不想要了", r"不喜欢.{0,6}退",
        r"(没|未)拆封", r"没怎么用|没用过|未使用", r"还.{0,4}能退不?",
    ],
    "refund_progress_query": [
        r"退款.{0,12}(多久|什么时候|几天|到账|进度|没到|未到|卡)",
        r"(多久|什么时候|几天).{0,6}(退款|退回|到账|回来)",
        r"钱.{0,6}(退回来|到账)",
        r"(原路|原卡|原支付渠道)(返回|退回|退)",
        r"几个?工作日",
    ],
    "payment_issue_query": [
        r"(付款|支付|扣款).{0,10}(失败|没反应|状态|问题|异常|延迟)",
        r"待付款", r"付了.{0,8}还(显示|是|挂)", r"付款.{0,6}有?问题",
        r"钱都扣了",
        # 已扣款但订单仍要求再次支付（重复支付/状态未同步类问题）
        r"扣(过|了)(钱|款).{0,20}(再|又|还).{0,6}付",
    ],
    "warranty_repair_query": [r"保修", r"维修", r"售后"],
    "aftersales_process_query": [
        r"(出了|有).{0,4}(毛病|问题).{0,10}(怎么办|咋整|怎么处理|怎么走|流程)",
        r"售后(流程|怎么)",
    ],
    "shipping_issue_query": [
        r"(物流|快递|包裹).{0,10}(多久|几天|慢|没到|未到|丢了|不见了)",
        r"(显示|提示).{0,8}(签收|代签)",
        r"签收.{0,14}没(有)?(收到|看到|拿到|拿着)",
        r"运费|包邮|邮费",
    ],
    "human_service_query": [r"转人工", r"人工客服", r"找客服", r"真人客服"],
    # 客服服务时间咨询（V3.2.1）：询问上班/下班/营业时间属普通服务咨询，
    # 不构成风险诉求，防止"客服"字样经语义相似触发规则安全网误转人工。
    "service_hours_query": [
        r"(客服|人工|店里|店铺|你们).{0,8}(几点|上班|下班|营业|工作时间)",
        r"(几点|什么时间)(上班|下班|营业|开门)",
    ],
}

# ---------------------------------------------------------------------------
# 未覆盖业务意图（unsupported_business：电商问题但资料没有覆盖）
# ---------------------------------------------------------------------------
_UNCOVERED_INTENT_PATTERNS = {
    "promo_activity": [
        r"促销", r"优惠", r"活动价", r"满减", r"折扣", r"优惠券", r"领券",
        r"双十一|双11|618|年货节", r"会员日", r"秒杀", r"拼团", r"便宜多少|比平时便宜",
        r"定金", r"预售", r"半价", r"第二件", r"立减",
        r"大促", r"(搞|做)活动", r"划算",
    ],
    "gift_policy": [r"赠品", r"买一送一", r"送(什么|啥)礼", r"小礼品", r"随单礼",
                    r"附赠|随单|赠送|礼品"],
    "livestream_policy": [r"直播间", r"主播"],
    "stock_promise": [r"库存", r"现货", r"有没有货", r"缺货", r"补货", r"断货", r"存货"],
    "delivery_promise": [
        r"(承诺|保证|担保|打包票).{0,14}(送到|收|到货|拿到|送达|几天到|多久到|次日达|办成|发货)",
        r"(次日|当天)达",
        r"(明天|后天|今明两天)(能|会)(到|送到|送达|发货)",
        r"(几天|多久|什么时候).{0,4}(能到|会到|送到|送达|能送|能收)",
        r"几天能到|多久能送到|多久到货",
    ],
    # 发票类型/条件/流程：知识库仅有兜底说明片段（FAQ-018 内容即"资料未覆盖发票
    # 类型/条件/流程，由人工核实处理"），不构成发票政策答案。按 V3.1 三分类口径
    # （用户批准，见 v3_1_phase2_freeze_report.md 第三节）属于"业务相关但资料未覆盖"，
    # 一律 unsupported_business：supported=false、results=[]、给出去人工核实的下一步。
    # 不得因存在兜底片段就将问题判为资料已覆盖。
    "invoice_policy": [
        r"发票", r"开票", r"电子发票", r"专票", r"增值税", r"开.{0,4}的?票",
        r"报销.{0,8}(票据|凭证|开)",
    ],
    "price_protect": [r"价保", r"退差价", r"保价", r"降价.{0,10}(补|退)", r"补差",
                      r"差价", r"价差"],
    "warehouse_carrier": [
        r"哪个城市.{0,4}发货", r"仓库.{0,8}(哪|什么)", r"哪家.{0,2}快递",
        r"(用什么|哪个)快递", r"从哪(儿|里)发货",
    ],
    "unknown_product_sales": [
        r"(卖不卖|有没有卖|卖吗|有售|上架了|出售|上新了?|上新)", r"(新品|新款)",
        r"(其他|别家|别人家)品牌", r"(代理|经销)",
    ],
    # 延保/付费延长保修：资料仅有12个月有限保修，无延保产品与价格（V3.2 新增）
    "warranty_extension": [
        r"延保", r"延长保修", r"(付费|花钱|加钱).{0,8}保修", r"保修(套餐|升级|加购)",
    ],
    # 商品清洗/保养方法：商品资料仅记录个别注意事项（如不建议洗碗机），
    # 无系统性清洗保养说明（V3.2 新增，属资料未覆盖）
    "product_care_method": [
        r"(怎么|如何|怎样)(清洗|清洁|保养|打理)", r"清洗(方法|方式)",
        r"(多久|怎么)(洗一次|保养)", r"除(味|臭)", r"去味",
    ],
    # 商品横向对比/排名/水平评价：需要竞品与市场数据，资料完全未覆盖（V3.2）。
    # 比较句式要求比较后接评价结论词，避免把"跟朋友的比是不是便宜些"这类
    # 价格确认（价格属已覆盖属性）误判为竞品对比。
    "comparison_or_review": [
        r"算什么水平", r"什么水平", r"排第几", r"排名第?",
        r"(跟|和|与)[^，。？?比]{1,8}(比|相比|对比|比较)(哪个|谁)?(更|比较)?(好|强|划算|耐用|值得|性价比高|省电|清楚|舒服)",
    ],
    # 多人拼单/代付的售后责任归属：涉及订单归属与分摊，资料未记录（V3.2）
    "joint_purchase": [
        r"拼单", r"拼购", r"合买", r"一起买的?", r"(代|帮).{0,3}付(钱|款)?", r"垫付",
    ],
    # 防伪码/正品验证：资料无防伪验证机制说明（V3.2）
    "anti_counterfeit": [
        r"防伪", r"验货", r"验证真假", r"(辨别|鉴别|验证).{0,4}(真|假|正品)",
        r"正品(验证|查询|码)?",
    ],
    # 配件/周边单独售卖：商品资料仅记录包装内随附内容，无配件售卖信息（V3.2）
    "accessory_sales": [
        r"配套", r"杯套", r"保护套", r"单独卖", r"单买", r"(卖|送).{0,4}(套|配件)",
    ],
    # 客服服务时效/响应速度评价与咨询：资料无服务时效承诺（V3.2）
    "service_response_speed": [
        r"客服.{0,10}(速度|响应)", r"客服.{0,6}回复.{0,3}(快|慢)",
        r"(回复|响应).{0,6}(快|慢)(吗|么)?",
    ],
}

# ---------------------------------------------------------------------------
# 明显范围外主题（irrelevant：非电商客服问题）
# ---------------------------------------------------------------------------
_OUT_OF_SCOPE_PATTERNS = {
    "weather": [r"天气", r"气温", r"下雨", r"下雪", r"台风", r"降温"],
    "investment": [r"股票", r"基金", r"理财", r"黄金", r"汇率", r"外汇", r"btc|比特币"],
    "travel_visa": [r"签证", r"护照", r"旅游攻略", r"景点", r"机票", r"酒店", r"民宿", r"爬山", r"徒步", r"露营"],
    "study_writing": [r"论文", r"开题", r"作文", r"简历", r"作业", r"复习资料",
                      r"零基础", r"入门", r"教程", r"课程", r"自学", r"毕业设计", r"选题",
                      r"补习", r"辅导", r"高数", r"微积分", r"数学题", r"自我介绍", r"演讲稿", r"检讨书",
                      r"英语角", r"雅思", r"托福"],
    "health_medical": [r"失眠", r"就医", r"看病", r"用药", r"医院", r"症状", r"疾病", r"体检"],
    "entertainment": [r"电影", r"电视剧", r"演唱会", r"综艺", r"游戏攻略", r"攻略",
                      r"游戏名", r"追剧", r"动漫", r"小说", r"书单", r"追更", r"漫画"],
    "life_misc": [r"菜谱", r"做菜", r"健身计划", r"健身房", r"瑜伽", r"风水", r"星座",
                  r"护肤", r"化妆", r"美甲"],
    "tech_dev": [r"编程", r"写代码", r"数据库", r"服务器搭建", r"系统提示词", r"提示词",
                 r"忽略.{0,8}(指令|提示|规则|设定)", r"越狱", r"系统指令", r"内部规则",
                 r"(检索|相似度|融合)?阈值", r"门控", r"\brrf\b", r"向量库|向量检索",
                 r"(告诉我|透露|说说).{0,10}(内部|系统|设定|机制|实现)"],
    # 办公软件使用类（与商品售后无关的通用软件问题）
    "office_software": [r"excel", r"vlookup", r"数据透视", r"透视表", r"公式怎么",
                        r"函数怎么", r"ppt", r"word文档", r"ps抠图", r"表格公式",
                        r"宏命令", r"数据可视化"],
    # 宠物类（非电商客服业务）
    "pet_animal": [r"宠物", r"猫粮", r"狗粮", r"遛狗", r"铲屎", r"猫咪", r"小狗",
                   r"养猫", r"养狗", r"猫砂", r"猫", r"狗"],
}

# 电商语境信号（用于 unknown 兜底分类：有信号→unsupported_business，无→irrelevant）
_COMMERCE_SIGNAL_RE = re.compile(
    r"买|卖|购|订单|下单|发货|退|换|修|客服|售后|商品|商品|货|款|价|包邮|运费|快递|物流|包裹|优惠|发票|尺码|型号"
)

_kb_cache = None


def _load_kb():
    global _kb_cache
    if _kb_cache is None:
        with open(KB_PATH, encoding="utf-8") as f:
            _kb_cache = json.load(f)
    return _kb_cache


def _product_alias_table():
    """[(alias短语, product_id, 是否扩展同义词)]；名称+别名+扩展同义词。"""
    table = []
    for p in _load_kb().get("products", []):
        pid = p["id"]
        for phrase in [p.get("name", "")] + list(p.get("aliases", [])):
            phrase = (phrase or "").strip().lower()
            if len(phrase) >= 2:
                table.append((phrase, pid, False))
    for syn, pid in EXTENDED_SYNONYMS.items():
        table.append((syn.lower(), pid, True))
    return table


_catalog_cache = None


def _load_catalog():
    """加载业务能力目录（已知商品+已覆盖属性+未覆盖业务类型）。"""
    global _catalog_cache
    if _catalog_cache is None:
        with open(CATALOG_PATH, encoding="utf-8") as f:
            _catalog_cache = json.load(f)
    return _catalog_cache


def _covered_attributes(q, pids):
    """查询命中的已覆盖属性列表（能力目录驱动）。返回 ([(pid, attr)], [命中关键词])。
    排除规则：关键词若是该商品别名/名称的子串（如"保温"⊂"保温杯"），
    则只是商品指称本身而非属性询问，不计为属性命中。"""
    cat = _load_catalog()
    alias_by_pid = {}
    for phrase, pid, _is_ext in _product_alias_table():
        alias_by_pid.setdefault(pid, set()).add(phrase)
    hits = []
    kw_hits = []
    for pid in pids:
        spec = (cat.get("known_products") or {}).get(pid) or {}
        aliases = alias_by_pid.get(pid) or set()
        for a in spec.get("covered_attributes") or []:
            for kw in a.get("keywords") or []:
                if kw in q and not any(kw in al for al in aliases):
                    hits.append((pid, a["attr"]))
                    kw_hits.append(kw)
                    break
    return hits, kw_hits


def _is_attribute_question(q):
    """是否为属性/能力询问句式（吗/呢/多少/能不能/支持不/怎么样…）。"""
    return bool(re.search(
        r"吗|么[??。！!]?|呢|？|\?|多少|怎么样|如何|能不能|可不可以|可以不|支持不|"
        r"有没有|几|多久|多大|哪个|什么|会不会|能不能|行不行|好不好|能不能装|多久能",
        q))


# ---------------------------------------------------------------------------
# 未知商品询问模式（V3.2）：句式指向"本店在售的某商品"但该商品不在能力目录
# （P001-P005）中 → 资料未覆盖该商品（unsupported_business，unknown_product_inquiry）。
# 只用句式结构判断 + 已知商品名单反查，不枚举任何具体测试商品词。
# ---------------------------------------------------------------------------
_RE_YOURSHOP_PRODUCT = re.compile(r"你们(?:家|店)(?:里的?)?(.{1,8}?)(是|有|卖|怎么样|哪个|怎么)")
_RE_PRESUBJ_HASSELL = re.compile(r"^(.{1,6}?)有没有[^，。？！?!]*?(卖|款式|售|在售|上新)")

# ---------------------------------------------------------------------------
# 未知商品结构化识别（V3.2.1 扩展）：三要素结构化组合——
#   ① 商家指向词（你们的/你们家/店里/贵店…）
#   ② 属性/功能/售价/库存/购买意图信号
#   ③ 指向对象不在已知商品目录（双向包含核对：主体⊂已知别名 或 已知别名⊂主体）。
# 只用结构模式 + 已知商品反查，不建立任何具体未知商品名称名单；
# 通用指称（东西/商品/这款…）与动词开头主体（去/吃/办…）不视为未知商品实体。
# ---------------------------------------------------------------------------
_RE_SHOP_POINTER = re.compile(
    r"你们(?:的|家(?:里的?)?|店(?:里的?)?)|你?店里|贵店|咱(?:们)?(?:店|家)")
_RE_PRODUCT_INTENT = re.compile(
    r"有没有|卖不卖|卖吗|有售|在售|上架|出售|发售|有货|现货|库存|"
    r"多少钱|什么价|价格|贵不贵|便不便宜|"
    r"功能|支持[^，。？?]{0,6}(?:吗|么)|"
    r"防水|续航|保修|充电|蓝牙|音质|降噪|容量|尺寸|尺码|型号|材质|重量|功率|"
    r"质量(?:怎么样|如何|好吗|好不好)|怎么样|好不好|好用|好使|耐用|"
    r"推荐|值得(?:买|入手)|能用|可以用|有(?:什么|哪些)(?:颜色|款式|功能|型号)")
# 通用指称/非商品主体（指向这些词时不是"某款未知商品"询问）
_GENERIC_SUBJECT_REFERS = ("东西", "商品", "产品", "货品", "物品", "这款", "这个",
                           "那个", "此种", "服务", "客服", "售后", "快递", "物流",
                           "发货", "发票", "老板", "公司", "回复", "态度", "上班",
                           "下班", "营业", "发货速度", "店")
# 主体以动词开头多为事务/服务询问（去北京多少钱/修表多少钱），非商品实体
_RE_SUBJECT_LEAD_VERB = re.compile(
    r"^(去|来|吃|喝|玩|学|办|做|修|看|听|上|交|寄|问|参加|报|考|租|寄|送)")
# 承诺要求中的施压/命令语义（V3.2.1 调和用）：带此类表述的承诺要求按风险处理
_RE_PROMISE_PRESSURE = re.compile(
    r"你就告诉我|给我(个)?(准话|保证|承诺)|跟我(保证|担保|打包票|承诺)"
    r"|向我(保证|担保|承诺)|必须(要)?(给我|跟我)?(保证|承诺|担保)"
    r"|不(保证|承诺)就|否则|不然的话|马上|立即|立刻")
# 主体尾部的属性引导片段（"空气炸锅有定时功能吗"→主体剥离"有定时"）
_RE_SUBJECT_ATTR_TAIL = re.compile(r"(有|带|支持|含|能不能|可以|是否|是不是)[^，。？?]{0,8}$")


def _unknown_product_subject_check(q, subject, known_phrases):
    """主体合法性核对：返回 True 表示"指向不在售目录内商品"（未知商品询问）。"""
    if not subject:
        return False
    subject = _RE_SUBJECT_ATTR_TAIL.sub("", subject).strip("的了吗呢吧啊呢了是，,。 ？?！!")
    if len(subject) < 2 or len(subject) > 14:
        return False
    if any(g in subject for g in _GENERIC_SUBJECT_REFERS):
        return False
    if _RE_SUBJECT_LEAD_VERB.match(subject):
        return False
    # 双向包含核对：主体与任一已知商品名称/别名互为子串 → 已知商品
    if any(subject in p or p in subject for p in known_phrases):
        return False
    return True

# 生活场景闲聊语境（类别级通用词）：无任何业务/商品/风险信号且命中此类词时，
# 多为生活话题而非电商客服问题（如干电池型号、家用电器闲聊）。
_LIFE_CONTEXT_RE = re.compile(
    r"家里|客厅|卧室|厨房|卫生间|楼道|楼下|小区|单位|办公室|宿舍|出租屋")

# 商品别名/同义词全集（用于未知商品反查），analyze 首次调用时构建
_KNOWN_PRODUCT_PHRASES = None


def _known_product_phrases():
    global _KNOWN_PRODUCT_PHRASES
    if _KNOWN_PRODUCT_PHRASES is None:
        phrases = set()
        for phrase, _pid, _is_ext in _product_alias_table():
            phrases.add(phrase)
        _KNOWN_PRODUCT_PHRASES = phrases
    return _KNOWN_PRODUCT_PHRASES


def analyze(query):
    """分析用户问题，返回意图与业务范围三分类结果（纯函数，无副作用）。"""
    query = (query or "").strip()
    reasons = []

    q = RE_ORDER_ID.sub(" ", query.lower())  # 订单号剥离，不参与实体/意图识别

    # 1. 明确商品编号
    product_ids = []
    for m in RE_PRODUCT_ID.finditer(q.upper()):
        pid = "P" + m.group(0)[-3:]
        if pid not in product_ids:
            product_ids.append(pid)
    if product_ids:
        reasons.append(f"商品编号命中: {','.join(product_ids)}")

    # 2. 商品名称/别名/扩展同义词
    alias_pid_map = {}
    extended_used = []
    for phrase, pid, is_ext in _product_alias_table():
        if phrase in q:
            alias_pid_map[phrase] = pid
            if is_ext:
                extended_used.append(phrase)
    best_by_pid = {}
    for phrase, pid in alias_pid_map.items():
        if pid not in best_by_pid or len(phrase) > len(best_by_pid[pid]):
            best_by_pid[pid] = phrase
    product_aliases = sorted(best_by_pid.values())
    if product_aliases:
        reasons.append(f"商品名称/别名命中: {','.join(product_aliases)}")
    if extended_used:
        reasons.append(f"产品同义词扩展命中(仅V3检索层): {','.join(extended_used)}")

    entity_pids = sorted(set(product_ids) | set(best_by_pid.keys()))
    # 显式编号命中的商品（仅 PXXX 字面出现）；与别名/同义词推导区分：
    # 只有显式编号才允许强制 Top-1，别名命中只做业务提升（V3.1 修正）。
    exact_product_ids = list(product_ids)

    # 3. 风险/售后意图：V3.2 结构化检测器（对象+动作/状态+语境组合+守卫）
    risk_hits = detect_risk_intents(q)
    intents = [r["intent"] for r in risk_hits]
    matched_detail = {r["intent"]: [r["reason"]] for r in risk_hits}
    risk_evidence = {r["intent"]: r["evidence"] for r in risk_hits}
    has_defect = "post_purchase_defect" in intents

    has_generic_quality = any(re.search(p, q) for p in _GENERIC_QUALITY_PATTERNS)
    has_concern_scenario = any(re.search(p, q) for p in _CONCERN_SCENARIO_PATTERNS)
    if has_generic_quality:
        if has_defect:
            reasons.append("同时存在质量缺陷表述与质量咨询措辞，按已发生缺陷处理")
        else:
            reasons.append("泛化质量咨询（未表明已购买或已发生问题）")

    required_rule_ids = []
    for intent in dict.fromkeys(intents):
        rid = INTENT_RULE_MAP.get(intent)
        if rid and rid not in required_rule_ids:
            required_rule_ids.append(rid)
    if required_rule_ids:
        reasons.append(f"风险意图: {','.join(dict.fromkeys(intents))} -> {','.join(required_rule_ids)}")

    # 4. 已覆盖业务意图（supported 非风险类）+ FAQ 意图归一化改写
    supported_intents = []
    rewrites = []
    for intent, patterns in _SUPPORTED_INTENT_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, q):
                supported_intents.append(intent)
                break
    REWRITE_BY_INTENT = {
        "order_status_query": "查询订单状态 物流进度 发货情况",
        "order_modify_query": "修改订单商品信息 订单提交后还能改吗",
        "address_change_query": "修改收货地址 更改配送地址",
        "return_exchange_query": "七天无理由退货条件 拆封未使用退货 换货流程",
        "refund_progress_query": "退款进度 退款多久到账",
        "payment_issue_query": "支付状态延迟 付款后仍显示待付款 已扣款还要求再次支付",
        "warranty_repair_query": "保修政策 售后处理流程",
        "aftersales_process_query": "质量问题售后流程 商品有问题怎么办",
        "shipping_issue_query": "物流查询 包裹签收未收到 退货运费",
        "human_service_query": "转人工客服 人工服务",
        "service_hours_query": "客服工作时间 上下班及营业时间咨询",
    }
    for it in dict.fromkeys(supported_intents):
        if it in REWRITE_BY_INTENT:
            rewrites.append(REWRITE_BY_INTENT[it])
    if supported_intents:
        reasons.append(f"已覆盖业务意图: {','.join(dict.fromkeys(supported_intents))}")

    # 5. 未覆盖业务意图（unsupported_business）
    #    配送时效承诺类例外：询问对象是退款/退货到达时间时属于已覆盖的退款进度问题，
    #    不按"配送时效承诺"拦截（"退款多久能到"≠"快递几天能送到"）。
    uncovered_intents = []
    refund_context = bool(re.search(r"退款|退回|退货|退款到", q))
    for intent, patterns in _UNCOVERED_INTENT_PATTERNS.items():
        if intent == "delivery_promise" and refund_context:
            continue
        for pat in patterns:
            if re.search(pat, q):
                uncovered_intents.append(intent)
                break
    if uncovered_intents:
        reasons.append(f"未覆盖业务意图: {','.join(dict.fromkeys(uncovered_intents))}")

    # 5.6 复合未覆盖价格意图（V3.2.1）：优先于通用"价格"属性判定——
    #     问句包含"价格"字样不等于询问商品售价（二手回收价/估价/以旧换新/
    #     折价/保值/历史价格/未来降价等资料均未记录）。关键词类别维护于
    #     能力目录 price_related_uncovered（可追溯），此处仅加载判定。
    composite_price_hits = []
    for entry in _load_catalog().get("uncovered_business_types") or []:
        if entry.get("type") == "price_related_uncovered":
            composite_price_hits = [kw for kw in entry.get("keywords") or [] if kw in q]
            break
    if composite_price_hits:
        uncovered_intents.append("price_related_uncovered")
        reasons.append("复合未覆盖价格意图(优先于通用价格属性): " + ",".join(composite_price_hits))

    # 5.5 电商语境信号（提前计算：未知商品/生活闲聊检测与门控均需要）
    has_commerce_signal = bool(_COMMERCE_SIGNAL_RE.search(q))

    # 6. 范围外主题（irrelevant）
    out_of_scope_topics = []
    for topic, patterns in _OUT_OF_SCOPE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, q):
                out_of_scope_topics.append(topic)
                break
    if out_of_scope_topics:
        # 场景描述豁免：天气等范围外词仅作使用场景描述（同时出现常见商品名词 +
        # 担忧式表述，如雨天背包会不会淋湿）时，问题实际是商品使用咨询，不按范围外拦截。
        if has_concern_scenario and any(n in q for n in _GENERAL_PRODUCT_NOUNS):
            reasons.append("范围外词仅作场景描述，问题实际指向商品使用场景，不按范围外处理")
            out_of_scope_topics = []
        else:
            reasons.append(f"范围外主题: {','.join(out_of_scope_topics)}")

    # 6.5 未知商品询问（V3.2 建立句式，V3.2.1 扩展为结构化三要素识别）：
    #     句式指向本店在售商品但商品不在目录 → 未覆盖业务。
    #     仅在无风险意图、无已覆盖业务意图、无未覆盖意图时检查（避免抢位）。
    unknown_product_inquiry = False
    if not intents and not supported_intents and not uncovered_intents:
        known_phrases = _known_product_phrases()
        has_known_entity = bool(entity_pids) or any(p in q for p in known_phrases)

        # A. 商家指向 + 购买/属性意图 + 主体不在目录（V3.2.1：覆盖"你们的/贵店"等
        #    指向词与"XX有XX功能吗"句式；主体经通用指称/动词开头/双向包含核对）
        if not has_known_entity and _RE_SHOP_POINTER.search(q):
            m_ptr = _RE_SHOP_POINTER.search(q)
            m_int = _RE_PRODUCT_INTENT.search(q, m_ptr.end())
            if m_int and _unknown_product_subject_check(
                    q, q[m_ptr.end():m_int.start()], known_phrases):
                unknown_product_inquiry = True
                reasons.append("商家指向词+商品意图信号，询问对象不在在售商品目录")

        # B. 主体前置 + 销售/库存动词（有没有卖/卖不卖/在售/有现货…）（V3.2 原有）
        if not unknown_product_inquiry and not has_known_entity:
            m = _RE_PRESUBJ_HASSELL.search(q)
            if m and _unknown_product_subject_check(q, m.group(1), known_phrases):
                unknown_product_inquiry = True
                reasons.append("询问对象不在在售商品目录内: %s" % m.group(1))

        # C. 主体前置 + 售价询问（XX多少钱，V3.2.1 新增）
        if not unknown_product_inquiry and not has_known_entity:
            m = re.match(r"(.{2,12}?)(多少钱|什么价格|价格是多少|卖多少钱)", q)
            if m and _unknown_product_subject_check(q, m.group(1), known_phrases):
                unknown_product_inquiry = True
                reasons.append("售价询问对象不在在售商品目录内: %s" % m.group(1))

        # 兼容保留 V3.2 原有句式（你们(家|店)+是/有/卖/怎么样/哪个/怎么），
        # V3.2.1 起同样经过主体合法性核对（通用指称/动词开头/双向包含排除）
        if not unknown_product_inquiry:
            for m in _RE_YOURSHOP_PRODUCT.finditer(q):
                if _unknown_product_subject_check(q, m.group(1), known_phrases):
                    unknown_product_inquiry = True
                    reasons.append("询问对象不在在售商品目录内: %s" % m.group(1))
                    break
        if unknown_product_inquiry:
            uncovered_intents.append("unknown_product_inquiry")

    # 6.6 生活场景闲聊（V3.2）：无风险/业务/范围外信号、无商品实体、无电商语境，
    #     且命中生活场景语境词 → 非电商客服问题（irrelevant）。
    life_offtopic = False
    if (not intents and not supported_intents and not uncovered_intents
            and not entity_pids and not out_of_scope_topics
            and not has_generic_quality and not has_concern_scenario
            and not has_commerce_signal and _LIFE_CONTEXT_RE.search(q)):
        life_offtopic = True
        out_of_scope_topics.append("life_context_chat")
        reasons.append("无电商业务信号且为生活场景话题，非客服问题范围")

    # 6.8 承诺类调和（V3.2.1）：over_promise 是唯一风险意图、承诺对象仅为
    #     发货/送达/送到（配送时效类）、且同时命中 delivery_promise 未覆盖意图时：
    #     - 无施压/命令语义（纯"能保证…吗"政策性询问）→ 按"配送时效承诺"未覆盖
    #       业务处理（资料无配送时效政策）；
    #     - 带施压语义（你就告诉我/给我保证/跟我打包票/必须…/否则…）→ 仍按
    #       超范围承诺风险转人工。
    #     保证/承诺对象涉及退款、到账、赔偿、修好等非配送类时不受此调和影响。
    if intents == ["over_promise"] and "delivery_promise" in uncovered_intents:
        obj_ev = (risk_evidence.get("over_promise") or {}).get("object") or []
        if obj_ev and all(o in ("发货", "送达", "送到") for o in obj_ev) \
                and not _RE_PROMISE_PRESSURE.search(q):
            intents = []
            required_rule_ids = []
            reasons.append("纯配送时效承诺询问（无施压语义），按未覆盖配送时效政策处理")

    # 7. 业务范围三分类门控（V3.2：能力目录驱动）
    #    优先级：风险/售后意图 > 范围外主题 > 未覆盖业务意图 > 商品实体+属性覆盖判断
    #    > 泛化质量咨询 > unknown（交由检索层证据判定）
    #    V3.2 关键变化：识别到商品实体不再默认支持该商品的所有问题——
    #    属性询问句式 + 未见任何已覆盖属性 → unsupported_business（未知属性）。
    scope = None
    covered_attr_hits = []
    covered_attr_keywords = []
    if entity_pids and not intents:
        covered_attr_hits, covered_attr_keywords = _covered_attributes(q, entity_pids)
        if composite_price_hits:
            # 复合未覆盖价格意图命中时，"价格"字样不按商品售价属性处理（V3.2.1）
            filtered = [(p, a) for (p, a) in covered_attr_hits if a != "价格"]
            if len(filtered) != len(covered_attr_hits):
                reasons.append("价格字样属复合未覆盖价格意图，不按商品售价属性处理")
            covered_attr_hits = filtered
            covered_attr_keywords = [k for k in covered_attr_keywords if k != "价格"]
        if covered_attr_hits:
            reasons.append("已覆盖属性: " + ",".join(
                f"{pid}.{attr}" for pid, attr in covered_attr_hits))

    if intents:
        scope = "supported"
    elif out_of_scope_topics:
        scope = "irrelevant"
    elif uncovered_intents:
        scope = "unsupported_business"
    elif entity_pids:
        if covered_attr_hits or supported_intents:
            scope = "supported"
        elif _is_attribute_question(q):
            # 已知商品 + 属性询问 + 目录未见覆盖属性 → 资料未覆盖该属性
            scope = "unsupported_business"
        else:
            scope = "unknown"
    elif supported_intents:
        scope = "supported"
    elif has_generic_quality:
        # 无实体+仅泛化质量咨询：电商范围但资料无法支撑回答
        scope = "unsupported_business"
    else:
        scope = "unknown"

    if scope == "unsupported_business":
        if any(i in uncovered_intents
               for i in ("unknown_product_inquiry", "unknown_product_sales")):
            gate_reason = ("目前资料中没有这款商品的信息，暂时无法确认。"
                           "请提供商品编号或联系人工客服核实。")
        else:
            gate_reason = "现有资料没有覆盖这项信息，建议联系人工客服确认。"
    elif scope == "irrelevant":
        gate_reason = "抱歉，我只能协助处理本店商品、订单和售后相关问题。"
    else:
        gate_reason = None

    return {
        "product_ids": entity_pids,
        "exact_product_ids": exact_product_ids,
        "product_aliases": product_aliases,
        "has_exact_entity": bool(entity_pids),
        "intents": list(dict.fromkeys(intents)),
        "risk_evidence": risk_evidence,
        "covered_attributes": ["%s.%s" % (p, a) for p, a in covered_attr_hits],
        "covered_attribute_keywords": list(dict.fromkeys(covered_attr_keywords)),
        "required_rule_ids": required_rule_ids,
        "supported_intents": list(dict.fromkeys(supported_intents)),
        "uncovered_intents": list(dict.fromkeys(uncovered_intents)),
        "out_of_scope_topics": list(dict.fromkeys(out_of_scope_topics)),
        "rewrites": rewrites,
        "has_post_purchase_defect": has_defect,
        "has_generic_quality_question": has_generic_quality,
        "has_concern_scenario": has_concern_scenario,
        "scope": scope,
        "is_supported_domain": scope in ("supported", "unknown"),
        "gate_reason": gate_reason,
        "has_commerce_signal": has_commerce_signal,
        "reasons": reasons,
    }


if __name__ == "__main__":
    demos = [
        "P001的耳机续航多久",
        "书包侧面能装下16寸的电脑吗",
        "这个杯子到手就有裂痕了",
        "你们家东西质量怎么样，靠谱吗",
        "包裹好几天没动静了",
        "帮我查下我同事的单子",
        "拉链昨天就拉不动了，买来第二天就这样",
        "这包拉链好用吗，会不会卡",
    ]
    for d in demos:
        print(d, "->", json.dumps(analyze(d), ensure_ascii=False))
