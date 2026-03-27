#!/usr/bin/env python3
"""
entropy_filter.py — Entropy-Based Token Filtering
==================================================
Remove low-information tokens from text using Shannon entropy scoring.

Tokens with entropy below a configurable threshold are considered
low-information (e.g., stopwords, filler, repeated fragments) and
are filtered out to reduce noise and token cost.

Key functions:
  - token_entropy(token, corpus_freq) -> float
  - filter_low_entropy_tokens(text, threshold=1.0) -> str
  - build_frequency_table(texts) -> dict[str, float]
  - entropy_score(text) -> float
"""

import math
import re
from collections import Counter
from typing import Optional


# ---------------------------------------------------------------------------
# Default stopwords / ultra-common tokens (English) — always low-entropy
# ---------------------------------------------------------------------------
DEFAULT_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out",
    "off", "over", "under", "again", "further", "then", "once", "it",
    "its", "this", "that", "these", "those", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "what", "which", "who", "whom", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "about", "up", "also", "well", "back", "even", "still",
    "new", "get", "got", "go", "going", "went", "make", "made",
})

# Filler phrases that carry near-zero information
FILLER_PHRASES = [
    r"\bbasically\b",
    r"\bactually\b",
    r"\bin order to\b",
    r"\bat the end of the day\b",
    r"\bit is worth noting that\b",
    r"\bit should be noted that\b",
    r"\bas a matter of fact\b",
    r"\bneedless to say\b",
    r"\bin terms of\b",
    r"\bwith respect to\b",
    r"\bfor what it'?s worth\b",
    r"\bin this case\b",
    r"\bas mentioned (?:earlier|above|before|previously)\b",
    r"\bplease note that\b",
    r"\bkindly note that\b",
    r"\bas you can see\b",
    r"\bas we know\b",
]

_FILLER_RE = re.compile("|".join(FILLER_PHRASES), re.IGNORECASE)
_TOKENIZE_RE = re.compile(r"[a-zA-Z0-9_]+(?:'[a-z]+)?|[^\s]")


# ---------------------------------------------------------------------------
# Core: Shannon entropy of a single token given corpus frequencies
# ---------------------------------------------------------------------------
def token_entropy(token: str, corpus_freq: dict[str, float], total_tokens: int) -> float:
    """
    Compute the self-information (surprisal) of a token:
        -log2(P(token))
    where P(token) = count(token) / total_tokens.

    Higher values = more informative / surprising.
    Lower values = more common / less informative.
    """
    token_lower = token.lower()
    count = corpus_freq.get(token_lower, 0)
    if count == 0:
        # Unseen token — assign maximum surprisal (very informative)
        return math.log2(total_tokens + 1)
    prob = count / total_tokens
    return -math.log2(prob)


def build_frequency_table(texts: list[str]) -> dict[str, int]:
    """Build a token frequency table from a list of texts."""
    freq: Counter = Counter()
    for text in texts:
        tokens = _TOKENIZE_RE.findall(text.lower())
        freq.update(tokens)
    return dict(freq)


def entropy_score(text: str) -> float:
    """
    Compute the average per-token entropy of a text using its own
    internal frequency distribution.

    This is the Shannon entropy H = -sum(p * log2(p)) over unique tokens,
    normalized. Useful as a quick quality signal — lower means more
    repetitive / less informative.
    """
    tokens = _TOKENIZE_RE.findall(text.lower())
    if not tokens:
        return 0.0
    freq = Counter(tokens)
    total = len(tokens)
    h = 0.0
    for count in freq.values():
        p = count / total
        h -= p * math.log2(p)
    return h


def _remove_filler_phrases(text: str) -> str:
    """Strip known filler phrases from text."""
    result = _FILLER_RE.sub("", text)
    # Clean up double spaces left behind
    result = re.sub(r"  +", " ", result)
    return result.strip()


def _is_punctuation(token: str) -> bool:
    return len(token) == 1 and not token.isalnum()


