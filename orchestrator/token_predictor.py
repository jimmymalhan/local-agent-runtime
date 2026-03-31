"""
Predictive Token Estimation Engine

ML model that predicts token count before execution and guides routing decisions.
Uses historical execution data to train a lightweight gradient-boosted model,
falling back to heuristic estimation when insufficient training data exists.
"""

import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

class TaskCategory(Enum):
    CODE_GEN = "code_gen"
    BUG_FIX = "bug_fix"
    DEBUG = "debug"
    TEST_GEN = "test_gen"
    REFACTOR = "refactor"
    REVIEW = "review"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"
    ARCHITECTURE = "arch"
    PLANNING = "planning"
    SCORING = "scoring"
    UNKNOWN = "unknown"


class Complexity(Enum):
    TRIVIAL = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


_CATEGORY_INDEX = {c.value: i for i, c in enumerate(TaskCategory)}
_COMPLEXITY_INDEX = {c.name.lower(): c.value for c in Complexity}

# Keyword signals used to infer complexity when not explicitly provided
_COMPLEXITY_KEYWORDS: dict[str, list[str]] = {
    "trivial": ["format", "rename", "typo", "lint", "style"],
    "low": ["fix", "patch", "tweak", "small", "simple", "minor"],
    "medium": ["add", "implement", "feature", "update", "modify", "change"],
    "high": ["architect", "redesign", "migrate", "optimize", "complex", "multi-file"],
    "critical": ["security", "incident", "production", "data-loss", "outage", "breach"],
}


def _infer_complexity(text: str) -> Complexity:
    text_lower = text.lower()
    scores = {level: 0 for level in Complexity}
    for level_name, keywords in _COMPLEXITY_KEYWORDS.items():
        level = Complexity[level_name.upper()]
        for kw in keywords:
            if kw in text_lower:
                scores[level] += 1
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] == 0:
        return Complexity.MEDIUM
    return best


# ---------------------------------------------------------------------------
# Feature vector
# ---------------------------------------------------------------------------

@dataclass
class TaskFeatures:
    """Numeric feature vector extracted from a task dict."""
    category_idx: float = 0.0
    complexity_idx: float = 2.0
    description_len: float = 0.0
    title_len: float = 0.0
    num_skills: float = 0.0
    files_affected: float = 1.0
    has_code_context: float = 0.0
    word_count: float = 0.0

    def to_vector(self) -> list[float]:
        return [
            self.category_idx,
            self.complexity_idx,
            self.description_len,
            self.title_len,
            self.num_skills,
            self.files_affected,
            self.has_code_context,
            self.word_count,
        ]

    @staticmethod
    def feature_names() -> list[str]:
        return [
            "category_idx", "complexity_idx", "description_len", "title_len",
            "num_skills", "files_affected", "has_code_context", "word_count",
        ]


def extract_features(task: dict) -> TaskFeatures:
    """Extract numeric features from a task dictionary."""
    title = task.get("title", "")
    description = task.get("description", "")
    combined = f"{title} {description}"

    category = task.get("category", "unknown")
    cat_idx = float(_CATEGORY_INDEX.get(category, _CATEGORY_INDEX["unknown"]))

    complexity_raw = task.get("complexity", "")
    if complexity_raw and complexity_raw.lower() in _COMPLEXITY_INDEX:
        comp_idx = float(_COMPLEXITY_INDEX[complexity_raw.lower()])
    else:
        comp_idx = float(_infer_complexity(combined).value)

    skills = task.get("skills", [])
    files = task.get("files_affected", 1)
    has_code = 1.0 if task.get("code_context") else 0.0

    return TaskFeatures(
        category_idx=cat_idx,
        complexity_idx=comp_idx,
        description_len=float(len(description)),
        title_len=float(len(title)),
        num_skills=float(len(skills)),
        files_affected=float(files),
        has_code_context=has_code,
        word_count=float(len(combined.split())),
    )


# ---------------------------------------------------------------------------
# Prediction result
# ---------------------------------------------------------------------------

