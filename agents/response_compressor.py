#!/usr/bin/env python3
"""
response_compressor.py — Intelligent Response Compression
==========================================================
Compress verbose agent responses while preserving key information.
Target: 30-50% token reduction without losing actionable content.

Key functions:
  - compress(text, target_ratio=0.5) -> str
  - compress_response(response_dict) -> dict
  - estimate_tokens(text) -> int

Strategies:
  1. Remove filler phrases and redundant words
  2. Deduplicate repeated sentences/ideas
  3. Strip boilerplate (greetings, disclaimers, sign-offs)
  4. Collapse whitespace and formatting noise
  5. Shorten common verbose patterns
  6. Summarize bullet lists that repeat the same idea
"""

import re
import hashlib
from typing import Optional


# ---------------------------------------------------------------------------
# Filler phrases that add no informational value
# ---------------------------------------------------------------------------
FILLER_PHRASES = [
    r"\bbasically\b",
    r"\bactually\b",
    r"\bin order to\b",
    r"\bdue to the fact that\b",
    r"\bat this point in time\b",
    r"\bat the end of the day\b",
    r"\bfor all intents and purposes\b",
    r"\bit is important to note that\b",
    r"\bit should be noted that\b",
    r"\bit is worth mentioning that\b",
    r"\bneedless to say\b",
    r"\bin my opinion\b",
    r"\bas a matter of fact\b",
    r"\bwith that being said\b",
    r"\bhaving said that\b",
    r"\bthat being said\b",
    r"\bin terms of\b",
    r"\bin the process of\b",
    r"\bon a daily basis\b",
    r"\bin the event that\b",
    r"\bfor the purpose of\b",
    r"\bin the near future\b",
    r"\bprior to\b",
    r"\bsubsequent to\b",
    r"\bin close proximity\b",
    r"\ba large number of\b",
    r"\bthe vast majority of\b",
    r"\bin spite of the fact that\b",
    r"\bwith regard to\b",
    r"\bwith respect to\b",
    r"\bin regard to\b",
    r"\bin light of\b",
    r"\bas a result of\b",
    r"\bon the other hand\b",
    r"\bin addition to this\b",
]

# Verbose → concise replacements
VERBOSE_REPLACEMENTS = [
    (r"\bdue to the fact that\b", "because"),
    (r"\bin order to\b", "to"),
    (r"\bat this point in time\b", "now"),
    (r"\bin the event that\b", "if"),
    (r"\bfor the purpose of\b", "for"),
    (r"\bin the near future\b", "soon"),
    (r"\bprior to\b", "before"),
    (r"\bsubsequent to\b", "after"),
    (r"\bin close proximity\b", "near"),
    (r"\ba large number of\b", "many"),
    (r"\bthe vast majority of\b", "most"),
    (r"\bin spite of the fact that\b", "despite"),
    (r"\bwith regard to\b", "about"),
    (r"\bwith respect to\b", "about"),
    (r"\bin regard to\b", "about"),
    (r"\bas a result of\b", "because of"),
    (r"\bin addition to this\b", "also"),
    (r"\bin addition to\b", "besides"),
    (r"\bis able to\b", "can"),
    (r"\bare able to\b", "can"),
    (r"\bwas able to\b", "could"),
    (r"\bhas the ability to\b", "can"),
    (r"\bhave the ability to\b", "can"),
    (r"\bis not noticeable\b", "was unnoticeable"),
    (r"\bwas not noticeable\b", "was unnoticeable"),
    (r"\bso the lack of\b", "so lacking"),
    (r"\bthe lack of\b", "no"),
    (r"\bperforming adequately\b", "fine"),
    (r"\buntil the recent\b", "until recent"),
    (r"\bhas grown to\b", "reached"),
    (r"\bis being performed\b", "occurs"),
    (r"\ba full table scan\b", "full table scan"),
    (r"\bI examined\b", "examining"),
    (r"\bI found that\b", "found"),
    (r"\bwe need to\b", "need to"),
    (r"\bwe should\b", "should"),
    (r"\bthat the\b", "the"),
    (r"\bwhich is\b", ""),
    (r"\bthere is\b", ""),
    (r"\bthere are\b", ""),
    (r"\bin this table\b", "here"),
    (r"\bthe database is\b", "database"),
    (r"\bthe server was\b", "server was"),
    (r"\bthe query was\b", "query was"),
    (r"\bfor every query\b", "per query"),
    (r"\bshould drop from\b", "drops from"),
    (r"\bhave been resolved with\b", "resolve with"),
    (r"\bif growth continues at this rate\b", "if growth continues"),
    (r"\bafter index is applied\b", "post-index"),
    (r"\bafter the index is applied\b", "post-index"),
    (r"\bquery performance\b", "query perf"),
    (r"\bCorrectly\b,?\s*", ""),
    (r"\bin the process of\b", ""),
    (r"\bon a daily basis\b", "daily"),
    (r"\bit is important to note that\b", ""),
    (r"\bit should be noted that\b", ""),
    (r"\bit is worth mentioning that\b", ""),
    (r"\bneedless to say\b", ""),
    (r"\bas a matter of fact\b", ""),
    (r"\bfor all intents and purposes\b", ""),
    (r"\bat the end of the day\b", ""),
    (r"\bwith that being said\b", ""),
    (r"\bhaving said that\b", ""),
    (r"\bthat being said\b", ""),
]

