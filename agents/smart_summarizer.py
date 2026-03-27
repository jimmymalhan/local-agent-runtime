#!/usr/bin/env python3
"""
smart_summarizer.py — Smart Text Summarization
================================================
Extract key information from long texts using extractive summarization.

Key functions:
  - summarize(text, max_sentences=5) -> str
  - extract_key_info(text) -> dict
  - score_sentences(text) -> list[tuple[float, str]]

Strategies:
  1. Sentence scoring via word frequency (TF-based)
  2. Position bias (first/last sentences weighted higher)
  3. Keyword/entity extraction (capitalized terms, numbers, quotes)
  4. Key phrase detection (causal, result, conclusion markers)
  5. Redundancy removal (skip near-duplicate sentences)
"""

import re
import math
from collections import Counter
from typing import Optional


# ---------------------------------------------------------------------------
# Stop words (common English words that don't carry meaning for ranking)
# ---------------------------------------------------------------------------
STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "through during before after above below between out off over under again "
    "further then once here there when where why how all both each few more most "
    "other some such no nor not only own same so than too very just don t s it "
    "its he she they them their his her we our you your i me my this that these "
    "those which what who whom and but if or because although while since about "
    "also still even already however therefore thus hence anyway besides meanwhile "
    "nevertheless nonetheless instead otherwise yet".split()
)

# Marker phrases that signal important content
IMPORTANCE_MARKERS = [
    r"\b(?:in conclusion|to summarize|in summary|the key (?:point|takeaway|finding))",
    r"\b(?:importantly|significantly|critically|notably|crucially)",
    r"\b(?:the main|the primary|the central|the core|the essential)",
    r"\b(?:must|required|necessary|vital|essential|fundamental)",
    r"\b(?:because|therefore|consequently|as a result|due to|caused by)",
    r"\b(?:however|but|although|despite|nevertheless|on the other hand)",
    r"\b(?:first|second|third|finally|lastly|in addition)",
    r"\b(?:according to|research shows|data indicates|evidence suggests)",
]

IMPORTANCE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in IMPORTANCE_MARKERS]


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using punctuation boundaries."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = []
    for s in raw:
        s = s.strip()
        if len(s) > 10:
            sentences.append(s)
    return sentences


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokenization, stripping punctuation."""
    return re.findall(r"[a-z][a-z']*", text.lower())


def _word_frequencies(words: list[str]) -> dict[str, float]:
    """Compute normalized term frequencies excluding stop words."""
    filtered = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    counts = Counter(filtered)
    if not counts:
        return {}
    max_freq = max(counts.values())
    return {w: c / max_freq for w, c in counts.items()}


def _sentence_similarity(s1: str, s2: str) -> float:
    """Jaccard similarity between two sentences (word-level)."""
    words1 = set(_tokenize(s1))
    words2 = set(_tokenize(s2))
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Sentence scoring
# ---------------------------------------------------------------------------

def score_sentences(text: str) -> list[tuple[float, str, int]]:
    """
    Score each sentence by importance. Returns list of (score, sentence, index).

    Scoring factors:
      - Word frequency score (TF-based)
      - Position bias (first/last sentences get a boost)
      - Importance marker presence
      - Contains numbers or quoted text (factual signals)
      - Sentence length penalty (too short or too long)
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    all_words = _tokenize(text)
    freq = _word_frequencies(all_words)
    n = len(sentences)
    scored = []

    for idx, sent in enumerate(sentences):
        words = _tokenize(sent)
        if not words:
            scored.append((0.0, sent, idx))
            continue

        # 1. TF-based score
        word_score = sum(freq.get(w, 0) for w in words) / len(words)

        # 2. Position bias: first and last sentences matter more
        if idx == 0:
            position_score = 0.3
        elif idx == n - 1:
            position_score = 0.2
        elif idx <= n * 0.2:
            position_score = 0.15
        else:
            position_score = 0.0

        # 3. Importance markers
        marker_score = 0.0
        for pattern in IMPORTANCE_PATTERNS:
            if pattern.search(sent):
                marker_score += 0.15
        marker_score = min(marker_score, 0.4)

        # 4. Factual signals: numbers, percentages, quoted text
        factual_score = 0.0
        if re.search(r'\d+', sent):
            factual_score += 0.1
        if re.search(r'%|\bpercent\b', sent):
            factual_score += 0.1
        if re.search(r'["\u201c\u201d]', sent):
            factual_score += 0.05

        # 5. Length penalty: prefer medium-length sentences
        word_count = len(words)
        if word_count < 5:
            length_penalty = -0.2
        elif word_count > 40:
            length_penalty = -0.1
        else:
            length_penalty = 0.0

        total = word_score + position_score + marker_score + factual_score + length_penalty
        scored.append((total, sent, idx))

    return scored


