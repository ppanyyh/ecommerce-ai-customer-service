/* =============================================================
 * app.js — 电商客服AI助手 核心逻辑
 * 规则来源：项目知识库资料（商品资料 / 客服FAQ / 售后SOP / 模拟订单数据）
 * 原则：资料中有明确依据才回答并标注依据；无依据明确说明未覆盖；不编造。
 * ============================================================= */

/* ---------------- 通用工具 ---------------- */
function norm(t) { return (t || '').toString().toLowerCase(); }

var KNOWN_ORDER_IDS = ['202609180001', '202609180002', '202609180003'];

/* ---------------- 可维护的风险/意图关键词集合 ----------------
 * 集中管理，避免在逻辑里散落写死单一测试语句。
 * 依据：《售后SOP》必须转人工 / 退款处理 / 物流异常处理 / 隐私规则 */
var COMPLAINT_KEYS = ['投诉', '太坑了', '骗人', '垃圾', '差评', '曝光', '消协', '315', '赔钱', '赔偿', '三倍', '给个说法', '举报', '维权', '媒体'];
var AMOUNT_DISPUTE_KEYS = ['金额不对', '多扣钱', '重复扣款', '少退款', '退款金额有误', '实付金额不一致', '金额异常', '金额错误', '金额有误', '金额不一致', '多扣', '少退', '扣了两次', '扣错', '多收费', '多收了', '价格不对'];
var URGE_KEYS = ['还不退款', '还不退', '为什么还不', '马上退款', '立即退款', '立刻退款', '尽快退款', '赶紧退', '催', '催促', '请立即处理', '立即处理', '马上处理', '尽快处理'];
var HUMAN_KEYS = ['转人工', '人工介入', '人工客服', '找人工', '人工处理'];
var LOSS_KEYS = ['丢了', '丢失', '不见了', '遗失', '找不到了', '找不到'];
var QUALITY_KEYS = ['质量', '坏了', '损坏', '破损', '故障', '无法使用', '用不了', '有问题'];

/* 物流长时间无更新表达（SOP：超过24小时无更新→转人工核实） */
var STALL_TIME_KEYS = ['超过24小时', '超24小时', '24小时没', '一天多没', '两天没', '两天都', '三天没', '好几天没', '不动', '卡住', '很久没', '一直没有', '一直没'];
var STALL_CTX_KEYS = ['物流', '快递', '包裹', '更新', '轨迹', '运输', '发货'];

function hitKeys(t, arr) { return arr.some(function (k) { return t.indexOf(k) >= 0; }); }

/* 物流停滞识别 */
function logisticsStall(text) {
  var t = norm(text);
  return hitKeys(t, STALL_TIME_KEYS) && hitKeys(t, STALL_CTX_KEYS);
}

/* 不完整订单号识别：有查询意图但只输入了6~11位连续数字（有效订单号为12位） */
function detectIncompleteOrder(text) {
  var t = norm(text);
  if (/2026\d{8}/.test(t)) return null;               // 已含完整12位单号
  var m = t.match(/(^|[^\d])(\d{6,11})(?![\d])/);
  if (!m) return null;
  var intent = /(订单|单号|查询|查一下|物流|退款|退货|发货|快递|包裹|签收)/.test(t);
  return intent ? m[2] : null;
}

/* 识别文本中的订单号（12位、以2026开头的数字串） */
function detectOrders(text) {
  var t = norm(text);
  var found = t.match(/2026\d{8}/g) || [];
  var known = [], unknown = [];
  found.forEach(function (id) {
    if (KNOWN_ORDER_IDS.indexOf(id) >= 0) { if (known.indexOf(id) < 0) known.push(id); }
    else if (unknown.indexOf(id) < 0) unknown.push(id);
  });
  return { mentioned: found.length > 0, known: known, unknown: unknown };
}

/* 匹配商品（按别名打分） */
function matchProduct(text) {
  var t = norm(text), best = null, bestScore = 0;
  KB.products.forEach(function (p) {
    var score = 0;
    p.aliases.forEach(function (a) { if (t.indexOf(a.toLowerCase()) >= 0) score += a.length; });
    if (t.indexOf(p.id.toLowerCase()) >= 0) score += 4;
    if (t.indexOf(p.name.toLowerCase()) >= 0) score += 8;
    if (score > bestScore) { bestScore = score; best = p; }
  });
  return bestScore > 0 ? best : null;
}

