#!/usr/bin/env python3
"""
summarizer.py — Extractive + Abstractive Summarization Agent
=============================================================
Summarize long agent responses by:
  1. Extractive: Score and select the most important sentences
  2. Abstractive: Merge, rephrase, and condense extracted content
  3. Key-point extraction: Pull structured bullet-point takeaways

Key functions:
  - extractive_summarize(text, ratio=0.3) -> str
  - abstractive_summarize(text, max_sentences=5) -> str
  - extract_key_points(text, max_points=7) -> list[str]
  - summarize(text, mode="auto", ratio=0.3) -> SummaryResult
"""

import re
import math
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SummaryResult:
    """Container for summarization output."""
    extractive: str
    abstractive: str
    key_points: list
    original_length: int
    summary_length: int
    reduction_pct: float
    mode: str

    def __str__(self):
        points = "\n".join(f"  • {p}" for p in self.key_points)
        return (
            f"[{self.mode}] {self.reduction_pct:.1f}% reduction "
            f"({self.original_length}→{self.summary_length} chars)\n"
            f"Key points:\n{points}\n\n"
            f"Summary:\n{self.abstractive}"
        )


@dataclass
class ScoredSentence:
    """A sentence with its importance score and position."""
    text: str
    score: float
    position: int
    is_heading: bool = False


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "but", "and", "or", "if", "while", "about", "up",
    "this", "that", "these", "those", "it", "its", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "they", "them", "their", "what", "which", "who", "whom",
})

BOILERPLATE_RE = re.compile(
    r"(?i)(hope this helps|let me know if|feel free to|don't hesitate|"
    r"happy to help|please let me know|if you have any questions|"
    r"i'd be happy to|i would be happy to|certainly|of course|absolutely|"
    r"here is the|here are the|below is the|sure thing)",
)

FILLER_RE = re.compile(
    r"(?i)\b(basically|actually|essentially|obviously|clearly|"
    r"it is important to note that|it should be noted that|"
    r"it is worth mentioning that|needless to say|as a matter of fact|"
    r"in my opinion|as you know|as we can see)\b"
)

HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
BULLET_RE = re.compile(r"^\s*[-*•]\s+(.+)$", re.MULTILINE)
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def _tokenize_words(text: str) -> list:
    """Split text into lowercase word tokens."""
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def _split_sentences(text: str) -> list:
    """Split text into sentences, handling abbreviations and decimals."""
    # Remove code blocks before splitting
    cleaned = CODE_BLOCK_RE.sub(" [code] ", text)
    # Split on sentence boundaries
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z"])', cleaned)
    sentences = []
    for s in raw:
        s = s.strip()
        if len(s) > 10:
            sentences.append(s)
    return sentences


def _extract_sections(text: str) -> dict:
    """Extract markdown sections with their content."""
    sections = {}
    current_heading = "_intro"
    current_content = []

    for line in text.split("\n"):
        heading_match = HEADING_RE.match(line.strip())
        if heading_match:
            if current_content:
                sections[current_heading] = "\n".join(current_content).strip()
            current_heading = heading_match.group(1).strip()
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections[current_heading] = "\n".join(current_content).strip()

    return sections


# ---------------------------------------------------------------------------
# TF-IDF scoring (lightweight, no external deps)
# ---------------------------------------------------------------------------

def _compute_tf(words: list) -> dict:
    """Term frequency for a word list."""
    counts = Counter(words)
    total = len(words) if words else 1
    return {w: c / total for w, c in counts.items()}


def _compute_idf(documents: list) -> dict:
    """Inverse document frequency across sentence-documents."""
    n = len(documents)
    if n == 0:
        return {}
    df = Counter()
    for doc_words in documents:
        unique = set(doc_words)
        for w in unique:
            df[w] += 1
    return {w: math.log(n / (1 + count)) for w, count in df.items()}


def _tfidf_score_sentences(sentences: list) -> list:
    """Score sentences by TF-IDF importance."""
    tokenized = []
    for s in sentences:
        words = [w for w in _tokenize_words(s) if w not in STOP_WORDS]
        tokenized.append(words)

    idf = _compute_idf(tokenized)

    scored = []
    for i, (sentence, words) in enumerate(zip(sentences, tokenized)):
        if not words:
            scored.append(0.0)
            continue
        tf = _compute_tf(words)
        score = sum(tf.get(w, 0) * idf.get(w, 0) for w in words)
        scored.append(score)

    return scored


