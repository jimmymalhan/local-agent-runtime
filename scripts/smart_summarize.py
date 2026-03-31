#!/usr/bin/env python3
"""
smart_summarize.py — Smart Summarization: Extract Key Info from Long Texts
==========================================================================
Multi-strategy summarizer that extracts structured key information:
  - Extractive summary (TF-IDF + positional scoring)
  - Named entities (people, orgs, technologies, metrics)
  - Action items and recommendations
  - Key statistics and numeric facts
  - Topic classification
  - Structured KeyInfo output with confidence scores
"""

import re
import math
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Stop words
# ---------------------------------------------------------------------------

STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "could should may might shall can need dare ought in on at to for of with by "
    "from as into through during before after above below between out off over "
    "under again further then once here there when where why how all each every "
    "both few more most other some such no nor not only own same so than too very "
    "just because but and or if while about up this that these those it its i me "
    "my we our you your he him his she her they them their what which who whom".split()
)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\(\[])')
CODE_BLOCK = re.compile(r"```[\s\S]*?```")
HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
BULLET = re.compile(r"^\s*[-*\u2022]\s+(.+)$", re.MULTILINE)

# Named entity patterns
TECH_TERMS = re.compile(
    r"\b(Python|Java|JavaScript|TypeScript|Go|Rust|C\+\+|Ruby|PHP|Swift|Kotlin|SQL|"
    r"React|Angular|Vue|Node\.?js|Django|Flask|FastAPI|Express|Spring|Rails|"
    r"Docker|Kubernetes|AWS|GCP|Azure|Redis|PostgreSQL|MySQL|MongoDB|"
    r"Kafka|RabbitMQ|Elasticsearch|Nginx|Apache|GraphQL|REST|gRPC|"
    r"TensorFlow|PyTorch|scikit-learn|pandas|NumPy|"
    r"Git|GitHub|GitLab|Jenkins|CircleCI|Terraform|Ansible|"
    r"Linux|macOS|Windows|HTTP|HTTPS|TCP|UDP|DNS|SSL|TLS|API|SDK|CLI|"
    r"CPU|GPU|RAM|SSD|HDD|CDN|VPC|IAM|S3|EC2|RDS|ECS|EKS|Lambda)\b",
    re.IGNORECASE,
)

METRIC_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*"
    r"(%|percent|ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|"
    r"MB|GB|TB|PB|KB|bytes?|requests?/s(?:ec)?|req/s|rps|QPS|qps|"
    r"rows?|records?|users?|connections?|threads?|cores?|nodes?|"
    r"errors?|failures?|retries|timeouts?|"
    r"[Kk]|[Mm]|[Bb]illion)\b"
)

DATE_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s*\d{2,4}|"
    r"\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|UTC|GMT|EST|PST|ET|PT)?)\b",
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

ACTION_CUES = re.compile(
    r"(?i)\b(must|should|need to|recommend|fix|resolve|update|migrate|"
    r"deploy|configure|add|remove|create|delete|upgrade|downgrade|"
    r"implement|refactor|monitor|alert|review|investigate|"
    r"set up|scale|optimize|patch|revert|rollback|restart)\b"
)

IMPORTANCE_CUES = re.compile(
    r"(?i)\b(critical|important|key|essential|required|mandatory|"
    r"root cause|conclusion|finding|result|impact|severity|"
    r"breaking|blocking|urgent|high priority|p0|p1|incident|outage|"
    r"vulnerability|security|performance|degradation|regression)\b"
)

BOILERPLATE = re.compile(
    r"(?i)(hope this helps|let me know|feel free|don't hesitate|"
    r"happy to help|please let me know|if you have any questions|"
    r"certainly|of course|absolutely|sure thing)"
)

FILLER = re.compile(
    r"(?i)\b(basically|actually|essentially|obviously|clearly|"
    r"it is important to note that|it should be noted that|"
    r"it is worth mentioning that|needless to say|as a matter of fact)\b"
)