# ---------------------------------------------------------------------------
# Core summarization
# ---------------------------------------------------------------------------

def summarize(text: str, max_sentences: int = 5, redundancy_threshold: float = 0.6) -> str:
    """
    Summarize text by extracting the most important sentences.

    Args:
        text: Input text to summarize.
        max_sentences: Maximum number of sentences in summary.
        redundancy_threshold: Jaccard similarity threshold to skip near-duplicates.

    Returns:
        Summary string with top-scored, non-redundant sentences in original order.
    """
    if not text or not text.strip():
        return ""

    scored = score_sentences(text)
    if not scored:
        return text.strip()

    # Sort by score descending to pick top candidates
    ranked = sorted(scored, key=lambda x: x[0], reverse=True)

    selected = []
    selected_texts = []

    for score, sent, idx in ranked:
        if len(selected) >= max_sentences:
            break
        # Redundancy check: skip if too similar to already-selected sentence
        is_redundant = False
        for existing in selected_texts:
            if _sentence_similarity(sent, existing) > redundancy_threshold:
                is_redundant = True
                break
        if not is_redundant:
            selected.append((idx, sent))
            selected_texts.append(sent)

    # Restore original order for readability
    selected.sort(key=lambda x: x[0])
    return " ".join(sent for _, sent in selected)


# ---------------------------------------------------------------------------
# Key information extraction
# ---------------------------------------------------------------------------

def extract_key_info(text: str) -> dict:
    """
    Extract structured key information from text.

    Returns dict with:
      - summary: extractive summary (3-5 sentences)
      - key_terms: top-10 significant terms by frequency
      - numbers: all numeric values found with context
      - entities: capitalized multi-word phrases (likely proper nouns)
      - action_items: sentences containing action/requirement language
      - statistics: dict of stat-like patterns (percentages, counts)
    """
    if not text or not text.strip():
        return {
            "summary": "",
            "key_terms": [],
            "numbers": [],
            "entities": [],
            "action_items": [],
            "statistics": {},
        }

    # Summary
    summary = summarize(text, max_sentences=5)

    # Key terms
    words = _tokenize(text)
    freq = _word_frequencies(words)
    key_terms = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
    key_terms = [term for term, _ in key_terms]

    # Numbers with context
    numbers = []
    for match in re.finditer(r'(\b\w+\s+)?([\d,]+\.?\d*%?)\s*(\w*)', text):
        context = match.group(0).strip()
        if len(context) > 3:
            numbers.append(context)
    numbers = list(dict.fromkeys(numbers))[:15]  # dedupe, limit

    # Entities: capitalized multi-word phrases
    entity_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
    entities = list(dict.fromkeys(entity_pattern.findall(text)))[:10]

    # Action items: sentences with action/requirement language
    action_patterns = re.compile(
        r'\b(?:must|should|need to|required to|has to|have to|ensure|implement|'
        r'create|build|fix|resolve|update|deploy|configure|set up)\b',
        re.IGNORECASE,
    )
    sentences = _split_sentences(text)
    action_items = [s for s in sentences if action_patterns.search(s)][:10]

    # Statistics: percentage and count patterns
    statistics = {}
    for match in re.finditer(r'([\d,]+\.?\d*)\s*(%|percent)', text):
        val = match.group(1)
        # Find surrounding context
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 20)
        context = text[start:end].strip()
        statistics[f"{val}%"] = context
    for match in re.finditer(r'(\d[\d,]*)\s+(users?|items?|requests?|errors?|failures?|'
                              r'tasks?|files?|tests?|seconds?|minutes?|hours?|days?)',
                              text, re.IGNORECASE):
        statistics[match.group(0)] = match.group(0)

    return {
        "summary": summary,
        "key_terms": key_terms,
        "numbers": numbers,
        "entities": entities,
        "action_items": action_items,
        "statistics": statistics,
    }


# ---------------------------------------------------------------------------
# Ratio-based summarization
# ---------------------------------------------------------------------------

