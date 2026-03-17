#!/usr/bin/env python3
"""Hybrid retrieval with dense + sparse search and local/hosted rerank switch.

Supports:
- Dense retrieval via embedding vectors (Ollama nomic-embed or compatible)
- Sparse retrieval via BM25-style keyword scoring
- Local reranker using Ollama chat models (e.g. BAAI/bge-reranker via Ollama)
- Hosted reranker stub for Pinecone-hosted rerankers
- Score fusion (reciprocal rank fusion) to combine dense and sparse results
"""
import hashlib
import json
import math
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "qwen2.5:3b")


# ---------------------------------------------------------------------------
# Sparse retrieval: BM25-style keyword scoring
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"\w+", text.lower())


def bm25_score(query: str, documents: list[str],
               k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Compute BM25 scores for a query against a list of documents."""
    query_terms = _tokenize(query)
    doc_tokens = [_tokenize(doc) for doc in documents]
    avg_dl = sum(len(dt) for dt in doc_tokens) / max(len(doc_tokens), 1)
    n_docs = len(documents)

    # Document frequency for each query term
    df: dict[str, int] = {}
    for term in set(query_terms):
        df[term] = sum(1 for dt in doc_tokens if term in dt)

    scores = []
    for dt in doc_tokens:
        tf_map = Counter(dt)
        dl = len(dt)
        score = 0.0
        for term in query_terms:
            if term not in df or df[term] == 0:
                continue
            idf = math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
            tf = tf_map.get(term, 0)
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
            score += idf * tf_norm
        scores.append(score)
    return scores


def sparse_retrieve(query: str, documents: list[str],
                    top_k: int = 10) -> list[dict]:
    """Sparse retrieval using BM25."""
    scores = bm25_score(query, documents)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    results = []
    for idx, score in ranked[:top_k]:
        results.append({
            "index": idx,
            "score": score,
            "text": documents[idx][:500],
            "method": "sparse",
        })
    return results


# ---------------------------------------------------------------------------
# Dense retrieval: embedding-based similarity (requires Ollama embeddings API)
# ---------------------------------------------------------------------------

def _embed(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """Get embeddings from Ollama embeddings API."""
    url = f"{OLLAMA_BASE}/api/embed"
    payload = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(url, data=payload,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("embeddings", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1e-9
    norm_b = math.sqrt(sum(x * x for x in b)) or 1e-9
    return dot / (norm_a * norm_b)


def dense_retrieve(query: str, documents: list[str],
                   top_k: int = 10) -> list[dict]:
    """Dense retrieval using embedding similarity via Ollama."""
    all_texts = [query] + documents
    embeddings = _embed(all_texts)
    if len(embeddings) < 2:
        return []  # Embeddings unavailable, fall back to sparse
    query_emb = embeddings[0]
    doc_embs = embeddings[1:]
    scored = []
    for idx, doc_emb in enumerate(doc_embs):
        sim = _cosine_sim(query_emb, doc_emb)
        scored.append({
            "index": idx,
            "score": sim,
            "text": documents[idx][:500],
            "method": "dense",
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion: combine dense + sparse results
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(result_lists: list[list[dict]],
                           k: int = 60) -> list[dict]:
    """Fuse multiple ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF score = sum(1 / (k + rank)) across all lists.
    """
    fused_scores: dict[int, float] = {}
    best_text: dict[int, str] = {}
    for results in result_lists:
        for rank, item in enumerate(results):
            idx = item["index"]
            fused_scores[idx] = fused_scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
            if idx not in best_text:
                best_text[idx] = item.get("text", "")
    fused = [
        {"index": idx, "score": score, "text": best_text.get(idx, ""), "method": "rrf"}
        for idx, score in fused_scores.items()
    ]
    fused.sort(key=lambda x: x["score"], reverse=True)
    return fused


# ---------------------------------------------------------------------------
# Hybrid retrieval: dense + sparse with RRF fusion
# ---------------------------------------------------------------------------

def hybrid_retrieve(query: str, documents: list[str],
                    top_k: int = 10,
                    dense_weight: float = 0.6,
                    sparse_weight: float = 0.4) -> list[dict]:
    """Run both dense and sparse retrieval, fuse with RRF, return top_k."""
    sparse_results = sparse_retrieve(query, documents, top_k=top_k * 2)
    dense_results = dense_retrieve(query, documents, top_k=top_k * 2)

    if not dense_results:
        # Embeddings unavailable: fall back to sparse only
        return sparse_results[:top_k]

    fused = reciprocal_rank_fusion([dense_results, sparse_results])
    return fused[:top_k]


# ---------------------------------------------------------------------------
# Local reranker: use Ollama chat model to rerank candidates
# ---------------------------------------------------------------------------

def local_rerank(query: str, candidates: list[dict],
                 model: str = RERANK_MODEL,
                 top_k: int = 5) -> list[dict]:
    """Rerank candidates using a local Ollama model as a pointwise scorer.

    Asks the model to score each candidate's relevance to the query on 0-10.
    """
    reranked = []
    for candidate in candidates[:top_k * 2]:  # Limit rerank calls
        text = candidate.get("text", "")[:300]
        prompt = (
            f"Rate the relevance of this passage to the query on a scale of 0-10.\n"
            f"Query: {query}\n"
            f"Passage: {text}\n"
            f"Reply with ONLY a number 0-10."
        )
        url = f"{OLLAMA_BASE}/v1/chat/completions"
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 10,
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                    headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "0")
            score_match = re.search(r"(\d+)", reply)
            score = int(score_match.group(1)) if score_match else 0
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            score = candidate.get("score", 0)
        reranked.append({**candidate, "rerank_score": score, "method": "local_rerank"})
    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked[:top_k]


def hosted_rerank(query: str, candidates: list[dict],
                  top_k: int = 5,
                  api_key: Optional[str] = None) -> list[dict]:
    """Stub for hosted reranker (e.g. Pinecone rerank API or Cohere).

    Replace the body with actual API calls when a hosted reranker is available.
    """
    # Fallback: return candidates sorted by existing score
    api_key = api_key or os.environ.get("RERANK_API_KEY", "")
    if not api_key:
        # No hosted reranker configured, fall back to local
        return local_rerank(query, candidates, top_k=top_k)

    # TODO: Implement hosted reranker API call here
    # Example for Pinecone:
    #   POST https://api.pinecone.io/rerank
    #   { "model": "bge-reranker-v2-m3", "query": query, "documents": [...] }
    return candidates[:top_k]


# ---------------------------------------------------------------------------
# Full pipeline: hybrid retrieve + rerank
# ---------------------------------------------------------------------------

def retrieve_and_rerank(query: str, documents: list[str],
                        top_k: int = 5,
                        use_local_rerank: bool = True) -> list[dict]:
    """Full hybrid retrieval pipeline: retrieve, fuse, rerank."""
    candidates = hybrid_retrieve(query, documents, top_k=top_k * 2)
    if use_local_rerank:
        return local_rerank(query, candidates, top_k=top_k)
    else:
        return hosted_rerank(query, candidates, top_k=top_k)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: hybrid_retrieval.py <query> <file1> [file2 ...]")
        print("Each file is treated as one document.")
        raise SystemExit(1)

    query = sys.argv[1]
    docs = []
    for path in sys.argv[2:]:
        docs.append(pathlib.Path(path).read_text(errors="ignore"))

    print(f"Query: {query}")
    print(f"Documents: {len(docs)}")
    results = retrieve_and_rerank(query, docs)
    for r in results:
        score_info = f"rerank={r.get('rerank_score', 'N/A')}" if "rerank_score" in r else f"score={r['score']:.4f}"
        print(f"  [{score_info}] doc[{r['index']}]: {r['text'][:80]}...")