# Verbose-to-concise rewrites
REWRITES = [
    (re.compile(r"(?i)due to the fact that"), "because"),
    (re.compile(r"(?i)in order to"), "to"),
    (re.compile(r"(?i)at this point in time"), "now"),
    (re.compile(r"(?i)in the event that"), "if"),
    (re.compile(r"(?i)for the purpose of"), "for"),
    (re.compile(r"(?i)the vast majority of"), "most"),
    (re.compile(r"(?i)a large number of"), "many"),
    (re.compile(r"(?i)prior to"), "before"),
    (re.compile(r"(?i)subsequent to"), "after"),
    (re.compile(r"(?i)has the ability to"), "can"),
    (re.compile(r"(?i)is able to"), "can"),
    (re.compile(r"(?i)it is important to note that\s*"), ""),
    (re.compile(r"(?i)it should be noted that\s*"), ""),
    (re.compile(r"(?i)as a matter of fact,?\s*"), ""),
    (re.compile(r"(?i)needless to say,?\s*"), ""),
    (re.compile(r"(?i)with regard to"), "about"),
    (re.compile(r"(?i)as a result of"), "because of"),
    (re.compile(r"(?i)\b(basically|actually|essentially|really|quite|very|just)\s+"), ""),
    (re.compile(r"(?i)\b(i think|i believe|it seems like|it appears that)\s+"), ""),
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    """A named entity found in text."""
    text: str
    entity_type: str  # "technology", "metric", "date", "email", "url"
    count: int = 1
    context: str = ""


@dataclass
class ActionItem:
    """An action or recommendation extracted from text."""
    text: str
    verb: str
    priority: str = "normal"  # "high", "normal", "low"
    source_sentence: str = ""


@dataclass
class KeyStat:
    """A key statistic or numeric fact."""
    value: str
    unit: str
    context: str


@dataclass
class TopicScore:
    """A detected topic with relevance score."""
    topic: str
    score: float
    evidence: list = field(default_factory=list)


@dataclass
class KeyInfo:
    """Complete structured key information extracted from text."""
    summary: str
    key_points: list
    entities: list
    action_items: list
    key_stats: list
    topics: list
    original_length: int
    summary_length: int
    reduction_pct: float
    sentence_count: int
    word_count: int

    def __str__(self):
        lines = [
            f"Smart Summary ({self.reduction_pct:.1f}% reduction, "
            f"{self.original_length} -> {self.summary_length} chars)",
            "",
            "=== Summary ===",
            self.summary,
            "",
        ]
        if self.key_points:
            lines.append(f"=== Key Points ({len(self.key_points)}) ===")
            for p in self.key_points:
                lines.append(f"  * {p}")
            lines.append("")
        if self.action_items:
            lines.append(f"=== Action Items ({len(self.action_items)}) ===")
            for a in self.action_items:
                marker = "[!]" if a.priority == "high" else "[-]"
                lines.append(f"  {marker} {a.text}")
            lines.append("")
        if self.key_stats:
            lines.append(f"=== Key Stats ({len(self.key_stats)}) ===")
            for s in self.key_stats:
                lines.append(f"  - {s.value} {s.unit}: {s.context}")
            lines.append("")
        if self.entities:
            by_type = defaultdict(list)
            for e in self.entities:
                by_type[e.entity_type].append(e.text)
            lines.append(f"=== Entities ({len(self.entities)}) ===")
            for etype, names in sorted(by_type.items()):
                lines.append(f"  {etype}: {', '.join(sorted(set(names)))}")
            lines.append("")
        if self.topics:
            lines.append(f"=== Topics ({len(self.topics)}) ===")
            for t in self.topics:
                lines.append(f"  - {t.topic} (score: {t.score:.2f})")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def _split_sentences(text: str) -> list:
    cleaned = CODE_BLOCK.sub(" [code block] ", text)
    raw = SENTENCE_SPLIT.split(cleaned)
    return [s.strip() for s in raw if len(s.strip()) > 15]


def _condense(sentence: str) -> str:
    result = sentence
    for pattern, replacement in REWRITES:
        result = pattern.sub(replacement, result)
    result = re.sub(r"\s{2,}", " ", result).strip()
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


# ---------------------------------------------------------------------------
# TF-IDF sentence scoring
# ---------------------------------------------------------------------------

def _tfidf_scores(sentences: list) -> list:
    tokenized = []
    for s in sentences:
        words = [w for w in _tokenize(s) if w not in STOP_WORDS and len(w) > 1]
        tokenized.append(words)

    n = len(tokenized)
    if n == 0:
        return []

    df = Counter()
    for doc_words in tokenized:
        for w in set(doc_words):
            df[w] += 1

    idf = {w: math.log(n / (1 + count)) for w, count in df.items()}

    scores = []
    for words in tokenized:
        if not words:
            scores.append(0.0)
            continue
        tf = Counter(words)
        total = len(words)
        score = sum((c / total) * idf.get(w, 0) for w, c in tf.items())
        scores.append(score)
    return scores


def _rank_sentences(text: str) -> list:
    """Return list of (sentence, score, position) tuples sorted by score desc."""
    sentences = _split_sentences(text)
    if not sentences:
        return []

    headings = HEADING.findall(text)
    title_words = set()
    for h in headings:
        title_words.update(w for w in _tokenize(h) if w not in STOP_WORDS)

    tfidf = _tfidf_scores(sentences)
    total = len(sentences)

    ranked = []
    for i, (sent, tf_score) in enumerate(zip(sentences, tfidf)):
        score = 0.0

        # TF-IDF (40%)
        score += min(tf_score * 0.1, 1.0) * 0.40

        # Position bias (20%)
        rel_pos = i / max(total, 1)
        if rel_pos < 0.15:
            score += 0.20
        elif rel_pos > 0.85:
            score += 0.12

        # Importance cues (15%)
        imp_count = len(IMPORTANCE_CUES.findall(sent))
        score += min(imp_count * 0.05, 0.15)

        # Numeric specifics (10%)
        num_count = len(METRIC_PATTERN.findall(sent))
        score += min(num_count * 0.05, 0.10)

        # Title word overlap (10%)
        words = set(_tokenize(sent)) - STOP_WORDS
        if title_words and words:
            overlap = len(words & title_words) / max(len(title_words), 1)
            score += overlap * 0.10

        # Penalize boilerplate
        if BOILERPLATE.search(sent):
            score -= 0.20
        filler_count = len(FILLER.findall(sent))
        score -= filler_count * 0.04

        ranked.append((sent, max(score, 0.0), i))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def extract_entities(text: str) -> list:
    """Extract named entities from text."""
    entities = []
    seen = set()

    # Technologies
    for m in TECH_TERMS.finditer(text):
        name = m.group(0)
        key = ("technology", name.lower())
        if key not in seen:
            seen.add(key)
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            ctx = text[start:end].strip()
            count = len(re.findall(re.escape(name), text, re.IGNORECASE))
            entities.append(Entity(name, "technology", count, ctx))

    # Metrics
    for m in METRIC_PATTERN.finditer(text):
        val, unit = m.group(1), m.group(2)
        key = ("metric", f"{val}{unit}")
        if key not in seen:
            seen.add(key)
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 50)
            ctx = text[start:end].strip()
            entities.append(Entity(f"{val} {unit}", "metric", 1, ctx))

    # Dates
    for m in DATE_PATTERN.finditer(text):
        dt = m.group(0)
        key = ("date", dt)
        if key not in seen:
            seen.add(key)
            entities.append(Entity(dt, "date", 1, ""))

    # URLs
    for m in URL_PATTERN.finditer(text):
        url = m.group(0)
        key = ("url", url)
        if key not in seen:
            seen.add(key)
            entities.append(Entity(url, "url", 1, ""))

    # Emails
    for m in EMAIL_PATTERN.finditer(text):
        email = m.group(0)
        key = ("email", email)
        if key not in seen:
            seen.add(key)
            entities.append(Entity(email, "email", 1, ""))

    return entities


