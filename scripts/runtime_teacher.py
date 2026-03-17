#!/usr/bin/env python3
"""Runtime teacher: learns from failures and teaches local agents to avoid repeating mistakes.

Maintains a lesson database that agents consult before executing. Lessons are derived from:
- ROI kill switch events
- Resource ceiling hits
- Takeover events
- Generic output retries
- Collision events
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LESSONS_PATH = REPO_ROOT / "state" / "runtime-lessons.json"
FEEDBACK_DIR = REPO_ROOT / "feedback"
MAX_LESSONS = 100
LESSON_TTL_DAYS = 30


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_lessons() -> list[dict]:
    if not LESSONS_PATH.exists():
        return []
    try:
        data = json.loads(LESSONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else data.get("lessons", [])


def save_lessons(lessons: list[dict]) -> None:
    LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Prune old lessons
    cutoff = datetime.now() - timedelta(days=LESSON_TTL_DAYS)
    active = []
    for lesson in lessons:
        stamp = lesson.get("learned_at", "")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            active.append(lesson)
            continue
        if when >= cutoff:
            active.append(lesson)
    active = active[-MAX_LESSONS:]
    LESSONS_PATH.write_text(json.dumps(active, indent=2) + "\n")


def record_lesson(
    category: str,
    trigger: str,
    lesson: str,
    fix: str,
    context: str = "",
) -> dict:
    """Record a new lesson for the runtime to learn from."""
    entry = {
        "category": category,
        "trigger": trigger,
        "lesson": lesson,
        "fix": fix,
        "context": context,
        "learned_at": _now_iso(),
        "applied_count": 0,
    }
    lessons = load_lessons()

    # Deduplicate by trigger+category
    lessons = [l for l in lessons if not (l.get("trigger") == trigger and l.get("category") == category)]
    lessons.append(entry)
    save_lessons(lessons)
    return entry


def get_lessons_for_stage(stage_id: str) -> list[dict]:
    """Return lessons relevant to a specific stage/role."""
    lessons = load_lessons()
    relevant = []
    for lesson in lessons:
        ctx = lesson.get("context", "").lower()
        trigger = lesson.get("trigger", "").lower()
        cat = lesson.get("category", "").lower()
        if stage_id.lower() in ctx or stage_id.lower() in trigger or cat in {"all", "global"}:
            relevant.append(lesson)
    return relevant


def get_lessons_for_category(category: str) -> list[dict]:
    """Return lessons for a category (resource, roi, quality, coordination, takeover)."""
    return [l for l in load_lessons() if l.get("category") == category]


def mark_applied(trigger: str) -> None:
    """Increment applied_count for a lesson by trigger."""
    lessons = load_lessons()
    for lesson in lessons:
        if lesson.get("trigger") == trigger:
            lesson["applied_count"] = lesson.get("applied_count", 0) + 1
            lesson["last_applied"] = _now_iso()
    save_lessons(lessons)


def format_lessons_for_prompt(lessons: list[dict], max_chars: int = 2000) -> str:
    """Format lessons as a prompt block for injection into agent prompts."""
    if not lessons:
        return ""
    lines = ["## Runtime lessons (learned from prior failures)"]
    chars = len(lines[0])
    for lesson in lessons:
        entry = (
            f"- [{lesson['category']}] {lesson['lesson']} "
            f"Fix: {lesson['fix']}"
        )
        if chars + len(entry) > max_chars:
            break
        lines.append(entry)
        chars += len(entry)
    return "\n".join(lines)


def ingest_from_feedback() -> int:
    """Scan feedback logs and extract lessons from takeover/optimize events."""
    count = 0
    for filename in ("prompt-log.md", "workflow-evolution.md"):
        path = FEEDBACK_DIR / filename
        if not path.exists():
            continue
        content = path.read_text(errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("- ") or "[takeover]" not in line.lower() and "[optimize]" not in line.lower():
                continue
            category = "takeover" if "[takeover]" in line.lower() else "optimize"
            # Extract reason
            reason = ""
            if "reason:" in line.lower():
                reason = line.split("reason:", 1)[-1].strip()
            elif "reason:" in content:
                idx = content.find(line)
                after = content[idx:idx+500]
                for sub_line in after.splitlines()[1:4]:
                    if "reason:" in sub_line.lower():
                        reason = sub_line.split("reason:", 1)[-1].strip()
                        break
            if reason:
                record_lesson(
                    category=category,
                    trigger=reason[:100],
                    lesson=f"Runtime hit {category} event: {reason[:200]}",
                    fix="Detect earlier, downgrade model or hand off to cloud sooner.",
                    context=line[:200],
                )
                count += 1
    return count


def report() -> str:
    """Human-readable lesson report."""
    lessons = load_lessons()
    lines = [f"RUNTIME LESSONS ({len(lessons)} active)", ""]
    categories: dict[str, int] = {}
    for lesson in lessons:
        cat = lesson.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    for cat, count in sorted(categories.items()):
        lines.append(f"  {cat:15} {count} lessons")

    lines.append("")
    for lesson in lessons[-10:]:
        applied = lesson.get("applied_count", 0)
        lines.append(
            f"  [{lesson['category']}] {lesson['lesson'][:80]}"
            f" (applied {applied}x, learned {lesson.get('learned_at', '?')})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print(report())
    elif len(sys.argv) > 1 and sys.argv[1] == "ingest":
        count = ingest_from_feedback()
        print(f"Ingested {count} lessons from feedback logs.")
    elif len(sys.argv) > 1 and sys.argv[1] == "for-stage" and len(sys.argv) > 2:
        lessons = get_lessons_for_stage(sys.argv[2])
        print(format_lessons_for_prompt(lessons))
    else:
        print("Usage: runtime_teacher.py <report|ingest|for-stage STAGE_ID>")
