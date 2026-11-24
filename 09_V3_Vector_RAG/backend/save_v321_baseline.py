# -*- coding: utf-8 -*-
"""V3.2.1 落地前修复阶段：保存冻结基线。
只读验证 V3.2 候选冻结清单 all_match，并生成 v3_2_1_baseline_manifest.json。
不覆盖任何既有清单。"""
import sys, io, json, hashlib, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

out = []

# 1. 验证 V3.2 候选冻结清单
fm = json.load(open('data/v3_2_candidate_freeze_manifest.json', encoding='utf-8'))
mismatch = []
for path, old in fm['files_sha256'].items():
    cur = sha(path)
    if cur.lower() != old.lower():
        mismatch.append(path)
out.append('V3.2 candidate freeze: %d files, mismatch=%d, recorded all_match=%s'
           % (len(fm['files_sha256']), len(mismatch), fm.get('all_match')))
if mismatch:
    out.append('MISMATCH: ' + ', '.join(mismatch))
    print('\n'.join(out))
    sys.exit(1)

# 2. 生成 V3.2.1 基线清单
pre_sha = {p: sha(p) for p in sorted(fm['files_sha256'].keys())}
baseline = {
    "phase": "V3.2.1 pre-blind fix baseline",
    "created_at": "2026-09-26",
    "v3_2_candidate_freeze_manifest_path": "data/v3_2_candidate_freeze_manifest.json",
    "v3_2_candidate_freeze_manifest_sha256": sha('data/v3_2_candidate_freeze_manifest.json'),
    "v3_2_candidate_freeze_verified_all_match": True,
    "candidate_files_pre_modification_sha256": pre_sha,
    "known_residues_carried_in": [
        "DV3-010（HR-05 规则片段未进 Top-3，意图与 handoff 正确）——本阶段明确不处理",
        "DV3-079/DV3-089 hit1 Top-2 语义竞争（Recall@3 正常）",
        "wrong_handoff 2 条保守侧（DV3-080/090 诱导用例）",
        "detect_over_promise 无否定守卫——本阶段修复对象",
        "未知商品自然句式（你们的XX有XX功能吗）漏判——本阶段修复对象",
        "二手回收价格/以旧换新价格 被通用价格属性误判——本阶段修复对象",
        "有效订单 DeepSeek 不可用时 answer 仅通用降级文案——本阶段修复对象",
        "部分高风险场景仅通用繁忙文案——本阶段修复对象",
        "V3.1 开发集 DV-007/025/029/032 hit1 残留（既有）",
    ],
    "blind_status": {
        "final_blind_set_v1": "已执行并永久消耗，禁止重跑",
        "final_blind_set_v2": "已执行并永久消耗（execution_count=1），禁止重建/重跑/用于V3.2.1评分",
        "final_blind_set_v3": "尚未创建",
    },
    "deepseek_call_count": 0,
    "allowed_to_modify": [
        "query_analyzer.py",
        "risk_intents.py",
        "data/business_capability_catalog.json",
        "v3_retrieval_adapter.py",
        "main.py",
        "新增开发集/检查脚本/测试/报告",
    ],
    "modify_only_if_necessary": ["hybrid_retriever_v2.py"],
    "forbidden": [
        "keyword_retriever_v3.py", "vector_retriever.py",
        "data/knowledge_chunks.jsonl", "data/index_manifest.json",
        "Embedding模型", "RRF/EPSILON/RULE_NET_VEC_SIM 等检索参数",
        "旧开发集与旧盲测集标注", "V2/frontend/05_AI_Demo",
    ],
}
with open('data/v3_2_1_baseline_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(baseline, f, ensure_ascii=False, indent=2)

out.append('v3_2_1_baseline_manifest.json written: %d files pre-SHA recorded' % len(pre_sha))
out.append('baseline manifest sha256 = %s' % sha('data/v3_2_1_baseline_manifest.json'))
print('\n'.join(out))
