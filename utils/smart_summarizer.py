"""
Smart text summarization: extract key information from long texts.

Uses extractive summarization with multi-signal sentence scoring:
  1. TF-IDF relevance — upweight rare, informative terms
  2. Position bias — sentences near the start/end carry more weight
  3. Length normalization — prefer medium-length sentences over fragments
  4. Entity density — sentences with capitalized terms / numbers score higher
  5. Cue phrases — sentences with "important", "key", "result", etc. boosted
  6. Redundancy penalty — MMR-style dedup to avoid repeating the same info

Public API:
  - summarize(text, ratio=0.3)          -> str   (extractive summary)
  - summarize_to_bullets(text, n=5)     -> list[str]  (top-N bullet points)
  - extract_key_facts(text)             -> list[KeyFact]  (structured facts)
  - extract_keywords(text)              -> list[str]  (top-N keywords)
  - extract_entities(text)              -> list[str]  (named entity phrases)
  - extract_numbers(text)               -> list[str]  (numeric values)
  - summarize_with_metadata(text)       -> dict  (summary + keywords + entities + numbers)
  - SectionSummarizer.summarize(text)   -> str  (section-aware summary)

No external dependencies beyond the Python standard library.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SENT_RE = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z"])|(?<=[.!?])$', re.MULTILINE
)

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+(?:'[a-z]+)?")

_ENTITY_RE = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b")

_NUMBER_RE = re.compile(r"\b\d[\d,.]*%?")

STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "i", "we", "you", "he", "she", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "what", "which", "who", "whom", "where", "when", "how", "not", "no",
    "so", "if", "as", "than", "too", "very", "just", "about", "up", "out",
    "then", "also", "into", "over", "after", "before", "between", "under",
    "such", "each", "all", "any", "both", "more", "most", "other", "some",
    "only", "own", "same", "few", "there", "here", "because", "while",
    "must", "get", "got", "go", "going", "went", "make", "made",
    "back", "even", "still", "new", "well", "further", "again", "once",
    "off", "through", "during", "above", "below", "every", "nor",
})

CUE_PHRASES: frozenset[str] = frozenset({
    "important", "key", "critical", "significant", "notably", "result",
    "conclusion", "finding", "summary", "therefore", "consequently",
    "demonstrates", "reveals", "shows", "indicates", "confirms",
    "essential", "fundamental", "primary", "main", "core", "crucial",
    "caused", "root", "because", "reason", "impact", "effect",
    "recommend", "suggestion", "solution", "fix", "resolve",
    "increase", "decrease", "grow", "decline", "rise", "drop", "surge",
    "major", "necessary", "mandatory", "evidence",
})


# ---------------------------------------------------------------------------
# Tokenization & sentence splitting
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, handling common patterns."""
    text = text.strip()
    if not text:
        return []
    parts = _SENT_RE.split(text)
    sentences = []
    for p in parts:
        p = p.strip()
        if len(p) > 10:
            sentences.append(p)
    # If regex didn't split well, try newlines
    if len(sentences) <= 1 and "\n" in text:
        sentences = []
        for line in text.split("\n"):
            line = line.strip()
            if len(line) > 10:
                sentences.append(line)
    if not sentences and text.strip():
        sentences = [text.strip()]
    return sentences