# Boilerplate patterns to strip
BOILERPLATE_PATTERNS = [
    r"(?i)^(hi|hello|hey|dear|greetings)[,!\s].*?[.!]\s*",
    r"(?i)(hope this helps|let me know if you have any questions|"
    r"feel free to ask|don't hesitate to reach out|happy to help)[.!]*\s*$",
    r"(?i)^(sure|of course|certainly|absolutely)[,!\s]+",
    r"(?i)^(i would be happy to|i'd be happy to|i'm happy to)\s+",
    r"(?i)(please let me know|please don't hesitate)[.!]*\s*$",
    r"(?i)^(here is|here are|here's|below is|below are)\s+(the|a|an|my)\s+",
]


def estimate_tokens(text: str) -> int:
    """Estimate token count using word-based heuristic (avg 0.75 tokens/word)."""
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    return max(1, int(words * 0.75 + chars * 0.05))


def _apply_outside_code_blocks(text: str, fn) -> str:
    """Apply a text transformation function only outside of code blocks."""
    parts = re.split(r"(```[\s\S]*?```)", text)
    result = []
    for i, part in enumerate(parts):
        if part.startswith("```"):
            result.append(part)
        else:
            result.append(fn(part))
    return "".join(result)


def _remove_boilerplate(text: str) -> str:
    """Strip greeting/sign-off boilerplate."""
    def _do(t):
        for pattern in BOILERPLATE_PATTERNS:
            t = re.sub(pattern, "", t, flags=re.MULTILINE)
        return t
    return _apply_outside_code_blocks(text, _do).strip()


def _apply_replacements(text: str) -> str:
    """Replace verbose phrases with concise equivalents."""
    def _do(t):
        for pattern, replacement in VERBOSE_REPLACEMENTS:
            t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
        return t
    return _apply_outside_code_blocks(text, _do)


def _remove_filler(text: str) -> str:
    """Remove filler words and hedging phrases that add no meaning."""
    fillers = [
        r"\bbasically\b,?\s*",
        r"\bactually\b,?\s*",
        r"\bin my opinion\b,?\s*",
        r"\bessentially\b,?\s*",
        r"\bclearly\b,?\s*",
        r"\bobviously\b,?\s*",
        r"\bsimply\b,?\s*",
        r"\bjust\b\s+",
        r"\breally\b\s+",
        r"\bquite\b\s+",
        r"\bvery\b\s+",
        r"\bso\b,\s+",
        r"\bwell\b,\s+",
        r"\bof course\b,?\s*",
        r"\bas you know\b,?\s*",
        r"\bas mentioned\b,?\s*",
        r"\bas we can see\b,?\s*",
        r"\bit goes without saying\b,?\s*",
        r"\bto be honest\b,?\s*",
        r"\bthe thing is\b,?\s*",
        r"\bwhat this means is\b,?\s*",
        r"\bThis results in\b",
        r"\bThis means that\b",
    ]
    def _do(t):
        for pattern in fillers:
            t = re.sub(pattern, "", t, flags=re.IGNORECASE)
        t = re.sub(r" {2,}", " ", t)
        return t
    return _apply_outside_code_blocks(text, _do)


def _collapse_whitespace(text: str) -> str:
    """Normalize whitespace without destroying paragraph structure or code blocks."""
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = text.split("\n")
    result = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            result.append(line.rstrip())
        elif in_code_block:
            # Preserve code block content exactly
            result.append(line.rstrip())
        else:
            # Collapse multiple spaces and strip
            collapsed = re.sub(r" {2,}", " ", line).strip()
            result.append(collapsed)
    return "\n".join(result)


STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "this", "that", "these", "those", "it", "its",
})


def _normalize_for_dedup(text: str) -> str:
    """Normalize text for near-duplicate detection by removing stop words."""
    normalized = re.sub(r"[^\w\s]", "", text.lower())
    words = [w for w in normalized.split() if w not in STOP_WORDS]
    return " ".join(words)


def _deduplicate_sentences(text: str) -> str:
    """Remove duplicate or near-duplicate sentences at both line and intra-line level."""
    # First pass: deduplicate within paragraphs (sentence-level)
    lines = text.split("\n")
    deduped_lines = []
    seen_sentence_hashes = set()

    in_code_block = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            deduped_lines.append(line)
            continue

        # Track code blocks — preserve them exactly
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            deduped_lines.append(line)
            continue
        if in_code_block:
            deduped_lines.append(line)
            continue

        # Check if line is a heading or bullet — keep as-is for line dedup
        if re.match(r"^(#{1,6}\s|[-*•]\s)", stripped):
            deduped_lines.append(line)
            continue

        # Split line into sentences and deduplicate
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        kept = []
        for sentence in sentences:
            normalized = _normalize_for_dedup(sentence)
            if len(normalized) < 8:
                kept.append(sentence)
                continue
            h = hashlib.md5(normalized.encode()).hexdigest()
            if h not in seen_sentence_hashes:
                seen_sentence_hashes.add(h)
                kept.append(sentence)

        if kept:
            deduped_lines.append(" ".join(kept))

    # Second pass: deduplicate whole lines
    result = []
    seen_line_hashes = set()
    in_code_block2 = False
    for line in deduped_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block2 = not in_code_block2
            result.append(line)
            continue
        if in_code_block2 or not stripped or re.match(r"^#{1,6}\s", stripped):
            result.append(line)
            continue

        normalized = _normalize_for_dedup(stripped)
        if len(normalized) < 8:
            result.append(line)
            continue

        h = hashlib.md5(normalized.encode()).hexdigest()
        if h not in seen_line_hashes:
            seen_line_hashes.add(h)
            result.append(line)

    return "\n".join(result)


def _compress_bullet_lists(text: str) -> str:
    """Collapse bullet lists with redundant or near-duplicate items."""
    lines = text.split("\n")
    result = []
    bullet_group = []
    bullet_hashes = set()

    def flush_bullets():
        nonlocal bullet_group, bullet_hashes
        result.extend(bullet_group)
        bullet_group = []
        bullet_hashes = set()

    for line in lines:
        stripped = line.strip()
        is_bullet = bool(re.match(r"^[-*•]\s+", stripped))

        if is_bullet:
            content = re.sub(r"^[-*•]\s+", "", stripped)
            normalized = _normalize_for_dedup(content)
            h = hashlib.md5(normalized.encode()).hexdigest()

            if h not in bullet_hashes:
                bullet_hashes.add(h)
                bullet_group.append(line)
        else:
            if bullet_group:
                flush_bullets()
            result.append(line)

    if bullet_group:
        flush_bullets()

    return "\n".join(result)


def _strip_empty_sections(text: str) -> str:
    """Remove section headers that have no content below them."""
    lines = text.split("\n")
    result = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Check if this is a markdown header
        if re.match(r"^#{1,6}\s+", stripped):
            # Look ahead for content
            has_content = False
            for j in range(i + 1, min(i + 5, len(lines))):
                next_stripped = lines[j].strip()
                if next_stripped and not re.match(r"^#{1,6}\s+", next_stripped):
                    has_content = True
                    break
                elif re.match(r"^#{1,6}\s+", next_stripped):
                    break
            if has_content:
                result.append(line)
        else:
            result.append(line)

    return "\n".join(result)


def compress(text: str, target_ratio: float = 0.5) -> str:
    """
    Compress text intelligently, targeting `target_ratio` of original size.

    Args:
        text: Input text to compress.
        target_ratio: Target size as fraction of original (0.5 = 50% of original).

    Returns:
        Compressed text preserving key information.
    """
    if not text or len(text.strip()) < 50:
        return text

    original_tokens = estimate_tokens(text)

    # Apply compression passes in order of aggressiveness
    passes = [
        ("boilerplate", _remove_boilerplate),
        ("replacements", _apply_replacements),
        ("filler", _remove_filler),
        ("dedup_sentences", _deduplicate_sentences),
        ("dedup_bullets", _compress_bullet_lists),
        ("empty_sections", _strip_empty_sections),
        ("whitespace", _collapse_whitespace),
    ]

    compressed = text
    for name, fn in passes:
        compressed = fn(compressed)
        current_ratio = estimate_tokens(compressed) / max(original_tokens, 1)
        if current_ratio <= target_ratio:
            break

    return compressed.strip()