/* 匹配FAQ（关键词打分；带 specific 专用触发词的条目优先于泛化条目） */
function matchFaq(text) {
  var t = norm(text), best = null, bestScore = 0;
  KB.faqs.forEach(function (f) {
    var score = 0;
    f.keywords.forEach(function (k) { if (t.indexOf(k.toLowerCase()) >= 0) score += k.length; });
    if (score > bestScore) { bestScore = score; best = f; }
  });
  /* 专用条目：问题命中其 specific 触发词时，优先于按关键词得分选出的泛化条目 */
  var spec = null;
  for (var i = 0; i < KB.faqs.length; i++) {
    var f = KB.faqs[i];
    if (f.specific && f.specific.some(function (k) { return t.indexOf(k.toLowerCase()) >= 0; })) { spec = f; break; }
  }
  if (spec) return { faq: spec, score: Math.max(bestScore, 1), bySpecific: true };
  return bestScore > 0 ? { faq: best, score: bestScore } : null;
}

/* 商品属性关键词 → 规格字段 */
var ATTR_MAP = [
  { keys: ['价格', '多少钱', '售价', '卖多少', '费用'], fields: ['售价'] },
  { keys: ['续航', '能用多久', '用多久', '待机'], fields: ['单次续航', '综合续航', '电池容量', '供电', '保温参考'] },
  { keys: ['保修', '质保'], fields: ['保修期限'] },
  { keys: ['防水', '泼溅', '泼水', '进水'], fields: ['防护等级', '防水能力', '注意事项'] },
  { keys: ['降噪'], fields: ['降噪能力'] },
  { keys: ['容量'], fields: ['容量', '电池容量'] },
  { keys: ['材质', '内胆', '不锈钢'], fields: ['材质'] },
  { keys: ['颜色', '配色'], fields: ['颜色'] },
  { keys: ['型号'], fields: ['型号'] },
  { keys: ['包装', '配件', '里面有什么', '清单'], fields: ['包装内容'] },
  { keys: ['兼容', '支持什么', '系统', 'mac', 'windows', '安卓', 'ios'], fields: ['兼容设备', '系统兼容'] },
  { keys: ['保温', '保温多久'], fields: ['保温参考'] },
  { keys: ['接口', '充电', '充电口'], fields: ['充电接口', '供电'] },
  { keys: ['功率', '亮度', '色温', '定时'], fields: ['功率', '亮度', '色温', '定时'] },
  { keys: ['蓝牙'], fields: ['蓝牙版本', '连接方式'] },
  { keys: ['连接方式', '有线', '2.4g', '无线连接', '怎么连接', '如何连接'], fields: ['连接方式'] },
  { keys: ['轴体', '轴'], fields: ['轴体'] },
  { keys: ['背光', '灯光'], fields: ['灯光'] },
  { keys: ['配列', '键数', '几键'], fields: ['配列'] },
  { keys: ['电脑仓', '笔记本'], fields: ['电脑仓'] }
];

/* 商品问答：识别问题中命中的属性组（可多个），逐项回答 */
function matchAttrGroups(text) {
  var t = norm(text), groups = [];
  ATTR_MAP.forEach(function (m) {
    var hitKey = null;
    m.keys.forEach(function (k) { if (hitKey === null && t.indexOf(k.toLowerCase()) >= 0) hitKey = k; });
    if (hitKey) groups.push({ key: hitKey, fields: m.fields });
  });
  return groups;
}

/* 兼容旧调用：返回命中的字段列表 */
function productFields(p, text) {
  var fields = [];
  matchAttrGroups(text).forEach(function (g) {
    g.fields.forEach(function (f) { if (fields.indexOf(f) < 0) fields.push(f); });
  });
  return fields;
}

