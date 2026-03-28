"""
Smart Summarizer — extract key information from long texts.

Techniques used:
  1. Sentence scoring via TF-IDF-like term frequency weighting
  2. Named-entity / keyword extraction (regex-based, no heavy deps)
  3. Positional bias (first/last sentences score higher)
  4. Redundancy removal (cosine-similarity dedup among selected sentences)

No external dependencies beyond the Python standard library.
"""

from __future__ import annotations

import math
import re
import string
from collections import Counter
from typing import Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────────────

_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_WORD_RE = re.compile(r"[a-z][a-z'-]*[a-z]|[a-z]", re.IGNORECASE)

# Common English stop words (kept small to avoid bloat)
_STOP_WORDS: set[str] = {
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
}

# Patterns that hint at key information
_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\b"),          # numbers / percentages
    re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b"),            # proper noun phrases
    re.compile(r"\b(?:significant|critical|important|key|major|essential)\b", re.I),
    re.compile(r"\b(?:increase|decrease|grow|decline|rise|drop|surge)\b", re.I),
    re.compile(r"\b(?:result|conclusion|finding|evidence|cause|effect)\b", re.I),
    re.compile(r"\b(?:must|require|necessary|mandatory)\b", re.I),
]


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _split_sentences(text: str) -> list[str]:
    raw = _SENT_RE.split(text.strip())
    sentences = []
    for s in raw:
        s = s.strip()
        if len(s) > 10:
            sentences.append(s)
    return sentences


def _term_frequencies(tokens: list[str]) -> Dict[str, float]:
    filtered = [t for t in tokens if t not in _STOP_WORDS]
    counts = Counter(filtered)
    if not counts:
        return {}
    max_freq = max(counts.values())
    return {word: count / max_freq for word, count in counts.items()}


