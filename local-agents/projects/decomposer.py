"""
ProjectDecomposer — heuristic brief → epics → tasks (no LLM required).

Pattern library:
  - fastapi / flask / django   → backend epics
  - react / nextjs / vue       → frontend epics
  - auth / authentication      → auth epic
  - database / postgres etc.   → db epic
  - docker / kubernetes / deploy → infra epic
  - test / testing             → testing epic
  - api / REST / GraphQL       → api epic
  - redis / cache              → caching epic
  - celery / queue / async tasks → workers epic
"""
import re
from dataclasses import asdict
from typing import Optional

from projects.schema import Epic, SubTask


# ---------------------------------------------------------------------------
# Pattern definitions
# Each entry: (keywords, epic_title, epic_description, tasks[])
# tasks[]: (title, description, category, complexity)  complexity: 1-3
# ---------------------------------------------------------------------------

_PATTERNS = [
    # ---- Backend framework ------------------------------------------------
    {
        "keywords": ["fastapi", "flask", "django"],
        "epic_title": "Backend Setup",
        "epic_description": "Initialize backend framework, project structure, and core configuration.",
        "priority": 1,
        "tasks": [
            ("Project scaffold", "Initialize project structure, virtual env, and dependencies.", "scaffold", 1),
            ("Data models", "Define ORM models or Pydantic schemas.", "code_gen", 2),
            ("Core routes", "Implement primary API route handlers.", "code_gen", 2),
            ("Unit tests", "Write unit tests for models and route handlers.", "tdd", 2),
            ("API documentation", "Auto-generate or write OpenAPI/Swagger docs.", "doc", 1),
            ("Docker image", "Write Dockerfile and .dockerignore for the backend service.", "scaffold", 1),
        ],
    },
    # ---- Frontend framework -----------------------------------------------
    {
        "keywords": ["react", "nextjs", "next.js", "vue", "angular", "svelte"],
        "epic_title": "Frontend Setup",
        "epic_description": "Initialize frontend framework, component library, and routing.",
        "priority": 1,
        "tasks": [
            ("Project scaffold", "Bootstrap frontend project with chosen framework and tooling.", "scaffold", 1),
            ("Core components", "Build reusable UI components (buttons, forms, modals).", "code_gen", 2),
            ("Page layouts", "Create page-level layouts and routing structure.", "code_gen", 2),
            ("API client", "Implement typed API client for backend communication.", "code_gen", 2),
            ("Component tests", "Write unit and snapshot tests for key components.", "tdd", 2),
            ("Production build", "Configure build pipeline and static asset optimization.", "scaffold", 1),
        ],
    },
    # ---- Auth ---------------------------------------------------------------
    {
        "keywords": ["auth", "authentication", "login", "signup", "register", "oauth", "sso", "jwt", "session"],
        "epic_title": "Authentication",
        "epic_description": "User registration, login, session/token management, and access control.",
        "priority": 1,
        "tasks": [
            ("User model", "Create user entity with hashed password and profile fields.", "code_gen", 2),
            ("Register endpoint", "Implement user registration with validation and duplicate check.", "code_gen", 2),
            ("Login endpoint", "Implement login with credential verification and token issuance.", "code_gen", 2),
            ("JWT / session middleware", "Protect routes with token or session validation middleware.", "code_gen", 2),
            ("Password reset flow", "Implement forgot-password and reset-password endpoints.", "code_gen", 3),
            ("Auth tests", "Integration tests for register, login, protected routes, and reset.", "tdd", 3),
        ],
    },
    # ---- Database -----------------------------------------------------------
    {
        "keywords": ["database", "postgres", "postgresql", "mysql", "sqlite", "mongodb", "db", "orm", "prisma", "sqlalchemy"],
        "epic_title": "Database Layer",
        "epic_description": "Schema design, migrations, ORM models, and seed data.",
        "priority": 1,
        "tasks": [
            ("Schema design", "Design normalized entity-relationship schema.", "arch", 2),
            ("Migrations", "Write and run database migration scripts.", "code_gen", 2),
            ("ORM models", "Implement ORM model classes with relationships.", "code_gen", 2),
            ("Seed data", "Create seed scripts for development and test data.", "code_gen", 1),
            ("Query optimization", "Add indexes and optimize slow queries.", "refactor", 2),
        ],
    },
    # ---- Infrastructure / DevOps -------------------------------------------
    {
        "keywords": ["docker", "kubernetes", "k8s", "deploy", "deployment", "ci", "cd", "github actions", "helm", "terraform"],
        "epic_title": "Infrastructure & Deployment",
        "epic_description": "Containerization, orchestration, CI/CD pipelines, and deployment scripts.",
        "priority": 2,
        "tasks": [
            ("Dockerfile", "Write optimized multi-stage Dockerfile.", "scaffold", 1),
            ("Docker Compose", "Write docker-compose.yml for local development stack.", "scaffold", 1),
            ("CI pipeline", "Configure GitHub Actions (or equivalent) for lint, test, build.", "scaffold", 2),
            ("Deploy scripts", "Write deployment scripts for staging and production.", "scaffold", 2),
            ("Environment config", "Document and template all environment variables.", "doc", 1),
        ],
    },
    # ---- Testing ------------------------------------------------------------
    {
        "keywords": ["test", "testing", "e2e", "pytest", "jest", "cypress", "playwright"],
        "epic_title": "Testing Suite",
        "epic_description": "Comprehensive unit, integration, and end-to-end test coverage.",
        "priority": 2,
        "tasks": [
            ("Unit tests", "Write unit tests for all pure functions and utilities.", "tdd", 2),
            ("Integration tests", "Test module interactions and external service boundaries.", "tdd", 2),
            ("End-to-end tests", "Automated browser or API flow tests covering happy paths.", "e2e", 3),
            ("Coverage report", "Configure coverage tooling and enforce minimum thresholds.", "scaffold", 1),
        ],
    },
    # ---- API / REST / GraphQL -----------------------------------------------
    {
        "keywords": ["api", "rest", "restful", "graphql", "endpoints", "routes"],
        "epic_title": "API Layer",
        "epic_description": "REST or GraphQL API design, validation, serialization, and documentation.",
        "priority": 1,
        "tasks": [
            ("Route definitions", "Define all API endpoints with HTTP methods and URL patterns.", "code_gen", 2),
            ("Request validation", "Add schema validation for all request bodies and params.", "code_gen", 2),
            ("Response serializers", "Implement response serializers/DTOs for consistent output.", "code_gen", 2),
            ("Error handling", "Centralized error handler with proper HTTP status codes.", "code_gen", 2),
            ("Rate limiting", "Add rate limiting middleware to prevent abuse.", "code_gen", 2),
            ("API docs", "Generate or write OpenAPI/GraphQL schema documentation.", "doc", 1),
        ],
    },
    # ---- Caching ------------------------------------------------------------
    {
        "keywords": ["redis", "cache", "caching", "memcached", "cdn"],
        "epic_title": "Caching Layer",
        "epic_description": "Cache setup, cache decorators, TTL strategy, and cache invalidation.",
        "priority": 2,
        "tasks": [
            ("Cache client setup", "Configure Redis or Memcached client with connection pooling.", "scaffold", 1),
            ("Cache decorators", "Implement decorator/helper for caching function results.", "code_gen", 2),
            ("TTL strategy", "Define TTL values per data type and document the strategy.", "doc", 1),
            ("Cache invalidation", "Implement targeted and pattern-based cache invalidation.", "code_gen", 2),
            ("Cache tests", "Unit and integration tests for cache hit/miss behavior.", "tdd", 2),
        ],
    },
    # ---- Background workers -------------------------------------------------
    {
        "keywords": ["celery", "worker", "queue", "task queue", "async tasks", "job", "rq", "bull", "sidekiq"],
        "epic_title": "Background Workers",
        "epic_description": "Async task definitions, worker configuration, retry logic, and monitoring.",
        "priority": 2,
        "tasks": [
            ("Worker setup", "Configure task queue broker and worker process.", "scaffold", 2),
            ("Task definitions", "Implement background task functions with retry logic.", "code_gen", 2),
            ("Worker config", "Tune concurrency, timeouts, and queue routing.", "scaffold", 1),
            ("Dead-letter queue", "Set up DLQ or error queue for failed tasks.", "code_gen", 2),
            ("Worker monitoring", "Add health checks and metrics for worker processes.", "code_gen", 2),
        ],
    },
    # ---- CLI ----------------------------------------------------------------
    {
        "keywords": ["cli", "command line", "command-line", "argparse", "click", "typer"],
        "epic_title": "CLI Interface",
        "epic_description": "Command-line interface with argument parsing, help text, and subcommands.",
        "priority": 1,
        "tasks": [
            ("CLI scaffold", "Set up CLI framework (Click/Typer/argparse) with entry point.", "scaffold", 1),
            ("Core commands", "Implement primary subcommands and argument handling.", "code_gen", 2),
            ("Help text", "Write clear help strings and usage examples for every command.", "doc", 1),
            ("Error output", "Consistent error formatting with exit codes.", "code_gen", 1),
            ("CLI tests", "Tests for command parsing, output, and exit codes.", "tdd", 2),
        ],
    },
]