function answerProduct(p, text) {
  var groups = matchAttrGroups(text);
  var lines = [], missing = [], seen = {};
  groups.forEach(function (g) {
    var fl = p.specs.filter(function (s) { return g.fields.indexOf(s[0]) >= 0 && !seen[s[0]]; });
    if (fl.length) {
      fl.forEach(function (s) { seen[s[0]] = 1; lines.push(s[0] + '：' + s[1]); });
    } else {
      missing.push(g.key);
    }
  });
  var reply;
  if (groups.length && lines.length) {
    /* 多属性：逐项回答已有资料的属性；资料未覆盖的属性明确说明 */
    reply = '根据《商品资料》，' + p.name + '（' + p.id + '）的相关信息：\n' +
      lines.map(function (l) { return '· ' + l; }).join('\n');
    if (missing.length) {
      reply += '\n· ' + missing.join('、') + '：现有资料未覆盖该参数，无法确认。';
    }
  } else if (groups.length && !lines.length) {
    /* 问到的属性在资料中均无对应参数 → 无依据处理 */
    return null;
  } else {
    lines = p.specs.slice(0, 8).map(function (s) { return s[0] + '：' + s[1]; });
    reply = '根据《商品资料》，' + p.name + '（' + p.id + '）的相关信息：\n' +
      lines.map(function (l) { return '· ' + l; }).join('\n') +
      '\n……如需其他参数请继续提问。';
  }
  if (p.notes.length && (missing.length === 0) &&
      (lines.some(function (l) { return l.indexOf('防护等级') >= 0 || l.indexOf('防水能力') >= 0 || l.indexOf('单次续航') >= 0 || l.indexOf('保温参考') >= 0; }))) {
    reply += '\n补充说明：' + p.notes.join(' ');
  }
  return reply;
}

/* 订单问答 */
function orderReply(o, text) {
  var t = norm(text);
  var lines = [
    '· 订单号：' + o.id + '（用户：' + o.user + '）',
    '· 商品：' + o.productName + '（' + o.productId + '），单价 ' + o.unitPrice + ' × ' + o.quantity + ' = ' + o.amount,
    '· 订单状态：' + o.orderStatus,
    '· 物流状态：' + o.logisticsStatus + (o.logisticsCompany !== '-' ? '（' + o.logisticsCompany + ' ' + o.trackingNo + '）' : '（暂无物流信息）'),
    '· 售后状态：' + o.afterSalesStatus
  ];
  var reply = '已为你查询到该模拟订单：\n' + lines.join('\n');
  var transfer = false, reason = '', risk = '低';
  if (o.id === '202609180002') {
    reply += '\n处理提示：该订单存在进行中的售后申请。仅查询进度无需转人工；如需催促退款或修改售后申请，请转人工跟进，AI不承诺审核结果或到账时间。';
  } else if (o.afterSalesStatus !== '无') {
    reply += '\n处理提示：该订单存在进行中的售后申请。';
  }
  if (t.indexOf('发货') >= 0 && o.orderStatus === '待发货') {
    reply += '\n说明：订单当前为待发货状态，只能提供当前状态，不能承诺具体发货时间（《客服FAQ》FAQ-009）。';
  }
  if (t.indexOf('到账') >= 0 || t.indexOf('退款多久') >= 0) {
    reply += '\n说明：审核通过后仍需支付渠道处理，具体到账时间无法由AI保证（《售后SOP》退款处理）。';
  }
  return { reply: reply, transfer: transfer, reason: reason, risk: risk };
}

/* 退款施压/风险意图识别：仅查询进度不转人工，出现以下意图才转人工 */
function refundPressure(text) {
  var t = norm(text);
  if (hitKeys(t, AMOUNT_DISPUTE_KEYS)) {
    return { type: 'amount', risk: '高', transfer: true, reason: '涉及金额争议（金额不符/多扣/少退/重复扣款等），必须转人工核对订单及支付记录（《售后SOP》必须转人工），AI不承诺退款金额、处理结果或到账时间' };
  }
  if (hitKeys(t, COMPLAINT_KEYS)) {
    return { type: 'complaint', risk: '高', transfer: true, reason: '涉及投诉、赔偿、曝光或差评等诉求，必须转人工（《售后SOP》必须转人工），AI不承诺任何赔偿金额或处理结果' };
  }
  if (hitKeys(t, URGE_KEYS)) {
    return { type: 'urge', risk: '中', transfer: true, reason: '用户催促退款或审核，需人工跟进，AI不承诺具体退款时间或审核结果（《售后SOP》退款处理）' };
  }
  if (hitKeys(t, HUMAN_KEYS)) {
    return { type: 'human', risk: '中', transfer: true, reason: '用户明确要求人工介入，转人工处理' };
  }
  return null;
}