# ---------------------------------------------------------------------------
# Action item extraction
# ---------------------------------------------------------------------------

def extract_action_items(text: str, max_items: int = 10) -> list:
    """Extract action items and recommendations from text."""
    sentences = _split_sentences(text)
    items = []
    seen_hashes = set()

    for sent in sentences:
        if BOILERPLATE.search(sent):
            continue

        matches = ACTION_CUES.finditer(sent)
        for m in matches:
            verb = m.group(1).lower()
            condensed = _condense(sent)
            if len(condensed) > 200:
                end = re.search(r"[.;,]", condensed[60:])
                if end:
                    condensed = condensed[: 60 + end.start()]
                else:
                    condensed = condensed[:200]

            norm = re.sub(r"[^\w\s]", "", condensed.lower())
            h = hashlib.md5(norm.encode()).hexdigest()[:12]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            priority = "normal"
            if IMPORTANCE_CUES.search(sent):
                priority = "high"

            items.append(ActionItem(
                text=condensed,
                verb=verb,
                priority=priority,
                source_sentence=sent[:200],
            ))

    items.sort(key=lambda x: (0 if x.priority == "high" else 1))
    return items[:max_items]


# ---------------------------------------------------------------------------
# Key statistics extraction
# ---------------------------------------------------------------------------