# ---------------------------------------------------------------------------
# Main filtering function
# ---------------------------------------------------------------------------
def filter_low_entropy_tokens(
    text: str,
    threshold: float = 1.0,
    corpus_freq: Optional[dict[str, int]] = None,
    preserve_structure: bool = True,
    remove_stopwords: bool = True,
    remove_fillers: bool = True,
) -> str:
    """
    Filter low-information tokens from text using entropy-based scoring.

    Args:
        text: Input text to filter.
        threshold: Minimum self-information (bits) for a token to be kept.
            Tokens below this are removed. Default 1.0 bit.
        corpus_freq: Pre-built frequency table. If None, uses the text's own
            frequency distribution (plus stopword penalties).
        preserve_structure: Keep punctuation and newlines for readability.
        remove_stopwords: Also remove tokens in DEFAULT_STOPWORDS.
        remove_fillers: Strip known filler phrases before token filtering.

    Returns:
        Filtered text with low-information tokens removed.
    """
    if not text or not text.strip():
        return text.strip() if text else text

    # Step 1: Remove filler phrases
    working = text
    if remove_fillers:
        working = _remove_filler_phrases(working)

    # Step 2: Build frequency table from the text itself if not provided
    tokens_raw = _TOKENIZE_RE.findall(working)
    if not tokens_raw:
        return working

    if corpus_freq is None:
        freq = Counter(t.lower() for t in tokens_raw)
        # Boost stopword frequencies to penalize them
        for sw in DEFAULT_STOPWORDS:
            freq[sw] = freq.get(sw, 0) + len(tokens_raw)
        total = sum(freq.values())
    else:
        freq = corpus_freq
        total = sum(freq.values())

    # Step 3: Score and filter tokens
    lines = working.split("\n")
    filtered_lines = []

    for line in lines:
        line_tokens = _TOKENIZE_RE.findall(line)
        kept = []
        for tok in line_tokens:
            # Always keep punctuation if preserving structure
            if preserve_structure and _is_punctuation(tok):
                kept.append(tok)
                continue

            tok_lower = tok.lower()

            # Explicit stopword removal
            if remove_stopwords and tok_lower in DEFAULT_STOPWORDS:
                continue

            # Entropy-based filtering
            score = token_entropy(tok_lower, freq, total)
            if score >= threshold:
                kept.append(tok)

        filtered_line = " ".join(kept)
        # Clean up spacing around punctuation
        filtered_line = re.sub(r"\s+([.,;:!?])", r"\1", filtered_line)
        filtered_lines.append(filtered_line)

    result = "\n".join(filtered_lines)
    # Collapse multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ---------------------------------------------------------------------------
# Batch filtering with shared corpus
# ---------------------------------------------------------------------------
def filter_batch(
    texts: list[str],
    threshold: float = 1.0,
    remove_stopwords: bool = True,
    remove_fillers: bool = True,
) -> list[str]:
    """
    Filter multiple texts using a shared frequency table built from
    all texts combined. This gives better entropy estimates than
    filtering each text in isolation.
    """
    corpus_freq = build_frequency_table(texts)
    # Boost stopwords
    total_tokens = sum(corpus_freq.values())
    for sw in DEFAULT_STOPWORDS:
        corpus_freq[sw] = corpus_freq.get(sw, 0) + total_tokens

    return [
        filter_low_entropy_tokens(
            t,
            threshold=threshold,
            corpus_freq=corpus_freq,
            remove_stopwords=remove_stopwords,
            remove_fillers=remove_fillers,
        )
        for t in texts
    ]


# ---------------------------------------------------------------------------
# Token reduction stats
# ---------------------------------------------------------------------------
def reduction_stats(original: str, filtered: str) -> dict:
    """Return token counts and reduction percentage."""
    orig_tokens = len(_TOKENIZE_RE.findall(original))
    filt_tokens = len(_TOKENIZE_RE.findall(filtered))
    reduction = (1 - filt_tokens / orig_tokens) * 100 if orig_tokens > 0 else 0.0
    return {
        "original_tokens": orig_tokens,
        "filtered_tokens": filt_tokens,
        "tokens_removed": orig_tokens - filt_tokens,
        "reduction_pct": round(reduction, 1),
    }


