"""V3.0 阶段二一致性检查（不调用 DeepSeek）。"""
import hashlib
import io
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
CHUNKS_PATH = os.path.join(BACKEND_DIR, "data", "knowledge_chunks.jsonl")
MANIFEST_PATH = os.path.join(BACKEND_DIR, "data", "index_manifest.json")
CHROMA_DB_DIR = os.path.join(PROJECT_DIR, "data", "chroma_db")

out = []


def check(name, ok, detail=""):
    out.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


chunks = [json.loads(l) for l in io.open(CHUNKS_PATH, encoding="utf-8") if l.strip()]
ids = [c["chunk_id"] for c in chunks]
check("chunk_id无重复", len(ids) == len(set(ids)), f"共{len(ids)}条")
check("商品片段5条", sum(1 for c in chunks if c["doc_type"] == "product") == 5)
check("FAQ片段20条", sum(1 for c in chunks if c["doc_type"] == "faq") == 20)
check("规则片段8条", sum(1 for c in chunks if c["doc_type"] == "rule") == 8)
check("订单片段0条", sum(1 for c in chunks if c["doc_type"] == "order") == 0)
check("text/source均非空", all(c["text"] and c["source"] for c in chunks))
check("metadata均为简单标量", all(
    isinstance(v, (str, int, float, bool)) for c in chunks
    for k, v in c.items() if k not in ("chunk_id", "text")))
check("source可追溯", all(
    c["source"].startswith(("《商品资料》", "《客服FAQ》", "《售后SOP》", "《模拟订单数据》", "无明确规则依据"))
    for c in chunks), f"sources={sorted(set(c['source'] for c in chunks))}")

manifest = json.load(io.open(MANIFEST_PATH, encoding="utf-8"))
sha = hashlib.sha256(io.open(CHUNKS_PATH, "rb").read()).hexdigest()
check("manifest哈希正确", manifest["chunks_sha256"] == sha, f"{sha[:16]}...")
check("manifest不含绝对路径/Key", not any(k in json.dumps(manifest) for k in (".env", "API_KEY", "sk-", "Mr.Perfectan")))

import chromadb
client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
names = {c.name for c in client.list_collections()}
check("collection为ecommerce_kb_v1", names == {"ecommerce_kb_v1"}, f"{sorted(names)}")
col = client.get_collection("ecommerce_kb_v1")
check("Chroma数量与JSONL一致", col.count() == len(chunks), f"db={col.count()} jsonl={len(chunks)}")
got = col.get(ids=["RULE-HR-08"], include=["metadatas"])
check("抽查metadata完整", got["metadatas"][0]["doc_type"] == "rule" and got["metadatas"][0]["ref_id"] == "HR-08")

io.open(os.path.join(os.environ.get("TEMP", "/tmp"), "v3_consistency.txt"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
sys.exit(0 if all("[FAIL]" not in l for l in out) else 1)