def extract_key_stats(text: str, max_stats: int = 10) -> list:
    """Extract key statistics and numeric facts."""
    stats = []
    seen = set()

    for m in METRIC_PATTERN.finditer(text):
        val, unit = m.group(1), m.group(2)
        key = f"{val}{unit}"
        if key in seen:
            continue
        seen.add(key)

        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        context = text[start:end].strip()
        context = re.sub(r"\s+", " ", context)

        stats.append(KeyStat(value=val, unit=unit, context=context))

    return stats[:max_stats]


# ---------------------------------------------------------------------------
# Topic detection
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS = {
    "performance": [
        "latency", "throughput", "response time", "slow", "fast", "optimize",
        "bottleneck", "cache", "benchmark", "p50", "p95", "p99", "qps",
    ],
    "reliability": [
        "error", "failure", "retry", "timeout", "outage", "downtime",
        "crash", "recovery", "fallback", "resilience", "availability",
    ],
    "security": [
        "vulnerability", "auth", "permission", "token", "encryption",
        "ssl", "tls", "xss", "sql injection", "csrf", "firewall",
    ],
    "database": [
        "query", "index", "table", "migration", "schema", "sql",
        "postgresql", "mysql", "mongodb", "redis", "connection pool",
    ],
    "infrastructure": [
        "deploy", "kubernetes", "docker", "server", "cloud", "aws",
        "gcp", "azure", "terraform", "scaling", "load balancer",
    ],
    "api": [
        "endpoint", "request", "response", "rest", "graphql", "grpc",
        "status code", "rate limit", "webhook", "payload",
    ],
    "testing": [
        "test", "coverage", "assertion", "mock", "fixture", "ci",
        "regression", "integration test", "unit test", "e2e",
    ],
    "data": [
        "pipeline", "etl", "transform", "ingest", "stream", "batch",
        "partition", "replication", "consistency", "backup",
    ],
}


def detect_topics(text: str, max_topics: int = 5) -> list:
    """Detect topics/themes in text by keyword frequency."""
    text_lower = text.lower()
    words = set(_tokenize(text_lower))

    scores = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        hits = []
        for kw in keywords:
            if " " in kw:
                count = text_lower.count(kw)
            else:
                count = 1 if kw in words else 0
            if count > 0:
                hits.append(kw)

        if hits:
            score = len(hits) / len(keywords)
            scores.append(TopicScore(topic=topic, score=round(score, 3), evidence=hits))

    scores.sort(key=lambda t: t.score, reverse=True)
    return [t for t in scores[:max_topics] if t.score > 0.05]


# ---------------------------------------------------------------------------
# Extractive summary
# ---------------------------------------------------------------------------

