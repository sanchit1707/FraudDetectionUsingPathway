import os
import time
import pathway as pw
import numpy as np
from sentence_transformers import SentenceTransformer
from _sidecar import start_sidecar

print("Loading sentence-transformers embedding model...")
embed_model = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded successfully.")

# ── Load compliance docs into memory at startup ──────────────────────────────
COMPLIANCE_DOCS = []   # list of raw text strings
COMPLIANCE_VECS = []   # parallel list of numpy vectors

# Real, in-memory counters exposed via GET /stats (no synthetic data)
STATS = {
    "total_queries": 0,
    "last_query": None,
    "last_retrieved_count": 0,
    "started_at": time.time(),
}

def load_docs_into_memory(docs_dir: str = "./compliance_docs/"):
    """Read every file in docs_dir, embed, store in module-level lists."""
    if not os.path.exists(docs_dir):
        print(f"[WARN] docs_dir {docs_dir} not found — no docs loaded.")
        return
    texts = []
    for fname in sorted(os.listdir(docs_dir)):
        fpath = os.path.join(docs_dir, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read().strip()
                if text:
                    texts.append(text)
            except Exception as e:
                print(f"[WARN] Could not read {fpath}: {e}")
    if texts:
        print(f"[A5] Embedding {len(texts)} compliance docs...")
        vecs = embed_model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        COMPLIANCE_DOCS.extend(texts)
        COMPLIANCE_VECS.extend(vecs)
        print(f"[A5] {len(COMPLIANCE_DOCS)} docs ready in memory.")
    else:
        print("[A5] No docs found in compliance_docs/.")

# ── Schema ───────────────────────────────────────────────────────────────────
class QuerySchema(pw.Schema):
    query: str
    top_k: int = pw.column_definition(default_value=3)

# ── UDF: full retrieval in a single synchronous call ─────────────────────────
@pw.udf
def retrieve_docs(query: str, top_k: int) -> dict:
    STATS["total_queries"] += 1
    STATS["last_query"] = query

    if not COMPLIANCE_DOCS:
        STATS["last_retrieved_count"] = 0
        return {
            "agent": "A5 Compliance RAG",
            "query": query,
            "retrieved_count": 0,
            "compliance_context": []
        }
    q_vec = embed_model.encode(query, normalize_embeddings=True, convert_to_numpy=True)
    scores = [float(np.dot(q_vec, d_vec)) for d_vec in COMPLIANCE_VECS]
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    retrieved = [
        {
            "snippet": COMPLIANCE_DOCS[i][:600],
            "relevance_score": round(scores[i], 4)
        }
        for i in top_idx
    ]
    STATS["last_retrieved_count"] = len(retrieved)
    return {
        "agent": "A5 Compliance RAG",
        "query": query,
        "retrieved_count": len(retrieved),
        "compliance_context": retrieved
    }

# ── Agent entrypoint ──────────────────────────────────────────────────────────
def run_agent():
    # Embed all docs BEFORE starting Pathway so the UDF has data immediately
    load_docs_into_memory("./compliance_docs/")

    webserver = pw.io.http.PathwayWebserver(host="0.0.0.0", port=8011)
    queries, writer = pw.io.http.rest_connector(
        webserver=webserver,
        schema=QuerySchema,
        autocommit_duration_ms=50,
        delete_completed_queries=True,
    )

    results = queries.select(
        result=retrieve_docs(pw.this.query, pw.this.top_k)
    )

    writer(results)

    def get_stats():
        return {
            "agent": "A5 Compliance RAG",
            "docs_loaded": len(COMPLIANCE_DOCS),
            "total_queries": STATS["total_queries"],
            "last_query": STATS["last_query"],
            "last_retrieved_count": STATS["last_retrieved_count"],
            "uptime_seconds": round(time.time() - STATS["started_at"], 1),
        }

    # Sidecar on 8511 gives the browser CORS + a GET status route while
    # proxying real /query POSTs through to this Pathway webserver on 8011.
    start_sidecar(8511, "http://localhost:8011/", get_stats)

    print("Starting A5 Compliance RAG on port 8011 (sidecar on 8511)...")
    pw.run()

if __name__ == "__main__":
    run_agent()