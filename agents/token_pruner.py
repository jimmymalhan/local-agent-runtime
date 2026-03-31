#!/usr/bin/env python3
"""
token_pruner.py — Token-Level Pruning Engine
=============================================
Identifies and removes low-value tokens from text to reduce token count
while preserving semantic meaning and critical information.

Unlike response_compressor.py (which operates on phrases/sentences), this module
works at the individual token level using information-theoretic scoring:
  - TF-IDF signals to identify low-information tokens
  - Entropy-based scoring to detect redundant tokens
  - Positional decay to deprioritize tokens far from key terms
  - Domain-aware stop lists tuned for agent/code responses

Key functions:
  - prune(text, budget) -> str: Prune text to fit within a token budget
  - score_tokens(text) -> list[TokenScore]: Score each token by value
  - estimate_savings(text, budget) -> PruningSummary: Preview pruning impact
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Token value scoring
# ---------------------------------------------------------------------------

@dataclass
class TokenScore:
    """Score for a single token indicating its informational value."""
    token: str
    index: int
    score: float  # 0.0 = no value, 1.0 = critical
    category: str  # "stop", "filler", "structural", "content", "critical"
    prunable: bool = True


@dataclass
class PruningSummary:
    """Summary of pruning operation or preview."""
    original_tokens: int
    pruned_tokens: int
    removed_tokens: int
    reduction_pct: float
    tokens_by_category: dict = field(default_factory=dict)
    preserved_keywords: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Domain-specific token classifications
# ---------------------------------------------------------------------------

# Tokens with near-zero informational value in agent responses
STOP_TOKENS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "must",
    "am", "it", "its", "i", "we", "you", "they", "he", "she",
    "me", "us", "him", "her", "them", "my", "our", "your", "their",
    "this", "that", "these", "those", "which", "who", "whom", "whose",
    "what", "where", "when", "how", "why",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "about", "up", "down", "out",
    "and", "or", "but", "nor", "so", "yet", "both", "either", "neither",
    "not", "no", "if", "then", "else", "than", "also", "too",
    "very", "really", "just", "quite", "rather", "somewhat",
    "here", "there", "now", "then", "still", "already", "again",
})

# Filler tokens that pad responses without adding meaning
FILLER_TOKENS = frozenset({
    "basically", "actually", "essentially", "simply", "clearly",
    "obviously", "certainly", "definitely", "absolutely", "literally",
    "perhaps", "maybe", "possibly", "probably", "likely",
    "generally", "typically", "usually", "normally", "often",
    "specifically", "particularly", "especially", "notably",
    "importantly", "interestingly", "unfortunately", "fortunately",
    "however", "therefore", "furthermore", "moreover", "nevertheless",
    "consequently", "accordingly", "meanwhile", "otherwise",
    "apparently", "seemingly", "reportedly", "supposedly",
    "honestly", "frankly", "admittedly",
})

# Structural tokens: headers, bullets, formatting — low value if redundant
STRUCTURAL_PATTERNS = [
    r"^#{1,6}\s",        # markdown headers
    r"^[-*•]\s",         # bullet points
    r"^---+$",           # horizontal rules
    r"^\d+\.\s",         # numbered lists
    r"^>\s",             # blockquotes
]

# Critical domain terms that must never be pruned (agent/code context)
CRITICAL_PATTERNS = [
    r"\b(?:error|exception|fail|crash|bug|issue|problem)\b",
    r"\b(?:fix|patch|resolve|solution|workaround)\b",
    r"\b(?:timeout|retry|backoff|circuit.?breaker)\b",
    r"\b(?:index|query|table|column|schema|migration)\b",
    r"\b(?:api|endpoint|route|request|response)\b",
    r"\b(?:test|assert|expect|mock|stub)\b",
    r"\b(?:deploy|rollback|revert|release|merge)\b",
    r"\b(?:config|env|secret|credential|token)\b",
    r"\b(?:cache|memory|cpu|disk|network|latency)\b",
    r"\b(?:log|metric|alert|monitor|trace)\b",
    r"\b\d+(?:\.\d+)?(?:ms|s|m|h|MB|GB|TB|%|x)\b",  # measurements
    r"\b(?:p50|p95|p99|SLA|SLO|SLI)\b",
    r"\b[A-Z_]{2,}\b",  # constants/env vars (e.g., MAX_RETRIES)
    r"`[^`]+`",          # inline code
]

_CRITICAL_RE = [
    re.compile(p) if p == r"\b[A-Z_]{2,}\b"
    else re.compile(p, re.IGNORECASE)
    for p in CRITICAL_PATTERNS
]


# ---------------------------------------------------------------------------
# Tokenizer (word-level, preserving structure)
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Split text into tokens preserving whitespace boundaries and punctuation."""
    return re.findall(r"\S+|\n", text)