@dataclass
class TokenPrediction:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    confidence: float  # 0.0 - 1.0
    model_used: str  # "ml" or "heuristic"
    routing_hint: str  # suggested model tier
    estimated_cost_usd: float
    feature_importances: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "confidence": round(self.confidence, 4),
            "model_used": self.model_used,
            "routing_hint": self.routing_hint,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "feature_importances": {
                k: round(v, 4) for k, v in self.feature_importances.items()
            },
        }


# ---------------------------------------------------------------------------
# Heuristic estimator (baseline / fallback)
# ---------------------------------------------------------------------------

_BASE_TOKENS: dict[int, tuple[int, int]] = {
    # complexity_idx -> (input, output)
    0: (200, 100),
    1: (500, 300),
    2: (1500, 800),
    3: (4000, 2000),
    4: (8000, 5000),
}

_CATEGORY_MULTIPLIERS: dict[str, float] = {
    "code_gen": 1.3,
    "bug_fix": 1.1,
    "debug": 1.2,
    "test_gen": 1.4,
    "refactor": 1.5,
    "review": 0.9,
    "research": 0.6,
    "documentation": 1.1,
    "arch": 1.6,
    "planning": 0.7,
    "scoring": 0.5,
    "unknown": 1.0,
}


def heuristic_estimate(features: TaskFeatures, task: dict) -> tuple[int, int]:
    """Rule-based token estimation used as fallback."""
    comp = int(features.complexity_idx)
    base_in, base_out = _BASE_TOKENS.get(comp, (1500, 800))

    cat = task.get("category", "unknown")
    cat_mult = _CATEGORY_MULTIPLIERS.get(cat, 1.0)

    text_len = features.description_len + features.title_len
    text_mult = 1.0 + min(text_len / 2000.0, 1.0)

    skill_mult = 1.0 + features.num_skills * 0.1
    file_mult = 1.0 + max(0, features.files_affected - 1) * 0.15
    code_mult = 1.3 if features.has_code_context else 1.0

    combined = cat_mult * text_mult * skill_mult * file_mult * code_mult
    return int(base_in * combined), int(base_out * combined)


# ---------------------------------------------------------------------------
# Lightweight gradient-boosted tree ensemble (pure Python, no deps)
# ---------------------------------------------------------------------------

@dataclass
class TreeNode:
    feature_idx: int = 0
    threshold: float = 0.0
    left: Optional["TreeNode"] = None
    right: Optional["TreeNode"] = None
    value: float = 0.0  # leaf prediction (residual)

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