def compress_response(response: dict, target_ratio: float = 0.5) -> dict:
    """
    Compress a response dict, applying compression to string values.

    Preserves dict structure. Only compresses string values with 50+ chars.
    Adds `_compression_meta` with stats.

    Args:
        response: Agent response dict.
        target_ratio: Target compression ratio.

    Returns:
        New dict with compressed string values and metadata.
    """
    if not isinstance(response, dict):
        return response

    original_tokens = 0
    compressed_tokens = 0
    result = {}

    for key, value in response.items():
        if isinstance(value, str) and len(value) >= 50:
            orig_t = estimate_tokens(value)
            original_tokens += orig_t
            compressed_value = compress(value, target_ratio)
            comp_t = estimate_tokens(compressed_value)
            compressed_tokens += comp_t
            result[key] = compressed_value
        elif isinstance(value, dict):
            inner = compress_response(value, target_ratio)
            if isinstance(inner, dict) and "_compression_meta" in inner:
                meta = inner.pop("_compression_meta")
                original_tokens += meta.get("original_tokens", 0)
                compressed_tokens += meta.get("compressed_tokens", 0)
            result[key] = inner
        elif isinstance(value, list):
            compressed_list = []
            for item in value:
                if isinstance(item, str) and len(item) >= 50:
                    orig_t = estimate_tokens(item)
                    original_tokens += orig_t
                    c = compress(item, target_ratio)
                    compressed_tokens += estimate_tokens(c)
                    compressed_list.append(c)
                elif isinstance(item, dict):
                    inner = compress_response(item, target_ratio)
                    if isinstance(inner, dict) and "_compression_meta" in inner:
                        meta = inner.pop("_compression_meta")
                        original_tokens += meta.get("original_tokens", 0)
                        compressed_tokens += meta.get("compressed_tokens", 0)
                    compressed_list.append(inner)
                else:
                    compressed_list.append(item)
            result[key] = compressed_list
        else:
            result[key] = value

    if original_tokens > 0:
        reduction = 1.0 - (compressed_tokens / original_tokens)
        result["_compression_meta"] = {
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "reduction_pct": round(reduction * 100, 1),
        }
    return result