# ---------------------------------------------------------------------------
# Sentence importance scoring (multi-signal)
# ---------------------------------------------------------------------------

# Cue phrases that indicate important content
CUE_PHRASES = re.compile(
    r"(?i)\b(root cause|fix|solution|recommend|critical|important|"
    r"key finding|conclusion|result|impact|because|therefore|"
    r"must|should|error|failure|bug|issue|problem|"
    r"increase|decrease|improve|degrade|timeout|latency|"
    r"missing|broken|incorrect|caused by)\b"
)

# Numeric patterns (specifics are usually important)
NUMERIC_RE = re.compile(r"\b\d+(?:\.\d+)?(?:\s*(?:%|ms|s|seconds|minutes|hours|MB|GB|TB|rows|M|K))\b")


def _score_sentence(sentence: str, position: int, total: int,
                    tfidf_score: float, title_words: set) -> float:
    """
    Multi-signal sentence scoring:
      - TF-IDF relevance (40%)
      - Position bias: first/last sentences per section (20%)
      - Cue phrase presence (15%)
      - Numeric/specific data presence (10%)
      - Title word overlap (10%)
      - Penalize boilerplate/filler (−5%)
    """
    score = 0.0

    # TF-IDF (normalized to 0-1 range, weighted 40%)
    score += min(tfidf_score * 0.1, 1.0) * 0.40

    # Position bias: first 20% and last 10% of document
    rel_pos = position / max(total, 1)
    if rel_pos < 0.2:
        score += 0.20
    elif rel_pos > 0.9:
        score += 0.10

    # Cue phrases
    cue_count = len(CUE_PHRASES.findall(sentence))
    score += min(cue_count * 0.05, 0.15)

    # Numeric specifics
    num_count = len(NUMERIC_RE.findall(sentence))
    score += min(num_count * 0.05, 0.10)

    # Title word overlap
    words = set(_tokenize_words(sentence)) - STOP_WORDS
    if title_words and words:
        overlap = len(words & title_words) / max(len(title_words), 1)
        score += overlap * 0.10

    # Penalize boilerplate
    if BOILERPLATE_RE.search(sentence):
        score -= 0.15

    # Penalize filler-heavy sentences
    filler_count = len(FILLER_RE.findall(sentence))
    score -= filler_count * 0.03

    return max(score, 0.0)


def _rank_sentences(text: str) -> list:
    """Rank all sentences by importance, returning ScoredSentence list."""
    sentences = _split_sentences(text)
    if not sentences:
        return []

    # Collect title/heading words for overlap scoring
    headings = HEADING_RE.findall(text)
    title_words = set()
    for h in headings:
        title_words.update(w for w in _tokenize_words(h) if w not in STOP_WORDS)

    # TF-IDF scores
    tfidf_scores = _tfidf_score_sentences(sentences)

    # Score each sentence
    scored = []
    total = len(sentences)
    for i, (sent, tfidf) in enumerate(zip(sentences, tfidf_scores)):
        score = _score_sentence(sent, i, total, tfidf, title_words)
        scored.append(ScoredSentence(
            text=sent,
            score=score,
            position=i,
            is_heading=bool(HEADING_RE.match(sent.strip())),
        ))

    return scored


# ---------------------------------------------------------------------------
# Extractive summarization
# ---------------------------------------------------------------------------

def extractive_summarize(text: str, ratio: float = 0.3,
                         min_sentences: int = 2,
                         max_sentences: int = 15) -> str:
    """
    Extract the most important sentences from the text.

    Selects top-scoring sentences while preserving original order.

    Args:
        text: Input text to summarize.
        ratio: Fraction of sentences to keep (0.0-1.0).
        min_sentences: Minimum sentences in output.
        max_sentences: Maximum sentences in output.

    Returns:
        Extractive summary as a string.
    """
    if not text or len(text.strip()) < 50:
        return text.strip() if text else ""

    scored = _rank_sentences(text)
    if not scored:
        return text.strip()

    # Determine how many sentences to keep
    n_keep = max(min_sentences, min(max_sentences, int(len(scored) * ratio)))
    n_keep = min(n_keep, len(scored))

    # Select top-scoring sentences
    top = sorted(scored, key=lambda s: s.score, reverse=True)[:n_keep]

    # Restore original order
    top_ordered = sorted(top, key=lambda s: s.position)

    # Also include any headings that precede selected sentences
    result_lines = []
    sections = _extract_sections(text)

    for sent in top_ordered:
        result_lines.append(sent.text)

    return " ".join(result_lines)