def _tokenize(text: str) -> List[str]:
    """Extract word tokens, lowercased."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def _content_tokens(text: str) -> List[str]:
    """Extract non-stopword tokens."""
    return [t for t in _tokenize(text) if t not in STOPWORDS]


# ---------------------------------------------------------------------------
# TF-IDF computation
# ---------------------------------------------------------------------------

def _build_tf(tokens: List[str]) -> Dict[str, float]:
    counts = Counter(tokens)
    total = len(tokens) or 1
    return {w: c / total for w, c in counts.items()}


def _build_idf(sentences: List[List[str]]) -> Dict[str, float]:
    """IDF from sentence-level document frequency."""
    n = len(sentences)
    if n == 0:
        return {}
    df: Counter = Counter()
    for sent_tokens in sentences:
        df.update(set(sent_tokens))
    return {w: math.log((n + 1) / (count + 1)) + 1.0 for w, count in df.items()}


def _term_frequencies(tokens: List[str]) -> Dict[str, float]:
    """Normalized term frequencies for non-stop words."""
    filtered = [t for t in tokens if t not in STOPWORDS]
    counts = Counter(filtered)
    if not counts:
        return {}
    max_freq = max(counts.values())
    return {word: count / max_freq for word, count in counts.items()}


def _tfidf_score(tokens: List[str], idf: Dict[str, float]) -> float:
    """Average TF-IDF score for the tokens in one sentence."""
    if not tokens:
        return 0.0
    tf = _build_tf(tokens)
    score = sum(tf[w] * idf.get(w, 1.0) for w in tokens)
    return score / len(tokens)


# ---------------------------------------------------------------------------
# Sentence scoring signals
# ---------------------------------------------------------------------------

def _position_score(idx: int, total: int) -> float:
    """Bias toward first and last sentences (U-shaped curve)."""
    if total <= 1:
        return 1.0
    pos = idx / (total - 1)
    return 1.0 - 0.5 * math.sin(math.pi * pos)


def _length_score(n_words: int) -> float:
    """Prefer sentences of medium length (10-30 words)."""
    if n_words < 3:
        return 0.1
    if n_words < 5:
        return 0.3
    if n_words <= 10:
        return 0.5 + 0.05 * n_words
    if n_words <= 30:
        return 1.0
    return max(0.3, 1.0 - 0.02 * (n_words - 30))


def _entity_density(text: str) -> float:
    """Fraction of words that are capitalized entities or numbers."""
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    entities = len(_ENTITY_RE.findall(text))
    numbers = len(_NUMBER_RE.findall(text))
    return (entities + numbers) / len(words)


def _cue_phrase_score(tokens: List[str]) -> float:
    """Bonus for sentences containing cue phrases."""
    hits = sum(1 for t in tokens if t in CUE_PHRASES)
    return min(hits * 0.15, 0.6)


def _cosine_similarity(a: Counter, b: Counter) -> float:
    """Cosine similarity between two term-frequency counters."""
    if not a or not b:
        return 0.0
    intersection = set(a.keys()) & set(b.keys())
    dot = sum(a[w] * b[w] for w in intersection)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

@dataclass
class ScoredSentence:
    text: str
    index: int
    score: float
    tokens: List[str] = field(default_factory=list, repr=False)


def score_sentences(
    sentences: List[str],
    weights: Optional[Dict[str, float]] = None,
) -> List[ScoredSentence]:
    """Score each sentence by multiple signals and return sorted (descending)."""
    if not sentences:
        return []

    w = {
        "tfidf": 0.35,
        "position": 0.15,
        "length": 0.10,
        "entity": 0.20,
        "cue": 0.20,
    }
    if weights:
        w.update(weights)

    all_tokens = [_content_tokens(s) for s in sentences]
    idf = _build_idf(all_tokens)
    n = len(sentences)

    scored: List[ScoredSentence] = []
    for i, (sent, tokens) in enumerate(zip(sentences, all_tokens)):
        words = _WORD_RE.findall(sent)
        s = (
            w["tfidf"] * _tfidf_score(tokens, idf)
            + w["position"] * _position_score(i, n)
            + w["length"] * _length_score(len(words))
            + w["entity"] * _entity_density(sent)
            + w["cue"] * _cue_phrase_score(tokens)
        )
        scored.append(ScoredSentence(text=sent, index=i, score=s, tokens=tokens))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


# ---------------------------------------------------------------------------
# MMR redundancy removal
# ---------------------------------------------------------------------------

def _mmr_select(
    scored: List[ScoredSentence],
    n: int,
    lambda_: float = 0.7,
) -> List[ScoredSentence]:
    """Maximal Marginal Relevance: balance relevance with diversity."""
    if not scored or n <= 0:
        return []
    selected: List[ScoredSentence] = [scored[0]]
    selected_counters = [Counter(scored[0].tokens)]
    remaining = list(scored[1:])

    while len(selected) < n and remaining:
        best_idx = -1
        best_mmr = -float("inf")
        for j, candidate in enumerate(remaining):
            relevance = candidate.score
            c_counter = Counter(candidate.tokens)
            max_sim = max(
                _cosine_similarity(c_counter, sc) for sc in selected_counters
            )
            mmr = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = j
        pick = remaining.pop(best_idx)
        selected.append(pick)
        selected_counters.append(Counter(pick.tokens))

    return selected


# ---------------------------------------------------------------------------
# Key fact extraction
# ---------------------------------------------------------------------------

@dataclass
class KeyFact:
    text: str
    category: str  # "entity", "metric", "action", "finding"
    confidence: float
    source_sentence: str

    def __repr__(self) -> str:
        return f"KeyFact({self.category}: {self.text!r}, conf={self.confidence:.2f})"


_METRIC_RE = re.compile(
    r"\b\d[\d,.]*\s*(?:%|percent|ms|seconds?|minutes?|hours?|MB|GB|TB|KB"
    r"|requests?/s|ops/s|tokens?|items?|users?|errors?)\b",
    re.IGNORECASE,
)

_ACTION_RE = re.compile(
    r"\b(?:must|should|need to|recommend|fix|resolve|upgrade|migrate|deploy"
    r"|configure|enable|disable|restart|retry|rollback|revert)\b",
    re.IGNORECASE,
)

_FINDING_RE = re.compile(
    r"\b(?:caused by|root cause|because|due to|result of|led to"
    r"|indicates|reveals|shows that|confirms that|found that)\b",
    re.IGNORECASE,
)


def extract_key_facts(text: str, max_facts: int = 10) -> List[KeyFact]:
    """Extract structured key facts (metrics, entities, actions, findings)."""
    sentences = _split_sentences(text)
    if not sentences:
        return []

    facts: List[KeyFact] = []

    for sent in sentences:
        # Metrics
        for m in _METRIC_RE.finditer(sent):
            facts.append(KeyFact(
                text=m.group().strip(), category="metric",
                confidence=0.9, source_sentence=sent,
            ))
        # Named entities
        seen_ents: Set[str] = set()
        for e in _ENTITY_RE.findall(sent):
            if e not in seen_ents and e.lower() not in STOPWORDS:
                seen_ents.add(e)
                facts.append(KeyFact(
                    text=e, category="entity",
                    confidence=0.7, source_sentence=sent,
                ))
        # Actions
        if _ACTION_RE.search(sent):
            facts.append(KeyFact(
                text=sent.strip(), category="action",
                confidence=0.8, source_sentence=sent,
            ))
        # Findings
        if _FINDING_RE.search(sent):
            facts.append(KeyFact(
                text=sent.strip(), category="finding",
                confidence=0.85, source_sentence=sent,
            ))

    # Deduplicate
    seen: Set[str] = set()
    unique: List[KeyFact] = []
    for f in facts:
        key = f.text.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(f)

    unique.sort(key=lambda f: (-f.confidence, f.text))
    return unique[:max_facts]


# ---------------------------------------------------------------------------
# Keyword / entity / number extraction
# ---------------------------------------------------------------------------

def extract_keywords(text: str, top_n: int = 10) -> List[str]:
    """Return the top-N most important keywords from text."""
    tokens = _tokenize(text)
    filtered = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(top_n)]


def extract_entities(text: str) -> List[str]:
    """Extract capitalised multi-word phrases (proxy for named entities)."""
    found = _ENTITY_RE.findall(text)
    seen: set[str] = set()
    entities: list[str] = []
    for e in found:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            entities.append(e)
    return entities


def extract_numbers(text: str) -> List[str]:
    """Extract numeric values and percentages."""
    return list(dict.fromkeys(_NUMBER_RE.findall(text)))


# ---------------------------------------------------------------------------
# Section-aware summarizer
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(
    r"^(?:#{1,4}\s+.+|[A-Z][A-Za-z\s]{2,50}:\s*$|[A-Z][A-Z\s]{3,}$)",
    re.MULTILINE,
)


class SectionSummarizer:
    """Summarize text that has section headers, preserving structure."""

    def __init__(self, ratio: float = 0.3, min_sentences: int = 1):
        self.ratio = ratio
        self.min_sentences = min_sentences

    def _split_sections(self, text: str) -> List[Tuple[str, str]]:
        """Split into (header, body) pairs."""
        matches = list(_SECTION_RE.finditer(text))
        if not matches:
            return [("", text)]

        sections: List[Tuple[str, str]] = []
        if matches[0].start() > 0:
            pre = text[:matches[0].start()].strip()
            if pre:
                sections.append(("", pre))

        for i, m in enumerate(matches):
            header = m.group().strip().rstrip(":")
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.end():end].strip()
            if body:
                sections.append((header, body))

        return sections

    def summarize(self, text: str) -> str:
        """Summarize preserving section structure."""
        sections = self._split_sections(text)
        parts: List[str] = []

        for header, body in sections:
            sentences = _split_sentences(body)
            if not sentences:
                continue
            n_keep = max(self.min_sentences, int(len(sentences) * self.ratio))
            scored = score_sentences(sentences)
            selected = _mmr_select(scored, n_keep, lambda_=0.7)
            selected.sort(key=lambda s: s.index)
            summary_text = " ".join(s.text for s in selected)

            if header:
                parts.append(f"{header}\n{summary_text}")
            else:
                parts.append(summary_text)

        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main public functions
# ---------------------------------------------------------------------------

def summarize(
    text: str,
    ratio: float = 0.3,
    max_sentences: Optional[int] = None,
    min_sentences: int = 1,
    mmr_lambda: float = 0.7,
    weights: Optional[Dict[str, float]] = None,
) -> str:
    """Extractive summarization: pick the most informative sentences.

    Parameters
    ----------
    text : str
        Input text to summarize.
    ratio : float
        Fraction of sentences to keep (0.0-1.0).
    max_sentences : int or None
        Hard cap on output sentences.
    min_sentences : int
        Always return at least this many sentences.
    mmr_lambda : float
        Balance between relevance (1.0) and diversity (0.0).
    weights : dict, optional
        Override signal weights (tfidf, position, length, entity, cue).

    Returns
    -------
    str
        The extractive summary.
    """
    if not text or not text.strip():
        return ""

    sentences = _split_sentences(text)
    if not sentences:
        return text.strip()

    n_keep = max(min_sentences, int(math.ceil(len(sentences) * ratio)))
    if max_sentences is not None:
        n_keep = min(n_keep, max_sentences)
    n_keep = min(n_keep, len(sentences))

    scored = score_sentences(sentences, weights=weights)
    selected = _mmr_select(scored, n_keep, lambda_=mmr_lambda)
    selected.sort(key=lambda s: s.index)
    return " ".join(s.text for s in selected)


def summarize_to_bullets(
    text: str,
    n: int = 5,
    mmr_lambda: float = 0.7,
) -> List[str]:
    """Return top-N key sentences as bullet points."""
    if not text or not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    n = min(n, len(sentences))
    scored = score_sentences(sentences)
    selected = _mmr_select(scored, n, lambda_=mmr_lambda)
    selected.sort(key=lambda s: s.index)
    return [s.text.strip() for s in selected]


def summarize_with_metadata(
    text: str,
    ratio: float = 0.3,
    max_sentences: Optional[int] = None,
    keyword_count: int = 10,
) -> Dict[str, Any]:
    """Return a rich summary dict with summary text, keywords, entities, and numbers."""
    summary = summarize(text, ratio=ratio, max_sentences=max_sentences)
    return {
        "summary": summary,
        "keywords": extract_keywords(text, top_n=keyword_count),
        "entities": extract_entities(text),
        "numbers": extract_numbers(text),
        "original_length": len(text),
        "summary_length": len(summary),
        "compression_ratio": round(len(summary) / max(len(text), 1), 3),
    }


# ---------------------------------------------------------------------------
# __main__: assertions verifying correctness
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # ===== Sentence splitting =====
    sents = _split_sentences("Hello world is here. This is a test sentence. Final sentence goes here.")
    assert len(sents) == 3, f"Expected 3 sentences, got {len(sents)}: {sents}"
    print("[PASS] sentence splitting")

    sents_nl = _split_sentences("Line one has content\nLine two has content\nLine three has content")
    assert len(sents_nl) == 3, f"Expected 3, got {len(sents_nl)}"
    print("[PASS] newline splitting")

    assert _split_sentences("") == []
    assert _split_sentences("   ") == []
    assert len(_split_sentences("Single sentence that is long enough")) == 1
    print("[PASS] edge cases: empty / single")

    # ===== Tokenization =====
    tokens = _tokenize("The Quick Brown Fox-123")
    assert "the" in tokens
    assert "quick" in tokens
    assert "123" in tokens
    print("[PASS] tokenization")

    ct = _content_tokens("The quick brown fox jumps over the lazy dog")
    assert "the" not in ct
    assert "quick" in ct
    assert "fox" in ct
    print("[PASS] content tokens")

    # ===== TF-IDF =====
    tf = _build_tf(["cat", "dog", "cat", "fish"])
    assert abs(tf["cat"] - 0.5) < 1e-9
    assert abs(tf["dog"] - 0.25) < 1e-9
    print("[PASS] TF")

    sent_tokens = [["cat", "dog"], ["cat", "fish"], ["bird"]]
    idf = _build_idf(sent_tokens)
    assert idf["cat"] < idf["bird"], "cat appears in 2/3, bird in 1/3 => cat lower IDF"
    print("[PASS] IDF")

    # ===== Position score =====
    assert abs(_position_score(0, 10) - 1.0) < 1e-9
    assert abs(_position_score(9, 10) - 1.0) < 1e-9
    mid = _position_score(5, 10)
    assert mid < 1.0, f"Middle should be < 1.0, got {mid}"
    assert _position_score(0, 1) == 1.0
    print("[PASS] position score")

    # ===== Length score =====
    assert _length_score(1) == 0.1
    assert _length_score(15) == 1.0
    assert _length_score(50) < 1.0
    print("[PASS] length score")

    # ===== Entity density =====
    ed = _entity_density("Google and Microsoft released new APIs in 2024")
    assert ed > 0.0
    assert _entity_density("") == 0.0
    print("[PASS] entity density")

    # ===== Cue phrase score =====
    cps = _cue_phrase_score(["important", "result", "hello"])
    assert cps > 0.0
    assert _cue_phrase_score(["hello", "world"]) == 0.0
    print("[PASS] cue phrase score")

    # ===== Cosine similarity =====
    c1 = Counter({"a": 1, "b": 2})
    c2 = Counter({"a": 1, "b": 2})
    assert abs(_cosine_similarity(c1, c2) - 1.0) < 1e-9
    c3 = Counter({"c": 1, "d": 2})
    assert _cosine_similarity(c1, c3) == 0.0
    assert _cosine_similarity(Counter(), c1) == 0.0
    print("[PASS] cosine similarity")

    # ===== Score sentences =====
    test_sents = [
        "The database encountered a critical segmentation fault causing 500 errors.",
        "Memory usage increased to 95% before the crash occurred.",
        "The system was running normally earlier that day.",
        "Root cause analysis shows the connection pool was exhausted.",
        "We recommend restarting the service and increasing the pool size to 200.",
    ]
    scored = score_sentences(test_sents)
    assert len(scored) == 5
    assert scored[0].score >= scored[-1].score
    print("[PASS] score_sentences ranking")

    # ===== MMR selection =====
    mmr = _mmr_select(scored, 3, lambda_=0.7)
    assert len(mmr) == 3
    assert len(set(s.text for s in mmr)) == 3
    print("[PASS] MMR selection")

    # ===== Full summarize test =====
    long_text = (
        "The production database experienced a critical outage at 3:42 AM UTC. "
        "The monitoring system detected a spike in error rates, reaching 500 errors per second. "
        "Memory usage on the primary node climbed to 95% before the OOM killer terminated the process. "
        "The connection pool had been configured with a maximum of 50 connections, which was insufficient for peak traffic. "
        "During the incident, approximately 12,000 requests were dropped over a 15-minute window. "
        "The on-call engineer was paged and began investigation at 3:47 AM. "
        "Initial triage focused on the application logs, which showed repeated connection timeout errors. "
        "Root cause analysis reveals the connection pool exhaustion was caused by a recent deployment that introduced long-running queries. "
        "The long-running queries held connections for up to 30 seconds each, preventing other requests from acquiring connections. "
        "We recommend increasing the connection pool size to 200 and adding query timeout limits of 5 seconds. "
        "A rollback of the problematic deployment was performed at 4:02 AM, restoring service within 3 minutes. "
        "Post-incident review should also evaluate circuit breaker patterns to prevent cascading failures."
    )
    summary = summarize(long_text, ratio=0.3)
    assert len(summary) > 0
    assert len(summary) < len(long_text)
    summary_lower = summary.lower()
    assert any(term in summary_lower for term in ["root cause", "connection pool", "recommend"]), \
        f"Summary should contain key info: {summary}"
    print(f"[PASS] summarize: {len(long_text)} -> {len(summary)} chars")

    # ===== Ratio extremes =====
    tiny = summarize(long_text, ratio=0.1, min_sentences=1)
    assert len(tiny) <= len(summary)
    full = summarize(long_text, ratio=1.0)
    assert len(full) >= len(summary)
    print("[PASS] summarize ratio extremes")

    # ===== Edge cases =====
    assert summarize("") == ""
    assert summarize("   ") == ""
    single = "Just one sentence here that is long enough."
    assert summarize(single) == single
    print("[PASS] summarize edge cases")

    # ===== max_sentences =====
    short_summ = summarize(long_text, max_sentences=2)
    short_sents = _split_sentences(short_summ)
    assert len(short_sents) <= 2, f"max_sentences violated: got {len(short_sents)}"
    print("[PASS] max_sentences cap")

    # ===== Bullets =====
    bullets = summarize_to_bullets(long_text, n=3)
    assert len(bullets) == 3
    assert all(isinstance(b, str) and len(b) > 0 for b in bullets)
    assert summarize_to_bullets("") == []
    assert len(summarize_to_bullets("One sentence that is long enough.", n=5)) == 1
    print(f"[PASS] bullets: {len(bullets)} points")

    # ===== Key fact extraction =====
    facts = extract_key_facts(long_text)
    assert len(facts) > 0
    categories = {f.category for f in facts}
    assert "metric" in categories, f"Should find metrics, got: {categories}"
    assert "finding" in categories, f"Should find findings, got: {categories}"
    assert "action" in categories, f"Should find actions, got: {categories}"
    assert extract_key_facts("") == []
    print(f"[PASS] key facts: {len(facts)} extracted")
    for f in facts[:5]:
        print(f"  {f}")

    # ===== Fact deduplication =====
    dup_text = (
        "The error was caused by a memory leak in the service. "
        "Root cause analysis shows the error was caused by a memory leak in the process. "
        "We recommend fixing the memory leak immediately and restarting the service."
    )
    dup_facts = extract_key_facts(dup_text)
    texts_lower = [f.text.lower() for f in dup_facts]
    assert len(texts_lower) == len(set(texts_lower)), "Facts should be deduplicated"
    print("[PASS] fact deduplication")

    # ===== Keywords =====
    kws = extract_keywords(long_text, top_n=5)
    assert len(kws) == 5
    assert all(isinstance(k, str) for k in kws)
    print(f"[PASS] keywords: {kws}")

    # ===== Entities =====
    doc_with_entities = (
        "Geoffrey Hinton and Yoshua Bengio warned about AI risks. "
        "The European Union passed the AI Act for regulation."
    )
    entities = extract_entities(doc_with_entities)
    entity_names = [e.lower() for e in entities]
    assert any("geoffrey hinton" in n for n in entity_names)
    assert any("yoshua bengio" in n for n in entity_names)
    print(f"[PASS] entities: {entities}")

    # ===== Numbers =====
    nums = extract_numbers("The model achieved 94.5% accuracy on 1,000 samples in 30 seconds.")
    assert any("94.5%" in n for n in nums)
    assert any("1,000" in n for n in nums)
    print(f"[PASS] numbers: {nums}")

    # ===== Metadata =====
    meta = summarize_with_metadata(long_text, ratio=0.3, keyword_count=8)
    assert "summary" in meta
    assert "keywords" in meta
    assert "entities" in meta
    assert "numbers" in meta
    assert "compression_ratio" in meta
    assert 0 < meta["compression_ratio"] < 1
    assert len(meta["keywords"]) == 8
    print("[PASS] summarize_with_metadata")

    # ===== Section-aware summarizer =====
    sectioned_text = """# Incident Summary
