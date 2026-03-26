"""
prioritizer.py — RICE scoring + MoSCoW classification for task backlog.

RICE = (Reach x Impact x Confidence) / Effort
MoSCoW = Must/Should/Could/Won't
"""


class RICEScorer:
    @staticmethod
    def score(reach: float, impact: float, confidence: float, effort: float) -> float:
        """reach: users affected, impact: 1-3, confidence: 0-1, effort: person-weeks"""
        if effort <= 0:
            return 0
        return round((reach * impact * confidence) / effort, 2)

    @staticmethod
    def classify_moscow(rice_score: float, is_blocking: bool, deadline_days: int = 999) -> str:
        if is_blocking or deadline_days <= 3:
            return "must"
        elif rice_score >= 10:
            return "should"
        elif rice_score >= 3:
            return "could"
        else:
            return "wont"

    @staticmethod
    def sort_backlog(tasks: list) -> list:
        """Sort by: must first, then by RICE score desc, then by blocking_score desc"""
        order = {"must": 0, "should": 1, "could": 2, "wont": 3}
        return sorted(tasks, key=lambda t: (
            order.get(t.get("moscow", "could"), 2),
            -t.get("rice_score", 0),
            -t.get("blocking_score", 0)
        ))

    @staticmethod
    def auto_score_task(task: dict) -> dict:
        """Auto-assign RICE scores based on task metadata"""
        category = task.get("category", "code_gen")
        title = task.get("title", "").lower()

        reach_map = {"scaffold": 100, "migrate": 50, "test_gen": 30, "code_gen": 10, "doc": 5}
        impact_map = {"scaffold": 3, "bug_fix": 3, "test_gen": 2, "refactor": 1, "doc": 1}
        effort_map = {"scaffold": 2, "migrate": 3, "code_gen": 0.5, "test_gen": 1, "doc": 0.5}

        reach = reach_map.get(category, 10)
        impact = impact_map.get(category, 2)
        confidence = 0.8 if "test" in title else 0.7
        effort = effort_map.get(category, 1)

        task["rice_score"] = RICEScorer.score(reach, impact, confidence, effort)
        task["moscow"] = RICEScorer.classify_moscow(
            task["rice_score"],
            is_blocking=task.get("blocks_count", 0) > 2
        )
        return task
