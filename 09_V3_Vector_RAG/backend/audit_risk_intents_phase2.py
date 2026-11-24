# -*- coding: utf-8 -*-
"""V3.2 第二阶段静态审核辅助脚本（只读，不修改任何候选代码）。"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

out = []

# ---------- 1. 知识片段中的规则 ID ----------
chunks = [json.loads(l) for l in open('data/knowledge_chunks.jsonl', encoding='utf-8')]
rule_chunks = {c['chunk_id']: c for c in chunks if c['chunk_id'].startswith('RULE-')}
out.append('== knowledge_chunks 规则片段 (%d 条) ==' % len(rule_chunks))
for cid in sorted(rule_chunks):
    c = rule_chunks[cid]
    out.append('  %s | risk=%s | %s' % (cid, c.get('risk_level'), c['text'][:42].replace('\n', ' ')))

# ---------- 2. 检测器 rule_id 全覆盖核对 ----------
import risk_intents
probe = {
    'RULE-HR-01': ['我要投诉你们', '太坑了这店给我个说法'],
    'RULE-HR-02': ['这个月被扣了两次款', '少退了我十块钱'],
    'RULE-HR-03': ['退款拖三天还没到账', '马上给我退款'],
    'RULE-HR-04': ['包裹停在转运中心三天了', '物流一直没更新'],
    'RULE-HR-05': ['帮我朋友查下他的包裹', '她名下那个件到哪了'],
    'RULE-HR-06': ['把我的收货地址发我一下', '能查到收件人电话吗'],
    'RULE-HR-07': ['你保证今天必须退款到账', '跟我担保一定办成'],
    'RULE-HR-08': ['杯子到手就有裂痕', '拉链第二天拉不上了'],
}
out.append('')
out.append('== 检测器 rule_id 全覆盖核对 ==')
all_ok = True
for rid, qs in sorted(probe.items()):
    hit = any(any(r['rule_id'] == rid for r in risk_intents.detect_risk_intents(q)) for q in qs)
    out.append('  %s : %s' % (rid, 'OK' if hit else 'NOT REACHED'))
    all_ok = all_ok and hit
out.append('  全覆盖: %s' % all_ok)

# ---------- 3. INTENT_RULE_MAP 与 retriever.RULES 一致性 ----------
import importlib
qa = importlib.import_module('query_analyzer')
irm = getattr(qa, 'INTENT_RULE_MAP', None)
out.append('')
out.append('== query_analyzer.INTENT_RULE_MAP ==')
if irm is None:
    out.append('  (未找到 INTENT_RULE_MAP 属性，列出含 RULE 的全局名)')
    for n in dir(qa):
        if 'RULE' in n.upper():
            out.append('  attr:', n)
else:
    for k, v in irm.items():
        out.append('  %s -> %s' % (k, v))

import retriever
rules_ids = [r['id'] for r in retriever.RULES]
out.append('')
out.append('== retriever.RULES ids ==')
out.append('  ' + str(rules_ids))

# 规范化检查：MAP 值 -> 去前缀后是否命中 RULES
if irm:
    def norm(rid):
        return rid[5:] if rid.startswith('RULE-') else rid
    bad = [(k, v) for k, vs in irm.items() for v in ([vs] if isinstance(vs, str) else vs)
           if norm(v) not in rules_ids]
    out.append('  规范化后无法映射到 retriever.RULES 的: %s' % (bad if bad else '无（全部一致）'))

# 适配器 _risk_floor 前缀处理
src = open('v3_retrieval_adapter.py', encoding='utf-8').read()
m = re.search(r'def _risk_floor.*?(?=\ndef |\Z)', src, re.S)
out.append('')
out.append('== adapter._risk_floor 前缀规范化（源码摘录） ==')
if m:
    body = m.group(0)
    for line in body.splitlines():
        if 'RULE-' in line or 'lstrip' in line or 'replace' in line or 'startswith' in line or 'ids' in line.lower():
            out.append('  ' + line.strip())

# ---------- 4. 过短/孤立模式扫描 ----------
out.append('')
out.append('== 模式长度扫描（各类表中纯字面 ≤2 字且无量词锚定的模式） ==')
tables = {
    'COMPLAINT_EXPLICIT': risk_intents._COMPLAINT_EXPLICIT,
    'PROMISE_OBJECT': risk_intents._PROMISE_OBJECT,
    'DEFECT_STRONG': risk_intents._DEFECT_STRONG,
    'DEFECT_FUNC': risk_intents._DEFECT_FUNC,
    'AMOUNT_STRONG': risk_intents._AMOUNT_STRONG,
    'PRIVACY_SENSITIVE': risk_intents._PRIVACY_SENSITIVE,
}
for name, pats in tables.items():
    short = []
    for p in pats:
        literal = re.sub(r'[\[\]\(\)\?\*\+\{\}\|\\\^\$s d w S D W]', '', p)
        clean = p.replace('(吗|么|嘛|呢)', '').replace('[了掉]', '').replace('?', '')
        core = re.sub(r'[()\[\]?*+|\\^$]', '', p)
        if len(core) <= 2 and not any(x in p for x in ('(', '|', '[')):
            short.append(p)
    out.append('  %s: %s' % (name, short if short else '无'))

# 各短模式的触发通道（是否复合条件）
out.append('')
out.append('== 复合条件说明（短模式所在通道） ==')
out.append('  PROMISE_OBJECT.赔: 须与 PROMISE_VERB（保证/担保/承诺…）同时出现，非孤立触发')
out.append('  DEFECT_STRONG.碎[了掉]?: strong 通道（可直接触发），"碎"字面最短 1 字——记录为潜在边界')
out.append('  AMOUNT_MONEY_CTX.钱: 复合通道（须 dispute_state+非尺寸排除），非孤立')
out.append('  DEFECT_PART_STATE.断/掉/松: 须与 DEFECT_PART 或已购语境复合，非孤立')

# ---------- 5. 否定承诺 / 售前担忧守卫实验 ----------
out.append('')
out.append('== 否定表达承诺实验（detect_over_promise） ==')
for q in ['你保证今天必须退款到账', '我不要求你保证退款', '你不用保证能退款',
          '无法由AI保证退款到账', '退款一般几天到账']:
    r = risk_intents.detect_risk_intents(q)
    out.append('  %r -> %s' % (q, [x['intent'] for x in r]))

out.append('')
out.append('== 售前担忧守卫实验（detect_defect） ==')
for q in ['这包拉链耐用吗', '杯子容易裂吗', '是不是质量不好', '会不会漏',
          '杯子到手就有裂痕', '拉链拉不动了是不是质量不好', '裂缝了吗']:
    r = risk_intents.detect_risk_intents(q)
    out.append('  %r -> %s' % (q, [x['intent'] for x in r]))

with open('data/_v32_audit_risk_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('written', len(out), 'lines')