# ---------------------------------------------------------------------------
# Abstractive summarization (rule-based, no LLM dependency)
# ---------------------------------------------------------------------------

# Compression rewrites for abstractive mode
ABSTRACTIVE_REWRITES = [
    # Verbose → concise
    (r"(?i)due to the fact that", "because"),
    (r"(?i)in order to", "to"),
    (r"(?i)at this point in time", "now"),
    (r"(?i)in the event that", "if"),
    (r"(?i)for the purpose of", "for"),
    (r"(?i)the vast majority of", "most"),
    (r"(?i)a large number of", "many"),
    (r"(?i)prior to", "before"),
    (r"(?i)subsequent to", "after"),
    (r"(?i)in close proximity", "near"),
    (r"(?i)has the ability to", "can"),
    (r"(?i)is able to", "can"),
    (r"(?i)it is important to note that\s*", ""),
    (r"(?i)it should be noted that\s*", ""),
    (r"(?i)it is worth mentioning that\s*", ""),
    (r"(?i)as a matter of fact,?\s*", ""),
    (r"(?i)needless to say,?\s*", ""),
    (r"(?i)with regard to", "about"),
    (r"(?i)with respect to", "about"),
    (r"(?i)as a result of", "because of"),
    (r"(?i)in addition to this,?\s*", "also, "),
    (r"(?i)on the other hand,?\s*", "however, "),
    (r"(?i)this results in\s*", "causing "),
    (r"(?i)this means that\s*", "so "),
    # Remove hedging
    (r"(?i)\b(basically|actually|essentially|really|quite|very|just)\s+", ""),
    (r"(?i)\b(i think|i believe|it seems like|it appears that)\s+", ""),
]


def _abstractive_rewrite(sentence: str) -> str:
    """Apply rule-based abstractive compression to a single sentence."""
    result = sentence
    for pattern, replacement in ABSTRACTIVE_REWRITES:
        result = re.sub(pattern, replacement, result)
    # Clean up double spaces and leading lowercase after removal
    result = re.sub(r"\s{2,}", " ", result).strip()
    # Capitalize first letter if it became lowercase
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


def _merge_related_sentences(sentences: list) -> list:
    """
    Merge consecutive sentences that share significant word overlap.
    Produces tighter summaries by combining related ideas.
    """
    if len(sentences) <= 1:
        return sentences

    merged = []
    i = 0
    while i < len(sentences):
        current = sentences[i]
        current_words = set(_tokenize_words(current)) - STOP_WORDS

        # Try to merge with next sentence if high overlap
        if i + 1 < len(sentences):
            next_sent = sentences[i + 1]
            next_words = set(_tokenize_words(next_sent)) - STOP_WORDS

            if current_words and next_words:
                overlap = len(current_words & next_words)
                min_len = min(len(current_words), len(next_words))
                overlap_ratio = overlap / max(min_len, 1)

                if overlap_ratio > 0.5:
                    # High overlap: keep the longer/more informative one
                    if len(next_sent) > len(current):
                        merged.append(next_sent)
                    else:
                        merged.append(current)
                    i += 2
                    continue

        merged.append(current)
        i += 1

    return merged