class DecisionStump:
    """Single-split decision tree (depth 1-3) trained on residuals."""

    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth
        self.root: Optional[TreeNode] = None

    def fit(self, X: list[list[float]], residuals: list[float]) -> None:
        self.root = self._build(X, residuals, depth=0)

    def predict(self, x: list[float]) -> float:
        if self.root is None:
            return 0.0
        return self._traverse(self.root, x)

    def _traverse(self, node: TreeNode, x: list[float]) -> float:
        if node.is_leaf:
            return node.value
        if x[node.feature_idx] <= node.threshold:
            return self._traverse(node.left, x)  # type: ignore[arg-type]
        return self._traverse(node.right, x)  # type: ignore[arg-type]

    def _build(self, X: list[list[float]], residuals: list[float], depth: int) -> TreeNode:
        if depth >= self.max_depth or len(X) <= 2:
            return TreeNode(value=self._mean(residuals))

        best_feat, best_thresh, best_score = 0, 0.0, float("inf")
        n_features = len(X[0]) if X else 0

        for f_idx in range(n_features):
            values = sorted(set(row[f_idx] for row in X))
            thresholds = [(values[i] + values[i + 1]) / 2 for i in range(len(values) - 1)]
            for thresh in thresholds[:10]:  # limit splits for speed
                left_r, right_r = [], []
                for row, r in zip(X, residuals):
                    if row[f_idx] <= thresh:
                        left_r.append(r)
                    else:
                        right_r.append(r)
                if not left_r or not right_r:
                    continue
                score = self._mse(left_r) * len(left_r) + self._mse(right_r) * len(right_r)
                if score < best_score:
                    best_feat, best_thresh, best_score = f_idx, thresh, score

        left_X, left_r, right_X, right_r = [], [], [], []
        for row, r in zip(X, residuals):
            if row[best_feat] <= best_thresh:
                left_X.append(row)
                left_r.append(r)
            else:
                right_X.append(row)
                right_r.append(r)

        if not left_X or not right_X:
            return TreeNode(value=self._mean(residuals))

        node = TreeNode(feature_idx=best_feat, threshold=best_thresh)
        node.left = self._build(left_X, left_r, depth + 1)
        node.right = self._build(right_X, right_r, depth + 1)
        return node

    @staticmethod
    def _mean(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    @staticmethod
    def _mse(vals: list[float]) -> float:
        if not vals:
            return 0.0
        m = sum(vals) / len(vals)
        return sum((v - m) ** 2 for v in vals) / len(vals)


class GradientBoostedPredictor:
    """
    Lightweight gradient-boosted regression ensemble.
    Trains two separate models: one for input tokens, one for output tokens.
    """

    def __init__(
        self,
        n_trees: int = 50,
        learning_rate: float = 0.1,
        max_depth: int = 3,
        min_samples: int = 20,
    ):
        self.n_trees = n_trees
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_samples = min_samples  # minimum training samples to use ML
        self.input_trees: list[DecisionStump] = []
        self.output_trees: list[DecisionStump] = []
        self.input_base: float = 0.0
        self.output_base: float = 0.0
        self.is_trained: bool = False
        self._feature_importances: dict[int, float] = {}
        self._training_mse_input: float = 0.0
        self._training_mse_output: float = 0.0
        self._n_samples: int = 0

    def fit(
        self,
        X: list[list[float]],
        y_input: list[float],
        y_output: list[float],
    ) -> None:
        """Train the ensemble on historical data."""
        if len(X) < self.min_samples:
            self.is_trained = False
            return

        self._n_samples = len(X)
        self.input_base = sum(y_input) / len(y_input)
        self.output_base = sum(y_output) / len(y_output)

        self.input_trees = self._boost(X, y_input, self.input_base)
        self.output_trees = self._boost(X, y_output, self.output_base)
        self._compute_feature_importances(X)
        self.is_trained = True

        # Compute training error
        self._training_mse_input = self._eval_mse(X, y_input, is_input=True)
        self._training_mse_output = self._eval_mse(X, y_output, is_input=False)

    def predict_raw(self, x: list[float]) -> tuple[float, float]:
        """Predict raw input/output token counts."""
        inp = self.input_base + sum(
            self.learning_rate * t.predict(x) for t in self.input_trees
        )
        out = self.output_base + sum(
            self.learning_rate * t.predict(x) for t in self.output_trees
        )
        return max(50, inp), max(20, out)

    def _boost(
        self, X: list[list[float]], y: list[float], base: float
    ) -> list[DecisionStump]:
        trees: list[DecisionStump] = []
        residuals = [yi - base for yi in y]
        for _ in range(self.n_trees):
            stump = DecisionStump(max_depth=self.max_depth)
            stump.fit(X, residuals)
            trees.append(stump)
            for i, row in enumerate(X):
                residuals[i] -= self.learning_rate * stump.predict(row)
        return trees

    def _eval_mse(self, X: list[list[float]], y: list[float], is_input: bool) -> float:
        total = 0.0
        for row, yi in zip(X, y):
            pred_in, pred_out = self.predict_raw(row)
            pred = pred_in if is_input else pred_out
            total += (yi - pred) ** 2
        return total / len(y) if y else 0.0

    def _compute_feature_importances(self, X: list[list[float]]) -> None:
        """Approximate feature importance by counting split usage."""
        counts: dict[int, int] = {}
        for tree_list in [self.input_trees, self.output_trees]:
            for tree in tree_list:
                self._count_splits(tree.root, counts)
        total = sum(counts.values()) or 1
        n_features = len(X[0]) if X else 0
        self._feature_importances = {
            i: counts.get(i, 0) / total for i in range(n_features)
        }

    def _count_splits(self, node: Optional[TreeNode], counts: dict[int, int]) -> None:
        if node is None or node.is_leaf:
            return
        counts[node.feature_idx] = counts.get(node.feature_idx, 0) + 1
        self._count_splits(node.left, counts)
        self._count_splits(node.right, counts)

    def get_feature_importances(self) -> dict[str, float]:
        names = TaskFeatures.feature_names()
        return {
            names[i]: self._feature_importances.get(i, 0.0)
            for i in range(len(names))
        }

    def get_confidence(self) -> float:
        """Confidence based on training set size and fit quality."""
        if not self.is_trained:
            return 0.0
        size_factor = min(self._n_samples / 200, 1.0)
        avg_mse = (self._training_mse_input + self._training_mse_output) / 2
        rmse_ratio = math.sqrt(avg_mse) / max(self.input_base, 1)
        fit_factor = max(0.0, 1.0 - rmse_ratio)
        return round(0.6 * fit_factor + 0.4 * size_factor, 4)


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

# Model tiers with approximate costs per 1K tokens
_MODEL_TIERS = {
    "local_small": {"max_tokens": 4096, "cost_per_1k": 0.0, "label": "nexus-local"},
    "local_large": {"max_tokens": 16384, "cost_per_1k": 0.0, "label": "nexus-local-large"},
    "remote_cheap": {"max_tokens": 32768, "cost_per_1k": 0.00025, "label": "nexus-remote-fast"},
    "remote_mid": {"max_tokens": 65536, "cost_per_1k": 0.003, "label": "nexus-remote"},
    "remote_expensive": {"max_tokens": 200000, "cost_per_1k": 0.015, "label": "nexus-remote-max"},
}


def _select_tier(total_tokens: int, complexity: int) -> str:
    """Select model tier based on predicted tokens and complexity."""
    if total_tokens <= 2000 and complexity <= 1:
        return "local_small"
    if total_tokens <= 8000 and complexity <= 2:
        return "local_large"
    if total_tokens <= 16000 and complexity <= 2:
        return "remote_cheap"
    if total_tokens <= 40000 and complexity <= 3:
        return "remote_mid"
    return "remote_expensive"


def _estimate_cost(total_tokens: int, tier: str) -> float:
    cost_per_1k = _MODEL_TIERS[tier]["cost_per_1k"]
    return (total_tokens / 1000.0) * cost_per_1k


# ---------------------------------------------------------------------------
# Training data store
# ---------------------------------------------------------------------------

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "state", "token_prediction_history.jsonl",
)


