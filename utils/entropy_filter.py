"""
Entropy-based token filtering.

Removes low-information tokens from a token stream using multiple
entropy signals:
  1. Character entropy — Shannon entropy over character distribution
  2. Bigram entropy — entropy over character bigrams (sequential structure)
  3. Corpus entropy — self-information (-log2 P(token)) given corpus frequencies

Tokens scoring below configurable thresholds are dropped.

Supports raw string tokens, dict-style token objects, batch filtering,
filler phrase removal, and combined multi-signal scoring.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

Token = Union[str, Dict]

# ---- Default stopwords (English) ----
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

# ---- Filler phrases (near-zero information) ----
FILLER_PHRASES = [
    r"\bbasically\b", r"\bactually\b", r"\bin order to\b",
    r"\bat the end of the day\b", r"\bit is worth noting that\b",
    r"\bit should be noted that\b", r"\bas a matter of fact\b",
    r"\bneedless to say\b", r"\bin terms of\b", r"\bwith respect to\b",
    r"\bfor what it'?s worth\b", r"\bin this case\b",
    r"\bas mentioned (?:earlier|above|before|previously)\b",
    r"\bplease note that\b", r"\bkindly note that\b",
    r"\bas you can see\b", r"\bas we know\b",
]

_FILLER_RE = re.compile("|".join(FILLER_PHRASES), re.IGNORECASE)
_TOKENIZE_RE = re.compile(r"[a-zA-Z0-9_]+(?:'[a-z]+)?|[^\s]")


# ---------------------------------------------------------------------------
# Low-level entropy functions
# ---------------------------------------------------------------------------

def char_entropy(text: str) -> float:
    """Shannon entropy (bits) of the character distribution in *text*."""
    if len(text) <= 1:
        return 0.0
    counts = Counter(text)
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)


def bigram_entropy(text: str) -> float:
    """Shannon entropy over character bigrams."""
    if len(text) < 2:
        return 0.0
    bigrams = [text[i:i + 2] for i in range(len(text) - 1)]
    counts = Counter(bigrams)
    total = len(bigrams)
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)


def normalized_entropy(text: str) -> float:
    """Entropy normalized to [0, 1] by dividing by log2(alphabet_size)."""
    if len(text) <= 1:
        return 0.0
    unique = len(set(text))
    if unique <= 1:
        return 0.0
    max_ent = math.log2(unique)
    return char_entropy(text) / max_ent if max_ent > 0 else 0.0


def corpus_entropy(token: str, freq: Dict[str, int], total: int) -> float:
    """Self-information: -log2(P(token)). Higher = more surprising/informative."""
    count = freq.get(token.lower(), 0)
    if count == 0:
        return math.log2(total + 1)
    return -math.log2(count / total)


# ---------------------------------------------------------------------------
# Statistics dataclass
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Frequency table builder
# ---------------------------------------------------------------------------

def build_frequency_table(texts: List[str]) -> Dict[str, int]:
    """Build a token frequency table from a list of texts."""
    freq: Counter = Counter()
    for text in texts:
        freq.update(t.lower() for t in _TOKENIZE_RE.findall(text))
    return dict(freq)


# ---------------------------------------------------------------------------
# Main filter class
# ---------------------------------------------------------------------------

class EntropyTokenFilter:
    """Filter tokens by information content using multiple entropy signals.

    Parameters
    ----------
    threshold : float
        Minimum character entropy (bits) to keep a token. Default 1.0.
    min_length : int
        Tokens shorter than this are auto-removed.
    text_key : str
        Key for extracting text from dict tokens.
    use_bigram : bool
        Also enforce bigram entropy >= threshold * bigram_weight.
    bigram_weight : float
        Multiplier for bigram entropy check.
    use_corpus : bool
        Use corpus-frequency self-information as an additional signal.
    corpus_freq : dict or None
        Pre-built {token: count} table. If None and use_corpus=True,
        frequencies are computed from the input batch.
    corpus_threshold : float
        Minimum self-information (bits) when corpus mode is active.
    stopwords : set or None
        Tokens always removed regardless of entropy.
    whitelist : set or None
        Tokens always kept regardless of entropy.
    remove_fillers : bool
        Strip known filler phrases from text before filtering.
    """

    def __init__(
        self,
        threshold: float = 1.0,
        min_length: int = 1,
        text_key: str = "text",
        use_bigram: bool = False,
        bigram_weight: float = 0.5,
        use_corpus: bool = False,
        corpus_freq: Optional[Dict[str, int]] = None,
        corpus_threshold: float = 2.0,
        stopwords: Optional[set] = None,
        whitelist: Optional[set] = None,
        remove_fillers: bool = False,
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
        self.use_corpus = use_corpus
        self.corpus_freq = corpus_freq
        self.corpus_threshold = corpus_threshold
        self.stopwords = stopwords or set()
        self.whitelist = whitelist or set()
        self.remove_fillers = remove_fillers
        self._corpus_total: int = sum(corpus_freq.values()) if corpus_freq else 0

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
        """Return all entropy signals for a token."""
        text = self._extract_text(token)
        result = {
            "char_entropy": char_entropy(text),
            "bigram_entropy": bigram_entropy(text),
            "normalized_entropy": normalized_entropy(text),
            "length": float(len(text)),
        }
        if self.use_corpus and self.corpus_freq:
            result["corpus_entropy"] = corpus_entropy(text, self.corpus_freq, self._corpus_total)
        return result

    def should_keep(self, token: Token) -> bool:
        """Decide whether a single token passes all entropy gates."""
        text = self._extract_text(token)

        if text in self.whitelist:
            return True
        if text.lower() in self.stopwords:
            return False
        if len(text) < self.min_length:
            return False

        stripped = text.strip()
        if not stripped:
            return False

        # Character entropy gate
        ent = char_entropy(text)
        if ent < self.threshold:
            return False

        # Bigram entropy gate
        if self.use_bigram:
            if bigram_entropy(text) < self.threshold * self.bigram_weight:
                return False

        # Corpus self-information gate
        if self.use_corpus and self.corpus_freq:
            if corpus_entropy(text, self.corpus_freq, self._corpus_total) < self.corpus_threshold:
                return False

        return True

    def filter(
        self, tokens: Sequence[Token], collect_stats: bool = False
    ) -> Union[List[Token], Tuple[List[Token], FilterStats]]:
        """Filter a sequence of tokens, removing low-entropy ones."""
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
                if removed_entropies else 0.0
            )
            return kept, stats

        return kept

    def filter_text(
        self,
        text: str,
        pattern: Optional[str] = None,
        join_str: str = " ",
    ) -> str:
        """Tokenize text by regex, filter, rejoin. Optionally strips fillers first."""
        if not text or not text.strip():
            return text.strip() if text else ""

        working = text
        if self.remove_fillers:
            working = _remove_filler_phrases(working)

        if pattern:
            tokens = re.findall(pattern, working)
        else:
            tokens = working.split()
        return join_str.join(self.filter(tokens))

    def batch_filter(
        self, token_batches: Sequence[Sequence[Token]]
    ) -> List[Tuple[List[Token], FilterStats]]:
        """Filter multiple token sequences with stats."""
        return [self.filter(batch, collect_stats=True) for batch in token_batches]


# ---------------------------------------------------------------------------
# Text-level filtering (convenience)
# ---------------------------------------------------------------------------

def _remove_filler_phrases(text: str) -> str:
    result = _FILLER_RE.sub("", text)
    result = re.sub(r"  +", " ", result)
    return result.strip()


def _is_punctuation(token: str) -> bool:
    return len(token) == 1 and not token.isalnum()


def filter_low_entropy_tokens(
    text: str,
    threshold: float = 1.0,
    corpus_freq: Optional[Dict[str, int]] = None,
    preserve_structure: bool = True,
    remove_stopwords: bool = True,
    remove_fillers: bool = True,
) -> str:
    """Filter low-information tokens from text.

    Combines stopword removal, filler phrase removal, and entropy-based
    scoring (self-information given corpus frequencies) into one pass.
    """
    if not text or not text.strip():
        return text.strip() if text else text

    working = text
    if remove_fillers:
        working = _remove_filler_phrases(working)

    tokens_raw = _TOKENIZE_RE.findall(working)
    if not tokens_raw:
        return working

    if corpus_freq is None:
        freq = Counter(t.lower() for t in tokens_raw)
        for sw in DEFAULT_STOPWORDS:
            freq[sw] = freq.get(sw, 0) + len(tokens_raw)
        total = sum(freq.values())
    else:
        freq = corpus_freq
        total = sum(freq.values())

    lines = working.split("\n")
    filtered_lines = []

    for line in lines:
        line_tokens = _TOKENIZE_RE.findall(line)
        kept = []
        for tok in line_tokens:
            if preserve_structure and _is_punctuation(tok):
                kept.append(tok)
                continue
            tok_lower = tok.lower()
            if remove_stopwords and tok_lower in DEFAULT_STOPWORDS:
                continue
            score = corpus_entropy(tok_lower, freq, total)
            if score >= threshold:
                kept.append(tok)
        filtered_line = " ".join(kept)
        filtered_line = re.sub(r"\s+([.,;:!?])", r"\1", filtered_line)
        filtered_lines.append(filtered_line)

    result = "\n".join(filtered_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def filter_batch(
    texts: List[str],
    threshold: float = 1.0,
    remove_stopwords: bool = True,
    remove_fillers: bool = True,
) -> List[str]:
    """Filter multiple texts using a shared frequency table."""
    freq = build_frequency_table(texts)
    total_tokens = sum(freq.values())
    for sw in DEFAULT_STOPWORDS:
        freq[sw] = freq.get(sw, 0) + total_tokens
    return [
        filter_low_entropy_tokens(
            t, threshold=threshold, corpus_freq=freq,
            remove_stopwords=remove_stopwords, remove_fillers=remove_fillers,
        )
        for t in texts
    ]


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
# __main__: assertions verifying correctness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # ==== Character entropy ====
    assert char_entropy("") == 0.0
    assert char_entropy("a") == 0.0
    assert char_entropy("aaaa") == 0.0
    assert abs(char_entropy("ab") - 1.0) < 1e-9
    assert abs(char_entropy("aabb") - 1.0) < 1e-9
    assert abs(char_entropy("abc") - math.log2(3)) < 1e-9
    print("[PASS] char_entropy")

    # ==== Bigram entropy ====
    assert bigram_entropy("") == 0.0
    assert bigram_entropy("a") == 0.0
    assert bigram_entropy("aa") == 0.0
    assert bigram_entropy("ab") == 0.0
    assert abs(bigram_entropy("aba") - 1.0) < 1e-9
    print("[PASS] bigram_entropy")

    # ==== Normalized entropy ====
    assert normalized_entropy("") == 0.0
    assert normalized_entropy("aaa") == 0.0
    assert abs(normalized_entropy("ab") - 1.0) < 1e-9
    print("[PASS] normalized_entropy")

    # ==== Corpus entropy (self-information) ====
    freq = {"error": 2, "the": 100, "segfault": 1}
    total = 103
    e_the = corpus_entropy("the", freq, total)
    e_error = corpus_entropy("error", freq, total)
    e_segfault = corpus_entropy("segfault", freq, total)
    e_unseen = corpus_entropy("unseen", freq, total)
    assert e_the < e_error < e_segfault, "Common tokens should have lower self-info"
    assert e_unseen > e_segfault, "Unseen token = max surprisal"
    print("[PASS] corpus_entropy")

    # ==== EntropyTokenFilter: string tokens ====
    f = EntropyTokenFilter(threshold=1.0, min_length=2)
    tokens = ["hello", "world", "aa", "aaaa", "x", "", "  ", "ab", "the"]
    result = f.filter(tokens)
    assert "hello" in result
    assert "world" in result
    assert "aa" not in result
    assert "aaaa" not in result
    assert "x" not in result
    assert "" not in result
    assert "  " not in result
    assert "ab" in result  # entropy=1.0 meets threshold
    assert "the" in result
    print("[PASS] filter strings")

    # ==== Filter with stats ====
    result, stats = f.filter(tokens, collect_stats=True)
    assert stats.total == len(tokens)
    assert stats.kept == len(result)
    assert stats.removed == stats.total - stats.kept
    assert stats.removal_rate == stats.removed / stats.total
    assert stats.min_entropy >= 0.0
    assert stats.max_entropy >= stats.min_entropy
    assert len(stats.removed_tokens) == stats.removed
    print(f"[PASS] filter stats: kept={stats.kept}, removed={stats.removed}, rate={stats.removal_rate:.2%}")

    # ==== Dict tokens ====
    dict_tokens = [
        {"text": "hello", "logprob": -0.1},
        {"text": "aaaa", "logprob": -0.5},
        {"text": "world", "logprob": -0.2},
        {"text": "zz", "logprob": -3.0},
        {"text": "diverse", "logprob": -0.3},
    ]
    f2 = EntropyTokenFilter(threshold=1.0, min_length=2)
    result2 = f2.filter(dict_tokens)
    kept_texts = [t["text"] for t in result2]
    assert "hello" in kept_texts
    assert "world" in kept_texts
    assert "diverse" in kept_texts
    assert "aaaa" not in kept_texts
    assert "zz" not in kept_texts
    print("[PASS] filter dicts")

    # ==== Stopwords ====
    f3 = EntropyTokenFilter(threshold=0.5, min_length=1, stopwords={"the", "a", "is"})
    sw_result = f3.filter(["the", "cat", "is", "a", "diverse", "animal"])
    assert "the" not in sw_result
    assert "is" not in sw_result
    assert "a" not in sw_result
    assert "cat" in sw_result
    print("[PASS] stopwords")

    # ==== Whitelist ====
    f4 = EntropyTokenFilter(threshold=5.0, whitelist={"ok"})
    wl_result = f4.filter(["ok", "hello", "aaaa"])
    assert "ok" in wl_result
    assert "hello" not in wl_result
    print("[PASS] whitelist")

    # ==== Bigram mode ====
    f5 = EntropyTokenFilter(threshold=0.5, min_length=2, use_bigram=True, bigram_weight=0.5)
    bg_result = f5.filter(["aab", "hello", "aaaa"])
    assert "hello" in bg_result
    assert "aaaa" not in bg_result
    print("[PASS] bigram mode")

    # ==== Corpus mode ====
    cf = {"hello": 100, "world": 50, "rare": 1, "aaaa": 200}
    f6 = EntropyTokenFilter(
        threshold=0.0, min_length=1,
        use_corpus=True, corpus_freq=cf, corpus_threshold=3.0,
    )
    corpus_result = f6.filter(["hello", "rare", "world", "aaaa"])
    # "rare" has high self-information (count=1/351), should be kept
    assert "rare" in corpus_result, f"rare should be kept: {corpus_result}"
    # "aaaa" is very common (count=200/351), low self-info < 3.0, should be removed
    assert "aaaa" not in corpus_result, f"aaaa should be removed: {corpus_result}"
    print("[PASS] corpus mode")

    # ==== Combined: char + corpus ====
    f7 = EntropyTokenFilter(
        threshold=1.0, min_length=2,
        use_corpus=True, corpus_freq={"hello": 1, "aabb": 500}, corpus_threshold=2.0,
    )
    combo = f7.filter(["hello", "aabb", "xyz"])
    # "hello" passes char entropy (>1.0) and corpus (count=1, high self-info)
    assert "hello" in combo
    # "aabb" passes char entropy (1.0) but fails corpus (very common, low self-info)
    assert "aabb" not in combo
    # "xyz" passes char entropy (log2(3)) and corpus (unseen = max self-info)
    assert "xyz" in combo
    print("[PASS] combined char + corpus")

    # ==== filter_text ====
    f8 = EntropyTokenFilter(threshold=1.0, min_length=2)
    text_out = f8.filter_text("the quick brown fox jumps over aaaa aaaa the lazy dog")
    assert "aaaa" not in text_out
    assert "quick" in text_out
    assert "brown" in text_out
    print("[PASS] filter_text")

    # ==== filter_text with filler removal ====
    f9 = EntropyTokenFilter(threshold=1.0, min_length=2, remove_fillers=True)
    filler_text = "Basically, in order to fix the bug, the parser fails."
    filler_out = f9.filter_text(filler_text)
    assert "basically" not in filler_out.lower()
    assert "in order to" not in filler_out.lower()
    print("[PASS] filter_text with filler removal")

    # ==== batch_filter ====
    batches = [
        ["hello", "aaaa", "world"],
        ["diverse", "zz", "tokens", "here"],
    ]
    batch_results = f8.batch_filter(batches)
    assert len(batch_results) == 2
    for filtered, st in batch_results:
        assert st.total > 0
        assert st.kept + st.removed == st.total
    print("[PASS] batch_filter")

    # ==== score_detailed ====
    f10 = EntropyTokenFilter()
    sd = f10.score_detailed("hello")
    assert "char_entropy" in sd
    assert "bigram_entropy" in sd
    assert "normalized_entropy" in sd
    assert "length" in sd
    assert sd["length"] == 5
    print("[PASS] score_detailed")

    # ==== score_detailed with corpus ====
    f11 = EntropyTokenFilter(use_corpus=True, corpus_freq={"hello": 10, "world": 90}, corpus_threshold=1.0)
    sd2 = f11.score_detailed("hello")
    assert "corpus_entropy" in sd2
    assert sd2["corpus_entropy"] > 0
    print("[PASS] score_detailed with corpus")

    # ==== Edge cases ====
    assert f10.filter([]) == []
    assert f10.filter_text("") == ""
    print("[PASS] edge: empty")

    # ==== Threshold 0 keeps everything ====
    f12 = EntropyTokenFilter(threshold=0.0, min_length=1)
    assert len(f12.filter(["a", "bb", "ccc"])) == 3
    print("[PASS] threshold=0")

    # ==== Validation ====
    try:
        EntropyTokenFilter(threshold=-1)
        assert False
    except ValueError:
        pass
    try:
        EntropyTokenFilter(min_length=-1)
        assert False
    except ValueError:
        pass
    print("[PASS] validation")

    # ==== Text-level: filler phrase removal ====
    text_with_fillers = "Basically, in order to fix the bug, it should be noted that the parser fails."
    cleaned = _remove_filler_phrases(text_with_fillers)
    assert "basically" not in cleaned.lower()
    assert "in order to" not in cleaned.lower()
    assert "parser" in cleaned.lower()
    print("[PASS] filler phrase removal")

    # ==== Text-level: filter_low_entropy_tokens ====
    simple = "The quick brown fox jumps over the lazy dog"
    filtered = filter_low_entropy_tokens(simple, threshold=0.5, remove_stopwords=True)
    assert "quick" in filtered.lower()
    assert "brown" in filtered.lower()
    assert "fox" in filtered.lower()
    for sw in ["the", "over"]:
        assert sw not in filtered.lower().split()
    print("[PASS] filter_low_entropy_tokens")

    # ==== Measurable reduction ====
    verbose = (
        "In order to actually understand the problem, it is worth noting that "
        "the system basically processes the data through the pipeline, and as "
        "mentioned earlier, the architecture is designed in terms of modularity "
        "and scalability, which is very important for the overall performance."
    )
    filtered_verbose = filter_low_entropy_tokens(verbose, threshold=1.0)
    rstats = reduction_stats(verbose, filtered_verbose)
    assert rstats["reduction_pct"] > 30, f"Expected >30% reduction, got {rstats['reduction_pct']}%"
    assert rstats["tokens_removed"] > 10
    print(f"[PASS] reduction: {rstats['reduction_pct']}% ({rstats['tokens_removed']} tokens removed)")

    # ==== Batch filtering (text-level) ====
    texts = [
        "The system encountered a critical segmentation fault in the parser module.",
        "The parser module failed with a segmentation fault during initialization.",
        "Please note that the initialization error was caused by the parser.",
    ]
    filtered_batch = filter_batch(texts, threshold=1.0)
    assert len(filtered_batch) == 3
    for i, ft in enumerate(filtered_batch):
        orig_count = len(_TOKENIZE_RE.findall(texts[i]))
        filt_count = len(_TOKENIZE_RE.findall(ft))
        assert filt_count < orig_count
    print("[PASS] filter_batch")

    # ==== build_frequency_table ====
    ft = build_frequency_table(["hello world", "hello again"])
    assert ft["hello"] == 2
    assert ft["world"] == 1
    assert ft["again"] == 1
    print("[PASS] build_frequency_table")

    # ==== Preserve newlines ====
    multiline = "The error occurred.\nThe root cause is memory.\nThe fix is simple."
    filtered_ml = filter_low_entropy_tokens(multiline, threshold=0.5, preserve_structure=True)
    assert "\n" in filtered_ml
    assert "error" in filtered_ml.lower()
    assert "memory" in filtered_ml.lower()
    print("[PASS] preserve structure")

    # ==== High vs low threshold ====
    text = "The database connection pool exhausted all available sockets during peak traffic"
    high_thresh = filter_low_entropy_tokens(text, threshold=4.0)
    low_thresh = filter_low_entropy_tokens(text, threshold=0.1, remove_stopwords=False)
    assert len(_TOKENIZE_RE.findall(high_thresh)) < len(_TOKENIZE_RE.findall(low_thresh))
    print("[PASS] threshold tuning")

    print("\n=== All assertions passed ===")