def _detect_type(brief_lower: str) -> str:
    """Infer project type from brief keywords."""
    if any(k in brief_lower for k in ["fastapi", "flask", "django"]):
        return "fastapi" if "fastapi" in brief_lower else ("flask" if "flask" in brief_lower else "django")
    if any(k in brief_lower for k in ["nextjs", "next.js"]):
        return "nextjs"
    if "react" in brief_lower:
        return "react"
    if "vue" in brief_lower:
        return "vue"
    if "django" in brief_lower:
        return "django"
    if any(k in brief_lower for k in ["cli", "command line", "argparse", "click", "typer"]):
        return "cli"
    if any(k in brief_lower for k in ["pipeline", "orchestrat", "agent"]):
        return "pipeline"
    return "unknown"


class ProjectDecomposer:
    """
    Decomposes a plain-English project brief into structured epics and tasks.

    Uses heuristic pattern matching — no LLM dependency.
    """

    def decompose(self, brief: str, project_type: str = "") -> dict:
        """
        Given a project brief, return a dict with:
          {
            "project_type": str,
            "epics": [
              {
                "title": str,
                "description": str,
                "priority": int,
                "tasks": [SubTask dict, ...]
              },
              ...
            ]
          }
        """
        brief_lower = brief.lower()
        detected_type = project_type or _detect_type(brief_lower)

        matched_epics: list[dict] = []
        seen_epic_titles: set[str] = set()

        for pattern in _PATTERNS:
            if any(kw in brief_lower for kw in pattern["keywords"]):
                title = pattern["epic_title"]
                if title in seen_epic_titles:
                    continue
                seen_epic_titles.add(title)

                tasks = []
                for t_title, t_desc, t_cat, _complexity in pattern["tasks"]:
                    task = SubTask(
                        title=t_title,
                        description=t_desc,
                        category=t_cat,
                    )
                    tasks.append(asdict(task))

                matched_epics.append(
                    {
                        "title": title,
                        "description": pattern["epic_description"],
                        "priority": pattern["priority"],
                        "tasks": tasks,
                    }
                )

        # If nothing matched, generate a generic epic
        if not matched_epics:
            task = SubTask(
                title="Implement core feature",
                description=f"Implement: {brief[:200]}",
                category="code_gen",
            )
            matched_epics.append(
                {
                    "title": "Core Implementation",
                    "description": brief[:300],
                    "priority": 1,
                    "tasks": [asdict(task)],
                }
            )

        # Sort epics by priority ascending (1=high first)
        matched_epics.sort(key=lambda e: e["priority"])

        return {
            "project_type": detected_type,
            "epics": matched_epics,
        }

    def decompose_into_project(self, brief: str, name: str = "", project_type: str = "") -> dict:
        """
        Full decomposition returning a dict ready to pass to ProjectManager.

        Returns:
          {
            "name": str,
            "type": str,
            "description": str,
            "epics": [Epic dict with embedded SubTask dicts]
          }
        """
        result = self.decompose(brief, project_type)

        epics_out = []
        for ep_data in result["epics"]:
            epic = Epic(
                title=ep_data["title"],
                description=ep_data["description"],
                priority=ep_data["priority"],
            )
            e_dict = asdict(epic)
            e_dict["tasks"] = ep_data["tasks"]
            epics_out.append(e_dict)

        return {
            "name": name or brief[:60].strip(),
            "type": result["project_type"],
            "description": brief,
            "epics": epics_out,
        }