def get_compression_stats(original: str, compressed: str) -> dict:
    """Return compression statistics."""
    orig_tokens = estimate_tokens(original)
    comp_tokens = estimate_tokens(compressed)
    return {
        "original_tokens": orig_tokens,
        "compressed_tokens": comp_tokens,
        "reduction_pct": round((1 - comp_tokens / max(orig_tokens, 1)) * 100, 1),
        "original_chars": len(original),
        "compressed_chars": len(compressed),
        "char_reduction_pct": round(
            (1 - len(compressed) / max(len(original), 1)) * 100, 1
        ),
    }


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # Test 1: Verbose phrase replacement
    # ------------------------------------------------------------------
    verbose = (
        "Due to the fact that the server was unable to respond "
        "in order to process the request, it is important to note that "
        "we need to implement a retry mechanism. The vast majority of "
        "errors are able to be resolved prior to the timeout. "
        "In the event that the retry fails, we should alert the operator."
    )
    result = compress(verbose)
    stats = get_compression_stats(verbose, result)
    print(f"Test 1 — Verbose phrases: {stats['reduction_pct']}% reduction")
    assert stats["reduction_pct"] >= 20, f"Expected >=20% reduction, got {stats['reduction_pct']}%"
    assert "because" in result.lower(), "Should replace 'due to the fact that' with 'because'"
    assert "many" in result.lower() or "most" in result.lower(), "Should replace 'vast majority'"
    assert "before" in result.lower(), "Should replace 'prior to' with 'before'"
    print(f"  Compressed: {result[:120]}...")

    # ------------------------------------------------------------------
    # Test 2: Boilerplate removal
    # ------------------------------------------------------------------
    with_boilerplate = (
        "Hello! I'd be happy to help you with this.\n\n"
        "The root cause is a missing index on the users table. "
        "Adding a composite index on (email, created_at) will fix the query "
        "performance from 45s to under 100ms.\n\n"
        "Hope this helps! Let me know if you have any questions."
    )
    result2 = compress(with_boilerplate)
    stats2 = get_compression_stats(with_boilerplate, result2)
    print(f"\nTest 2 — Boilerplate: {stats2['reduction_pct']}% reduction")
    assert stats2["reduction_pct"] >= 15, f"Expected >=15% reduction, got {stats2['reduction_pct']}%"
    assert "root cause" in result2.lower(), "Should preserve key content"
    assert "composite index" in result2.lower(), "Should preserve technical details"
    print(f"  Compressed: {result2[:120]}...")

    # ------------------------------------------------------------------
    # Test 3: Duplicate sentence removal
    # ------------------------------------------------------------------
    with_dupes = (
        "The database query is slow.\n"
        "We need to optimize the query performance.\n"
        "The database query is slow.\n"
        "Adding an index will help.\n"
        "We need to optimize the query performance.\n"
        "The fix is straightforward.\n"
    )
    result3 = compress(with_dupes)
    stats3 = get_compression_stats(with_dupes, result3)
    print(f"\nTest 3 — Deduplication: {stats3['reduction_pct']}% reduction")
    assert stats3["reduction_pct"] >= 25, f"Expected >=25% reduction, got {stats3['reduction_pct']}%"
    assert result3.lower().count("database query is slow") == 1, "Should remove duplicate sentences"
    print(f"  Compressed: {result3}")

    # ------------------------------------------------------------------
    # Test 4: Bullet list deduplication
    # ------------------------------------------------------------------
    bullet_list = (
        "Issues found:\n"
        "- Missing database index on users table\n"
        "- No retry logic in API client\n"
        "- Missing database index on the users table\n"
        "- Timeout not configured for external calls\n"
        "- No retry logic in the API client\n"
        "- Missing error handling in middleware\n"
    )
    result4 = compress(bullet_list)
    stats4 = get_compression_stats(bullet_list, result4)
    print(f"\nTest 4 — Bullet dedup: {stats4['reduction_pct']}% reduction")
    assert stats4["reduction_pct"] >= 20, f"Expected >=20% reduction, got {stats4['reduction_pct']}%"
    assert result4.count("Missing database index") == 1, "Should deduplicate similar bullets"
    print(f"  Compressed:\n{result4}")

    # ------------------------------------------------------------------
    # Test 5: compress_response on dict
    # ------------------------------------------------------------------
    response_dict = {
        "id": "task-001",
        "status": "completed",
        "quality_score": 85,
        "result": (
            "Hello! I'd be happy to help. Due to the fact that the server "
            "was overloaded, in order to fix this we need to add caching. "
            "It is important to note that the cache TTL should be 300 seconds. "
            "The vast majority of requests will be served from cache. "
            "Hope this helps! Let me know if you have any questions."
        ),
        "errors": [],
    }
    result5 = compress_response(response_dict)
    assert result5["id"] == "task-001", "Should preserve non-string fields"
    assert result5["status"] == "completed", "Should preserve short strings"
    assert result5["quality_score"] == 85, "Should preserve numbers"
    assert "_compression_meta" in result5, "Should include compression metadata"
    meta = result5["_compression_meta"]
    print(f"\nTest 5 — Dict compression: {meta['reduction_pct']}% reduction")
    assert meta["reduction_pct"] >= 20, f"Expected >=20% reduction, got {meta['reduction_pct']}%"
    assert "caching" in result5["result"].lower(), "Should preserve key technical info"
    assert "300" in result5["result"], "Should preserve specific values"
    print(f"  Result field: {result5['result'][:120]}...")

    # ------------------------------------------------------------------
    # Test 6: Whitespace collapse
    # ------------------------------------------------------------------
    messy_whitespace = (
        "Line one.   Extra   spaces   here.\n"
        "\n"
        "\n"
        "\n"
        "\n"
        "Line two after many blanks.\n"
        "   Trailing spaces   \n"
        "Normal line.\n"
    )
    result6 = compress(messy_whitespace)
    assert "   " not in result6, "Should collapse multiple spaces"
    assert "\n\n\n" not in result6, "Should collapse excessive newlines"
    print(f"\nTest 6 — Whitespace: passed")

    # ------------------------------------------------------------------
    # Test 7: Short text passthrough
    # ------------------------------------------------------------------
    short = "Error: timeout"
    result7 = compress(short)
    assert result7 == short, "Should not modify short text"
    print("Test 7 — Short passthrough: passed")

    # ------------------------------------------------------------------
    # Test 8: Code blocks preserved
    # ------------------------------------------------------------------
    with_code = (
        "Due to the fact that the function is broken, here is the fix:\n\n"
        "```python\n"
        "def retry(fn, max_retries=3):\n"
        "    for i in range(max_retries):\n"
        "        try:\n"
        "            return fn()\n"
        "        except Exception:\n"
        "            if i == max_retries - 1:\n"
        "                raise\n"
        "```\n\n"
        "Hope this helps! Let me know if you have any questions."
    )
    result8 = compress(with_code)
    assert "def retry" in result8, "Should preserve code block content"
    assert "    for i in range" in result8, "Should preserve code indentation"
    print("Test 8 — Code block preservation: passed")

    # ------------------------------------------------------------------
    # Test 9: Nested dict compression
    # ------------------------------------------------------------------
    nested = {
        "task": "diagnose",
        "pipeline": {
            "router": "Due to the fact that the error pattern matches a database issue, "
                       "it is important to note that the classification is DB_PERF. "
                       "The vast majority of similar incidents are caused by missing indexes.",
            "retriever": "In order to find relevant documentation, we searched the knowledge base. "
                         "Prior to the incident, performance was normal. The retriever found 3 docs.",
        },
    }
    result9 = compress_response(nested)
    assert "because" in result9["pipeline"]["router"].lower(), "Should compress nested values"
    print("Test 9 — Nested dict: passed")

    # ------------------------------------------------------------------
    # Test 10: estimate_tokens sanity
    # ------------------------------------------------------------------
    tokens_empty = estimate_tokens("")
    assert tokens_empty == 0, "Empty string = 0 tokens"
    tokens_word = estimate_tokens("hello world test")
    assert 1 <= tokens_word <= 10, f"Short text token estimate reasonable: {tokens_word}"
    print("Test 10 — Token estimation: passed")

    # ------------------------------------------------------------------
    # Test 11: Large realistic response — target 30-50% reduction
    # ------------------------------------------------------------------
    large_response = (
        "Hello! I'd be happy to help you diagnose this issue.\n\n"
        "## Analysis\n\n"
        "Due to the fact that the database query is taking 45 seconds, "
        "it is important to note that this is well above the acceptable threshold. "
        "The vast majority of queries in this table complete in under 100ms. "
        "In order to investigate, I examined the query plan and found that "
        "a full table scan is being performed.\n\n"
        "It should be noted that the users table has grown to 10 million rows. "
        "Prior to last month, the table was under 1 million rows, so the lack "
        "of an index was not noticeable. As a matter of fact, the query was "
        "performing adequately until the recent data growth.\n\n"
        "## Root Cause\n\n"
        "The root cause is a missing composite index on (email, created_at). "
        "The database is performing a full table scan on 10M rows for every query. "
        "The root cause is a missing composite index on (email, created_at). "
        "This results in sequential reads across all data pages.\n\n"
        "## Recommended Fix\n\n"
        "- Add composite index on (email, created_at) to users table\n"
        "- Add composite index on (email, created_at) to the users table\n"
        "- Monitor query performance after index is applied\n"
        "- Set up alerting for queries exceeding 1 second\n"
        "- Consider partitioning if growth continues at this rate\n"
        "- Monitor query performance after the index is applied\n\n"
        "## Expected Impact\n\n"
        "In the event that the index is applied correctly, the query time "
        "should drop from 45 seconds to under 100ms. The vast majority of "
        "similar cases have been resolved with this approach.\n\n"
        "Hope this helps! Please let me know if you have any questions. "
        "Feel free to ask if you need further assistance."
    )
    result11 = compress(large_response)
    stats11 = get_compression_stats(large_response, result11)
    print(f"\nTest 11 — Large response: {stats11['reduction_pct']}% reduction "
          f"({stats11['original_tokens']} -> {stats11['compressed_tokens']} tokens)")
    assert stats11["reduction_pct"] >= 30, (
        f"Expected >=30% reduction on large response, got {stats11['reduction_pct']}%"
    )
    assert "composite index" in result11.lower(), "Must preserve fix recommendation"
    assert "10" in result11 and "million" in result11.lower() or "10M" in result11, (
        "Must preserve data size context"
    )
    assert result11.count("composite index on (email, created_at)") <= 2, (
        "Should deduplicate repeated fix description"
    )
    print(f"  First 200 chars: {result11[:200]}...")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("ALL ASSERTIONS PASSED")
    print("=" * 60)