@dataclass
class TrainingRecord:
    features: list[float]
    actual_input_tokens: int
    actual_output_tokens: int
    category: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "features": self.features,
            "actual_input_tokens": self.actual_input_tokens,
            "actual_output_tokens": self.actual_output_tokens,
            "category": self.category,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "TrainingRecord":
        return TrainingRecord(
            features=d["features"],
            actual_input_tokens=d["actual_input_tokens"],
            actual_output_tokens=d["actual_output_tokens"],
            category=d.get("category", ""),
            timestamp=d.get("timestamp", 0.0),
        )


class TrainingDataStore:
    """Append-only JSONL store for historical token usage."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or _DEFAULT_DATA_PATH

    def load(self) -> list[TrainingRecord]:
        records = []
        p = Path(self.path)
        if not p.exists():
            return records
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(TrainingRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return records

    def append(self, record: TrainingRecord) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def count(self) -> int:
        p = Path(self.path)
        if not p.exists():
            return 0
        with open(p) as f:
            return sum(1 for line in f if line.strip())


# ---------------------------------------------------------------------------
# Main predictor engine
# ---------------------------------------------------------------------------

class TokenPredictor:
    """
    Predictive token estimation engine.

    Trains an ML model on historical execution data to predict token counts
    before task execution, guiding model routing decisions.
    Falls back to heuristic estimation when training data is insufficient.
    """

    def __init__(
        self,
        data_path: Optional[str] = None,
        n_trees: int = 50,
        learning_rate: float = 0.1,
        min_samples: int = 20,
    ):
        self.store = TrainingDataStore(data_path)
        self.model = GradientBoostedPredictor(
            n_trees=n_trees,
            learning_rate=learning_rate,
            min_samples=min_samples,
        )
        self._trained = False

    def train(self) -> dict:
        """Train the ML model on historical data. Returns training stats."""
        records = self.store.load()
        if not records:
            return {"status": "no_data", "samples": 0, "trained": False}

        X = [r.features for r in records]
        y_in = [float(r.actual_input_tokens) for r in records]
        y_out = [float(r.actual_output_tokens) for r in records]

        self.model.fit(X, y_in, y_out)
        self._trained = self.model.is_trained

        return {
            "status": "trained" if self._trained else "insufficient_data",
            "samples": len(records),
            "trained": self._trained,
            "confidence": self.model.get_confidence(),
            "feature_importances": self.model.get_feature_importances(),
        }

    def predict(self, task: dict) -> TokenPrediction:
        """Predict token usage for a task and provide routing guidance."""
        features = extract_features(task)
        vec = features.to_vector()
        complexity = int(features.complexity_idx)

        if self._trained and self.model.is_trained:
            pred_in, pred_out = self.model.predict_raw(vec)
            input_tokens = max(50, int(round(pred_in)))
            output_tokens = max(20, int(round(pred_out)))
            confidence = self.model.get_confidence()
            model_used = "ml"
            importances = self.model.get_feature_importances()
        else:
            h_in, h_out = heuristic_estimate(features, task)
            input_tokens = h_in
            output_tokens = h_out
            confidence = 0.5  # heuristic baseline confidence
            model_used = "heuristic"
            importances = {}

        total = input_tokens + output_tokens
        tier = _select_tier(total, complexity)
        cost = _estimate_cost(total, tier)

        return TokenPrediction(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            confidence=confidence,
            model_used=model_used,
            routing_hint=tier,
            estimated_cost_usd=cost,
            feature_importances=importances,
        )

    def record_actual(
        self, task: dict, actual_input: int, actual_output: int
    ) -> None:
        """Record actual token usage for future training."""
        features = extract_features(task)
        record = TrainingRecord(
            features=features.to_vector(),
            actual_input_tokens=actual_input,
            actual_output_tokens=actual_output,
            category=task.get("category", "unknown"),
            timestamp=time.time(),
        )
        self.store.append(record)

    def evaluate(self, task: dict, actual_input: int, actual_output: int) -> dict:
        """Predict and compare against actuals. Returns accuracy metrics."""
        prediction = self.predict(task)
        input_error = abs(prediction.input_tokens - actual_input) / max(actual_input, 1)
        output_error = abs(prediction.output_tokens - actual_output) / max(actual_output, 1)
        total_actual = actual_input + actual_output
        total_error = abs(prediction.total_tokens - total_actual) / max(total_actual, 1)
        return {
            "prediction": prediction.to_dict(),
            "actual_input": actual_input,
            "actual_output": actual_output,
            "input_error_pct": round(input_error * 100, 2),
            "output_error_pct": round(output_error * 100, 2),
            "total_error_pct": round(total_error * 100, 2),
            "within_25pct": total_error <= 0.25,
            "within_50pct": total_error <= 0.50,
        }

    @property
    def is_ml_active(self) -> bool:
        return self._trained and self.model.is_trained


# ---------------------------------------------------------------------------
# Synthetic data generator (for bootstrapping / testing)
# ---------------------------------------------------------------------------

def generate_synthetic_data(n: int = 200, seed: int = 42) -> list[tuple[dict, int, int]]:
    """Generate synthetic task/token pairs that follow realistic distributions."""
    rng = random.Random(seed)
    categories = list(TaskCategory)
    complexities = list(Complexity)
    data = []

    for _ in range(n):
        cat = rng.choice(categories)
        comp = rng.choice(complexities)
        n_skills = rng.randint(0, 5)
        files = rng.randint(1, 8)
        desc_words = rng.randint(5, 80)
        description = " ".join(rng.choices(
            ["fix", "add", "implement", "refactor", "test", "debug",
             "optimize", "migrate", "update", "review", "deploy", "monitor",
             "the", "a", "for", "with", "in", "on", "to", "from"],
            k=desc_words,
        ))

        task = {
            "category": cat.value,
            "complexity": comp.name.lower(),
            "title": f"Task: {cat.value} ({comp.name})",
            "description": description,
            "skills": [rng.choice(["code_gen", "debug", "test", "review", "refactor"])
                       for _ in range(n_skills)],
            "files_affected": files,
            "code_context": rng.random() > 0.5,
        }

        features = extract_features(task)
        h_in, h_out = heuristic_estimate(features, task)
        # Add realistic noise (+-30%)
        noise_in = 1.0 + rng.uniform(-0.3, 0.3)
        noise_out = 1.0 + rng.uniform(-0.3, 0.3)
        actual_in = max(50, int(h_in * noise_in))
        actual_out = max(20, int(h_out * noise_out))

        data.append((task, actual_in, actual_out))

    return data


# ---------------------------------------------------------------------------
# __main__: comprehensive verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("=" * 70)
    print("TOKEN PREDICTOR — VERIFICATION SUITE")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Feature extraction
    # ------------------------------------------------------------------
    print("\n[1] Feature extraction...")
    task_simple = {
        "category": "bug_fix",
        "title": "Fix login crash",
        "description": "App errors when users submit invalid password",
        "skills": ["debug"],
        "files_affected": 1,
    }
    feats = extract_features(task_simple)
    assert feats.category_idx == _CATEGORY_INDEX["bug_fix"], "category index wrong"
    assert feats.num_skills == 1.0, "skill count wrong"
    assert feats.files_affected == 1.0, "files_affected wrong"
    assert feats.description_len > 0, "description_len should be > 0"
    assert len(feats.to_vector()) == 8, "feature vector must have 8 elements"
    print(f"  Features: {feats.to_vector()}")
    print("  PASS")

    # ------------------------------------------------------------------
    # 2. Complexity inference
    # ------------------------------------------------------------------
    print("\n[2] Complexity inference...")
    assert _infer_complexity("fix a small typo") == Complexity.TRIVIAL or \
           _infer_complexity("fix a small typo") == Complexity.LOW, \
           "simple text should be trivial or low"
    assert _infer_complexity("architect a new microservice migration").value >= 3, \
           "architecture task should be high+"
    assert _infer_complexity("production security breach incident").value >= 4, \
           "security incident should be critical"
    assert _infer_complexity("blah blah blah") == Complexity.MEDIUM, \
           "unknown text defaults to medium"
    print("  PASS")

    # ------------------------------------------------------------------
    # 3. Heuristic estimation
    # ------------------------------------------------------------------
    print("\n[3] Heuristic estimation...")
    feats_med = extract_features({
        "category": "code_gen",
        "complexity": "medium",
        "title": "Implement new feature",
        "description": "Add user authentication with OAuth2 support",
        "skills": ["code_gen", "arch"],
        "files_affected": 3,
    })
    h_in, h_out = heuristic_estimate(feats_med, {"category": "code_gen"})
    assert h_in > 1500, f"medium code_gen should have >1500 input tokens, got {h_in}"
    assert h_out > 800, f"medium code_gen should have >800 output tokens, got {h_out}"
    assert h_in < 50000, "tokens should be reasonable"

    # Trivial task should use fewer tokens
    feats_trivial = extract_features({
        "category": "scoring",
        "complexity": "trivial",
        "title": "Score",
        "description": "Rate it",
        "skills": [],
        "files_affected": 1,
    })
    t_in, t_out = heuristic_estimate(feats_trivial, {"category": "scoring"})
    assert t_in < h_in, "trivial should use fewer tokens than medium"
    print(f"  Medium code_gen: {h_in} in / {h_out} out")
    print(f"  Trivial scoring: {t_in} in / {t_out} out")
    print("  PASS")

    # ------------------------------------------------------------------
    # 4. Gradient boosted model training
    # ------------------------------------------------------------------
    print("\n[4] ML model training...")
    synthetic = generate_synthetic_data(n=200, seed=42)
    assert len(synthetic) == 200, "should generate 200 samples"

    X_train = [extract_features(t).to_vector() for t, _, _ in synthetic]
    y_in = [float(ai) for _, ai, _ in synthetic]
    y_out = [float(ao) for _, _, ao in synthetic]

    gb = GradientBoostedPredictor(n_trees=30, learning_rate=0.1, min_samples=20)
    gb.fit(X_train, y_in, y_out)
    assert gb.is_trained, "model should be trained with 200 samples"
    assert gb.get_confidence() > 0.0, "confidence should be > 0"

    importances = gb.get_feature_importances()
    assert len(importances) == 8, "should have 8 feature importances"
    assert abs(sum(importances.values()) - 1.0) < 0.01, "importances should sum to ~1.0"
    print(f"  Confidence: {gb.get_confidence()}")
    print(f"  Top features: {sorted(importances.items(), key=lambda x: -x[1])[:3]}")
    print("  PASS")

    # ------------------------------------------------------------------
    # 5. ML predictions should be in reasonable range
    # ------------------------------------------------------------------
    print("\n[5] ML prediction quality...")
    errors = []
    for task, actual_in, actual_out in synthetic[:50]:
        vec = extract_features(task).to_vector()
        pred_in, pred_out = gb.predict_raw(vec)
        err = abs(pred_in - actual_in) / max(actual_in, 1)
        errors.append(err)

    avg_error = sum(errors) / len(errors)
    within_50 = sum(1 for e in errors if e <= 0.5) / len(errors)
    assert avg_error < 1.0, f"average error should be < 100%, got {avg_error:.2%}"
    assert within_50 > 0.5, f"at least 50% should be within 50% error, got {within_50:.2%}"
    print(f"  Average error: {avg_error:.2%}")
    print(f"  Within 50%: {within_50:.2%}")
    print("  PASS")

    # ------------------------------------------------------------------
    # 6. End-to-end TokenPredictor with data store
    # ------------------------------------------------------------------
    print("\n[6] End-to-end TokenPredictor...")
    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = os.path.join(tmpdir, "history.jsonl")
        predictor = TokenPredictor(data_path=data_path, n_trees=30, min_samples=20)

        # Predict without training (heuristic fallback)
        pred = predictor.predict(task_simple)
        assert pred.model_used == "heuristic", "should use heuristic without training"
        assert pred.confidence == 0.5, "heuristic confidence should be 0.5"
        assert pred.input_tokens > 0, "should predict positive input tokens"
        assert pred.output_tokens > 0, "should predict positive output tokens"
        assert pred.routing_hint in _MODEL_TIERS, f"invalid tier: {pred.routing_hint}"
        assert pred.estimated_cost_usd >= 0, "cost should be non-negative"
        print(f"  Heuristic: {pred.input_tokens} in / {pred.output_tokens} out -> {pred.routing_hint}")

        # Record training data
        for task, actual_in, actual_out in synthetic:
            predictor.record_actual(task, actual_in, actual_out)

        assert predictor.store.count() == 200, "should have 200 records"

        # Train
        stats = predictor.train()
        assert stats["trained"], "should be trained now"
        assert stats["samples"] == 200
        assert predictor.is_ml_active, "ML should be active"

        # Predict with ML model
        pred_ml = predictor.predict(task_simple)
        assert pred_ml.model_used == "ml", "should use ML after training"
        assert pred_ml.confidence > 0.0, "ML confidence > 0"
        assert pred_ml.input_tokens > 0
        assert len(pred_ml.feature_importances) == 8
        print(f"  ML: {pred_ml.input_tokens} in / {pred_ml.output_tokens} out -> {pred_ml.routing_hint}")
        print(f"  Confidence: {pred_ml.confidence}")

        # Evaluate
        eval_result = predictor.evaluate(task_simple, 400, 250)
        assert "input_error_pct" in eval_result
        assert "within_25pct" in eval_result
        assert isinstance(eval_result["within_50pct"], bool)
        print(f"  Eval error: {eval_result['total_error_pct']}%")

    print("  PASS")

    # ------------------------------------------------------------------
    # 7. Routing hints
    # ------------------------------------------------------------------
    print("\n[7] Routing tier selection...")
    assert _select_tier(500, 0) == "local_small", "small trivial -> local_small"
    assert _select_tier(5000, 2) == "local_large", "medium 5k -> local_large"
    assert _select_tier(12000, 2) == "remote_cheap", "medium 12k -> remote_cheap"
    assert _select_tier(30000, 3) == "remote_mid", "high 30k -> remote_mid"
    assert _select_tier(100000, 4) == "remote_expensive", "critical 100k -> remote_expensive"

    cost_free = _estimate_cost(5000, "local_small")
    assert cost_free == 0.0, "local models should be free"
    cost_paid = _estimate_cost(10000, "remote_mid")
    assert cost_paid > 0, "remote models should have cost"
    print(f"  Local cost for 5K tokens: ${cost_free}")
    print(f"  Remote-mid cost for 10K tokens: ${cost_paid:.4f}")
    print("  PASS")

    # ------------------------------------------------------------------
    # 8. Serialization
    # ------------------------------------------------------------------
    print("\n[8] Serialization...")
    pred_dict = pred_ml.to_dict()
    assert isinstance(pred_dict, dict)
    assert "input_tokens" in pred_dict
    assert "routing_hint" in pred_dict
    assert isinstance(pred_dict["confidence"], float)
    assert isinstance(pred_dict["estimated_cost_usd"], float)
    print(f"  Dict keys: {list(pred_dict.keys())}")
    print("  PASS")

    # ------------------------------------------------------------------
    # 9. Edge cases
    # ------------------------------------------------------------------
    print("\n[9] Edge cases...")
    # Empty task
    pred_empty = predictor.predict({})
    assert pred_empty.input_tokens >= 50, "minimum 50 input tokens"
    assert pred_empty.output_tokens >= 20, "minimum 20 output tokens"

    # Very large task
    pred_large = predictor.predict({
        "category": "arch",
        "complexity": "critical",
        "title": "Full system migration",
        "description": "Migrate entire monolith to microservices " * 100,
        "skills": ["arch", "code_gen", "refactor", "debug", "test"],
        "files_affected": 50,
        "code_context": True,
    })
    assert pred_large.total_tokens > pred_empty.total_tokens, \
        "large task should predict more tokens"

    # Insufficient training data
    with tempfile.TemporaryDirectory() as tmpdir:
        small_predictor = TokenPredictor(
            data_path=os.path.join(tmpdir, "small.jsonl"),
            min_samples=100,
        )
        for task, ai, ao in synthetic[:5]:
            small_predictor.record_actual(task, ai, ao)
        small_stats = small_predictor.train()
        assert not small_stats["trained"], "5 samples < 100 min_samples"
        assert not small_predictor.is_ml_active
        pred_fallback = small_predictor.predict(task_simple)
        assert pred_fallback.model_used == "heuristic"

    print("  PASS")

    # ------------------------------------------------------------------
    # 10. Training data persistence
    # ------------------------------------------------------------------
    print("\n[10] Data persistence...")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "persist.jsonl")
        store = TrainingDataStore(path)
        assert store.count() == 0

        rec = TrainingRecord(
            features=[1.0, 2.0, 100.0, 20.0, 1.0, 2.0, 0.0, 15.0],
            actual_input_tokens=500,
            actual_output_tokens=300,
            category="bug_fix",
            timestamp=time.time(),
        )
        store.append(rec)
        store.append(rec)
        assert store.count() == 2

        loaded = store.load()
        assert len(loaded) == 2
        assert loaded[0].actual_input_tokens == 500
        assert loaded[0].features == [1.0, 2.0, 100.0, 20.0, 1.0, 2.0, 0.0, 15.0]

        roundtrip = TrainingRecord.from_dict(rec.to_dict())
        assert roundtrip.actual_input_tokens == rec.actual_input_tokens
        assert roundtrip.features == rec.features

    print("  PASS")

    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("ALL 10 CHECKS PASSED")
    print("=" * 70)