/* 风险识别（独立于问题分类的维度） */
function detectRisk(text) {
  /* 退款相关施压/风险意图优先判断（金额争议、投诉、催促退款、要求人工等） */
  var rp = refundPressure(text);
  if (rp) return rp;
  var t = norm(text);
  /* 物流长时间无更新（SOP：超过24小时→转人工核实） */
  if (logisticsStall(text)) {
    return { type: 'stall', risk: '中', transfer: true, reason: '物流信息超过24小时无更新，需人工核查物流节点（《售后SOP》物流异常处理），AI不承诺具体送达时间' };
  }
  if (hitKeys(t, COMPLAINT_KEYS)) {
    return { type: 'complaint', risk: '高', transfer: true, reason: '涉及投诉、举报或赔偿要求，必须转人工（《售后SOP》必须转人工）' };
  }
  if (hitKeys(t, AMOUNT_DISPUTE_KEYS)) {
    return { type: 'amount', risk: '高', transfer: true, reason: '涉及金额争议，必须转人工核实（《售后SOP》必须转人工：订单数据与用户描述冲突/超规则退款）' };
  }
  if (hitKeys(t, QUALITY_KEYS)) {
    return { type: 'quality', risk: '高', transfer: true, reason: '质量问题需要人工核验商品凭证，AI只说明材料和流程（《售后SOP》质量问题处理）' };
  }
  if (hitKeys(t, LOSS_KEYS)) {
    return { type: 'loss', risk: '中', transfer: true, reason: '商品或配件丢失/遗失需人工核实，需收集订单信息转人工（《售后SOP》物流异常处理：包裹破损或丢失）' };
  }
  if (hitKeys(t, ['密码', '验证码'])) {
    return { type: 'privacy', risk: '高', transfer: true, reason: '涉及支付密码或验证码，AI不会索要此类信息，请勿发送（《售后SOP》隐私规则）' };
  }
  if (hitKeys(t, ['别人的订单', '他人订单', '其他人的订单', '查别人', '朋友的订单', '手机号', '电话号码', '身份证', '完整地址', '收货地址是多少'])) {
    return { type: 'privacy', risk: '高', transfer: true, reason: '涉及隐私信息或他人订单，AI不输出（《售后SOP》隐私规则）' };
  }
  if (hitKeys(t, ['发票', '开票', '报销', '差价', '价保', '保价', '运费', '邮费', '修改订单', '改订单', '换商品', '取消订单', '待付款', '扣款', '付款'])) {
    return { type: 'noRule', risk: '中', transfer: true, reason: '现有资料无该问题的明确规则依据，必须转人工（《售后SOP》必须转人工：知识库没有明确依据）' };
  }
  return { type: 'none', risk: '低', transfer: false, reason: '' };
}