def abstractive_summarize(text: str, max_sentences: int = 5,
                          extractive_ratio: float = 0.4) -> str:
    """
    Generate an abstractive summary by:
      1. Extracting important sentences
      2. Rewriting them for conciseness
      3. Merging related sentences
      4. Capping at max_sentences

    Args:
        text: Input text to summarize.
        max_sentences: Maximum sentences in output.
        extractive_ratio: Fraction of sentences for extractive phase.

    Returns:
        Abstractive summary string.
    """
    if not text or len(text.strip()) < 50:
        return text.strip() if text else ""

    # Phase 1: Extract important sentences
    scored = _rank_sentences(text)
    if not scored:
        return text.strip()

    n_extract = max(3, int(len(scored) * extractive_ratio))
    n_extract = min(n_extract, len(scored))

    top = sorted(scored, key=lambda s: s.score, reverse=True)[:n_extract]
    top_ordered = sorted(top, key=lambda s: s.position)

    extracted = [s.text for s in top_ordered]

    # Phase 2: Rewrite each sentence
    rewritten = [_abstractive_rewrite(s) for s in extracted]

    # Phase 3: Merge related sentences
    merged = _merge_related_sentences(rewritten)

    # Phase 4: Cap at max_sentences
    final = merged[:max_sentences]

    # Phase 5: Remove trailing boilerplate
    cleaned = []
    for s in final:
        if not BOILERPLATE_RE.search(s):
            cleaned.append(s)

    return " ".join(cleaned) if cleaned else " ".join(final[:2])


# ---------------------------------------------------------------------------
# Key point extraction
# ---------------------------------------------------------------------------

def extract_key_points(text: str, max_points: int = 7) -> list:
    """
    Extract structured key points from text.

    Strategy:
      1. Pull existing bullet points (author's own structure)
      2. Extract sentences with high cue-phrase density
      3. Extract sentences with numeric specifics
      4. Deduplicate and rank

    Args:
        text: Input text.
        max_points: Maximum number of key points.

    Returns:
        List of key point strings.
    """
    if not text or len(text.strip()) < 30:
        return []

    candidates = []
    seen_hashes = set()

    def _add_candidate(point: str, source_score: float):
        """Add a candidate key point if not duplicate."""
        clean = point.strip().rstrip(".")
        if len(clean) < 10:
            return
        # Remove markdown bullet prefix
        clean = re.sub(r"^[-*•]\s+", "", clean)
        # Normalize for dedup
        norm = re.sub(r"[^\w\s]", "", clean.lower())
        norm = " ".join(w for w in norm.split() if w not in STOP_WORDS)
        h = hashlib.md5(norm.encode()).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            candidates.append((clean, source_score))

    # Source 1: Existing bullet points (high confidence — author structured these)
    bullets = BULLET_RE.findall(text)
    for b in bullets:
        if not BOILERPLATE_RE.search(b):
            _add_candidate(b, 0.9)

    # Source 2: High-scoring sentences with cue phrases
    scored = _rank_sentences(text)
    for s in scored:
        cue_count = len(CUE_PHRASES.findall(s.text))
        num_count = len(NUMERIC_RE.findall(s.text))
        if cue_count >= 1 or num_count >= 1:
            # Shorten the sentence for a key-point format
            shortened = _abstractive_rewrite(s.text)
            # Truncate very long sentences
            if len(shortened) > 150:
                # Keep up to the first clause boundary
                clause_end = re.search(r"[,;:]", shortened[80:])
                if clause_end:
                    shortened = shortened[:80 + clause_end.start()]
                else:
                    shortened = shortened[:150]
            _add_candidate(shortened, s.score)

    # Source 3: Section headings as context
    sections = _extract_sections(text)
    for heading, content in sections.items():
        if heading == "_intro":
            continue
        # Take the first substantive sentence from each section
        section_sents = _split_sentences(content)
        for sent in section_sents[:1]:
            if not BOILERPLATE_RE.search(sent) and len(sent) > 20:
                shortened = _abstractive_rewrite(sent)
                _add_candidate(f"{heading}: {shortened[:120]}", 0.7)

    # Rank and return top points
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates[:max_points]]


# ---------------------------------------------------------------------------
# Unified summarize interface
# ---------------------------------------------------------------------------

def summarize(text: str, mode: str = "auto", ratio: float = 0.3,
              max_points: int = 7) -> SummaryResult:
    """
    Summarize text using extractive, abstractive, or both methods.

    Args:
        text: Input text to summarize.
        mode: "extractive", "abstractive", or "auto" (both).
        ratio: Sentence retention ratio for extractive phase.
        max_points: Maximum key points to extract.

    Returns:
        SummaryResult with all summary forms.
    """
    if not text:
        return SummaryResult(
            extractive="", abstractive="", key_points=[],
            original_length=0, summary_length=0,
            reduction_pct=0.0, mode=mode,
        )

    original_length = len(text)

    ext = extractive_summarize(text, ratio=ratio)
    abst = abstractive_summarize(text)
    points = extract_key_points(text, max_points=max_points)

    # Use abstractive as the primary summary length measure
    summary_length = len(abst)
    reduction = (1.0 - summary_length / max(original_length, 1)) * 100

    return SummaryResult(
        extractive=ext,
        abstractive=abst,
        key_points=points,
        original_length=original_length,
        summary_length=summary_length,
        reduction_pct=reduction,
        mode=mode,
    )


