#!/usr/bin/env python3
"""Hierarchical memory for effective 10M context.

Provides rolling summaries, retrieval shards, and map-reduce context packing
so local models can work with arbitrarily large codebases without exceeding
their actual context window.
"""
import hashlib
import json
import pathlib
import re
import textwrap
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MEMORY_DIR = REPO_ROOT / "memory"
SHARD_DIR = MEMORY_DIR / "shards"
SUMMARY_DIR = MEMORY_DIR / "summaries"


# ---------------------------------------------------------------------------
# Rolling summary: condense old context into compact summaries
# ---------------------------------------------------------------------------

def rolling_summary(texts: list[str], max_summary_chars: int = 4000) -> str:
    """Condense a list of prior context blocks into a single rolling summary.

    Strategy: keep the first and last blocks verbatim (most important),
    compress middle blocks to their first sentence or first N chars.
    """
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0][:max_summary_chars]

    budget_per_block = max(200, max_summary_chars // max(len(texts), 1))

    parts: list[str] = []
    for idx, text in enumerate(texts):
        if idx == 0 or idx == len(texts) - 1:
            # Keep first and last blocks fuller
            parts.append(text[:budget_per_block * 2])
        else:
            # Compress middle blocks: first sentence or first N chars
            first_sentence = _first_sentence(text)
            if len(first_sentence) > 20:
                parts.append(first_sentence[:budget_per_block])
            else:
                parts.append(text[:budget_per_block])

    combined = "\n---\n".join(parts)
    if len(combined) > max_summary_chars:
        combined = combined[:max_summary_chars] + "\n[...truncated]"
    return combined


def _first_sentence(text: str) -> str:
    """Extract the first sentence from a text block."""
    match = re.match(r"^(.+?[.!?])\s", text.strip(), re.DOTALL)
    return match.group(1) if match else text[:200]


# ---------------------------------------------------------------------------
# Retrieval shards: split large context into indexed chunks
# ---------------------------------------------------------------------------

def create_shards(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[dict]:
    """Split a large text into overlapping indexed chunks.

    Returns a list of dicts with keys: id, index, text, hash.
    """
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    shards = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        chunk_hash = hashlib.md5(chunk.encode()).hexdigest()[:12]
        shard = {
            "id": f"shard-{index:04d}-{chunk_hash}",
            "index": index,
            "text": chunk,
            "hash": chunk_hash,
            "start_char": start,
            "end_char": end,
        }
        shards.append(shard)
        # Write shard to disk for later retrieval
        shard_path = SHARD_DIR / f"{shard['id']}.json"
        shard_path.write_text(json.dumps(shard, indent=2))
        start += chunk_size - overlap
        index += 1
    # Write index file
    index_path = SHARD_DIR / "shard-index.json"
    index_entries = [
        {"id": s["id"], "index": s["index"], "hash": s["hash"],
         "start_char": s["start_char"], "end_char": s["end_char"],
         "preview": s["text"][:80]}
        for s in shards
    ]
    index_path.write_text(json.dumps(index_entries, indent=2))
    return shards


def load_shard(shard_id: str) -> str:
    """Load a single shard by ID from disk."""
    shard_path = SHARD_DIR / f"{shard_id}.json"
    if not shard_path.exists():
        return ""
    data = json.loads(shard_path.read_text())
    return data.get("text", "")


def search_shards(query: str, top_k: int = 5) -> list[dict]:
    """Simple keyword-based shard search (no embeddings required).

    Scores shards by the number of query terms they contain.
    For production use, replace with vector similarity via hybrid_retrieval.py.
    """
    index_path = SHARD_DIR / "shard-index.json"
    if not index_path.exists():
        return []
    index_entries = json.loads(index_path.read_text())
    query_terms = set(query.lower().split())
    scored = []
    for entry in index_entries:
        shard_text = load_shard(entry["id"]).lower()
        score = sum(1 for term in query_terms if term in shard_text)
        if score > 0:
            scored.append({**entry, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Map-reduce context packer: combine relevant shards for current task
# ---------------------------------------------------------------------------

def map_reduce_pack(query: str, all_context_blocks: list[str],
                    max_packed_chars: int = 32000,
                    shard_chunk_size: int = 2000) -> str:
    """Combine relevant context for a task using map-reduce strategy.

    1. MAP: shard each context block and score by query relevance.
    2. REDUCE: combine top-scoring shards into a single packed context
       that fits within max_packed_chars.
    """
    # Map phase: create shards from all context blocks
    all_shards: list[dict] = []
    for block in all_context_blocks:
        if len(block) <= shard_chunk_size:
            # Small block: keep as-is
            block_hash = hashlib.md5(block.encode()).hexdigest()[:12]
            all_shards.append({
                "id": f"inline-{block_hash}",
                "text": block,
                "score": 0,
            })
        else:
            # Large block: shard it
            shards = create_shards(block, chunk_size=shard_chunk_size)
            all_shards.extend(shards)

    # Score shards by query relevance
    query_terms = set(query.lower().split())
    for shard in all_shards:
        text_lower = shard["text"].lower()
        shard["score"] = sum(1 for term in query_terms if term in text_lower)

    # Sort by relevance (highest first)
    all_shards.sort(key=lambda x: x["score"], reverse=True)

    # Reduce phase: pack top shards into budget
    packed_parts: list[str] = []
    chars_used = 0
    for shard in all_shards:
        chunk_text = shard["text"]
        if chars_used + len(chunk_text) > max_packed_chars:
            # Try to fit a trimmed version
            remaining = max_packed_chars - chars_used
            if remaining > 200:
                packed_parts.append(chunk_text[:remaining])
                chars_used += remaining
            break
        packed_parts.append(chunk_text)
        chars_used += len(chunk_text)

    return "\n\n---\n\n".join(packed_parts)


def save_rolling_summary(stage_id: str, summary_text: str) -> pathlib.Path:
    """Persist a rolling summary for a stage."""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SUMMARY_DIR / f"{stamp}-{stage_id}-summary.md"
    path.write_text(summary_text)
    return path


def load_latest_summary(stage_id: str) -> str:
    """Load the most recent rolling summary for a stage."""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(SUMMARY_DIR.glob(f"*-{stage_id}-summary.md"), reverse=True)
    if candidates:
        return candidates[0].read_text(errors="ignore")
    return ""


# ---------------------------------------------------------------------------
# CLI entry point for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: hierarchical_memory.py <command> [args]")
        print("Commands: shard <file>, search <query>, summary <file1> [file2 ...]")
        raise SystemExit(1)

    cmd = sys.argv[1]
    if cmd == "shard" and len(sys.argv) >= 3:
        text = pathlib.Path(sys.argv[2]).read_text(errors="ignore")
        shards = create_shards(text)
        print(f"Created {len(shards)} shards in {SHARD_DIR}")
    elif cmd == "search" and len(sys.argv) >= 3:
        results = search_shards(" ".join(sys.argv[2:]))
        for r in results:
            print(f"  [{r['score']}] {r['id']}: {r.get('preview', '')[:60]}")
    elif cmd == "summary" and len(sys.argv) >= 3:
        texts = [pathlib.Path(f).read_text(errors="ignore") for f in sys.argv[2:]]
        print(rolling_summary(texts))
    else:
        print(f"Unknown command: {cmd}")
        raise SystemExit(1)
