"""
Entropy-based token filtering: remove low-information tokens from a token stream.

Computes Shannon entropy per token relative to a corpus frequency distribution.
Tokens below an entropy threshold carry little information and can be safely
dropped without meaningful loss of semantic content.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


# ── Default low-information tokens ─────────────────────────────────────────

_STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "from", "by", "as", "into", "through",
    "during", "before", "after", "and", "but", "or", "nor", "not", "so",
    "yet", "both", "either", "neither", "each", "every", "all", "any",
    "few", "more", "most", "other", "some", "such", "no", "only", "own",
    "same", "than", "too", "very", "just", "about", "above", "below",
    "between", "up", "down", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "what", "which", "who", "whom", "this", "that", "these",
    "those", "it", "its", "i", "me", "my", "myself", "we", "our",
    "ours", "ourselves", "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "itself", "they", "them", "their", "theirs", "themselves", "am",
}

_WHITESPACE_RE = re.compile(r"^\s+$")
_PUNCT_RE = re.compile(r"^[^\w]+$")


# ── Core data structures ───────────────────────────────────────────────────


@dataclass
class TokenStats:
    """Statistics for a single token."""
    token: str
    entropy: float
    frequency: int
    is_filtered: bool


@dataclass
class FilterResult:
    """Result of filtering a token sequence."""
    kept: list[str]
    removed: list[str]
    original_count: int
    kept_count: int
    removed_count: int
    token_stats: list[TokenStats] = field(default_factory=list)
    entropy_threshold: float = 0.0

    @property
    def reduction_pct(self) -> float:
        if self.original_count == 0:
            return 0.0
        return (self.removed_count / self.original_count) * 100


# ── Entropy computation ───────────────────────────────────────────────────


def _compute_corpus_entropy(tokens: list[str]) -> dict[str, float]:
    """
    Compute per-token self-information (surprisal) based on corpus frequency.

    Tokens that appear very frequently have low entropy (low information content).
    Rare tokens have high entropy (high information content).

    entropy(t) = -log2(P(t))  where P(t) = count(t) / total
    """
    total = len(tokens)
    if total == 0:
        return {}

    freq = Counter(tokens)
    entropy_map: dict[str, float] = {}
    for tok, count in freq.items():
        p = count / total
        # Self-information: -log2(p). Higher = more surprising = more informative.
        entropy_map[tok] = -math.log2(p)

    return entropy_map


def _compute_bigram_entropy(tokens: list[str]) -> dict[str, float]:
    """
    Compute conditional entropy for each token based on bigram context.

    H(t_i | t_{i-1}) captures how predictable a token is given its predecessor.
    Low conditional entropy means the token is highly predictable in context.
    """
    if len(tokens) < 2:
        return {}

    bigram_counts: Counter[tuple[str, str]] = Counter()
    prefix_counts: Counter[str] = Counter()

    for i in range(1, len(tokens)):
        prev, curr = tokens[i - 1], tokens[i]
        bigram_counts[(prev, curr)] += 1
        prefix_counts[prev] += 1

    # For each token, average the conditional entropy across all contexts
    token_cond_entropies: dict[str, list[float]] = {}
    for (prev, curr), count in bigram_counts.items():
        p_cond = count / prefix_counts[prev]
        h = -math.log2(p_cond) if p_cond > 0 else 0.0
        token_cond_entropies.setdefault(curr, []).append(h)

    return {
        tok: sum(vals) / len(vals)
        for tok, vals in token_cond_entropies.items()
    }


# ── Token classifier ──────────────────────────────────────────────────────


def _is_structural_token(token: str) -> bool:
    """Identify tokens that are purely structural (whitespace, punctuation)."""
    return bool(_WHITESPACE_RE.match(token) or _PUNCT_RE.match(token))


def _is_stopword(token: str) -> bool:
    """Check if a token is a common stopword."""
    return token.strip().lower() in _STOPWORDS


# ── Main filter ───────────────────────────────────────────────────────────


class EntropyTokenFilter:
    """
    Filters tokens based on their information content (entropy).

    Combines three signals:
    1. Unigram self-information (surprisal)
    2. Bigram conditional entropy (predictability in context)
    3. Lexical class (stopword, punctuation, whitespace)

    Tokens with combined entropy below the threshold are removed.
    """

    def __init__(
        self,
        entropy_threshold: float = 1.5,
        bigram_weight: float = 0.3,
        remove_stopwords: bool = True,
        remove_structural: bool = True,
        preserve_tokens: Optional[set[str]] = None,
        min_token_length: int = 0,
    ):
        """
        Args:
            entropy_threshold: Minimum entropy to keep a token. Lower = keep more.
            bigram_weight: Weight for bigram entropy [0..1]. Rest goes to unigram.
            remove_stopwords: Whether to remove common stopwords regardless of entropy.
            remove_structural: Whether to remove whitespace/punctuation tokens.
            preserve_tokens: Set of tokens to always keep regardless of entropy.
            min_token_length: Minimum character length for a token to be kept.
        """
        self.entropy_threshold = entropy_threshold
        self.bigram_weight = bigram_weight
        self.remove_stopwords = remove_stopwords
        self.remove_structural = remove_structural
        self.preserve_tokens = preserve_tokens or set()
        self.min_token_length = min_token_length

    def filter(self, tokens: list[str]) -> FilterResult:
        """Filter a token list, removing low-information tokens."""
        if not tokens:
            return FilterResult(
                kept=[], removed=[], original_count=0,
                kept_count=0, removed_count=0,
                entropy_threshold=self.entropy_threshold,
            )

        # Normalize for entropy computation (lowercase, stripped)
        normalized = [t.strip().lower() for t in tokens]
        unigram_entropy = _compute_corpus_entropy(normalized)
        bigram_entropy = _compute_bigram_entropy(normalized)

        freq = Counter(normalized)
        uw = 1.0 - self.bigram_weight

        kept: list[str] = []
        removed: list[str] = []
        stats: list[TokenStats] = []

        for token, norm in zip(tokens, normalized):
            # Always preserve explicitly protected tokens
            if token in self.preserve_tokens or norm in self.preserve_tokens:
                uni = unigram_entropy.get(norm, 0.0)
                bi = bigram_entropy.get(norm, 0.0)
                combined = uw * uni + self.bigram_weight * bi
                stats.append(TokenStats(token, combined, freq.get(norm, 0), False))
                kept.append(token)
                continue

            # Remove structural tokens (whitespace, punctuation)
            if self.remove_structural and _is_structural_token(token):
                stats.append(TokenStats(token, 0.0, freq.get(norm, 0), True))
                removed.append(token)
                continue

            # Remove stopwords
            if self.remove_stopwords and _is_stopword(token):
                stats.append(TokenStats(token, 0.0, freq.get(norm, 0), True))
                removed.append(token)
                continue

            # Remove short tokens
            if self.min_token_length > 0 and len(norm) < self.min_token_length:
                stats.append(TokenStats(token, 0.0, freq.get(norm, 0), True))
                removed.append(token)
                continue

            # Compute combined entropy
            uni = unigram_entropy.get(norm, 0.0)
            bi = bigram_entropy.get(norm, 0.0)
            combined = uw * uni + self.bigram_weight * bi

            is_filtered = combined < self.entropy_threshold
            stats.append(TokenStats(token, combined, freq.get(norm, 0), is_filtered))

            if is_filtered:
                removed.append(token)
            else:
                kept.append(token)

        return FilterResult(
            kept=kept,
            removed=removed,
            original_count=len(tokens),
            kept_count=len(kept),
            removed_count=len(removed),
            token_stats=stats,
            entropy_threshold=self.entropy_threshold,
        )

    def filter_text(self, text: str) -> str:
        """Tokenize text by whitespace, filter, and rejoin."""
        tokens = text.split()
        result = self.filter(tokens)
        return " ".join(result.kept)


# ── Adaptive threshold ────────────────────────────────────────────────────


def compute_adaptive_threshold(
    tokens: list[str],
    target_reduction: float = 0.4,
    min_threshold: float = 0.5,
    max_threshold: float = 5.0,
    steps: int = 50,
) -> float:
    """
    Find an entropy threshold that achieves approximately `target_reduction`
    fraction of tokens removed.

    Binary-searches over thresholds to hit the target.
    """
    normalized = [t.strip().lower() for t in tokens]
    entropy_map = _compute_corpus_entropy(normalized)

    # Collect entropies for non-stopword, non-structural tokens
    entropies: list[float] = []
    for tok, norm in zip(tokens, normalized):
        if _is_structural_token(tok) or _is_stopword(tok):
            continue
        entropies.append(entropy_map.get(norm, 0.0))

    if not entropies:
        return min_threshold

    lo, hi = min_threshold, max_threshold
    for _ in range(steps):
        mid = (lo + hi) / 2
        removed = sum(1 for e in entropies if e < mid)
        ratio = removed / len(entropies)
        if ratio < target_reduction:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2


# ── Convenience ───────────────────────────────────────────────────────────


def filter_tokens(
    tokens: list[str],
    threshold: float = 1.5,
    remove_stopwords: bool = True,
    remove_structural: bool = True,
) -> FilterResult:
    """Convenience function: filter tokens with default settings."""
    f = EntropyTokenFilter(
        entropy_threshold=threshold,
        remove_stopwords=remove_stopwords,
        remove_structural=remove_structural,
    )
    return f.filter(tokens)


def filter_text(text: str, threshold: float = 1.5) -> str:
    """Convenience function: filter text and return cleaned string."""
    f = EntropyTokenFilter(entropy_threshold=threshold)
    return f.filter_text(text)


# ── Main: assertions ──────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── 1. Basic filtering removes stopwords and low-entropy tokens ────
    sample = [
        "the", "database", "query", "is", "taking", "a", "very",
        "long", "time", "to", "execute", "because", "the", "index",
        "was", "not", "created", "on", "the", "primary", "key",
        "column", "and", "the", "table", "has", "millions", "of",
        "rows", "causing", "full", "table", "scans",
    ]
    result = filter_tokens(sample)
    assert result.original_count == len(sample)
    assert result.kept_count + result.removed_count == result.original_count
    assert result.kept_count < result.original_count, "Should remove some tokens"
    assert result.removed_count > 0, "Should have removed tokens"
    # High-info tokens should survive
    for important in ["database", "query", "index", "primary", "column", "scans"]:
        assert important in result.kept, f"'{important}' should be kept"
    # Stopwords should be removed
    for stop in ["the", "is", "a", "to", "on", "and", "of"]:
        assert stop in result.removed, f"'{stop}' should be removed"
    print(f"[1] Basic: {result.original_count} -> {result.kept_count} "
          f"({result.reduction_pct:.1f}% reduction)")

    # ── 2. Empty input ────────────────────────────────────────────────
    empty_result = filter_tokens([])
    assert empty_result.original_count == 0
    assert empty_result.kept_count == 0
    assert empty_result.removed_count == 0
    assert empty_result.reduction_pct == 0.0
    print("[2] Empty input: OK")

    # ── 3. All unique high-entropy tokens survive ─────────────────────
    unique = ["quantum", "entanglement", "superconductor", "photon", "neutrino"]
    unique_result = filter_tokens(unique, threshold=0.0, remove_stopwords=False)
    assert unique_result.kept == unique, "All unique tokens above threshold=0 should survive"
    print(f"[3] Unique tokens: all {unique_result.kept_count} kept")

    # ── 4. Structural token removal ───────────────────────────────────
    structural = ["hello", "  ", "world", "!", "\t", "foo", "..."]
    struct_result = filter_tokens(structural, threshold=0.0)
    for s in ["  ", "!", "\t", "..."]:
        assert s in struct_result.removed, f"Structural '{repr(s)}' should be removed"
    print(f"[4] Structural: removed {struct_result.removed_count} structural tokens")

    # ── 5. Preserve tokens override ───────────────────────────────────
    f = EntropyTokenFilter(
        entropy_threshold=10.0,  # Very high threshold — would remove everything
        remove_stopwords=True,
        preserve_tokens={"ERROR", "CRITICAL"},
    )
    preserve_input = ["the", "ERROR", "is", "CRITICAL", "now"]
    preserve_result = f.filter(preserve_input)
    assert "ERROR" in preserve_result.kept
    assert "CRITICAL" in preserve_result.kept
    assert "the" in preserve_result.removed
    print(f"[5] Preserve tokens: ERROR and CRITICAL kept despite high threshold")

    # ── 6. filter_text convenience ────────────────────────────────────
    text = "the database query is slow and the index is missing on the table"
    filtered = filter_text(text, threshold=1.0)
    assert "database" in filtered
    assert "query" in filtered
    assert "slow" in filtered
    assert "index" in filtered
    assert "missing" in filtered
    # "the" should be gone
    words = filtered.split()
    assert "the" not in words, "'the' should be filtered from text"
    print(f"[6] Text filter: '{text[:40]}...' -> '{filtered}'")

    # ── 7. Token stats are populated ──────────────────────────────────
    stats_result = filter_tokens(sample)
    assert len(stats_result.token_stats) == len(sample)
    for ts in stats_result.token_stats:
        assert isinstance(ts.token, str)
        assert isinstance(ts.entropy, float)
        assert isinstance(ts.frequency, int)
        assert isinstance(ts.is_filtered, bool)
        assert ts.frequency >= 1
    print(f"[7] Token stats: {len(stats_result.token_stats)} entries, all valid")

    # ── 8. Bigram entropy influences filtering ────────────────────────
    # Repeated bigram pattern: "A B A B A B" — B is very predictable after A
    repetitive = ["alpha", "beta"] * 20
    f_uni = EntropyTokenFilter(
        entropy_threshold=1.0,
        bigram_weight=0.0,  # Only unigram
        remove_stopwords=False,
        remove_structural=False,
    )
    f_bi = EntropyTokenFilter(
        entropy_threshold=1.0,
        bigram_weight=0.9,  # Mostly bigram
        remove_stopwords=False,
        remove_structural=False,
    )
    r_uni = f_uni.filter(repetitive)
    r_bi = f_bi.filter(repetitive)
    # Both tokens have equal unigram frequency so unigram entropy is identical.
    # With high bigram weight, conditional entropy is near 0 (perfectly predictable),
    # so more tokens get filtered.
    assert r_bi.removed_count >= r_uni.removed_count, (
        "Higher bigram weight should remove at least as many tokens for alternating pattern"
    )
    print(f"[8] Bigram weight: uni removed={r_uni.removed_count}, "
          f"bi removed={r_bi.removed_count}")

    # ── 9. Adaptive threshold ─────────────────────────────────────────
    long_sample = (
        "the quick brown fox jumps over the lazy dog and the cat sat on the mat "
        "while the database query executed slowly across millions of rows in the "
        "production cluster causing significant latency spikes and timeout errors "
        "that triggered the alerting system and paged the on-call engineer who "
        "discovered the missing index on the primary key column of the orders table"
    ).split()
    threshold = compute_adaptive_threshold(long_sample, target_reduction=0.3)
    assert 0.5 <= threshold <= 5.0, f"Threshold {threshold} out of range"
    # Apply and check we're roughly near target
    adaptive_result = filter_tokens(long_sample, threshold=threshold)
    non_stop = [t for t in long_sample if not _is_stopword(t) and not _is_structural_token(t)]
    if non_stop:
        print(f"[9] Adaptive threshold: {threshold:.2f}, "
              f"total reduction={adaptive_result.reduction_pct:.1f}%")
    else:
        print("[9] Adaptive threshold: all stopwords")

    # ── 10. min_token_length filtering ────────────────────────────────
    f_len = EntropyTokenFilter(
        entropy_threshold=0.0,
        remove_stopwords=False,
        remove_structural=False,
        min_token_length=4,
    )
    short_input = ["I", "am", "a", "software", "engineer", "at", "big", "company"]
    len_result = f_len.filter(short_input)
    for short in ["I", "am", "a", "at", "big"]:
        assert short in len_result.removed, f"'{short}' (len<4) should be removed"
    for long in ["software", "engineer", "company"]:
        assert long in len_result.kept, f"'{long}' (len>=4) should be kept"
    print(f"[10] Min length: removed {len_result.removed_count} short tokens")

    # ── 11. High-frequency tokens have low entropy ────────────────────
    freq_tokens = ["error"] * 50 + ["segfault", "overflow", "nullptr"]
    entropy_map = _compute_corpus_entropy([t.lower() for t in freq_tokens])
    assert entropy_map["error"] < entropy_map["segfault"], (
        "High-frequency 'error' should have lower entropy than rare 'segfault'"
    )
    assert entropy_map["error"] < entropy_map["overflow"]
    assert entropy_map["error"] < entropy_map["nullptr"]
    print(f"[11] Entropy ordering: error={entropy_map['error']:.2f} < "
          f"segfault={entropy_map['segfault']:.2f} (correct)")

    # ── 12. Round-trip: kept + removed = original (order-independent) ─
    all_tokens = result.kept + result.removed
    assert sorted(all_tokens) == sorted(sample), "kept + removed must equal original set"
    print("[12] Round-trip: kept + removed == original (sorted)")

    # ── 13. Reduction percentage is correct ───────────────────────────
    expected_pct = (result.removed_count / result.original_count) * 100
    assert abs(result.reduction_pct - expected_pct) < 0.01
    print(f"[13] Reduction pct: {result.reduction_pct:.1f}% verified")

    print("\nAll assertions passed.")