def extractive_summary(text: str, ratio: float = 0.3,
                       min_sents: int = 2, max_sents: int = 12) -> str:
    """Select top-scoring sentences, preserving original order."""
    if not text or len(text.strip()) < 50:
        return text.strip() if text else ""

    ranked = _rank_sentences(text)
    if not ranked:
        return text.strip()

    n_keep = max(min_sents, min(max_sents, int(len(ranked) * ratio)))
    n_keep = min(n_keep, len(ranked))

    top = ranked[:n_keep]
    top.sort(key=lambda x: x[2])  # restore original order

    condensed = [_condense(s) for s, _, _ in top]
    return " ".join(condensed)


# ---------------------------------------------------------------------------
# Key point extraction
# ---------------------------------------------------------------------------

def extract_key_points(text: str, max_points: int = 7) -> list:
    """Extract structured key points from text."""
    if not text or len(text.strip()) < 30:
        return []

    candidates = []
    seen_hashes = set()

    def _add(point: str, score: float):
        clean = re.sub(r"^[-*\u2022]\s+", "", point.strip().rstrip("."))
        if len(clean) < 15:
            return
        norm = " ".join(w for w in _tokenize(clean) if w not in STOP_WORDS)
        h = hashlib.md5(norm.encode()).hexdigest()[:12]
        if h not in seen_hashes:
            seen_hashes.add(h)
            candidates.append((clean, score))

    # Source 1: Author's bullet points
    for b in BULLET.findall(text):
        if not BOILERPLATE.search(b):
            _add(b, 0.9)

    # Source 2: High-scoring sentences with cue phrases or numbers
    ranked = _rank_sentences(text)
    for sent, score, _ in ranked[:15]:
        has_cue = bool(IMPORTANCE_CUES.search(sent))
        has_num = bool(METRIC_PATTERN.search(sent))
        if has_cue or has_num:
            condensed = _condense(sent)
            if len(condensed) > 150:
                clip = re.search(r"[,;:]", condensed[70:])
                if clip:
                    condensed = condensed[: 70 + clip.start()]
                else:
                    condensed = condensed[:150]
            _add(condensed, score)

    # Source 3: First sentence of each section
    current_heading = None
    for line in text.split("\n"):
        hm = HEADING.match(line.strip())
        if hm:
            current_heading = hm.group(1).strip()
        elif current_heading and line.strip() and len(line.strip()) > 20:
            if not BOILERPLATE.search(line):
                condensed = _condense(line.strip())
                _add(f"{current_heading}: {condensed[:120]}", 0.7)
            current_heading = None  # only first sentence

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in candidates[:max_points]]


# ---------------------------------------------------------------------------
# Main interface
# ---------------------------------------------------------------------------

def smart_summarize(text: str, ratio: float = 0.3, max_points: int = 7,
                    max_actions: int = 10, max_stats: int = 10,
                    max_topics: int = 5) -> KeyInfo:
    """
    Smart summarization: extract all key information from text.

    Returns a KeyInfo object with summary, key points, entities,
    action items, statistics, and detected topics.
    """
    if not text:
        return KeyInfo(
            summary="", key_points=[], entities=[], action_items=[],
            key_stats=[], topics=[], original_length=0, summary_length=0,
            reduction_pct=0.0, sentence_count=0, word_count=0,
        )

    original_length = len(text)
    sentences = _split_sentences(text)
    words = _tokenize(text)

    summary = extractive_summary(text, ratio=ratio)
    key_points = extract_key_points(text, max_points=max_points)
    entities = extract_entities(text)
    action_items = extract_action_items(text, max_items=max_actions)
    key_stats = extract_key_stats(text, max_stats=max_stats)
    topics = detect_topics(text, max_topics=max_topics)

    summary_length = len(summary)
    reduction = (1.0 - summary_length / max(original_length, 1)) * 100

    return KeyInfo(
        summary=summary,
        key_points=key_points,
        entities=entities,
        action_items=action_items,
        key_stats=key_stats,
        topics=topics,
        original_length=original_length,
        summary_length=summary_length,
        reduction_pct=reduction,
        sentence_count=len(sentences),
        word_count=len(words),
    )