/* 主入口：生成一次回答 */
function generateAnswer(text) {
  text = (text || '').trim();
  var t = norm(text);
  var orderInfo = detectOrders(text);
  var product = matchProduct(text);
  var faqHit = matchFaq(text);
  var riskInfo = detectRisk(text);

  var category = '其他', basis = '', reply = '', hitDesc = '—';
  var transfer = riskInfo.transfer, reason = riskInfo.reason, risk = riskInfo.risk;

  /* 1) 订单查询优先 */
  if (orderInfo.unknown.length && !orderInfo.known.length) {
    category = '订单与支付';
    reply = '未查询到该模拟订单。Demo中仅存在3个模拟订单号：202609180001、202609180002、202609180003，请核对后重新输入；如需进一步核实，请转人工客服。';
    basis = '《模拟订单数据》仅包含3条模拟订单';
    hitDesc = '订单号 ' + orderInfo.unknown.join('、') + '（不存在）';
  } else if (orderInfo.known.length) {
    var o = KB.orders.filter(function (x) { return x.id === orderInfo.known[0]; })[0];
    var r = orderReply(o, text);
    reply = r.reply;
    /* 仅查询退款/售后进度：不转人工；出现催促/金额争议/投诉/要求人工等意图时才转人工 */
    transfer = riskInfo.transfer;
    risk = riskInfo.risk;
    reason = riskInfo.reason;
    basis = '《模拟订单数据》订单 ' + o.id;
    hitDesc = '订单 ' + o.id + '（' + o.productName + '）';
    if (riskInfo.type === 'amount') {
      reply += '\n金额争议说明：需要人工核对订单及支付记录，AI不承诺退款金额、处理结果或到账时间。';
    }
    category = (t.indexOf('退款') >= 0 || t.indexOf('售后') >= 0 || t.indexOf('退货') >= 0) ? '售后'
      : (t.indexOf('物流') >= 0 || t.indexOf('发货') >= 0 || t.indexOf('签收') >= 0 || t.indexOf('运输') >= 0) ? '物流'
      : '订单与支付';
  }
  /* 2) 风险命中（高风险直接转人工，用SOP口径回复） */
  else if (riskInfo.risk === '高') {
    if (t.indexOf('质量') >= 0 || hit2(t, ['坏了', '损坏', '破损', '故障', '无法使用', '用不了'])) {
      category = '售后';
      reply = '很抱歉给你带来不好的体验。请保留商品、包装和问题凭证，并准备以下信息由人工审核处理：\n' +
        KB.sop.quality.collect.map(function (c) { return '· ' + c; }).join('\n') +
        '\n是否属于质量问题由人工审核，AI无法直接承诺退款、换货或赔偿。';
      basis = '《售后SOP》质量问题处理';
      hitDesc = '质量问题（需人工核验凭证）';
    } else if (t.indexOf('密码') >= 0 || t.indexOf('验证码') >= 0 || t.indexOf('订单') >= 0 || t.indexOf('手机') >= 0 || t.indexOf('地址') >= 0 || t.indexOf('别人') >= 0 || t.indexOf('他人') >= 0) {
      category = '其他';
      reply = '为保护信息安全，AI客服不会输出完整手机号、完整收货地址，也不会提供其他人的订单，更不会索要支付密码或验证码。如有相关需求，请通过官方人工客服核实。';
      basis = '《售后SOP》隐私规则';
      hitDesc = '隐私/信息安全请求';
    } else if (riskInfo.type === 'amount') {
      category = '其他';
      reply = '涉及金额争议，需要人工核对订单及支付记录，AI无法核对也无法承诺退款金额、处理结果或到账时间。请提供：\n· 订单号\n· 具体金额问题（如多扣钱、少退款、实付金额不一致）\n已为你转交人工客服处理。';
      basis = '《售后SOP》必须转人工（金额争议）';
      hitDesc = '金额争议（金额不符/多扣/少退/重复扣款等）';
    } else {
      category = '其他';
      reply = KB.faqs.filter(function (f) { return f.id === 'FAQ-020'; })[0].a;
      basis = '《售后SOP》必须转人工';
      hitDesc = '投诉/赔偿诉求';
    }
  }
  /* 2.5) 物流长时间无更新：中风险，需人工核查物流节点 */
  else if (riskInfo.type === 'stall') {
    category = '物流';
    reply = '物流信息长时间未更新可能存在异常。请提供订单号，由人工客服核查物流节点；AI无法承诺具体送达或更新时间（《售后SOP》物流异常处理：超过24小时无更新→转人工核实）。';
    basis = '《售后SOP》物流异常处理';
    hitDesc = '物流长时间无更新（超过24小时）';
  }
  /* 2.6) 商品/配件丢失：需人工核实 */
  else if (riskInfo.type === 'loss') {
    category = '售后';
    reply = '很抱歉给你带来不好的体验。请提供订单号并说明具体情况（商品或配件丢失/遗失），已为你转交人工客服核实处理；AI无法直接判断责任或作出补偿承诺（《售后SOP》物流异常处理：包裹破损或丢失→收集订单信息并转人工）。';
    basis = '《售后SOP》物流异常处理';
    hitDesc = '商品/配件丢失（需人工核实）';
  }
  /* 2.7) 不完整订单号（6~11位数字 + 查询意图，且无其他风险信号） */
  else if (riskInfo.risk === '低' && detectIncompleteOrder(text)) {
    var partialId = detectIncompleteOrder(text);
    category = '订单与支付';
    reply = '你输入的订单号可能不完整，请提供完整的12位订单号后再查询。';
    basis = '《模拟订单数据》（订单号为12位数字）';
    hitDesc = '不完整订单号（' + partialId + '）';
    transfer = false; risk = '低'; reason = '';
  }
  /* 3) FAQ匹配 */
  else if (faqHit) {
    var f = faqHit.faq;
    category = f.category;
    reply = f.a;
    basis = f.source + '（' + f.id + '）';
    hitDesc = 'FAQ ' + f.id + '：' + f.q;
    if (f.source === '无明确规则依据') { transfer = true; reason = '现有资料无该问题明确规则依据，必须转人工（《售后SOP》必须转人工）'; risk = '中'; }
    if (f.id === 'FAQ-011') { transfer = true; reason = '修改地址需人工确认订单状态后处理（《售后SOP》物流异常处理）'; risk = '中'; }
    if (f.id === 'FAQ-013' || f.id === 'FAQ-015') {
      reply += '\n申请条件参考：' + KB.sop.sevenDay.canApply.join('；') + '。' + KB.sop.sevenDay.unifiedReply;
      basis = '《售后SOP》七天无理由规则（' + f.id + '）';
    }
  }
  /* 4) 商品问答 */
  else if (product) {
    var ansP = answerProduct(product, text);
    var yesNoQ = /[吗？?]\s*$/.test(text) || /能不能|可不可以|是否|能不能用/.test(t);
    if (ansP === null || (!matchAttrGroups(text).length && yesNoQ)) {
      /* 问到的属性在资料中无对应参数，或资料无法确认该问题 → 按无依据处理 */
      category = '其他';
      reply = '现有资料未覆盖该问题，我无法确认相关内容，为避免误导不作猜测。建议转人工客服进一步处理。';
      basis = '无明确规则依据（《商品资料》' + product.id + ' 中无对应参数）';
      transfer = true; risk = '中';
      reason = '知识库没有明确依据，必须转人工（《售后SOP》必须转人工）';
      hitDesc = '商品 ' + product.id + '（问题超出资料覆盖范围）';
    } else {
      category = '商品';
      reply = ansP;
      basis = '《商品资料》' + product.id;
      hitDesc = '商品 ' + product.id + '：' + product.name;
    }
  }
  /* 5) 无依据兜底 */
  else {
    category = '其他';
    basis = '无明确规则依据';
    transfer = true;
    risk = riskInfo.risk === '低' ? '中' : riskInfo.risk;
    hitDesc = '—';
    if (riskInfo.transfer && riskInfo.reason) {
      /* 已识别催促退款/要求人工等意图但未提供订单号 */
      reply = '请提供订单号，我可以协助查询模拟订单的退款/售后进度。如需催促退款或处理相关诉求，请转人工跟进，AI不承诺具体退款时间、审核结果或赔偿金额。';
      reason = riskInfo.reason;
    } else {
      reply = '现有资料未覆盖该问题，我无法确认相关内容，为避免误导不作猜测。建议转人工客服进一步处理。';
      reason = '知识库没有明确依据，必须转人工（《售后SOP》必须转人工）';
    }
  }

  return {
    question: text, reply: reply, category: category, basis: basis,
    hit: hitDesc, risk: risk, transfer: transfer, reason: reason || '—'
  };
}