def detokenize(tokens: list[str]) -> str:
    """Reconstruct text from tokens with appropriate spacing."""
    if not tokens:
        return ""
    parts = []
    for i, tok in enumerate(tokens):
        if tok == "\n":
            parts.append("\n")
        elif i > 0 and tokens[i - 1] != "\n":
            parts.append(" " + tok)
        else:
            parts.append(tok)
    return "".join(parts)


def estimate_token_count(text: str) -> int:
    """Estimate LLM token count (words * 1.3 heuristic for English)."""
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.3))


# ---------------------------------------------------------------------------
# TF-IDF scoring
# ---------------------------------------------------------------------------

def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """Compute term frequency for each token (normalized)."""
    lower_tokens = [t.lower().strip(".,;:!?\"'()[]{}") for t in tokens if t != "\n"]
    counts = Counter(lower_tokens)
    total = len(lower_tokens) or 1
    return {term: count / total for term, count in counts.items()}


def _compute_idf(tokens: list[str], window_size: int = 50) -> dict[str, float]:
    """Compute inverse document frequency using sliding windows as 'documents'."""
    lower_tokens = [t.lower().strip(".,;:!?\"'()[]{}") for t in tokens if t != "\n"]
    n_windows = max(1, len(lower_tokens) // window_size)
    doc_counts: Counter = Counter()
    for i in range(n_windows):
        start = i * window_size
        end = min(start + window_size, len(lower_tokens))
        window_terms = set(lower_tokens[start:end])
        for term in window_terms:
            doc_counts[term] += 1
    return {
        term: math.log(n_windows / (1 + count))
        for term, count in doc_counts.items()
    }


# ---------------------------------------------------------------------------
# Core scoring engine
# ---------------------------------------------------------------------------

def _is_in_code_block(text: str, pos: int) -> bool:
    """Check if a character position falls inside a fenced code block."""
    before = text[:pos]
    return before.count("```") % 2 == 1


def _classify_token(token: str) -> str:
    """Classify a token into a value category."""
    clean = token.lower().strip(".,;:!?\"'()[]{}#*->")

    # Check critical patterns first (highest priority)
    for pattern in _CRITICAL_RE:
        if pattern.search(token):
            return "critical"

    # Inline code is always critical
    if token.startswith("`") and token.endswith("`"):
        return "critical"

    # Numbers with units are critical
    if re.match(r"^\d+(?:\.\d+)?(?:ms|s|m|h|MB|GB|TB|%|x)?$", clean):
        return "critical"

    # Stop tokens
    if clean in STOP_TOKENS:
        return "stop"

    # Filler tokens
    if clean in FILLER_TOKENS:
        return "filler"

    # Structural markers
    if re.match(r"^#{1,6}$", token):
        return "structural"
    for pattern in STRUCTURAL_PATTERNS:
        if re.match(pattern, token):
            return "structural"

    return "content"


def score_tokens(text: str) -> list[TokenScore]:
    """
    Score each token in text by its informational value.

    Returns a list of TokenScore objects, one per token.
    Higher score = more valuable = should be preserved.
    """
    if not text:
        return []

    tokens = tokenize(text)
    tf = _compute_tf(tokens)
    idf = _compute_idf(tokens)

    # Build positional proximity to critical terms
    critical_positions = set()
    for i, tok in enumerate(tokens):
        if _classify_token(tok) == "critical":
            critical_positions.add(i)

    scores = []
    for i, token in enumerate(tokens):
        if token == "\n":
            scores.append(TokenScore(
                token=token, index=i, score=1.0,
                category="structural", prunable=False
            ))
            continue

        category = _classify_token(token)
        clean = token.lower().strip(".,;:!?\"'()[]{}#*->")

        # Base score from TF-IDF
        tf_val = tf.get(clean, 0.0)
        idf_val = idf.get(clean, 0.0)
        tfidf = tf_val * max(0, idf_val)

        # Category-based base scores
        category_base = {
            "critical": 1.0,
            "content": 0.5,
            "structural": 0.3,
            "filler": 0.1,
            "stop": 0.05,
        }
        base = category_base.get(category, 0.3)

        # Proximity boost: tokens near critical terms get score boost
        proximity_boost = 0.0
        if critical_positions:
            min_dist = min(abs(i - cp) for cp in critical_positions)
            if min_dist <= 3:
                proximity_boost = 0.3 * (1.0 - min_dist / 4.0)

        # TF-IDF contribution (normalized to 0-0.3 range)
        tfidf_boost = min(0.3, tfidf * 10)

        # Final score
        final_score = min(1.0, base + proximity_boost + tfidf_boost)

        # Determine if prunable (never prune critical or structural tokens)
        prunable = category not in ("critical", "structural") and final_score < 0.6

        # Check if inside code block — never prune code
        char_pos = sum(len(tokens[j]) + 1 for j in range(i))
        if _is_in_code_block(text, min(char_pos, len(text) - 1)):
            prunable = False
            final_score = 1.0
            category = "critical"

        scores.append(TokenScore(
            token=token, index=i, score=final_score,
            category=category, prunable=prunable
        ))

    return scores


# ---------------------------------------------------------------------------
# Pruning engine
# ---------------------------------------------------------------------------

def prune(text: str, budget: Optional[int] = None, target_ratio: float = 0.7) -> str:
    """
    Prune low-value tokens from text to fit within a token budget.

    Args:
        text: Input text to prune.
        budget: Maximum token count for output. If None, uses target_ratio.
        target_ratio: Target size as fraction of original (default 0.7 = 70%).

    Returns:
        Pruned text with low-value tokens removed.
    """
    if not text or not text.strip():
        return text

    current_count = estimate_token_count(text)
    if budget is None:
        budget = max(1, int(current_count * target_ratio))

    # If already within budget, return as-is
    if current_count <= budget:
        return text

    token_scores = score_tokens(text)
    if not token_scores:
        return text

    # Sort prunable tokens by score (lowest first = remove first)
    prunable_indices = [
        (ts.score, ts.index)
        for ts in token_scores
        if ts.prunable
    ]
    prunable_indices.sort(key=lambda x: x[0])

    # Calculate how many tokens to remove
    tokens_to_remove = current_count - budget
    removal_set = set()

    for score, idx in prunable_indices:
        if len(removal_set) >= tokens_to_remove:
            break
        removal_set.add(idx)

    # Reconstruct text without removed tokens, cleaning up spacing
    kept_tokens = [
        ts.token for ts in token_scores
        if ts.index not in removal_set
    ]

    result = detokenize(kept_tokens)

    # Clean up artifacts from removal
    result = re.sub(r" {2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"^\s+", "", result, flags=re.MULTILINE)
    # Remove orphaned punctuation
    result = re.sub(r"(?<!\w)[,;:]\s", " ", result)
    result = re.sub(r" {2,}", " ", result)

    return result.strip()


def prune_to_budget(text: str, max_tokens: int) -> str:
    """Convenience wrapper: prune text to fit exactly within max_tokens."""
    return prune(text, budget=max_tokens)


# ---------------------------------------------------------------------------
# Savings estimator
# ---------------------------------------------------------------------------

def estimate_savings(text: str, budget: Optional[int] = None,
                     target_ratio: float = 0.7) -> PruningSummary:
    """
    Preview how pruning would affect the text without actually pruning.

    Returns a PruningSummary with token counts and category breakdown.
    """
    if not text:
        return PruningSummary(
            original_tokens=0, pruned_tokens=0,
            removed_tokens=0, reduction_pct=0.0
        )

    current_count = estimate_token_count(text)
    if budget is None:
        budget = max(1, int(current_count * target_ratio))

    token_scores = score_tokens(text)

    # Count by category
    category_counts: dict[str, int] = {}
    for ts in token_scores:
        cat = ts.category
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Simulate pruning
    prunable = sorted(
        [(ts.score, ts.index) for ts in token_scores if ts.prunable],
        key=lambda x: x[0]
    )

    tokens_to_remove = max(0, current_count - budget)
    removable = min(len(prunable), tokens_to_remove)

    # Identify preserved keywords
    critical_tokens = [
        ts.token for ts in token_scores
        if ts.category == "critical" and ts.token != "\n"
    ]
    # Deduplicate while preserving order
    seen = set()
    preserved = []
    for t in critical_tokens:
        clean = t.lower().strip(".,;:!?\"'()[]{}#*->")
        if clean not in seen and clean:
            seen.add(clean)
            preserved.append(t)

    pruned_count = max(1, current_count - removable)
    reduction = (1.0 - pruned_count / current_count) * 100 if current_count > 0 else 0.0

    return PruningSummary(
        original_tokens=current_count,
        pruned_tokens=pruned_count,
        removed_tokens=removable,
        reduction_pct=round(reduction, 1),
        tokens_by_category=category_counts,
        preserved_keywords=preserved[:20],
    )


# ---------------------------------------------------------------------------
# Batch pruning for agent responses
# ---------------------------------------------------------------------------

def prune_response(response: dict, budget_per_field: Optional[int] = None,
                   target_ratio: float = 0.7) -> dict:
    """
    Prune all string fields in a response dict.

    Args:
        response: Agent response dict with string values.
        budget_per_field: Max tokens per field. If None, uses target_ratio.
        target_ratio: Target ratio for each field.

    Returns:
        New dict with pruned string values and _pruning_meta.
    """
    if not isinstance(response, dict):
        return response

    original_total = 0
    pruned_total = 0
    result = {}

    for key, value in response.items():
        if isinstance(value, str) and len(value) >= 30:
            orig_count = estimate_token_count(value)
            original_total += orig_count
            pruned_value = prune(value, budget=budget_per_field, target_ratio=target_ratio)
            pruned_count = estimate_token_count(pruned_value)
            pruned_total += pruned_count
            result[key] = pruned_value
        elif isinstance(value, dict):
            inner = prune_response(value, budget_per_field, target_ratio)
            if isinstance(inner, dict) and "_pruning_meta" in inner:
                meta = inner.pop("_pruning_meta")
                original_total += meta.get("original_tokens", 0)
                pruned_total += meta.get("pruned_tokens", 0)
            result[key] = inner
        else:
            result[key] = value

    if original_total > 0:
        result["_pruning_meta"] = {
            "original_tokens": original_total,
            "pruned_tokens": pruned_total,
            "removed_tokens": original_total - pruned_total,
            "reduction_pct": round((1 - pruned_total / original_total) * 100, 1),
        }

    return result


if __name__ == "__main__":
    # ==================================================================
    # Test 1: Tokenizer round-trip
    # ==================================================================
    text1 = "The quick brown fox jumps over the lazy dog."
    tokens1 = tokenize(text1)
    rebuilt = detokenize(tokens1)
    assert rebuilt == text1, f"Round-trip failed: {rebuilt!r} != {text1!r}"
    print("Test 1 — Tokenizer round-trip: PASSED")

    # ==================================================================
    # Test 2: Token classification
    # ==================================================================
    assert _classify_token("the") == "stop"
    assert _classify_token("basically") == "filler"
    assert _classify_token("error") == "critical"
    assert _classify_token("timeout") == "critical"
    assert _classify_token("`fix_query`") == "critical"
    assert _classify_token("45ms") == "critical"
    assert _classify_token("MAX_RETRIES") == "critical"
    assert _classify_token("database") == "content"
    print("Test 2 — Token classification: PASSED")

    # ==================================================================
    # Test 3: Score tokens produces valid scores
    # ==================================================================
    text3 = "The error timeout was basically 45ms on the API endpoint."
    scores3 = score_tokens(text3)
    assert len(scores3) > 0, "Should produce scores"
    for ts in scores3:
        assert 0.0 <= ts.score <= 1.0, f"Score out of range: {ts.score}"

    critical_tokens = [ts for ts in scores3 if ts.category == "critical"]
    assert any("error" in ts.token.lower() for ts in critical_tokens), \
        "error should be critical"
    assert any("timeout" in ts.token.lower() for ts in critical_tokens), \
        "timeout should be critical"
    assert any("45ms" in ts.token for ts in critical_tokens), \
        "45ms should be critical"
    print("Test 3 — Token scoring: PASSED")

    # ==================================================================
    # Test 4: Basic pruning reduces token count
    # ==================================================================
    verbose_text = (
        "Basically, the very important thing is that the database query "
        "was actually really quite slow, essentially taking about 45 seconds "
        "to complete. The error was obviously a timeout on the API endpoint. "
        "Clearly, we should probably definitely add an index to the users table. "
        "Generally, this would typically fix the problem. Furthermore, the "
        "retry logic should certainly handle the transient failures appropriately."
    )
    pruned = prune(verbose_text, target_ratio=0.6)
    orig_count = estimate_token_count(verbose_text)
    pruned_count = estimate_token_count(pruned)
    reduction = (1 - pruned_count / orig_count) * 100
    assert pruned_count < orig_count, "Pruning should reduce token count"
    assert reduction >= 15, f"Expected >= 15% reduction, got {reduction:.1f}%"
    # Critical terms must survive
    assert "45" in pruned, "Must preserve measurement '45'"
    assert "error" in pruned.lower(), "Must preserve 'error'"
    assert "timeout" in pruned.lower(), "Must preserve 'timeout'"
    assert "index" in pruned.lower(), "Must preserve 'index'"
    print(f"Test 4 — Basic pruning: PASSED ({reduction:.1f}% reduction)")

    # ==================================================================
    # Test 5: Budget-constrained pruning
    # ==================================================================
    long_text = (
        "The database query is experiencing a significant timeout error. "
        "The API endpoint returns a 500 error after 30 seconds. "
        "We need to add retry logic with exponential backoff. "
        "The fix involves adding a composite index on the users table. "
        "Monitor the p95 latency after deploying the fix. "
        "The current p95 is 45s which is well above the SLA of 200ms."
    )
    budget = 40
    pruned5 = prune_to_budget(long_text, max_tokens=budget)
    count5 = estimate_token_count(pruned5)
    assert count5 <= budget + 5, f"Should be near budget {budget}, got {count5}"
    assert "error" in pruned5.lower(), "Critical term 'error' must survive"
    assert "timeout" in pruned5.lower() or "30" in pruned5, \
        "Key diagnostic info must survive"
    print(f"Test 5 — Budget pruning: PASSED (budget={budget}, actual={count5})")

    # ==================================================================
    # Test 6: Code blocks are never pruned
    # ==================================================================
    code_text = (
        "Basically, the fix is very simple and quite straightforward:\n\n"
        "```python\n"
        "def retry(fn, max_retries=3):\n"
        "    for i in range(max_retries):\n"
        "        try:\n"
        "            return fn()\n"
        "        except Exception:\n"
        "            if i == max_retries - 1:\n"
        "                raise\n"
        "```\n\n"
        "This should basically definitely fix the very annoying problem."
    )
    pruned6 = prune(code_text, target_ratio=0.6)
    assert "def retry" in pruned6, "Code block must be preserved"
    assert "max_retries" in pruned6, "Code content must be preserved"
    assert "raise" in pruned6, "Code keywords must be preserved"
    print("Test 6 — Code block preservation: PASSED")

    # ==================================================================
    # Test 7: Estimate savings preview
    # ==================================================================
    summary = estimate_savings(verbose_text, target_ratio=0.6)
    assert summary.original_tokens > 0
    assert summary.removed_tokens >= 0
    assert summary.reduction_pct >= 0
    assert len(summary.tokens_by_category) > 0
    assert "stop" in summary.tokens_by_category
    assert "critical" in summary.tokens_by_category
    assert len(summary.preserved_keywords) > 0
    print(f"Test 7 — Savings estimate: PASSED "
          f"(would remove {summary.removed_tokens} tokens, "
          f"{summary.reduction_pct}% reduction)")

    # ==================================================================
    # Test 8: Response dict pruning
    # ==================================================================
    response = {
        "id": "task-42",
        "status": "done",
        "quality_score": 85,
        "result": (
            "Basically, the very important root cause was actually a "
            "missing index on the users table. The error timeout of 45s "
            "was essentially caused by a full table scan on the database. "
            "We should definitely probably add a composite index. "
            "Furthermore, the API endpoint retry logic should be improved."
        ),
        "pipeline": {
            "router": (
                "The classification is obviously DB_PERF. "
                "Basically all similar errors are typically database issues. "
                "The query timeout clearly indicates a missing index problem."
            ),
        },
    }
    pruned_resp = prune_response(response, target_ratio=0.65)
    assert pruned_resp["id"] == "task-42", "Non-string fields preserved"
    assert pruned_resp["quality_score"] == 85, "Numbers preserved"
    assert "_pruning_meta" in pruned_resp, "Meta included"
    meta = pruned_resp["_pruning_meta"]
    assert meta["removed_tokens"] >= 0, "Removed count valid"
    assert "index" in pruned_resp["result"].lower(), "Critical term preserved"
    assert "error" in pruned_resp["result"].lower() or "timeout" in pruned_resp["result"].lower(), \
        "Diagnostic terms preserved"
    print(f"Test 8 — Response pruning: PASSED "
          f"({meta['reduction_pct']}% reduction)")

    # ==================================================================
    # Test 9: Empty and short text passthrough
    # ==================================================================
    assert prune("", target_ratio=0.5) == ""
    assert prune("   ", target_ratio=0.5) == "   "
    short = "Error: timeout"
    assert prune(short, target_ratio=0.5) == short, "Short text unchanged"
    print("Test 9 — Edge cases: PASSED")

    # ==================================================================
    # Test 10: Critical terms always survive aggressive pruning
    # ==================================================================
    diagnostic = (
        "The error on the API endpoint caused a timeout after 30s. "
        "The fix is to add retry logic with exponential backoff. "
        "Deploy the patch and monitor p95 latency. "
        "Rollback if the SLA is still breached."
    )
    aggressive = prune(diagnostic, target_ratio=0.4)
    for keyword in ["error", "timeout", "30s", "retry", "p95", "rollback"]:
        assert keyword.lower() in aggressive.lower(), \
            f"Critical term '{keyword}' must survive aggressive pruning"
    print("Test 10 — Critical term survival: PASSED")

    # ==================================================================
    # Test 11: Filler-heavy text gets significant reduction
    # ==================================================================
    filler_heavy = (
        "Basically, I essentially want to obviously clearly explain that "
        "the problem is certainly definitely probably a timeout. "
        "Honestly, furthermore, apparently the server is generally usually "
        "typically performing somewhat rather quite slowly. Nevertheless, "
        "the error indicates a very really important issue."
    )
    pruned11 = prune(filler_heavy, target_ratio=0.5)
    orig11 = estimate_token_count(filler_heavy)
    pruned11_count = estimate_token_count(pruned11)
    reduction11 = (1 - pruned11_count / orig11) * 100
    assert reduction11 >= 20, f"Filler-heavy text should reduce >= 20%, got {reduction11:.1f}%"
    assert "timeout" in pruned11.lower(), "Key term survives"
    assert "error" in pruned11.lower(), "Key term survives"
    print(f"Test 11 — Filler-heavy pruning: PASSED ({reduction11:.1f}% reduction)")

    # ==================================================================
    # Test 12: Token count estimation
    # ==================================================================
    assert estimate_token_count("") == 0
    count12 = estimate_token_count("one two three four five")
    assert 5 <= count12 <= 10, f"Reasonable estimate for 5 words: {count12}"
    print(f"Test 12 — Token estimation: PASSED")

    # ==================================================================
    # Test 13: Already-within-budget text is unchanged
    # ==================================================================
    small_text = "Fix the error."
    result13 = prune(small_text, budget=100)
    assert result13 == small_text, "Within-budget text should be unchanged"
    print("Test 13 — Within-budget passthrough: PASSED")

    # ==================================================================
    # Test 14: Large realistic agent response
    # ==================================================================
    large_agent_response = (
        "## Analysis\n\n"
        "Basically, I essentially examined the database query that is "
        "obviously causing the very significant timeout error. The query "
        "was actually performing a full table scan on approximately 10M rows "
        "in the users table. This is clearly well above the acceptable "
        "threshold of 200ms as defined in the SLA.\n\n"
        "## Root Cause\n\n"
        "The root cause is definitely a missing composite index on "
        "(email, created_at). The error manifests as a 45s timeout on "
        "the GET /api/users endpoint. The p95 latency has generally been "
        "degrading since the table grew past 5M rows.\n\n"
        "## Recommended Fix\n\n"
        "- Add composite index on (email, created_at)\n"
        "- Configure retry with exponential backoff (1s, 2s, 4s)\n"
        "- Deploy and monitor p95 latency\n"
        "- Set alerting threshold at 500ms\n"
        "- Rollback plan: drop index if write performance degrades\n\n"
        "## Expected Impact\n\n"
        "The query time should essentially probably drop from 45s to "
        "approximately under 100ms. The API endpoint will certainly "
        "meet the 200ms SLA target after the fix is deployed."
    )
    pruned14 = prune(large_agent_response, target_ratio=0.65)
    orig14 = estimate_token_count(large_agent_response)
    pruned14_count = estimate_token_count(pruned14)
    reduction14 = (1 - pruned14_count / orig14) * 100

    assert reduction14 >= 15, f"Large response should reduce >= 15%, got {reduction14:.1f}%"
    # All critical diagnostic info must survive
    for term in ["index", "timeout", "error", "45s", "10M", "200ms",
                 "p95", "retry", "rollback", "/api/users"]:
        assert term.lower() in pruned14.lower(), \
            f"Critical term '{term}' must survive in large response"
    # Structural elements preserved
    assert "## Analysis" in pruned14 or "Analysis" in pruned14
    assert "## Root Cause" in pruned14 or "Root Cause" in pruned14
    print(f"Test 14 — Large response: PASSED ({reduction14:.1f}% reduction, "
          f"{orig14} -> {pruned14_count} tokens)")

    # ==================================================================
    # Summary
    # ==================================================================
    print("\n" + "=" * 60)
    print("ALL 14 ASSERTIONS PASSED — token_pruner.py verified")
    print("=" * 60)