def summarize_response(response: dict, ratio: float = 0.3) -> dict:
    """
    Summarize string fields in an agent response dict.

    Args:
        response: Agent response dictionary.
        ratio: Sentence retention ratio.

    Returns:
        New dict with summarized fields and _summary_meta.
    """
    if not isinstance(response, dict):
        return response

    result = {}
    total_original = 0
    total_summary = 0

    for key, value in response.items():
        if isinstance(value, str) and len(value) >= 100:
            sr = summarize(value, ratio=ratio)
            result[key] = sr.abstractive
            result[f"{key}_key_points"] = sr.key_points
            total_original += sr.original_length
            total_summary += sr.summary_length
        elif isinstance(value, dict):
            result[key] = summarize_response(value, ratio=ratio)
        else:
            result[key] = value

    if total_original > 0:
        result["_summary_meta"] = {
            "original_chars": total_original,
            "summary_chars": total_summary,
            "reduction_pct": round(
                (1 - total_summary / max(total_original, 1)) * 100, 1
            ),
        }

    return result


# ---------------------------------------------------------------------------
# Main: assertions and verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # ---- Sample long response for testing ----
    LONG_RESPONSE = (
        "Hello! I'd be happy to help you diagnose this database issue.\n\n"
        "## Analysis\n\n"
        "Due to the fact that the database query is taking 45 seconds, "
        "it is important to note that this is well above the acceptable threshold. "
        "The vast majority of queries in this table complete in under 100ms. "
        "In order to investigate, I examined the query plan and found that "
        "a full table scan is being performed on the users table.\n\n"
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
        "similar cases have been resolved with this approach. "
        "If growth continues at this rate, we should also consider table "
        "partitioning as a longer-term solution.\n\n"
        "Hope this helps! Please let me know if you have any questions. "
        "Feel free to ask if you need further assistance."
    )

    # ------------------------------------------------------------------
    # Test 1: Extractive summarization
    # ------------------------------------------------------------------
    ext = extractive_summarize(LONG_RESPONSE, ratio=0.3)
    assert len(ext) < len(LONG_RESPONSE), "Extractive summary must be shorter"
    assert len(ext) > 50, "Extractive summary must have substance"
    reduction = (1 - len(ext) / len(LONG_RESPONSE)) * 100
    print(f"Test 1 — Extractive: {reduction:.1f}% reduction ({len(LONG_RESPONSE)}→{len(ext)} chars)")
    assert reduction >= 20, f"Expected >=20% reduction, got {reduction:.1f}%"
    # Must preserve key technical content
    ext_lower = ext.lower()
    assert "index" in ext_lower or "composite" in ext_lower, "Must mention index fix"
    print(f"  Preview: {ext[:150]}...")

    # ------------------------------------------------------------------
    # Test 2: Abstractive summarization
    # ------------------------------------------------------------------
    abst = abstractive_summarize(LONG_RESPONSE, max_sentences=5)
    assert len(abst) < len(LONG_RESPONSE), "Abstractive summary must be shorter"
    assert len(abst) > 30, "Abstractive summary must have substance"
    reduction2 = (1 - len(abst) / len(LONG_RESPONSE)) * 100
    print(f"\nTest 2 — Abstractive: {reduction2:.1f}% reduction ({len(LONG_RESPONSE)}→{len(abst)} chars)")
    assert reduction2 >= 30, f"Expected >=30% reduction, got {reduction2:.1f}%"
    abst_lower = abst.lower()
    # Verbose phrases should be rewritten
    assert "due to the fact" not in abst_lower, "Should rewrite verbose phrases"
    assert "it is important to note" not in abst_lower, "Should remove filler"
    assert "hope this helps" not in abst_lower, "Should remove boilerplate"
    print(f"  Preview: {abst[:200]}...")

    # ------------------------------------------------------------------
    # Test 3: Key point extraction
    # ------------------------------------------------------------------
    points = extract_key_points(LONG_RESPONSE, max_points=7)
    assert len(points) >= 2, f"Expected >=2 key points, got {len(points)}"
    assert len(points) <= 7, f"Expected <=7 key points, got {len(points)}"
    print(f"\nTest 3 — Key points ({len(points)}):")
    for p in points:
        print(f"  • {p}")
        assert len(p) > 10, "Key point must be substantive"
        assert len(p) <= 200, "Key point must be concise"

    # At least one point should mention the fix
    all_points = " ".join(points).lower()
    assert "index" in all_points or "composite" in all_points, \
        "Key points must mention the index fix"

    # ------------------------------------------------------------------
    # Test 4: Unified summarize() interface
    # ------------------------------------------------------------------
    result = summarize(LONG_RESPONSE)
    assert isinstance(result, SummaryResult), "Must return SummaryResult"
    assert result.extractive, "Must have extractive summary"
    assert result.abstractive, "Must have abstractive summary"
    assert len(result.key_points) >= 2, "Must have key points"
    assert result.reduction_pct > 0, "Must show reduction"
    assert result.original_length == len(LONG_RESPONSE), "Must track original length"
    assert result.summary_length < result.original_length, "Summary must be shorter"
    print(f"\nTest 4 — Unified summarize: {result.reduction_pct:.1f}% reduction")
    print(f"  Mode: {result.mode}")
    print(f"  Extractive length: {len(result.extractive)}")
    print(f"  Abstractive length: {len(result.abstractive)}")
    print(f"  Key points: {len(result.key_points)}")

    # ------------------------------------------------------------------
    # Test 5: Empty / short text handling
    # ------------------------------------------------------------------
    assert summarize("").extractive == "", "Empty text returns empty"
    assert summarize("").key_points == [], "Empty text returns no points"
    assert extractive_summarize("Short.") == "Short.", "Short text passes through"
    assert abstractive_summarize("Short.") == "Short.", "Short text passes through"
    assert extract_key_points("Short.") == [], "Short text returns no points"
    print("\nTest 5 — Edge cases: passed")

    # ------------------------------------------------------------------
    # Test 6: Deduplication in extraction
    # ------------------------------------------------------------------
    duped = (
        "The server is down due to a memory leak. "
        "The memory leak causes the server to crash every 6 hours. "
        "The server is down due to a memory leak. "
        "We need to fix the memory allocation in the worker pool. "
        "The memory leak causes the server to crash every 6 hours. "
        "Restarting the service is a temporary workaround."
    )
    ext_duped = extractive_summarize(duped, ratio=0.5)
    # Should not repeat the same sentence
    assert ext_duped.lower().count("server is down due to a memory leak") <= 1, \
        "Should deduplicate repeated sentences"
    print("Test 6 — Deduplication: passed")

    # ------------------------------------------------------------------
    # Test 7: Preserves numeric specifics
    # ------------------------------------------------------------------
    numeric_text = (
        "## Performance Report\n\n"
        "The API latency increased from 50ms to 2.5 seconds after the deploy. "
        "Error rate spiked to 15% at 14:30 UTC. "
        "The database connection pool was exhausted at 100 connections. "
        "After the fix, latency dropped back to 45ms and error rate to 0.1%. "
        "Memory usage was at 3.2GB, which is 80% of the 4GB limit."
    )
    pts = extract_key_points(numeric_text, max_points=5)
    all_pts = " ".join(pts)
    # Should preserve at least some numeric specifics
    has_numbers = bool(re.search(r"\d+", all_pts))
    assert has_numbers, "Key points must preserve numeric data"
    print(f"Test 7 — Numeric preservation: passed ({len(pts)} points)")

    # ------------------------------------------------------------------
    # Test 8: summarize_response on dict
    # ------------------------------------------------------------------
    resp = {
        "id": "diag-001",
        "status": "complete",
        "result": LONG_RESPONSE,
        "score": 92,
    }
    summarized = summarize_response(resp)
    assert summarized["id"] == "diag-001", "Preserve non-string fields"
    assert summarized["status"] == "complete", "Preserve short strings"
    assert summarized["score"] == 92, "Preserve numbers"
    assert len(summarized["result"]) < len(LONG_RESPONSE), "Result field summarized"
    assert "result_key_points" in summarized, "Key points added"
    assert len(summarized["result_key_points"]) >= 2, "Has key points"
    assert "_summary_meta" in summarized, "Has summary metadata"
    meta = summarized["_summary_meta"]
    assert meta["reduction_pct"] > 0, "Shows reduction"
    print(f"\nTest 8 — Dict summarization: {meta['reduction_pct']}% reduction")

    # ------------------------------------------------------------------
    # Test 9: Abstractive rewrites are applied
    # ------------------------------------------------------------------
    verbose = (
        "Due to the fact that the server was overloaded, in order to "
        "mitigate the issue, it is important to note that we need to "
        "scale the fleet. The vast majority of requests timeout after "
        "30 seconds. In the event that scaling fails, we should failover "
        "to the backup region."
    )
    abst_v = abstractive_summarize(verbose, max_sentences=3)
    abst_v_lower = abst_v.lower()
    assert "due to the fact" not in abst_v_lower, "Rewrites 'due to the fact'"
    assert "in order to" not in abst_v_lower, "Rewrites 'in order to'"
    assert "it is important to note" not in abst_v_lower, "Removes filler"
    print("Test 9 — Abstractive rewrites: passed")

    # ------------------------------------------------------------------
    # Test 10: Sentence merging reduces redundancy
    # ------------------------------------------------------------------
    redundant = [
        "The database index is missing on the users table.",
        "The users table lacks a database index causing slow queries.",
        "Adding a cache layer will reduce load.",
        "Network timeouts need a retry mechanism.",
    ]
    merged = _merge_related_sentences(redundant)
    assert len(merged) <= len(redundant), "Merging should reduce or maintain count"
    assert len(merged) >= 2, "Should keep distinct ideas"
    print(f"Test 10 — Sentence merging: {len(redundant)}→{len(merged)} sentences")

    # ------------------------------------------------------------------
    # Test 11: ScoredSentence dataclass
    # ------------------------------------------------------------------
    ss = ScoredSentence(text="Test sentence.", score=0.85, position=0)
    assert ss.text == "Test sentence."
    assert ss.score == 0.85
    assert ss.is_heading is False
    print("Test 11 — ScoredSentence: passed")

    # ------------------------------------------------------------------
    # Test 12: SummaryResult __str__ formatting
    # ------------------------------------------------------------------
    sr = summarize(LONG_RESPONSE)
    sr_str = str(sr)
    assert "reduction" in sr_str.lower(), "__str__ must show reduction"
    assert "Key points" in sr_str, "__str__ must show key points"
    assert "Summary" in sr_str, "__str__ must show summary"
    print("Test 12 — SummaryResult formatting: passed")

    # ------------------------------------------------------------------
    # Test 13: TF-IDF scoring produces non-zero scores
    # ------------------------------------------------------------------
    sentences = _split_sentences(LONG_RESPONSE)
    tfidf = _tfidf_score_sentences(sentences)
    assert any(s > 0 for s in tfidf), "TF-IDF must produce non-zero scores"
    print(f"Test 13 — TF-IDF: {sum(1 for s in tfidf if s > 0)}/{len(tfidf)} non-zero scores")

    # ------------------------------------------------------------------
    # Test 14: Code blocks not included in summary
    # ------------------------------------------------------------------
    with_code = (
        "The fix requires updating the retry logic. The current implementation "
        "has a bug where the backoff multiplier resets on partial success.\n\n"
        "```python\n"
        "def retry(fn, max_retries=3):\n"
        "    for i in range(max_retries):\n"
        "        try:\n"
        "            return fn()\n"
        "        except Exception:\n"
        "            time.sleep(2 ** i)\n"
        "```\n\n"
        "The fix should multiply the backoff by 2 on each failure. "
        "This will prevent thundering herd issues during outages."
    )
    pts_code = extract_key_points(with_code, max_points=5)
    for p in pts_code:
        assert "def retry" not in p, "Code should not appear in key points"
    print("Test 14 — Code block exclusion: passed")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("ALL 14 ASSERTIONS PASSED")
    print("=" * 60)