function hit2(t, arr) { return arr.some(function (k) { return t.indexOf(k) >= 0; }); }

/* 供 Node 环境测试使用 */
if (typeof module !== 'undefined' && module.exports) {
  module.exports.generateAnswer = generateAnswer;
  module.exports.detectOrders = detectOrders;
  module.exports.matchProduct = matchProduct;
  module.exports.matchFaq = matchFaq;
}

/* =============================================================
 * 浏览器交互部分（Node测试环境跳过）
 * ============================================================= */
if (typeof document !== 'undefined' && typeof KB !== 'undefined') {
  (function () {
    var state = {
      sessions: [],       // {id,title,messages:[{role,text,meta,feedback}],log:[{q,category,transfer,feedback}]}
      current: 0,
      seq: 0
    };

    var $ = function (id) { return document.getElementById(id); };
    var chatList = $('chatList'), inputBox = $('inputBox'), sendBtn = $('sendBtn'),
      clearBtn = $('clearBtn'), newBtn = $('newSessionBtn'), sessList = $('sessionList'),
      quickBox = $('quickQuestions');

    var QUICK = [
      'SoundGo Air耳机续航多久？',
      '查询订单202609180001',
      '202609180002退款到哪一步？',
      '商品质量有问题怎么办？',
      '我要投诉并要求三倍赔偿。'
    ];

    function newSession(silent) {
      state.sessions.push({ id: ++state.seq, title: '新会话', messages: [], log: [] });
      state.current = state.sessions.length - 1;
      renderSessions(); renderChat();
      if (!silent) inputBox.focus();
    }

    function renderSessions() {
      sessList.innerHTML = '';
      state.sessions.forEach(function (s, i) {
        var div = document.createElement('div');
        div.className = 'session-item' + (i === state.current ? ' active' : '');
        div.textContent = (i === state.current ? '● ' : '○ ') + (s.title || '新会话');
        div.onclick = function () { state.current = i; renderSessions(); renderChat(); };
        sessList.appendChild(div);
      });
    }

    function esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

    function metaRows(m) {
      var meta = m.meta;
      return '<div class="meta-grid">' +
        '<div><span class="mk">问题分类</span><span class="mv">' + esc(meta.category) + '</span></div>' +
        '<div><span class="mk">信息依据</span><span class="mv">' + esc(meta.basis) + '</span></div>' +
        '<div><span class="mk">风险等级</span><span class="mv risk-' + esc(meta.risk) + '">' + esc(meta.risk) + '</span></div>' +
        '<div><span class="mk">是否转人工</span><span class="mv ' + (meta.transfer ? 'tag-yes' : 'tag-no') + '">' + (meta.transfer ? '需要转人工' : '不需要') + '</span></div>' +
        '<div class="full"><span class="mk">转人工原因</span><span class="mv">' + esc(meta.reason) + '</span></div>' +
        '</div>';
    }

    function renderChat() {
      var s = state.sessions[state.current];
      chatList.innerHTML = '';
      if (!s.messages.length) {
        chatList.innerHTML = '<div class="empty-tip">你好，我是电商客服AI助手。你可以直接输入问题，或点击左侧快捷问题开始体验。<br>本Demo仅基于项目知识库资料回答，资料未覆盖的问题会明确说明并建议转人工。</div>';
      }
      s.messages.forEach(function (m, idx) {
        var wrap = document.createElement('div');
        wrap.className = 'msg ' + m.role;
        if (m.role === 'user') {
          wrap.innerHTML = '<div class="bubble user-bubble">' + esc(m.text) + '</div>';
        } else {
          wrap.innerHTML =
            '<div class="ai-head">AI客服</div>' +
            '<div class="bubble ai-bubble">' + esc(m.text).replace(/\n/g, '<br>') + '</div>' +
            '<div class="meta-block"><div class="meta-title">回答分析</div>' + metaRows(m) + '</div>' +
            '<div class="fb-row" data-idx="' + idx + '">' +
            '<button class="fb-btn" data-fb="up">有帮助</button>' +
            '<button class="fb-btn" data-fb="down">无帮助</button>' +
            '<span class="fb-done"></span></div>';
        }
        chatList.appendChild(wrap);
      });
      chatList.scrollTop = chatList.scrollHeight;
      bindFeedback();
    }

    function bindFeedback() {
      Array.prototype.forEach.call(chatList.querySelectorAll('.fb-btn'), function (btn) {
        btn.onclick = function () {
          var idx = parseInt(btn.parentNode.getAttribute('data-idx'), 10);
          var s = state.sessions[state.current];
          var m = s.messages[idx];
          m.feedback = btn.getAttribute('data-fb') === 'up' ? '有帮助' : '无帮助';
          var logEntry = s.log.filter(function (l) { return l.msgIndex === idx; })[0];
          if (logEntry) logEntry.feedback = m.feedback;
          renderFeedbackMarks(); renderAnalysis(m.meta, true); renderLog();
        };
      });
      renderFeedbackMarks();
    }

    function renderFeedbackMarks() {
      var s = state.sessions[state.current];
      Array.prototype.forEach.call(chatList.querySelectorAll('.fb-row'), function (row) {
        var idx = parseInt(row.getAttribute('data-idx'), 10);
        var m = s.messages[idx];
        var done = row.querySelector('.fb-done');
        Array.prototype.forEach.call(row.querySelectorAll('.fb-btn'), function (b) { b.classList.remove('sel'); });
        if (m && m.feedback) {
          done.textContent = '已反馈：' + m.feedback;
          var target = row.querySelector(m.feedback === '有帮助' ? '[data-fb="up"]' : '[data-fb="down"]');
          if (target) target.classList.add('sel');
        } else { done.textContent = ''; }
      });
    }

    function renderAnalysis(meta, keepHit) {
      $('anCategory').textContent = meta.category;
      $('anHit').textContent = meta.hit;
      $('anBasis').textContent = meta.basis;
      var r = $('anRisk'); r.textContent = meta.risk;
      r.className = 'val risk-' + meta.risk;
      var tr = $('anTransfer'); tr.textContent = meta.transfer ? '需要转人工' : '不需要';
      tr.className = 'val ' + (meta.transfer ? 'tag-yes' : 'tag-no');
      $('anReason').textContent = meta.reason;
    }

    function renderLog() {
      var s = state.sessions[state.current];
      var box = $('sessionLog');
      if (!s.log.length) { box.innerHTML = '<div class="log-empty">本次会话暂无记录</div>'; return; }
      box.innerHTML = s.log.map(function (l, i) {
        return '<div class="log-item"><div class="log-q">' + (i + 1) + '. ' + esc(l.q) + '</div>' +
          '<div class="log-meta">分类：' + esc(l.category) + ' ｜ 转人工：' + (l.transfer ? '是' : '否') +
          ' ｜ 反馈：' + esc(l.feedback || '未反馈') + '</div></div>';
      }).join('');
    }

    var inputTipTimer = null;
    function showInputTip() {
      var tip = $('inputTip');
      if (!tip) return;
      tip.style.display = 'block';
      if (inputTipTimer) clearTimeout(inputTipTimer);
      inputTipTimer = setTimeout(function () { tip.style.display = 'none'; }, 2000);
    }

    function send(text) {
      text = (text || '').trim();
      if (!text) { showInputTip(); return; }
      var s = state.sessions[state.current];
      if (s.title === '新会话') s.title = text.slice(0, 16);
      var ans = generateAnswer(text);
      s.messages.push({ role: 'user', text: text });
      s.messages.push({ role: 'ai', text: ans.reply, meta: ans, feedback: null });
      s.log.push({ msgIndex: s.messages.length - 1, q: text, category: ans.category, transfer: ans.transfer, feedback: null });
      renderSessions(); renderChat(); renderAnalysis(ans); renderLog();
    }

    sendBtn.onclick = function () { send(inputBox.value); inputBox.value = ''; };
    inputBox.addEventListener('keydown', function (e) { if (e.key === 'Enter') { send(inputBox.value); inputBox.value = ''; } });
    clearBtn.onclick = function () {
      var s = state.sessions[state.current];
      s.messages = []; s.log = []; s.title = '新会话';
      renderSessions(); renderChat();
      $('anCategory').textContent = '—'; $('anHit').textContent = '—'; $('anBasis').textContent = '—';
      $('anRisk').textContent = '—'; $('anRisk').className = 'val';
      $('anTransfer').textContent = '—'; $('anTransfer').className = 'val';
      $('anReason').textContent = '—';
      renderLog();
    };
    newBtn.onclick = function () { newSession(false); };

    QUICK.forEach(function (q) {
      var b = document.createElement('button');
      b.className = 'quick-btn'; b.textContent = q;
      b.onclick = function () { send(q); };
      quickBox.appendChild(b);
    });

    newSession(true);
  })();
}
