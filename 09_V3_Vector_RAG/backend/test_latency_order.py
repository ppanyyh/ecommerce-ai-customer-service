# -*- coding: utf-8 -*-
"""V3.1 延迟顺序测试：验证延迟统计的"首次调用"语义与预热效果。

1. 合成数据单测：_latency_summary 的 first_call 必须取原始顺序第一条（含冷启动），
   P50/P95 用排序副本计算，excluding_first 先移除真实第一条再排序（旧版缺陷回归测试）。
2. 实测：hybrid_search_v2 首次调用（含模型加载）应显著慢于预热后的调用。
运行：项目根目录下 .venv\\Scripts\\python.exe backend\\test_latency_order.py
"""
import os
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

from evaluate_final_blind_set import _latency_summary  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ---- 1. 合成数据：首条是唯一慢调用 ----
raw = [5000.0, 10.0, 12.0, 11.0, 13.0, 10.5, 11.5, 12.5, 10.2, 11.8]
s = _latency_summary(raw)
check("first_call取原始顺序第一条(非最小值)", s["first_call"] == 5000.0, f"first_call={s['first_call']}")
check("p50基于排序副本", s["p50"] <= 12.6 and s["p50"] >= 10.0, f"p50={s['p50']}")
# n=10 且含唯一极端离群值时，既定分位口径（与评测脚本一致）P95 可合法落在最大值；
# 关键语义是 excluding_first 移除真实首条后分位数显著下降：
check("excluding_first后p95显著低于first_call",
      (s["p95_excluding_first"] or 1e9) < s["first_call"] / 10.0,
      f"p95_excl={s['p95_excluding_first']} first={s['first_call']}")
check("excluding_first移除真实首条", s["p50_excluding_first"] is not None
      and s["p50_excluding_first"] < s["p50"] + 5.0,
      f"p50_excl={s['p50_excluding_first']}")
check("max等于真实首条", s["max"] == 5000.0, f"max={s['max']}")

# ---- 1b. 旧版缺陷场景回归：最小值在中间，首条是慢调用 ----
raw2 = [800.0, 5.0, 3.0, 4.0]
s2 = _latency_summary(raw2)
check("回归:首条=800而非min=3", s2["first_call"] == 800.0 and s2["min"] == 3.0,
      f"first={s2['first_call']},min={s2['min']}")

# ---- 1c. 空列表 ----
s3 = _latency_summary([])
check("空列表不崩溃", s3["n"] == 0 and s3["first_call"] is None)

# ---- 2. 实测：首次调用（冷启动）vs 预热后 ----
try:
    import time
    from hybrid_retriever_v2 import hybrid_search_v2
    queries = ["杯子到手就有裂痕要退款", "退款多久到账", "书包侧面能装下16寸电脑吗",
               "转人工客服", "耳机用了没几天就没声音了"]
    lat = []
    for q in queries:
        t0 = time.perf_counter()
        hybrid_search_v2(q, top_k=5)
        lat.append(round((time.perf_counter() - t0) * 1000.0, 2))
    live = _latency_summary(lat)
    check("实测first_call为原始顺序第一条", live["first_call"] == lat[0], f"lat={lat}")
    check("实测首次调用显著慢于预热后(>=3x P50)",
          live["first_call"] >= 3.0 * (live["p50"] or 1.0),
          f"first={live['first_call']}ms p50={live['p50']}ms")
except Exception as e:
    check("实测段异常", False, f"{type(e).__name__}: {e}")

passed = sum(1 for _, ok, _ in results if ok)
print(f"延迟顺序测试: {passed}/{len(results)} 通过")
for name, ok, detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
sys.exit(0 if passed == len(results) else 1)
