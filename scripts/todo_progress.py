#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import time


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TODO_PATH = REPO_ROOT / "state" / "todo.md"
SECTION_RE = re.compile(r"^##\s+(.+)$")
ITEM_RE = re.compile(r"^- \[(?P<state>[xX ])\] (?P<text>.+)$")
LANE_ORDER = ("local", "cloud", "shared", "general")
LANE_LABELS = {
    "local": "Local agents",
    "cloud": "Cloud/session takeover",
    "shared": "Shared coordination",
    "general": "General",
}
EXPLICIT_LANE_RE = re.compile(r"^\[(local|cloud|shared|general)\]\s*", re.IGNORECASE)
LANE_RULES = {
    "cloud": ("cloud", "codex session", "claude session", "cursor", "paid api", "external api", "rate limit", "takeover", "take over"),
    "shared": ("common plan", "feedback", "coordination", "migration", "review", "qa", "uat", "progress", "session"),
    "local": ("local", "ollama", "local agent", "local agents", "local runtime", "sglang", "pinecone", "mcp", "rag", "skill", "autopilot"),
}
USE_CASE_ORDER = ("product", "business", "technical", "general")
USE_CASE_LABELS = {
    "product": "Product use cases",
    "business": "Business use cases",
    "technical": "Technical/runtime",
    "general": "General",
}
USE_CASE_RULES = {
    "product": ("product", "user", "ux", "session", "response style", "acceptance", "workflow"),
    "business": ("business", "sales", "marketing", "roi", "release", "24*7", "24x7", "free to run"),
    "technical": ("runtime", "local", "ollama", "sglang", "pinecone", "mcp", "checkpoint", "ci", "review", "qa", "model", "agent"),
}


def render_bar(percent: float, width: int = 24) -> str:
    percent = max(0.0, min(100.0, float(percent)))
    filled = round(width * percent / 100.0)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def percent(done: int, total: int) -> float:
    return round((done / total) * 100.0, 1) if total else 0.0


def parse_todo(path: pathlib.Path = TODO_PATH):
    sections = []
    current = None
    if not path.exists():
        return {
            "overall": {"done": 0, "open": 0, "total": 0, "percent": 0.0},
            "lanes": lane_summary([]),
            "use_cases": use_case_summary([]),
            "sections": [],
        }

    for raw_line in path.read_text().splitlines():
        line = raw_line.rstrip()
        section_match = SECTION_RE.match(line)
        if section_match:
            current = {"name": section_match.group(1), "items": []}
            sections.append(current)
            continue
        item_match = ITEM_RE.match(line)
        if item_match and current is not None:
            done = item_match.group("state").lower() == "x"
            text = item_match.group("text")
            current["items"].append(
                {
                    "done": done,
                    "text": text,
                    "lane": lane_for_item(current["name"], text),
                    "use_case": use_case_for_item(current["name"], text),
                }
            )

    for section in sections:
        done = sum(1 for item in section["items"] if item["done"])
        total = len(section["items"])
        section["done"] = done
        section["open"] = total - done
        section["total"] = total
        section["percent"] = percent(done, total)

    total_done = sum(section["done"] for section in sections)
    total_items = sum(section["total"] for section in sections)
    lanes = lane_summary(sections)
    use_cases = use_case_summary(sections)
    return {
        "overall": {
            "done": total_done,
            "open": total_items - total_done,
            "total": total_items,
            "percent": percent(total_done, total_items),
        },
        "lanes": lanes,
        "use_cases": use_cases,
        "sections": sections,
    }


def lane_for_item(section_name: str, text: str) -> str:
    explicit = EXPLICIT_LANE_RE.match(text)
    if explicit:
        return explicit.group(1).lower()
    blob = f"{section_name} {text}".lower()
    for lane in ("cloud", "local", "shared"):
        markers = LANE_RULES.get(lane, ())
        if any(marker in blob for marker in markers):
            return lane
    return "general"


def lane_summary(sections):
    summary = {lane: {"done": 0, "open": 0, "total": 0, "percent": 0.0} for lane in LANE_ORDER}
    for section in sections:
        for item in section["items"]:
            lane = item["lane"]
            summary[lane]["total"] += 1
            if item["done"]:
                summary[lane]["done"] += 1
            else:
                summary[lane]["open"] += 1
    for lane in summary.values():
        lane["percent"] = percent(lane["done"], lane["total"])
    return summary


def use_case_for_item(section_name: str, text: str) -> str:
    blob = f"{section_name} {text}".lower()
    for use_case in ("product", "business", "technical"):
        markers = USE_CASE_RULES.get(use_case, ())
        if any(marker in blob for marker in markers):
            return use_case
    return "general"


def use_case_summary(sections):
    summary = {name: {"done": 0, "open": 0, "total": 0, "percent": 0.0} for name in USE_CASE_ORDER}
    for section in sections:
        for item in section["items"]:
            bucket = summary[item["use_case"]]
            bucket["total"] += 1
            if item["done"]:
                bucket["done"] += 1
            else:
                bucket["open"] += 1
    for bucket in summary.values():
        bucket["percent"] = percent(bucket["done"], bucket["total"])
    return summary


def render_report(data) -> str:
    overall = data["overall"]
    lines = [
        f"TODO {render_bar(overall['percent'])} {overall['percent']:5.1f}% | done {overall['done']} / total {overall['total']} | open {overall['open']}"
    ]
    lines.append("LANES")
    for name in LANE_ORDER:
        lane = data["lanes"][name]
        if lane["total"] == 0:
            continue
        lines.append(
            f"- {LANE_LABELS[name]}: {render_bar(lane['percent'], 20)} {lane['percent']:5.1f}% | done {lane['done']} / total {lane['total']} | open {lane['open']}"
        )
    lines.append("USE CASES")
    for name in USE_CASE_ORDER:
        bucket = data["use_cases"][name]
        if bucket["total"] == 0:
            continue
        lines.append(
            f"- {USE_CASE_LABELS[name]}: {render_bar(bucket['percent'], 20)} {bucket['percent']:5.1f}% | done {bucket['done']} / total {bucket['total']} | open {bucket['open']}"
        )
    lines.append("SECTIONS")
    for section in data["sections"]:
        if section["total"] == 0:
            continue
        lines.append(
            f"- {section['name']}: {render_bar(section['percent'], 20)} {section['percent']:5.1f}% | done {section['done']} / total {section['total']} | open {section['open']}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Refresh the todo progress view every few seconds.")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval for --watch.")
    args = parser.parse_args()

    if args.watch:
        while True:
            print("\033[2J\033[H", end="")
            print(render_report(parse_todo()))
            time.sleep(max(0.2, args.interval))
    else:
        print(render_report(parse_todo()))


if __name__ == "__main__":
    main()