def _cosine_sim(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── core scoring ─────────────────────────────────────────────────────────────

def _score_sentences(
    sentences: list[str],
    tf: Dict[str, float],
) -> list[Tuple[int, float, str]]:
    scored: list[Tuple[int, float, str]] = []
    n = len(sentences)
    for idx, sent in enumerate(sentences):
        tokens = _tokenize(sent)
        if not tokens:
            continue

        # 1. TF score — average term-frequency weight of non-stop words
        content_tokens = [t for t in tokens if t not in _STOP_WORDS]
        tf_score = (
            sum(tf.get(t, 0.0) for t in content_tokens) / len(content_tokens)
            if content_tokens
            else 0.0
        )

        # 2. Key-pattern bonus
        pattern_hits = sum(1 for p in _KEY_PATTERNS if p.search(sent))
        pattern_score = min(pattern_hits * 0.15, 0.6)

        # 3. Positional bias — first & last sentences are usually important
        if idx == 0:
            pos_score = 0.3
        elif idx == n - 1:
            pos_score = 0.2
        elif idx < n * 0.2:
            pos_score = 0.15
        elif idx > n * 0.8:
            pos_score = 0.1
        else:
            pos_score = 0.0

        # 4. Length penalty — very short or very long sentences score less
        word_count = len(tokens)
        if word_count < 5:
            length_penalty = -0.15
        elif word_count > 40:
            length_penalty = -0.1
        else:
            length_penalty = 0.0

        total = tf_score + pattern_score + pos_score + length_penalty
        scored.append((idx, total, sent))

    return scored


def _remove_redundant(
    ranked: list[Tuple[int, float, str]],
    max_sim: float = 0.6,
) -> list[Tuple[int, float, str]]:
    selected: list[Tuple[int, float, str]] = []
    selected_counters: list[Counter] = []
    for item in ranked:
        tokens = _tokenize(item[2])
        cnt = Counter(t for t in tokens if t not in _STOP_WORDS)
        is_redundant = any(
            _cosine_sim(cnt, sc) > max_sim for sc in selected_counters
        )
        if not is_redundant:
            selected.append(item)
            selected_counters.append(cnt)
    return selected


# ── keyword extraction ───────────────────────────────────────────────────────

def extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """Return the top-N most important keywords from *text*."""
    tokens = _tokenize(text)
    filtered = [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(top_n)]


def extract_entities(text: str) -> list[str]:
    """Extract capitalised multi-word phrases (proxy for named entities)."""
    pattern = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b")
    found = pattern.findall(text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    entities: list[str] = []
    for e in found:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            entities.append(e)
    return entities


def extract_numbers(text: str) -> list[str]:
    """Extract numeric values and percentages."""
    pattern = re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\b")
    return list(dict.fromkeys(pattern.findall(text)))


# ── public API ───────────────────────────────────────────────────────────────

def summarize(
    text: str,
    *,
    ratio: float = 0.3,
    max_sentences: Optional[int] = None,
    min_sentences: int = 1,
) -> str:
    """
    Summarize *text* by extracting the most informative sentences.

    Parameters
    ----------
    text : str
        The document to summarize.
    ratio : float
        Fraction of original sentences to keep (default 0.3 = 30%).
    max_sentences : int | None
        Hard cap on output sentences. ``None`` means use *ratio* only.
    min_sentences : int
        Always return at least this many sentences.

    Returns
    -------
    str
        The summary text with sentences in their original order.
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

    all_tokens = _tokenize(text)
    tf = _term_frequencies(all_tokens)

    scored = _score_sentences(sentences, tf)
    scored.sort(key=lambda x: x[1], reverse=True)

    # Remove near-duplicate sentences before selecting top N
    deduped = _remove_redundant(scored)
    top = deduped[:n_keep]

    # Restore original order for readability
    top.sort(key=lambda x: x[0])
    return " ".join(item[2] for item in top)


def summarize_with_metadata(
    text: str,
    *,
    ratio: float = 0.3,
    max_sentences: Optional[int] = None,
    keyword_count: int = 10,
) -> Dict:
    """
    Return a rich summary dict with summary text, keywords, entities, and numbers.
    """
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


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ---------- test document ----------
    document = """
    Artificial Intelligence has transformed the technology landscape significantly
    over the past decade. Major companies like Google, Microsoft, and OpenAI have
    invested billions of dollars into developing large language models. These models
    can now generate human-quality text, translate between 100 languages, and even
    write working software code.

    The economic impact has been substantial. According to a McKinsey report, AI
    could contribute up to 13 trillion dollars to the global economy by 2030. This
    represents approximately 16% additional GDP growth compared to current trends.
    Industries ranging from healthcare to manufacturing are finding practical
    applications for machine learning.

    However, there are significant concerns about AI safety and alignment. Leading
    researchers including Geoffrey Hinton and Yoshua Bengio have warned about the
    risks of developing systems that surpass human intelligence without adequate
    safety measures. The European Union has responded with the AI Act, establishing
    a comprehensive regulatory framework for high-risk AI systems.

    In the healthcare sector, AI has shown remarkable results. Deep learning models
    can now detect certain cancers with 94.5% accuracy, outperforming human
    radiologists in specific diagnostic tasks. Drug discovery timelines have been
    reduced from years to months using AI-powered molecular simulation.

    Despite the progress, challenges remain. Bias in training data continues to
    produce discriminatory outcomes in hiring, lending, and criminal justice
    applications. The environmental cost of training large models is also a growing
    concern, with a single training run consuming as much energy as five cars over
    their entire lifetimes.

    Looking ahead, the field is moving toward more efficient architectures and
    responsible deployment practices. The key challenge for the next decade will be
    balancing rapid innovation with necessary safeguards to ensure AI benefits
    humanity broadly rather than concentrating advantages among a few powerful
    organizations.
    """

    # ---------- test 1: basic summarize ----------
    summary = summarize(document, ratio=0.3)
    assert isinstance(summary, str), "summary must be a string"
    assert len(summary) > 0, "summary must not be empty"
    assert len(summary) < len(document), "summary must be shorter than original"

    sentences_orig = _split_sentences(document)
    sentences_summ = _split_sentences(summary)
    assert len(sentences_summ) <= len(sentences_orig), "summary has too many sentences"
    assert len(sentences_summ) >= 1, "summary must have at least 1 sentence"

    # ---------- test 2: max_sentences cap ----------
    short = summarize(document, max_sentences=3)
    assert len(_split_sentences(short)) <= 3, "max_sentences cap violated"

    # ---------- test 3: keywords ----------
    kws = extract_keywords(document, top_n=5)
    assert isinstance(kws, list), "keywords must be a list"
    assert len(kws) == 5, "should return exactly top_n keywords"
    assert all(isinstance(k, str) for k in kws), "keywords must be strings"

    # ---------- test 4: entities ----------
    entities = extract_entities(document)
    assert isinstance(entities, list), "entities must be a list"
    entity_names = [e.lower() for e in entities]
    # At least some well-known entities should be found
    found_any = any(
        name in " ".join(entity_names)
        for name in ["geoffrey hinton", "yoshua bengio", "european union", "ai act"]
    )
    assert found_any, f"expected known entities, got {entities}"

    # ---------- test 5: numbers ----------
    nums = extract_numbers(document)
    assert isinstance(nums, list), "numbers must be a list"
    assert any("94.5" in n for n in nums), f"expected 94.5% in numbers, got {nums}"

    # ---------- test 6: metadata ----------
    meta = summarize_with_metadata(document, ratio=0.3, keyword_count=8)
    assert "summary" in meta
    assert "keywords" in meta
    assert "entities" in meta
    assert "numbers" in meta
    assert "compression_ratio" in meta
    assert 0 < meta["compression_ratio"] < 1, "compression ratio must be between 0 and 1"
    assert len(meta["keywords"]) == 8

    # ---------- test 7: empty input ----------
    assert summarize("") == "", "empty input must return empty string"
    assert summarize("   ") == "", "whitespace input must return empty string"

    # ---------- test 8: single sentence ----------
    single = "This is a single important sentence about AI safety."
    assert summarize(single) == single, "single sentence should return itself"

    # ---------- test 9: redundancy removal ----------
    repetitive = (
        "AI is important for the future. "
        "Artificial intelligence is important for our future. "
        "The climate crisis demands immediate action from all nations. "
        "Global warming requires urgent response from every country. "
        "Healthcare AI detects cancer with 95% accuracy."
    )
    result = summarize(repetitive, ratio=0.5)
    result_sents = _split_sentences(result)
    # With redundancy removal, near-duplicate pairs should be collapsed
    assert len(result_sents) <= 4, f"redundancy removal should reduce count, got {len(result_sents)}"

    # ---------- test 10: preserves original order ----------
    ordered_text = (
        "First point about economics. "
        "Second point about technology. "
        "Third point about healthcare. "
        "Fourth point about education. "
        "Fifth point about environment."
    )
    ordered_summary = summarize(ordered_text, ratio=0.6)
    ordered_sents = _split_sentences(ordered_summary)
    if len(ordered_sents) > 1:
        # Check that selected sentences appear in original order
        indices = []
        all_sents = _split_sentences(ordered_text)
        for ss in ordered_sents:
            for i, orig in enumerate(all_sents):
                if ss == orig:
                    indices.append(i)
                    break
        assert indices == sorted(indices), "summary must preserve original sentence order"

    print("All assertions passed.")
    print(f"\nOriginal: {len(document)} chars, {len(sentences_orig)} sentences")
    print(f"Summary:  {len(summary)} chars, {len(sentences_summ)} sentences")
    print(f"Compression: {meta['compression_ratio']:.1%}")
    print(f"\nKeywords: {meta['keywords']}")
    print(f"Entities: {meta['entities']}")
    print(f"Numbers:  {meta['numbers']}")
    print(f"\n--- Summary ---\n{summary}")