# ---------------------------------------------------------------------------
# Main: assertions verifying correctness
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Test 1: Filler phrase removal ---
    text_with_fillers = "Basically, in order to fix the bug, it should be noted that the parser fails."
    cleaned = _remove_filler_phrases(text_with_fillers)
    assert "basically" not in cleaned.lower(), f"Filler 'basically' not removed: {cleaned}"
    assert "in order to" not in cleaned.lower(), f"Filler 'in order to' not removed: {cleaned}"
    assert "it should be noted that" not in cleaned.lower(), f"Filler not removed: {cleaned}"
    assert "parser" in cleaned.lower(), f"Content word lost: {cleaned}"
    assert "bug" in cleaned.lower(), f"Content word lost: {cleaned}"
    print("[PASS] Test 1: Filler phrase removal")

    # --- Test 2: Stopword removal ---
    simple = "The quick brown fox jumps over the lazy dog"
    filtered = filter_low_entropy_tokens(simple, threshold=0.5, remove_stopwords=True)
    filtered_lower = filtered.lower()
    assert "quick" in filtered_lower, f"Content word 'quick' lost: {filtered}"
    assert "brown" in filtered_lower, f"Content word 'brown' lost: {filtered}"
    assert "fox" in filtered_lower, f"Content word 'fox' lost: {filtered}"
    assert "jumps" in filtered_lower, f"Content word 'jumps' lost: {filtered}"
    assert "lazy" in filtered_lower, f"Content word 'lazy' lost: {filtered}"
    assert "dog" in filtered_lower, f"Content word 'dog' lost: {filtered}"
    # Stopwords should be removed
    for sw in ["the", "over"]:
        assert sw not in filtered_lower.split(), f"Stopword '{sw}' not removed: {filtered}"
    print("[PASS] Test 2: Stopword removal preserves content words")

    # --- Test 3: Token reduction is measurable ---
    verbose = (
        "In order to actually understand the problem, it is worth noting that "
        "the system basically processes the data through the pipeline, and as "
        "mentioned earlier, the architecture is designed in terms of modularity "
        "and scalability, which is very important for the overall performance."
    )
    filtered_verbose = filter_low_entropy_tokens(verbose, threshold=1.0)
    stats = reduction_stats(verbose, filtered_verbose)
    assert stats["reduction_pct"] > 30, f"Expected >30% reduction, got {stats['reduction_pct']}%"
    assert stats["tokens_removed"] > 10, f"Expected >10 tokens removed, got {stats['tokens_removed']}"
    print(f"[PASS] Test 3: Token reduction {stats['reduction_pct']}% ({stats['tokens_removed']} tokens removed)")

    # --- Test 4: Entropy score computation ---
    repetitive = "the the the the the the the"
    diverse = "quantum neural cryptographic morphological serendipity ephemeral"
    score_rep = entropy_score(repetitive)
    score_div = entropy_score(diverse)
    assert score_div > score_rep, (
        f"Diverse text should have higher entropy: {score_div} vs {score_rep}"
    )
    print(f"[PASS] Test 4: Entropy scores — repetitive={score_rep:.2f}, diverse={score_div:.2f}")

    # --- Test 5: Empty / edge cases ---
    assert filter_low_entropy_tokens("") == ""
    assert filter_low_entropy_tokens("   ") == ""
    assert filter_low_entropy_tokens("hello") == "hello"
    print("[PASS] Test 5: Edge cases (empty, whitespace, single word)")

    # --- Test 6: token_entropy function ---
    freq = {"error": 2, "the": 100, "segfault": 1}
    total = 103
    e_the = token_entropy("the", freq, total)
    e_error = token_entropy("error", freq, total)
    e_segfault = token_entropy("segfault", freq, total)
    e_unseen = token_entropy("unprecedented", freq, total)
    assert e_the < e_error < e_segfault, (
        f"Expected the < error < segfault entropy: {e_the:.2f}, {e_error:.2f}, {e_segfault:.2f}"
    )
    assert e_unseen > e_segfault, (
        f"Unseen token should have highest entropy: {e_unseen:.2f} vs {e_segfault:.2f}"
    )
    print(f"[PASS] Test 6: token_entropy ordering correct")

    # --- Test 7: Batch filtering with shared corpus ---
    texts = [
        "The system encountered a critical segmentation fault in the parser module.",
        "The parser module failed with a segmentation fault during initialization.",
        "Please note that the initialization error was caused by the parser.",
    ]
    filtered_batch = filter_batch(texts, threshold=1.0)
    assert len(filtered_batch) == 3, f"Expected 3 results, got {len(filtered_batch)}"
    for i, ft in enumerate(filtered_batch):
        orig_count = len(_TOKENIZE_RE.findall(texts[i]))
        filt_count = len(_TOKENIZE_RE.findall(ft))
        assert filt_count < orig_count, f"Text {i}: no reduction ({orig_count} -> {filt_count})"
    print("[PASS] Test 7: Batch filtering reduces all texts")

    # --- Test 8: build_frequency_table ---
    ft = build_frequency_table(["hello world", "hello again"])
    assert ft["hello"] == 2, f"Expected hello=2, got {ft['hello']}"
    assert ft["world"] == 1, f"Expected world=1, got {ft['world']}"
    assert ft["again"] == 1, f"Expected again=1, got {ft['again']}"
    print("[PASS] Test 8: build_frequency_table correct")

    # --- Test 9: Preserve structure (newlines) ---
    multiline = "The error occurred.\nThe root cause is memory.\nThe fix is simple."
    filtered_ml = filter_low_entropy_tokens(multiline, threshold=0.5, preserve_structure=True)
    assert "\n" in filtered_ml, f"Newlines should be preserved: {filtered_ml}"
    assert "error" in filtered_ml.lower()
    assert "memory" in filtered_ml.lower()
    print("[PASS] Test 9: Structure preservation with newlines")

    # --- Test 10: High threshold keeps only rare tokens ---
    text = "The database connection pool exhausted all available sockets during peak traffic"
    high_thresh = filter_low_entropy_tokens(text, threshold=4.0)
    low_thresh = filter_low_entropy_tokens(text, threshold=0.1, remove_stopwords=False)
    high_count = len(_TOKENIZE_RE.findall(high_thresh))
    low_count = len(_TOKENIZE_RE.findall(low_thresh))
    assert high_count < low_count, (
        f"Higher threshold should keep fewer tokens: {high_count} vs {low_count}"
    )
    print(f"[PASS] Test 10: Threshold tuning works (high={high_count}, low={low_count} tokens)")

    print("\n=== All 10 assertions passed ===")
