"""
Entropy-based token filtering.

Removes low-information tokens from a token stream by computing per-token
Shannon entropy over character distributions.  Tokens whose entropy falls
below a configurable threshold are considered "low-information" (e.g.
repeated filler characters, padding, single-char tokens with no variety)
and are dropped.

Supports raw string tokens, dict-style token objects (with a configurable
text key), and batch filtering with statistics.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

Token = Union[str, Dict]


@dataclass
class FilterStats:
    """Statistics from a filtering pass."""
    total: int = 0
    kept: int = 0
    removed: int = 0
    removed_tokens: List[Tuple[str, float]] = field(default_factory=list)
    avg_entropy_kept: float = 0.0
    avg_entropy_removed: float = 0.0
    min_entropy: float = float("inf")
    max_entropy: float = 0.0

    @property
    def removal_rate(self) -> float:
        return self.removed / self.total if self.total else 0.0


def char_entropy(text: str) -> float:
    """Compute Shannon entropy (bits) of the character distribution in *text*.

    Returns 0.0 for empty or single-character strings.
    """
    if len(text) <= 1:
        return 0.0
    counts = Counter(text)
    total = len(text)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def bigram_entropy(text: str) -> float:
    """Compute Shannon entropy over character bigrams.

    Captures sequential structure that single-char entropy misses.
    Returns 0.0 when fewer than 2 characters.
    """
    if len(text) < 2:
        return 0.0
    bigrams = [text[i : i + 2] for i in range(len(text) - 1)]
    counts = Counter(bigrams)
    total = len(bigrams)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def normalized_entropy(text: str) -> float:
    """Entropy normalized to [0, 1] by dividing by log2(alphabet_size).

    1.0 = maximally diverse character usage; 0.0 = no diversity.
    """
    if len(text) <= 1:
        return 0.0
    unique = len(set(text))
    if unique <= 1:
        return 0.0
    max_ent = math.log2(unique)
    return char_entropy(text) / max_ent if max_ent > 0 else 0.0


class EntropyTokenFilter:
    """Filter tokens by information content using Shannon entropy.

    Parameters
    ----------
    threshold : float
        Minimum character entropy (bits) to keep a token.  Tokens below
        this value are removed.  Default 1.0 works well for English text
        (single repeated chars ~0.0, simple words ~2-3 bits).
    min_length : int
        Tokens shorter than this are auto-removed (they carry little info).
    text_key : str
        When tokens are dicts, use this key to extract the text.
    use_bigram : bool
        Also require bigram entropy >= threshold * bigram_weight.
    bigram_weight : float
        Multiplier applied to threshold for the bigram entropy check.
    stopwords : set or None
        Optional set of stopwords to always remove regardless of entropy.
    whitelist : set or None
        Tokens in this set are always kept regardless of entropy.
    """

    def __init__(
        self,
        threshold: float = 1.0,
        min_length: int = 1,
        text_key: str = "text",
        use_bigram: bool = False,
        bigram_weight: float = 0.5,
        stopwords: Optional[set] = None,
        whitelist: Optional[set] = None,
    ):
        if threshold < 0:
            raise ValueError("threshold must be non-negative")
        if min_length < 0:
            raise ValueError("min_length must be non-negative")
        self.threshold = threshold
        self.min_length = min_length
        self.text_key = text_key
        self.use_bigram = use_bigram
        self.bigram_weight = bigram_weight
        self.stopwords = stopwords or set()
        self.whitelist = whitelist or set()

    def _extract_text(self, token: Token) -> str:
        if isinstance(token, str):
            return token
        if isinstance(token, dict):
            return token.get(self.text_key, "")
        return str(token)

    def score(self, token: Token) -> float:
        """Return the character entropy of a token's text."""
        return char_entropy(self._extract_text(token))

    def score_detailed(self, token: Token) -> Dict[str, float]:
        """Return char entropy, bigram entropy, and normalized entropy."""
        text = self._extract_text(token)
        return {
            "char_entropy": char_entropy(text),
            "bigram_entropy": bigram_entropy(text),
            "normalized_entropy": normalized_entropy(text),
            "length": len(text),
        }

    def should_keep(self, token: Token) -> bool:
        """Decide whether a single token passes the entropy filter."""
        text = self._extract_text(token)

        # Whitelist override
        if text in self.whitelist:
            return True

        # Stopword removal
        if text.lower() in self.stopwords:
            return False

        # Length gate
        if len(text) < self.min_length:
            return False

        # Pure whitespace / punctuation-only
        stripped = text.strip()
        if not stripped:
            return False

        # Char entropy gate
        ent = char_entropy(text)
        if ent < self.threshold:
            return False

        # Optional bigram entropy gate
        if self.use_bigram:
            bg_ent = bigram_entropy(text)
            if bg_ent < self.threshold * self.bigram_weight:
                return False

        return True

    def filter(
        self, tokens: Sequence[Token], collect_stats: bool = False
    ) -> Union[List[Token], Tuple[List[Token], FilterStats]]:
        """Filter a sequence of tokens, removing low-entropy ones.

        Parameters
        ----------
        tokens : sequence of str or dict
            Token stream to filter.
        collect_stats : bool
            If True, return (filtered_tokens, FilterStats).

        Returns
        -------
        list or (list, FilterStats)
        """
        kept: List[Token] = []
        stats = FilterStats() if collect_stats else None

        kept_entropies: List[float] = []
        removed_entropies: List[float] = []

        for token in tokens:
            text = self._extract_text(token)
            ent = char_entropy(text)

            if stats:
                stats.total += 1
                stats.min_entropy = min(stats.min_entropy, ent)
                stats.max_entropy = max(stats.max_entropy, ent)

            if self.should_keep(token):
                kept.append(token)
                if stats:
                    stats.kept += 1
                    kept_entropies.append(ent)
            else:
                if stats:
                    stats.removed += 1
                    stats.removed_tokens.append((text, round(ent, 4)))
                    removed_entropies.append(ent)

        if stats:
            if stats.total == 0:
                stats.min_entropy = 0.0
            stats.avg_entropy_kept = (
                sum(kept_entropies) / len(kept_entropies) if kept_entropies else 0.0
            )
            stats.avg_entropy_removed = (
                sum(removed_entropies) / len(removed_entropies)
                if removed_entropies
                else 0.0
            )
            return kept, stats

        return kept

    def filter_text(
        self,
        text: str,
        pattern: Optional[str] = None,
        join_str: str = " ",
    ) -> str:
        """Tokenize text by regex pattern, filter, and rejoin.

        Parameters
        ----------
        text : str
            Raw text to filter.
        pattern : str or None
            Regex for tokenization.  Defaults to whitespace splitting.
        join_str : str
            String used to rejoin kept tokens.
        """
        if pattern:
            tokens = re.findall(pattern, text)
        else:
            tokens = text.split()
        return join_str.join(self.filter(tokens))

    def batch_filter(
        self, token_batches: Sequence[Sequence[Token]]
    ) -> List[Tuple[List[Token], FilterStats]]:
        """Filter multiple token sequences and return results with stats."""
        return [self.filter(batch, collect_stats=True) for batch in token_batches]


