"""V3.0 业务感知混合检索 v2 单元级验证（仅技术验证问题，不使用 validation_set_v1 句子）。

验证点（全部本地，不调用 DeepSeek，不接入 /api/chat）：
 1. analyzer：商品编号识别 + has_exact_entity
 2. analyzer：扩展同义词"书包"映射到 P004（产品同义词扩展，仅 V3 检索层）
 3. analyzer：已发生质量缺陷 → post_purchase_defect → RULE-HR-08
 4. analyzer：泛化质量咨询不算缺陷（"质量怎么样/靠谱吗"不触发 HR-08）
 5. analyzer：无实体 + 仅泛化质量咨询 → 业务范围门控 is_supported_domain=False
 6. analyzer：有实体 + 泛化质量措辞 → 不门控
 7. analyzer：退款催促/物流停滞/他人订单 分别映射 HR-03/HR-04/HR-05
 8. v2 门控生效：supported=False 且 results 为空
 9. v2：结果按 rrf_score 降序（允许 epsilon 内并列重排，分差 >= EPSILON 时必须降序）
10. v2：chunk_id 不重复
11. v2：完整商品编号 P001 → PRODUCT-P001 强制 Top-1
12. v2：订单号不触发编号置顶、不进入知识检索加分（无 id_boost）
13. v2：规则片段返回原始 text（"售后转人工规则"开头），非 retrieval_text 扩写
14. v2：缺陷+退款合成问题 → 必需规则进入 Top-3 且 Top-3 含至少 1 个内容片段
15. 治理评分：仅含通用弱词/汉字重合的查询，弱词单独不得构成高分（< 1.0）
16. 不调用 DeepSeek（源码无 deepseek 导入）

运行（项目根目录 09_V3_Vector_RAG 下）：
    .\\.venv\\Scripts\\python.exe backend\\test_hybrid_v2_validation.py
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from query_analyzer import analyze  # noqa: E402
from hybrid_retriever_v2 import (  # noqa: E402
    hybrid_search_v2, governed_keyword_search, EPSILON,
)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


# 1. 商品编号
a = analyze("P001的耳机续航多久")
check("01_商品编号识别", a["product_ids"] == ["P001"] and a["has_exact_entity"], str(a["product_ids"]))

# 2. 扩展同义词 书包→P004
a = analyze("书包侧面能装下16寸的电脑吗")
check("02_同义词扩展书包到P004", a["product_ids"] == ["P004"] and "书包" in a["product_aliases"],
      str(a["product_ids"]))

# 3. 售后缺陷 → HR-08（问题同时含退款催促，HR-03 一并产生属正确行为）
a = analyze("这个东西到手就有裂痕了，要求退款")
check("03_售后缺陷映射HR-08", a["has_post_purchase_defect"] and "RULE-HR-08" in a["required_rule_ids"],
      str(a["required_rule_ids"]))

# 4. 泛化质量咨询不算缺陷
a = analyze("你们家的东西质量怎么样，靠谱吗")
check("04_泛化质量咨询不触发缺陷",
      (not a["has_post_purchase_defect"]) and a["has_generic_quality_question"]
      and a["required_rule_ids"] == [],
      str(a["required_rule_ids"]))

# 5. 业务范围门控（无实体+仅泛化咨询）
a = analyze("直播买的东西是不是质量都差不多啊，靠谱吗")
check("05_泛化咨询触发门控", a["is_supported_domain"] is False, str(a["reasons"]))

# 6. 有实体不门控（V3.2 口径修订，见 v3_2_change_log.md）：
#    V3.1 期望"有实体→supported"；V3.2 能力目录驱动门控变更为
#    "已知商品 + 属性询问 + 目录未见覆盖属性 → unsupported_business"
#    （需求第五节：识别到商品实体不再默认支持该商品的所有问题）。
#    "P003这个杯子质量怎么样"中"质量"不在 P003 已覆盖属性（材质/保温性能等），
#    按新口径门控，但商品实体识别仍须正确。
a = analyze("P003这个杯子质量怎么样")
check("06_有实体不门控",
      a["product_ids"] == ["P003"] and a["is_supported_domain"] is False
      and a["covered_attributes"] == [],
      str(a["product_ids"]) + "/" + a["scope"])

# 7. 三类风险意图映射
a1 = analyze("退款拖了好多天了，马上给我退")
a2 = analyze("包裹好多天没动静了，是不是卡住了")
a3 = analyze("帮我查下我同事的单子到哪了")
check("07a_退款催促映射HR-03", a1["required_rule_ids"] == ["RULE-HR-03"], str(a1["intents"]))
check("07b_物流停滞映射HR-04", a2["required_rule_ids"] == ["RULE-HR-04"], str(a2["intents"]))
check("07c_他人订单映射HR-05", a3["required_rule_ids"] == ["RULE-HR-05"], str(a3["intents"]))

# 8. 门控返回结构
out = hybrid_search_v2("直播买的东西是不是质量都差不多啊，靠谱吗", top_k=5)
check("08_门控返回空结果", out["supported"] is False and out["results"] == [] and out["reason"],
      f"supported={out['supported']} n={len(out['results'])}")

# 9-13. 常规检索行为（技术验证问题）
out = hybrid_search_v2("P001的耳机续航多久", top_k=5)
rs = out["results"]
check("09_rrf_score降序", all(
    rs[i]["rrf_score"] >= rs[i + 1]["rrf_score"] - EPSILON for i in range(len(rs) - 1)),
    str([r["rrf_score"] for r in rs]))
check("10_chunk_id不重复", len({r["chunk_id"] for r in rs}) == len(rs), "")
check("11_编号强制Top1", rs and rs[0]["chunk_id"] == "PRODUCT-P001" and rs[0].get("id_boost"),
      rs[0]["chunk_id"] if rs else "空")

out2 = hybrid_search_v2("我查一下订单202609180001到哪一步了", top_k=5)
rs2 = out2["results"]
check("12_订单号不触发编号置顶", all(not r.get("id_boost") for r in rs2), "")
rule_hit = next((r for r in hybrid_search_v2("质量坏了怎么办", top_k=5)["results"]
                 if r["doc_type"] == "rule"), None)
check("13_规则返回原始text", rule_hit is not None and rule_hit["text"].startswith("售后转人工规则"),
      (rule_hit["text"][:20] if rule_hit else "无规则结果"))

# 14. 规则保留位（合成缺陷+退款问题）
out3 = hybrid_search_v2("商品收到就有破损了，钱什么时候退回来", top_k=5)
rs3 = out3["results"]
top3 = [r["chunk_id"] for r in rs3[:3]]
check("14a_必需规则进Top3", "RULE-HR-08" in top3, str(top3))
check("14b_Top3含内容片段", any(r["doc_type"] != "rule" for r in rs3[:3]), str(top3))
check("14c_保留位标记", "RULE-HR-08" in out3["rule_reserved"], str(out3["rule_reserved"]))

# 15. 弱词治理：仅泛化词不得构成高分
kw = governed_keyword_search("商品质量怎么样，处理问题", top_k=5)
weak_only_scores = [r["keyword_score"] for r in kw if r["keyword_score"] < 1.0]
check("15_弱词单独不构成高分", bool(kw) and all(r["keyword_score"] < 1.0 for r in kw),
      str([(r["chunk_id"], r["keyword_score"]) for r in kw[:3]]))

# 16. 无 DeepSeek 依赖
src = ""
for f in ("query_analyzer.py", "hybrid_retriever_v2.py"):
    src += open(os.path.join(BACKEND_DIR, f), encoding="utf-8").read().lower()
check("16_无DeepSeek依赖", "deepseek" not in src.replace("不调用 deepseek", ""), "")

# ---- 汇总 ----
passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n===== 混合检索 v2 单元级验证 {passed}/{len(RESULTS)} =====")
for name, ok, detail in RESULTS:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" | {detail}" if (detail and not ok) else ""))
sys.exit(0 if passed == len(RESULTS) else 1)
