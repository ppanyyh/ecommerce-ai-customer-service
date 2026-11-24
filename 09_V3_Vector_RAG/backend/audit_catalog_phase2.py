# -*- coding: utf-8 -*-
"""V3.2 第二阶段能力目录来源审核（只读）。核对每个 covered_attributes 关键词
能否在 knowledge_chunks 原始 text（非 retrieval_text）中找到出处。"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

chunks = [json.loads(l) for l in open('data/knowledge_chunks.jsonl', encoding='utf-8')]
prod = {c['chunk_id']: c for c in chunks if c['doc_type'] == 'product'}
cat = json.load(open('data/business_capability_catalog.json', encoding='utf-8'))

out = ['== 能力目录字段到来源核对 ==']
out.append('catalog_version = %s' % cat.get('catalog_version'))
out.append('revision_note = %s' % (cat.get('revision_note') or '')[:100])
out.append('')

total_kw, nohit = 0, []
for pid in sorted(cat['known_products']):
    p = cat['known_products'][pid]
    base = prod.get(pid)
    base_text = base['text'] if base else ''
    # 有些属性也可能来自 FAQ 片段，聚合全部片段文本做兜底追溯
    all_text = base_text + '\n' + '\n'.join(c['text'] for c in chunks)
    out.append('%s（%s）' % (pid, p.get('name', '')))
    for attr in p.get('covered_attributes', []):
        kws = attr.get('keywords', [])
        miss = []
        for k in kws:
            total_kw += 1
            if k not in base_text:
                if k not in all_text:
                    miss.append(k)
                else:
                    miss.append(k + '[仅FAQ等片段]')
        status = 'OK' if not miss else ('MISS: ' + ', '.join(miss))
        out.append('  %-10s kw=%d  %s' % (attr['attr'], len(kws), status))
        if miss:
            nohit.append((pid, attr['attr'], miss))
    out.append('  -- 商品名/别名来源: base_text=%s' % ('命中' if base else '缺失'))

out.append('')
out.append('关键词总数 = %d, 未在 PRODUCT 原始text命中 = %d' % (
    total_kw, sum(len(m) for _, _, m in nohit)))

# uncovered / out_of_scope 检查
out.append('')
out.append('== uncovered_business_types（类别级，非旧盲测问题） ==')
for t in cat.get('uncovered_business_types', []):
    out.append('  %s : %s' % (t.get('type'), (t.get('note') or '')[:60]))
bad_oos = []
for t in cat.get('out_of_scope_topics', []):
    kw = t.get('keywords', []) if isinstance(t, dict) else []
    for k in kw:
        if len(k) >= 12:  # 疑似完整句子复制
            bad_oos.append(k)
out.append('')
out.append('out_of_scope 是否含疑似完整问句（≥12字）: %s' % (bad_oos if bad_oos else '无（均为类别级短词）'))

# 发票口径
inv = [t for t in cat.get('uncovered_business_types', []) if 'invoice' in str(t.get('type', ''))]
out.append('发票口径: %s' % (json.dumps(inv, ensure_ascii=False)[:200] if inv else '未找到!'))

# gate priority（风险意图优先级）——代码侧核对
import re
qa_src = open('query_analyzer.py', encoding='utf-8').read()
m = re.search(r'risk_hits\s*=.*', qa_src)
out.append('')
out.append('query_analyzer 中风险检测调用: %s' % (m.group(0) if m else '未找到!'))
m2 = re.search(r'if risk_hits[^\n]*', qa_src)
out.append('风险优先分支: %s' % (m2.group(0) if m2 else '未找到!'))

with open('data/_v32_audit_catalog_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('written', len(out))