# ---------------------------------------------------------------------------
# __main__: assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # ---- Test document ----
    DOC = (
        "Hello! I'd be happy to help you diagnose this database issue.\n\n"
        "## Root Cause Analysis\n\n"
        "Due to the fact that the PostgreSQL query is taking 45 seconds, "
        "it is important to note that this is well above the acceptable threshold of 100ms. "
        "The vast majority of queries in the users table complete in under 50ms. "
        "In order to investigate, we examined the query plan and found a full table scan "
        "on the users table which now has 10 million rows.\n\n"
        "Prior to the January 15, 2026 deploy, the table had under 1 million rows. "
        "The missing composite index on (email, created_at) is the root cause. "
        "The database is performing sequential reads across all 10M data pages, "
        "causing 45 seconds of latency per query.\n\n"
        "## Recommended Actions\n\n"
        "- Add composite index on (email, created_at) to the users table\n"
        "- Monitor query performance after applying the index\n"
        "- Set up alerting for queries exceeding 1 second threshold\n"
        "- Consider table partitioning if growth exceeds 50M rows\n"
        "- Deploy the fix to production using the Kubernetes rolling update\n"
        "- Review Redis cache hit rate which dropped to 65%\n\n"
        "## Expected Impact\n\n"
        "In the event that the index is applied correctly, query time should drop "
        "from 45 seconds to under 50ms. Error rate should decrease from 15% to under 0.1%. "
        "The AWS RDS instance CPU utilization will drop from 95% to approximately 30%. "
        "Contact the team at ops@example.com or check https://status.example.com for updates.\n\n"
        "## Performance Metrics\n\n"
        "Current p95 latency: 45 seconds. Target p95: 100ms. "
        "Database connections: 95 of 100 max. Active queries: 250 concurrent. "
        "Error rate: 15% of requests failing with timeout.\n\n"
        "Hope this helps! Let me know if you have any questions."
    )

    # ---- Test 1: smart_summarize returns KeyInfo ----
    info = smart_summarize(DOC)
    assert isinstance(info, KeyInfo), "Must return KeyInfo"
    print(f"Test 1 PASS: KeyInfo returned")

    # ---- Test 2: Summary is shorter than original ----
    assert info.summary_length < info.original_length, "Summary must be shorter"
    assert info.reduction_pct > 20, f"Expected >20% reduction, got {info.reduction_pct:.1f}%"
    print(f"Test 2 PASS: {info.reduction_pct:.1f}% reduction ({info.original_length} -> {info.summary_length} chars)")

    # ---- Test 3: Summary preserves key technical content ----
    summary_lower = info.summary.lower()
    assert "index" in summary_lower or "composite" in summary_lower, "Summary must mention the index fix"
    assert "hope this helps" not in summary_lower, "Boilerplate must be removed"
    assert "due to the fact" not in summary_lower, "Verbose phrases must be rewritten"
    print(f"Test 3 PASS: Key content preserved, boilerplate removed")

    # ---- Test 4: Key points extracted ----
    assert len(info.key_points) >= 3, f"Expected >=3 key points, got {len(info.key_points)}"
    assert len(info.key_points) <= 7, f"Expected <=7 key points, got {len(info.key_points)}"
    all_points = " ".join(info.key_points).lower()
    assert "index" in all_points or "composite" in all_points, "Key points must mention the fix"
    for p in info.key_points:
        assert len(p) > 10, f"Key point too short: {p}"
    print(f"Test 4 PASS: {len(info.key_points)} key points extracted")

    # ---- Test 5: Entities extracted ----
    assert len(info.entities) >= 3, f"Expected >=3 entities, got {len(info.entities)}"
    entity_types = {e.entity_type for e in info.entities}
    entity_texts = {e.text.lower() for e in info.entities}
    assert "technology" in entity_types, "Must detect technology entities"
    assert any("postgresql" in t for t in entity_texts), "Must detect PostgreSQL"
    assert "metric" in entity_types, "Must detect metric entities"
    print(f"Test 5 PASS: {len(info.entities)} entities ({', '.join(sorted(entity_types))})")

    # ---- Test 6: Action items extracted ----
    assert len(info.action_items) >= 3, f"Expected >=3 action items, got {len(info.action_items)}"
    action_verbs = {a.verb for a in info.action_items}
    assert len(action_verbs) >= 2, "Must have diverse action verbs"
    has_high = any(a.priority == "high" for a in info.action_items)
    print(f"Test 6 PASS: {len(info.action_items)} actions ({len(action_verbs)} verbs, high_priority={has_high})")

    # ---- Test 7: Key stats extracted ----
    assert len(info.key_stats) >= 3, f"Expected >=3 key stats, got {len(info.key_stats)}"
    stat_units = {s.unit for s in info.key_stats}
    for s in info.key_stats:
        assert s.value, "Stat must have value"
        assert s.unit, "Stat must have unit"
        assert s.context, "Stat must have context"
    print(f"Test 7 PASS: {len(info.key_stats)} stats (units: {', '.join(sorted(stat_units))})")

    # ---- Test 8: Topics detected ----
    assert len(info.topics) >= 2, f"Expected >=2 topics, got {len(info.topics)}"
    topic_names = {t.topic for t in info.topics}
    assert "database" in topic_names or "performance" in topic_names, \
        f"Expected database or performance topic, got {topic_names}"
    for t in info.topics:
        assert 0 < t.score <= 1.0, f"Topic score out of range: {t.score}"
        assert len(t.evidence) > 0, f"Topic must have evidence"
    print(f"Test 8 PASS: {len(info.topics)} topics ({', '.join(sorted(topic_names))})")

    # ---- Test 9: Email and URL extraction ----
    url_entities = [e for e in info.entities if e.entity_type == "url"]
    email_entities = [e for e in info.entities if e.entity_type == "email"]
    assert len(url_entities) >= 1, "Must extract URL"
    assert len(email_entities) >= 1, "Must extract email"
    assert any("example.com" in e.text for e in url_entities), "Must find status URL"
    assert any("ops@example.com" in e.text for e in email_entities), "Must find ops email"
    print(f"Test 9 PASS: URLs={len(url_entities)}, Emails={len(email_entities)}")

    # ---- Test 10: Date extraction ----
    date_entities = [e for e in info.entities if e.entity_type == "date"]
    assert len(date_entities) >= 1, "Must extract dates"
    print(f"Test 10 PASS: {len(date_entities)} dates found")

    # ---- Test 11: Word and sentence counts ----
    assert info.word_count > 50, f"Expected >50 words, got {info.word_count}"
    assert info.sentence_count > 5, f"Expected >5 sentences, got {info.sentence_count}"
    print(f"Test 11 PASS: {info.word_count} words, {info.sentence_count} sentences")

    # ---- Test 12: __str__ formatting ----
    output = str(info)
    assert "Summary" in output, "__str__ must show Summary section"
    assert "Key Points" in output, "__str__ must show Key Points section"
    assert "Action Items" in output, "__str__ must show Action Items section"
    assert "Entities" in output, "__str__ must show Entities section"
    assert "Topics" in output, "__str__ must show Topics section"
    print(f"Test 12 PASS: __str__ formatting correct")

    # ---- Test 13: Empty input handling ----
    empty_info = smart_summarize("")
    assert empty_info.summary == "", "Empty input returns empty summary"
    assert empty_info.key_points == [], "Empty input returns no key points"
    assert empty_info.entities == [], "Empty input returns no entities"
    assert empty_info.action_items == [], "Empty input returns no actions"
    assert empty_info.reduction_pct == 0.0, "Empty input has 0% reduction"
    print(f"Test 13 PASS: Empty input handled")

    # ---- Test 14: Short input passthrough ----
    short_info = smart_summarize("Short text.")
    assert short_info.summary == "Short text.", "Short text passes through"
    print(f"Test 14 PASS: Short input passthrough")

    # ---- Test 15: Deduplication in key points ----
    duped_doc = (
        "The server crashed due to a memory leak. "
        "A critical memory leak caused the server to crash. "
        "The memory leak is a critical issue that crashes the server. "
        "We must fix the memory allocation bug in the worker pool. "
        "Deploy the hotfix to patch the memory leak immediately."
    )
    duped_info = smart_summarize(duped_doc)
    # Key points should not be exact duplicates
    point_hashes = set()
    for p in duped_info.key_points:
        norm = " ".join(w for w in _tokenize(p) if w not in STOP_WORDS)
        point_hashes.add(hashlib.md5(norm.encode()).hexdigest()[:12])
    assert len(point_hashes) == len(duped_info.key_points), "Key points must be deduplicated"
    print(f"Test 15 PASS: Deduplication works ({len(duped_info.key_points)} unique points)")

    # ---- Test 16: Verbose rewrite applied ----
    verbose = (
        "Due to the fact that the server was overloaded, in order to "
        "fix the issue we need to scale. The vast majority of requests "
        "timeout after 30 seconds. In the event that scaling fails, "
        "we should failover to the backup region."
    )
    verbose_info = smart_summarize(verbose)
    s_lower = verbose_info.summary.lower()
    assert "due to the fact" not in s_lower, "Must rewrite 'due to the fact'"
    assert "in order to" not in s_lower, "Must rewrite 'in order to'"
    print(f"Test 16 PASS: Verbose phrases rewritten")

    # ---- Test 17: Numeric facts preserved in summary ----
    numeric_doc = (
        "## Performance Report\n\n"
        "The API latency increased from 50ms to 2500ms after the deploy. "
        "Error rate spiked to 15% at 14:30 UTC on March 28, 2026. "
        "Database connections maxed out at 100 connections. "
        "After the fix, latency dropped to 45ms and errors to 0.1%. "
        "Memory usage peaked at 3200MB, which is 80% of the 4096MB limit."
    )
    num_info = smart_summarize(numeric_doc)
    assert len(num_info.key_stats) >= 3, f"Expected >=3 stats, got {len(num_info.key_stats)}"
    all_stat_text = " ".join(f"{s.value}{s.unit}" for s in num_info.key_stats)
    assert re.search(r"\d+", all_stat_text), "Stats must contain numbers"
    print(f"Test 17 PASS: {len(num_info.key_stats)} numeric facts preserved")

    # ---- Test 18: Topic detection accuracy ----
    security_doc = (
        "A critical SQL injection vulnerability was found in the authentication "
        "endpoint. The XSS attack vector allows token theft via the login form. "
        "SSL certificate expired causing CSRF protection to fail. "
        "The firewall rules need updating to block the malicious IPs."
    )
    sec_info = smart_summarize(security_doc)
    sec_topics = {t.topic for t in sec_info.topics}
    assert "security" in sec_topics, f"Must detect security topic, got {sec_topics}"
    print(f"Test 18 PASS: Security topic detected in security document")

    # ---- Test 19: Action item priority detection ----
    priority_doc = (
        "We must immediately fix the critical vulnerability in production. "
        "The security team should review the authentication module. "
        "Consider adding rate limiting to the API endpoints next quarter. "
        "Update the documentation when convenient."
    )
    pri_info = smart_summarize(priority_doc)
    high_actions = [a for a in pri_info.action_items if a.priority == "high"]
    assert len(high_actions) >= 1, "Must detect at least 1 high-priority action"
    print(f"Test 19 PASS: {len(high_actions)} high-priority actions detected")

    # ---- Test 20: Large document handling ----
    large_doc = "\n\n".join([
        f"## Section {i}\n\nThis section covers topic {i} with important details. "
        f"The system processed {i * 1000} requests with {i}ms latency. "
        f"We recommend upgrading component {i} to handle the increased load."
        for i in range(1, 51)
    ])
    large_info = smart_summarize(large_doc)
    assert large_info.reduction_pct > 50, f"Large doc should have >50% reduction, got {large_info.reduction_pct:.1f}%"
    assert len(large_info.key_points) <= 7, "Key points capped at max"
    assert len(large_info.topics) <= 5, "Topics capped at max"
    print(f"Test 20 PASS: Large doc ({large_info.word_count} words, {large_info.reduction_pct:.1f}% reduction)")

    # ---- Full output display ----
    print("\n" + "=" * 60)
    print("ALL 20 ASSERTIONS PASSED")
    print("=" * 60)
    print()
    print(info)