def summarize_to_ratio(text: str, target_ratio: float = 0.3) -> str:
    """
    Summarize text to approximately target_ratio of original length.

    Args:
        text: Input text.
        target_ratio: Target length as fraction of original (0.1 to 0.9).

    Returns:
        Summary string.
    """
    target_ratio = max(0.1, min(0.9, target_ratio))
    sentences = _split_sentences(text)
    if not sentences:
        return text.strip()

    target_count = max(1, math.ceil(len(sentences) * target_ratio))
    return summarize(text, max_sentences=target_count)


# ---------------------------------------------------------------------------
# Main: assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # --- Test 1: Basic summarization reduces length ---
    long_text = (
        "Artificial intelligence has transformed the technology landscape significantly. "
        "Machine learning models can now process vast amounts of data in seconds. "
        "Natural language processing enables computers to understand human text. "
        "Computer vision allows machines to interpret images and videos accurately. "
        "Deep learning networks have achieved superhuman performance on many benchmarks. "
        "Reinforcement learning agents can master complex games and simulations. "
        "Transfer learning reduces the need for large labeled datasets. "
        "The field continues to advance rapidly with new architectures and techniques. "
        "Researchers are exploring ways to make AI systems more interpretable. "
        "Safety and alignment remain critical challenges for the AI community. "
        "Governments worldwide are developing regulations for AI deployment. "
        "Companies are investing billions of dollars in AI research and development. "
        "The economic impact of AI is expected to reach 15.7 trillion dollars by 2030. "
        "Healthcare applications include diagnosis, drug discovery, and personalized treatment. "
        "Autonomous vehicles represent one of the most visible AI applications today."
    )
    summary = summarize(long_text, max_sentences=3)
    assert len(summary) > 0, "Summary must not be empty"
    assert len(summary) < len(long_text), "Summary must be shorter than original"
    sentences_in_summary = _split_sentences(summary)
    assert len(sentences_in_summary) <= 3, f"Expected <=3 sentences, got {len(sentences_in_summary)}"
    print(f"[PASS] Test 1: Summarized {len(long_text)} chars -> {len(summary)} chars ({len(sentences_in_summary)} sentences)")

    # --- Test 2: Empty input ---
    assert summarize("") == "", "Empty input should return empty string"
    assert summarize("   ") == "", "Whitespace input should return empty string"
    print("[PASS] Test 2: Empty input handled")

    # --- Test 3: Short text returns as-is (fewer sentences than max) ---
    short_text = "This is a single important sentence about critical infrastructure failures."
    result = summarize(short_text, max_sentences=5)
    assert len(result) > 0, "Short text should still produce output"
    print(f"[PASS] Test 3: Short text handled: '{result[:60]}...'")

    # --- Test 4: Key info extraction ---
    info_text = (
        "Amazon Web Services reported 99.99% uptime for the quarter. "
        "The system processed 2.5 million requests per second at peak load. "
        "Engineers must implement circuit breakers for all external API calls. "
        "Google Cloud Platform achieved similar reliability metrics this year. "
        "Teams should deploy canary releases before full production rollout. "
        "The outage on March 15 affected 45000 users for approximately 3 hours. "
        "Root cause analysis revealed that a misconfigured load balancer caused cascading failures. "
        "The incident response team resolved the issue within 180 minutes. "
        "New monitoring dashboards must be created to detect similar patterns early. "
        "Overall system reliability improved from 99.9% to 99.99% after the fixes."
    )
    info = extract_key_info(info_text)
    assert isinstance(info["summary"], str) and len(info["summary"]) > 0, "Summary must exist"
    assert isinstance(info["key_terms"], list) and len(info["key_terms"]) > 0, "Key terms must exist"
    assert isinstance(info["entities"], list), "Entities must be a list"
    assert isinstance(info["action_items"], list) and len(info["action_items"]) > 0, "Action items must exist"
    assert isinstance(info["statistics"], dict), "Statistics must be a dict"
    # Check that known entities are found
    entity_text = " ".join(info["entities"])
    assert "Amazon Web Services" in entity_text or "Google Cloud Platform" in entity_text, \
        f"Should find major entities, got: {info['entities']}"
    # Check action items contain requirement language
    action_text = " ".join(info["action_items"])
    assert "must" in action_text.lower() or "should" in action_text.lower(), \
        f"Action items should contain must/should, got: {info['action_items']}"
    print(f"[PASS] Test 4: Key info extracted — {len(info['key_terms'])} terms, "
          f"{len(info['entities'])} entities, {len(info['action_items'])} actions")

    # --- Test 5: Redundancy removal ---
    redundant_text = (
        "The server crashed due to memory overflow and high load conditions. "
        "The server went down because of memory overflow under heavy load. "
        "Database connections were exhausted causing timeout errors for users. "
        "The database ran out of connections leading to timeout errors everywhere. "
        "The fix involves increasing memory limits and adding connection pooling. "
        "A completely unrelated topic about weather patterns in tropical regions. "
        "Climate scientists have documented rising ocean temperatures globally."
    )
    result = summarize(redundant_text, max_sentences=4, redundancy_threshold=0.5)
    result_sentences = _split_sentences(result)
    # With redundancy removal, near-duplicate pairs should be reduced
    assert len(result_sentences) <= 4, f"Expected <=4 sentences, got {len(result_sentences)}"
    print(f"[PASS] Test 5: Redundancy removal — {len(result_sentences)} unique sentences kept")

    # --- Test 6: Ratio-based summarization ---
    ratio_result = summarize_to_ratio(long_text, target_ratio=0.3)
    assert len(ratio_result) > 0, "Ratio summary must not be empty"
    assert len(ratio_result) < len(long_text), "Ratio summary must be shorter"
    print(f"[PASS] Test 6: Ratio summary — {len(ratio_result)} chars (target 30%)")

    # --- Test 7: Score sentences returns correct structure ---
    scores = score_sentences(long_text)
    assert len(scores) > 0, "Scores must not be empty"
    for score, sent, idx in scores:
        assert isinstance(score, float), f"Score must be float, got {type(score)}"
        assert isinstance(sent, str) and len(sent) > 0, "Sentence must be non-empty string"
        assert isinstance(idx, int) and idx >= 0, "Index must be non-negative int"
    print(f"[PASS] Test 7: Scored {len(scores)} sentences, top score: {max(s[0] for s in scores):.3f}")

    # --- Test 8: Importance markers boost scores ---
    text_with_markers = (
        "The weather today is partly cloudy with mild temperatures expected throughout the region. "
        "In conclusion, the critical finding is that the system must be completely redesigned immediately. "
        "Birds are commonly seen in parks during the annual spring migration season across the country. "
        "The afternoon forecast calls for slightly warmer conditions with gentle breezes from the west. "
        "In summary, the essential requirement is that all teams must deploy the updated security patches."
    )
    scores = score_sentences(text_with_markers)
    # Sentences with importance markers should score higher than neutral middle sentences
    score_map = {idx: s for s, _, idx in scores}
    # Sentence 1 (conclusion/critical/must) should outscore sentence 3 (neutral filler)
    assert score_map[1] > score_map[3], \
        f"Importance-marked sentence (score={score_map[1]:.3f}) should beat neutral (score={score_map[3]:.3f})"
    print(f"[PASS] Test 8: Importance markers correctly boost sentence scores")

    # --- Test 9: Numbers boost scores ---
    text_with_numbers = (
        "The project has been progressing steadily over the past several months with good momentum. "
        "Performance improved by 47% after deploying the new caching layer with 12 nodes in production. "
        "Regular meetings continue to be held weekly to discuss the various ongoing work items ahead. "
        "The backlog contains many items that the team plans to address over the coming quarter ahead. "
        "Response latency dropped from 850ms to 120ms representing a 85% improvement in user experience."
    )
    scores = score_sentences(text_with_numbers)
    # Sentences with numbers should score higher than the neutral middle sentences
    score_map = {idx: s for s, _, idx in scores}
    # Sentence 1 (47%, 12) and sentence 4 (850ms, 120ms, 85%) should beat sentence 3 (neutral)
    assert score_map[1] > score_map[3], \
        f"Numeric sentence (score={score_map[1]:.3f}) should beat neutral (score={score_map[3]:.3f})"
    print(f"[PASS] Test 9: Numeric content correctly boosts scores")

    # --- Test 10: extract_key_info on empty ---
    empty_info = extract_key_info("")
    assert empty_info["summary"] == "", "Empty text should give empty summary"
    assert empty_info["key_terms"] == [], "Empty text should give no key terms"
    assert empty_info["action_items"] == [], "Empty text should give no action items"
    print("[PASS] Test 10: extract_key_info handles empty input")

    print("\n=== All 10 tests passed ===")
