# -*- coding: utf-8 -*-
"""调试 TC-06：定位模型输出被拒原因（输出到 debug_out.txt，不含任何Key）。"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import main
import retriever
import deepseek_client

out = io.StringIO()
msg = "我要投诉并要求三倍赔偿"
r = retriever.retrieve(msg)
out.write(f"retrieval.matched={r['matched']} type={r['match_type']} handoff={r['requires_handoff']}\n")
out.write(f"allowed_sources={r['sources']}\n")
out.write("context=\n" + r["context"] + "\n---\n")

for i in range(2):  # 跑两次观察稳定性
    reply = deepseek_client.generate_reply(message=msg, context=r["context"])
    out.write(f"reply[{i}]=" + json.dumps(reply, ensure_ascii=False) + "\n")
    out.write(f"  category_ok={reply['category'] in main.VALID_CATEGORIES}\n")
    out.write(f"  answer_empty={not reply['answer'].strip()}\n")
    pv = main._promise_violation(reply["answer"])
    out.write(f"  promise_violation={pv}\n")
    known = set(retriever.ORDERS)
    for o in retriever.ORDERS.values():
        if o.get("tracking_number"):
            known.add(o["tracking_number"])
    known |= set(re.findall(r"\d{6,}", r["context"]))
    bad = [n for n in main._ORDER_NUM_RE.findall(reply["answer"]) if n not in known]
    out.write(f"  bad_order_nums={bad}\n")
    allowed = set(r["sources"])
    filt = [s for s in reply["sources"] if s in allowed]
    out.write(f"  filtered_sources={filt} (model={reply['sources']}) -> rejected={not filt and not r['sources']}\n")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_out.txt"),
          "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print("done")