if __name__ == "__main__":
    # ---- char_entropy tests ----
    assert char_entropy("") == 0.0, "empty string should be 0"
    assert char_entropy("a") == 0.0, "single char should be 0"
    assert char_entropy("aaaa") == 0.0, "repeated single char should be 0"
    assert abs(char_entropy("ab") - 1.0) < 1e-9, "two equally likely chars = 1 bit"
    assert abs(char_entropy("aabb") - 1.0) < 1e-9, "balanced 2-char = 1 bit"
    ent_abc = char_entropy("abc")
    assert abs(ent_abc - math.log2(3)) < 1e-9, "3 unique equiprobable chars"
    print("[char_entropy] all assertions passed")

    # ---- bigram_entropy tests ----
    assert bigram_entropy("") == 0.0
    assert bigram_entropy("a") == 0.0
    assert bigram_entropy("aa") == 0.0, "single bigram type = 0 bits"
    assert bigram_entropy("ab") == 0.0, "single bigram = 0 bits"
    assert abs(bigram_entropy("aba") - 1.0) < 1e-9, "two bigrams equally likely"
    print("[bigram_entropy] all assertions passed")

    # ---- normalized_entropy tests ----
    assert normalized_entropy("") == 0.0
    assert normalized_entropy("aaa") == 0.0
    ne_ab = normalized_entropy("ab")
    assert abs(ne_ab - 1.0) < 1e-9, "2 unique chars, balanced = 1.0"
    print("[normalized_entropy] all assertions passed")

    # ---- EntropyTokenFilter with string tokens ----
    f = EntropyTokenFilter(threshold=1.0, min_length=2)
    tokens = ["hello", "world", "aa", "aaaa", "x", "", "  ", "ab", "the"]
    result = f.filter(tokens)
    # "aa" and "aaaa" have 0 entropy -> removed
    # "x" too short -> removed
    # "" too short -> removed
    # "  " whitespace only -> removed
    # "ab" has entropy 1.0 which is NOT < 1.0 so it stays
    assert "hello" in result, f"'hello' should be kept, got {result}"
    assert "world" in result, f"'world' should be kept"
    assert "aa" not in result, "'aa' should be removed (0 entropy)"
    assert "aaaa" not in result, "'aaaa' should be removed (0 entropy)"
    assert "x" not in result, "'x' should be removed (too short)"
    assert "" not in result, "empty should be removed"
    assert "  " not in result, "whitespace should be removed"
    assert "ab" in result, "'ab' has entropy=1.0 which meets threshold"
    assert "the" in result, "'the' should be kept (entropy > 1.0)"
    print("[filter strings] all assertions passed")

    # ---- Filter with stats ----
    result, stats = f.filter(tokens, collect_stats=True)
    assert stats.total == len(tokens)
    assert stats.kept == len(result)
    assert stats.removed == stats.total - stats.kept
    assert stats.removal_rate == stats.removed / stats.total
    assert stats.min_entropy >= 0.0
    assert stats.max_entropy >= stats.min_entropy
    assert len(stats.removed_tokens) == stats.removed
    print(f"[filter stats] kept={stats.kept}, removed={stats.removed}, "
          f"rate={stats.removal_rate:.2%}")
    print("[filter stats] all assertions passed")

    # ---- Filter with dict tokens ----
    dict_tokens = [
        {"text": "hello", "logprob": -0.1},
        {"text": "aaaa", "logprob": -0.5},
        {"text": "world", "logprob": -0.2},
        {"text": "zz", "logprob": -3.0},
        {"text": "diverse", "logprob": -0.3},
    ]
    f2 = EntropyTokenFilter(threshold=1.0, min_length=2, text_key="text")
    result2 = f2.filter(dict_tokens)
    kept_texts = [t["text"] for t in result2]
    assert "hello" in kept_texts
    assert "world" in kept_texts
    assert "diverse" in kept_texts
    assert "aaaa" not in kept_texts, "'aaaa' is low entropy"
    assert "zz" not in kept_texts, "'zz' is low entropy"
    print("[filter dicts] all assertions passed")

    # ---- Stopwords ----
    f3 = EntropyTokenFilter(threshold=0.5, min_length=1, stopwords={"the", "a", "is"})
    sw_result = f3.filter(["the", "cat", "is", "a", "diverse", "animal"])
    assert "the" not in sw_result
    assert "is" not in sw_result
    assert "a" not in sw_result
    assert "cat" in sw_result
    assert "diverse" in sw_result
    print("[stopwords] all assertions passed")

    # ---- Whitelist ----
    f4 = EntropyTokenFilter(threshold=5.0, whitelist={"ok"})
    wl_result = f4.filter(["ok", "hello", "aaaa"])
    assert "ok" in wl_result, "whitelisted token must be kept"
    # "hello" entropy ~2.32, below threshold 5.0, so removed
    assert "hello" not in wl_result
    print("[whitelist] all assertions passed")

    # ---- Bigram mode ----
    f5 = EntropyTokenFilter(threshold=0.5, min_length=2, use_bigram=True, bigram_weight=0.5)
    bg_result = f5.filter(["aab", "hello", "aaaa"])
    assert "hello" in bg_result, "diverse text should pass bigram"
    assert "aaaa" not in bg_result, "no bigram diversity"
    print("[bigram mode] all assertions passed")

    # ---- filter_text ----
    f6 = EntropyTokenFilter(threshold=1.0, min_length=2)
    text_in = "the quick brown fox jumps over aaaa aaaa the lazy dog"
    text_out = f6.filter_text(text_in)
    assert "aaaa" not in text_out, "repeated low-entropy token removed from text"
    assert "quick" in text_out
    assert "brown" in text_out
    print(f"[filter_text] '{text_out}'")
    print("[filter_text] all assertions passed")

    # ---- batch_filter ----
    batches = [
        ["hello", "aaaa", "world"],
        ["diverse", "zz", "tokens", "here"],
    ]
    batch_results = f6.batch_filter(batches)
    assert len(batch_results) == 2
    for filtered, st in batch_results:
        assert st.total > 0
        assert st.kept + st.removed == st.total
    print("[batch_filter] all assertions passed")

    # ---- score / score_detailed ----
    f7 = EntropyTokenFilter()
    s = f7.score("hello")
    assert s > 0, "non-trivial string should have positive entropy"
    sd = f7.score_detailed("hello")
    assert "char_entropy" in sd
    assert "bigram_entropy" in sd
    assert "normalized_entropy" in sd
    assert "length" in sd
    assert sd["length"] == 5
    assert sd["char_entropy"] == s
    print("[score_detailed] all assertions passed")

    # ---- Edge: empty input ----
    assert f7.filter([]) == []
    assert f7.filter_text("") == ""
    print("[edge: empty] all assertions passed")

    # ---- Threshold 0 keeps everything with length >= min_length ----
    f8 = EntropyTokenFilter(threshold=0.0, min_length=1)
    all_kept = f8.filter(["a", "bb", "ccc"])
    assert len(all_kept) == 3, "threshold=0 should keep all non-empty tokens"
    print("[threshold=0] all assertions passed")

    # ---- Validation ----
    try:
        EntropyTokenFilter(threshold=-1)
        assert False, "negative threshold should raise"
    except ValueError:
        pass

    try:
        EntropyTokenFilter(min_length=-1)
        assert False, "negative min_length should raise"
    except ValueError:
        pass
    print("[validation] all assertions passed")

    print("\nAll assertions passed.")