The production service experienced a 15-minute outage affecting 12,000 users.
The monitoring alerts fired at 3:42 AM UTC and escalated to severity 1.
The incident was classified as severity 1 and required immediate response.

# Root Cause
The connection pool was exhausted due to long-running database queries.
A recent deployment introduced queries that held connections for 30 seconds.
The pool was configured with only 50 connections for peak traffic of 200 concurrent requests.

# Resolution
The on-call engineer rolled back the deployment at 4:02 AM successfully.
Service was restored within 3 minutes of the rollback being applied.
We recommend increasing the pool size to 200 connections immediately.
Query timeout limits of 5 seconds should be enforced going forward.

# Prevention
Circuit breaker patterns should be implemented to prevent cascading failures.
Load testing should include connection pool saturation scenarios regularly.
Deployment canary analysis should check connection metrics before promotion."""

    sec_summarizer = SectionSummarizer(ratio=0.5)
    sec_summary = sec_summarizer.summarize(sectioned_text)
    assert len(sec_summary) > 0
    assert len(sec_summary) < len(sectioned_text)
    assert "Incident Summary" in sec_summary or "Root Cause" in sec_summary
    print(f"[PASS] section summarizer: {len(sectioned_text)} -> {len(sec_summary)} chars")

    # Section splitting
    sections = sec_summarizer._split_sections(sectioned_text)
    assert len(sections) == 4, f"Expected 4 sections, got {len(sections)}"
    assert sections[0][0] == "# Incident Summary"
    print("[PASS] section splitting")

    plain_sections = sec_summarizer._split_sections("Just plain text without any headers at all.")
    assert len(plain_sections) == 1
    assert plain_sections[0][0] == ""
    print("[PASS] section splitting (no headers)")

    # ===== Custom weights =====
    custom_summary = summarize(
        long_text, ratio=0.3,
        weights={"tfidf": 0.5, "position": 0.1, "length": 0.1, "entity": 0.2, "cue": 0.1},
    )
    assert len(custom_summary) > 0
    assert len(custom_summary) < len(long_text)
    print("[PASS] custom weights")

    # ===== MMR lambda tuning =====
    diverse = summarize(long_text, ratio=0.3, mmr_lambda=0.3)
    focused = summarize(long_text, ratio=0.3, mmr_lambda=0.95)
    assert len(diverse) > 0
    assert len(focused) > 0
    print("[PASS] MMR lambda tuning")

    # ===== Redundancy removal =====
    repetitive = (
        "AI is very important for the future of technology. "
        "Artificial intelligence is important for our future development. "
        "The climate crisis demands immediate action from all nations worldwide. "
        "Global warming requires urgent response from every country today. "
        "Healthcare AI detects cancer with 95% accuracy in clinical trials."
    )
    rep_summary = summarize(repetitive, ratio=0.5)
    rep_sents = _split_sentences(rep_summary)
    assert len(rep_sents) <= 4, f"Redundancy removal should reduce count, got {len(rep_sents)}"
    print("[PASS] redundancy removal")

    # ===== Preserves original order =====
    ordered_text = (
        "First point about economics and global markets. "
        "Second point about technology and innovation trends. "
        "Third point about healthcare and medical advances. "
        "Fourth point about education and learning systems. "
        "Fifth point about environment and climate change."
    )
    ordered_summary = summarize(ordered_text, ratio=0.6)
    ordered_sents = _split_sentences(ordered_summary)
    if len(ordered_sents) > 1:
        all_sents = _split_sentences(ordered_text)
        indices = []
        for ss in ordered_sents:
            for i, orig in enumerate(all_sents):
                if ss == orig:
                    indices.append(i)
                    break
        assert indices == sorted(indices), "Summary must preserve original sentence order"
    print("[PASS] preserves order")

    # ===== Large text stress test =====
    large_text = " ".join([
        f"Sentence number {i} discusses topic {chr(65 + i % 26)} with metric {i * 1.5:.1f} percent."
        for i in range(100)
    ])
    large_summary = summarize(large_text, ratio=0.1)
    large_sents = _split_sentences(large_text)
    summary_sents_large = _split_sentences(large_summary)
    assert len(summary_sents_large) <= len(large_sents)
    assert len(summary_sents_large) >= 1
    print(f"[PASS] stress test: {len(large_sents)} -> {len(summary_sents_large)} sentences")

    # ===== Reduction quality =====
    original_words = len(_WORD_RE.findall(long_text))
    summary_words = len(_WORD_RE.findall(summary))
    reduction_pct = (1 - summary_words / original_words) * 100
    assert reduction_pct > 40, f"Expected >40% word reduction, got {reduction_pct:.1f}%"
    print(f"[PASS] reduction quality: {reduction_pct:.1f}% word reduction")

    print("\n=== All assertions passed ===")
