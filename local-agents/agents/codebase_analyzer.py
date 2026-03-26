#!/usr/bin/env python3
"""
codebase_analyzer.py — Understand any real project on disk.

Detects: project type, language, framework, dependencies, entry points,
test setup, architecture patterns. Generates project_map.json.

Usage:
    from agents.codebase_analyzer import analyze
    result = analyze("/path/to/any/project")
    # Returns: {type, language, framework, files, deps, entry_points, test_setup,
    #            patterns, health_score, summary, project_map}
"""
import os
import sys
import json
import time
from pathlib import Path
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "codebase_analyzer",
    "version": 1,
    "capabilities": ["analyze", "onboard", "project_map"],
    "model": "local",
    "input_schema": {
        "path": "str",  # directory to analyze; defaults to cwd
    },
    "output_schema": {
        "status": "str",
        "type": "str",
        "language": "str",
        "framework": "str",
        "files": "dict",
        "deps": "dict",
        "entry_points": "list",
        "test_setup": "dict",
        "patterns": "list",
        "health_score": "int",
        "summary": "str",
        "project_map": "str",  # path to .nexus/project_map.json
        "quality": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

# Directories to skip during traversal
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "vendor",
}

MAX_DEPTH = 4


# ---------------------------------------------------------------------------
# 1. Project type detection
# ---------------------------------------------------------------------------

def _detect_project_type(root: Path) -> dict:
    """Return {type, language, framework, raw_deps}."""
    result = {
        "type": "unknown",
        "language": "unknown",
        "framework": "unknown",
        "raw_deps": [],
    }

    # Node.js
    pkg = root / "package.json"
    if pkg.exists():
        result["type"] = "node"
        result["language"] = "javascript"
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            result["raw_deps"] = list(deps.keys())
            if "next" in deps:
                result["framework"] = "next.js"
                result["language"] = "typescript" if (root / "tsconfig.json").exists() else "javascript"
            elif "react" in deps:
                result["framework"] = "react"
                result["language"] = "typescript" if (root / "tsconfig.json").exists() else "javascript"
            elif "express" in deps:
                result["framework"] = "express"
            elif "fastify" in deps:
                result["framework"] = "fastify"
            elif "vue" in deps:
                result["framework"] = "vue"
            elif "svelte" in deps:
                result["framework"] = "svelte"
        except Exception:
            pass
        return result

    # Python
    req = root / "requirements.txt"
    pyproject = root / "pyproject.toml"
    setup_py = root / "setup.py"
    if req.exists() or pyproject.exists() or setup_py.exists():
        result["type"] = "python"
        result["language"] = "python"
        raw: list[str] = []
        if req.exists():
            try:
                lines = req.read_text(encoding="utf-8", errors="replace").splitlines()
                raw = [l.split("==")[0].split(">=")[0].split("<=")[0].strip().lower()
                       for l in lines if l.strip() and not l.startswith("#")]
            except Exception:
                pass
        if pyproject.exists():
            try:
                text = pyproject.read_text(encoding="utf-8", errors="replace")
                import re
                matches = re.findall(r'"([a-zA-Z0-9_\-]+)\s*[>=<!]', text)
                raw += [m.lower() for m in matches]
            except Exception:
                pass
        result["raw_deps"] = list(set(raw))
        if "fastapi" in raw:
            result["framework"] = "fastapi"
        elif "django" in raw:
            result["framework"] = "django"
        elif "flask" in raw:
            result["framework"] = "flask"
        elif "starlette" in raw:
            result["framework"] = "starlette"
        return result

    # Go
    gomod = root / "go.mod"
    if gomod.exists():
        result["type"] = "go"
        result["language"] = "go"
        try:
            text = gomod.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            if lines:
                result["framework"] = lines[0].replace("module", "").strip()
        except Exception:
            pass
        return result

    # Rust
    cargo = root / "Cargo.toml"
    if cargo.exists():
        result["type"] = "rust"
        result["language"] = "rust"
        try:
            import re
            text = cargo.read_text(encoding="utf-8", errors="replace")
            name_match = re.search(r'name\s*=\s*"([^"]+)"', text)
            if name_match:
                result["framework"] = name_match.group(1)
        except Exception:
            pass
        return result

    # Java
    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        result["type"] = "java"
        result["language"] = "java"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            result["framework"] = "gradle"
        else:
            result["framework"] = "maven"
        return result

    # Ruby
    if (root / "Gemfile").exists():
        result["type"] = "ruby"
        result["language"] = "ruby"
        if (root / "config" / "application.rb").exists():
            result["framework"] = "rails"
        return result

    # .NET
    csproj_files = list(root.glob("*.csproj"))
    if csproj_files:
        result["type"] = "dotnet"
        result["language"] = "csharp"
        return result

    return result


# ---------------------------------------------------------------------------
# 2. File tree mapping
# ---------------------------------------------------------------------------

def _walk_tree(root: Path, max_depth: int = MAX_DEPTH) -> dict:
    """
    Walk directory up to max_depth, skipping SKIP_DIRS.
    Returns {
        ext_counts: {".py": 12, ...},
        key_dirs: ["src", "tests", ...],
        entry_points: ["main.py", ...],
        total_files: int,
    }
    """
    ext_counts: dict[str, int] = {}
    key_dir_names = {"src", "app", "api", "models", "tests", "test", "migrations",
                     "components", "pages", "lib", "pkg", "cmd", "domain",
                     "application", "infrastructure", "services", "handlers",
                     "controllers", "routes", "views", "templates", "repository",
                     "repositories", "service", "adapters", "utils", "helpers"}
    found_key_dirs: set[str] = set()
    entry_point_names = {
        "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
        "index.ts", "index.js", "main.ts", "main.js",
        "server.ts", "server.js", "app.ts", "app.js",
        "main.go", "main.rs",
    }
    found_entry_points: list[str] = []
    total_files = 0

    def _walk(path: Path, depth: int) -> None:
        nonlocal total_files
        if depth > max_depth:
            return
        try:
            entries = list(path.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".github", ".gitlab"}:
                continue
            if entry.is_dir():
                if entry.name in SKIP_DIRS:
                    continue
                if entry.name.lower() in key_dir_names:
                    found_key_dirs.add(entry.name)
                _walk(entry, depth + 1)
            elif entry.is_file():
                total_files += 1
                suffix = entry.suffix.lower()
                ext_counts[suffix] = ext_counts.get(suffix, 0) + 1
                if entry.name in entry_point_names:
                    rel = str(entry.relative_to(root))
                    found_entry_points.append(rel)

    _walk(root, 0)

    return {
        "ext_counts": ext_counts,
        "key_dirs": sorted(found_key_dirs),
        "entry_points": found_entry_points,
        "total_files": total_files,
    }


# ---------------------------------------------------------------------------
# 3. Dependency extraction and categorization
# ---------------------------------------------------------------------------

_DEP_CATEGORIES = {
    # web framework
    "web_framework": {
        "express", "fastify", "koa", "hapi", "nestjs", "@nestjs/core",
        "fastapi", "django", "flask", "starlette", "tornado", "sanic",
        "gin", "echo", "fiber", "actix-web", "warp",
    },
    # database
    "database": {
        "mongoose", "sequelize", "typeorm", "prisma", "knex", "@prisma/client",
        "sqlalchemy", "databases", "tortoise-orm", "peewee", "pymongo",
        "redis", "ioredis", "pg", "mysql2", "sqlite3", "psycopg2", "aiomysql",
        "asyncpg",
    },
    # auth
    "auth": {
        "passport", "jsonwebtoken", "bcrypt", "bcryptjs", "@auth/core",
        "python-jose", "pyjwt", "passlib", "authlib", "django-allauth",
        "oauthlib",
    },
    # cache
    "cache": {
        "redis", "ioredis", "node-cache", "lru-cache",
        "cachetools", "aiocache", "redis-py",
    },
    # testing
    "testing": {
        "jest", "vitest", "mocha", "chai", "supertest", "@testing-library/react",
        "playwright", "cypress", "puppeteer",
        "pytest", "unittest", "hypothesis", "factory-boy", "faker",
    },
    # dev tools
    "dev_tools": {
        "eslint", "prettier", "typescript", "ts-node", "nodemon", "webpack",
        "vite", "rollup", "esbuild", "babel", "@types/node",
        "black", "ruff", "mypy", "pyright", "isort", "flake8", "pylint",
    },
}


def _categorize_deps(raw_deps: list[str]) -> dict:
    """Return {category: [dep, ...]} groupings."""
    result: dict[str, list[str]] = {k: [] for k in _DEP_CATEGORIES}
    result["other"] = []
    for dep in raw_deps:
        dep_lower = dep.lower()
        placed = False
        for cat, keywords in _DEP_CATEGORIES.items():
            if dep_lower in keywords or any(dep_lower.startswith(k) for k in keywords if len(k) > 4):
                result[cat].append(dep)
                placed = True
                break
        if not placed:
            result["other"].append(dep)
    return {k: v for k, v in result.items() if v}


# ---------------------------------------------------------------------------
# 4. Test setup detection
# ---------------------------------------------------------------------------

def _detect_test_setup(root: Path, key_dirs: list[str]) -> dict:
    """Return {framework, config_file, test_dirs, has_coverage}."""
    framework = "unknown"
    config_file = None
    has_coverage = False

    # Python test frameworks
    for candidate in ["pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini"]:
        path = root / candidate
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "[tool:pytest]" in text or "[pytest]" in text or "[tool.pytest" in text:
                    framework = "pytest"
                    config_file = candidate
                    has_coverage = "coverage" in text or "cov" in text
                    break
            except Exception:
                pass

    # Node.js test frameworks
    if framework == "unknown":
        for jest_cfg in ["jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs"]:
            if (root / jest_cfg).exists():
                framework = "jest"
                config_file = jest_cfg
                break
    if framework == "unknown":
        for vitest_cfg in ["vitest.config.ts", "vitest.config.js", "vitest.config.mts"]:
            if (root / vitest_cfg).exists():
                framework = "vitest"
                config_file = vitest_cfg
                break
    if framework == "unknown":
        for mocha_cfg in [".mocharc.yml", ".mocharc.js", ".mocharc.json", ".mocharc.cjs"]:
            if (root / mocha_cfg).exists():
                framework = "mocha"
                config_file = mocha_cfg
                break

    # Check package.json for jest config
    if framework == "unknown":
        pkg = root / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
                if "jest" in data:
                    framework = "jest"
                    config_file = "package.json"
                elif "vitest" in str(data.get("scripts", {})):
                    framework = "vitest"
                    config_file = "package.json"
            except Exception:
                pass

    # Go: presence of *_test.go files
    if framework == "unknown":
        import re
        for f in root.rglob("*_test.go"):
            if not any(skip in str(f) for skip in SKIP_DIRS):
                framework = "go test"
                break

    # Infer test dirs
    test_dirs = [d for d in key_dirs if d.lower() in {"tests", "test", "__tests__", "spec"}]

    # Coverage presence
    if not has_coverage:
        has_coverage = any([
            (root / ".nycrc").exists(),
            (root / ".nycrc.json").exists(),
            (root / "coverage").is_dir(),
            (root / ".coverage").exists(),
            any("coverage" in str(f.name) for f in root.glob("*.cfg")),
        ])

    return {
        "framework": framework,
        "config_file": config_file,
        "test_dirs": test_dirs,
        "has_coverage": has_coverage,
    }


# ---------------------------------------------------------------------------
# 5. Architecture pattern detection
# ---------------------------------------------------------------------------

def _detect_patterns(root: Path, key_dirs: list[str]) -> list[str]:
    """Return list of detected architecture patterns."""
    dirs_lower = {d.lower() for d in key_dirs}
    patterns: list[str] = []

    # MVC
    has_models = "models" in dirs_lower
    has_views = "views" in dirs_lower or "templates" in dirs_lower
    has_controllers = "controllers" in dirs_lower or "routes" in dirs_lower
    if has_models and (has_views or has_controllers):
        patterns.append("mvc")

    # Clean / Hexagonal architecture
    if "domain" in dirs_lower and "application" in dirs_lower and "infrastructure" in dirs_lower:
        patterns.append("clean_architecture")
    elif "domain" in dirs_lower and "adapters" in dirs_lower:
        patterns.append("hexagonal")

    # Microservices: docker-compose with multiple services
    dc = root / "docker-compose.yml"
    dc_yaml = root / "docker-compose.yaml"
    for dc_path in [dc, dc_yaml]:
        if dc_path.exists():
            try:
                text = dc_path.read_text(encoding="utf-8", errors="replace")
                service_count = text.count("\n  ") - text.count("volumes:") - text.count("networks:")
                if service_count > 2:
                    patterns.append("microservices")
                break
            except Exception:
                break

    # Monorepo
    packages_dir = root / "packages"
    apps_dir = root / "apps"
    if packages_dir.is_dir() or apps_dir.is_dir():
        patterns.append("monorepo")

    # Layered (api + service + repository)
    if "api" in dirs_lower and ("service" in dirs_lower or "services" in dirs_lower):
        if "repository" in dirs_lower or "repositories" in dirs_lower:
            patterns.append("layered")

    return patterns if patterns else ["unstructured"]


# ---------------------------------------------------------------------------
# 6. Health score
# ---------------------------------------------------------------------------

def _compute_health_score(root: Path) -> tuple[int, dict]:
    """Return (score, breakdown) where score is 0-100."""
    breakdown: dict[str, bool] = {}
    score = 0

    # +20 if has tests
    has_tests = (
        (root / "tests").is_dir()
        or (root / "test").is_dir()
        or (root / "__tests__").is_dir()
        or (root / "spec").is_dir()
        or bool(list(root.glob("*.test.*"))[:1])
        or bool(list(root.glob("*_test.go"))[:1])
        or bool(list(root.glob("test_*.py"))[:1])
    )
    breakdown["has_tests"] = has_tests
    if has_tests:
        score += 20

    # +20 if has CI/CD
    has_ci = (root / ".github" / "workflows").is_dir() or (root / ".gitlab-ci.yml").exists()
    breakdown["has_ci"] = has_ci
    if has_ci:
        score += 20

    # +15 if has Docker
    has_docker = (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists() or (root / "docker-compose.yaml").exists()
    breakdown["has_docker"] = has_docker
    if has_docker:
        score += 15

    # +15 if has README
    has_readme = (root / "README.md").exists() or (root / "README.rst").exists() or (root / "README.txt").exists()
    breakdown["has_readme"] = has_readme
    if has_readme:
        score += 15

    # +10 if has lock file
    has_lock = (
        (root / "package-lock.json").exists()
        or (root / "yarn.lock").exists()
        or (root / "pnpm-lock.yaml").exists()
        or (root / "poetry.lock").exists()
        or (root / "Pipfile.lock").exists()
        or (root / "Cargo.lock").exists()
        or (root / "go.sum").exists()
        or (root / "Gemfile.lock").exists()
    )
    breakdown["has_lock_file"] = has_lock
    if has_lock:
        score += 10

    # +10 if has linting config
    lint_files = [
        ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
        ".pylintrc", "ruff.toml", ".ruff.toml", "pyproject.toml",
        ".flake8", ".stylelintrc",
    ]
    has_lint = any((root / f).exists() for f in lint_files)
    # also check pyproject.toml for [tool.ruff] or [tool.pylint]
    if not has_lint and (root / "pyproject.toml").exists():
        try:
            text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
            has_lint = "[tool.ruff]" in text or "[tool.pylint]" in text or "[tool.flake8]" in text
        except Exception:
            pass
    breakdown["has_linting"] = has_lint
    if has_lint:
        score += 10

    # +10 if has type checking
    type_check_files = [
        "tsconfig.json", "mypy.ini", "pyrightconfig.json", ".pyrightconfig.json",
    ]
    has_types = any((root / f).exists() for f in type_check_files)
    if not has_types and (root / "pyproject.toml").exists():
        try:
            text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
            has_types = "[tool.mypy]" in text or "[tool.pyright]" in text
        except Exception:
            pass
    breakdown["has_type_checking"] = has_types
    if has_types:
        score += 10

    return score, breakdown


# ---------------------------------------------------------------------------
# 7. Summary generation
# ---------------------------------------------------------------------------

def _generate_summary(root: Path, project_info: dict) -> str:
    """Generate 2-3 sentence summary from README + package.json/pyproject.toml."""
    description = ""

    # Try README.md first paragraph
    for readme_name in ["README.md", "README.rst", "README.txt"]:
        readme = root / readme_name
        if readme.exists():
            try:
                text = readme.read_text(encoding="utf-8", errors="replace")
                lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("!")]
                if lines:
                    description = lines[0][:300]
                    break
            except Exception:
                pass

    # Try package.json description
    if not description:
        pkg = root / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
                description = data.get("description", "")[:300]
            except Exception:
                pass

    # Try pyproject.toml description
    if not description:
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                import re
                text = pyproject.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'description\s*=\s*"([^"]+)"', text)
                if m:
                    description = m.group(1)[:300]
            except Exception:
                pass

    lang = project_info.get("language", "unknown")
    fw = project_info.get("framework", "unknown")
    ptype = project_info.get("type", "unknown")

    if description:
        base = description
    else:
        base = f"A {lang} project"
        if fw != "unknown":
            base += f" using {fw}"

    framework_note = f" Built with {fw}." if fw not in ("unknown", ptype) else ""
    type_note = f" Project type: {ptype}." if ptype != "unknown" else ""

    return f"{base}.{framework_note}{type_note}".replace("..", ".")


# ---------------------------------------------------------------------------
# 8. Write project_map.json
# ---------------------------------------------------------------------------

def _write_project_map(root: Path, data: dict) -> str:
    """Write .nexus/project_map.json and return its path."""
    nexus_dir = root / ".nexus"
    nexus_dir.mkdir(exist_ok=True)
    map_path = nexus_dir / "project_map.json"
    map_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(map_path)


# ---------------------------------------------------------------------------
# Main analyze() function
# ---------------------------------------------------------------------------

def analyze(path: str) -> dict:
    """
    Analyze any project directory and return structured understanding.

    Args:
        path: Absolute or relative path to a project directory.

    Returns:
        dict with keys: type, language, framework, files, deps, entry_points,
                        test_setup, patterns, health_score, summary, project_map
    """
    start = time.time()
    root = Path(path).resolve()

    if not root.exists():
        return {
            "status": "failed",
            "error": f"Path does not exist: {root}",
            "quality": 0,
            "elapsed_s": 0.0,
        }
    if not root.is_dir():
        return {
            "status": "failed",
            "error": f"Path is not a directory: {root}",
            "quality": 0,
            "elapsed_s": 0.0,
        }

    # 1. Project type
    project_info = _detect_project_type(root)

    # 2. File tree
    tree = _walk_tree(root, MAX_DEPTH)
    # Merge entry points from tree with project_info
    entry_points = tree["entry_points"]

    # 3. Dependencies
    raw_deps = project_info.pop("raw_deps", [])
    deps = _categorize_deps(raw_deps)

    # 4. Test setup
    test_setup = _detect_test_setup(root, tree["key_dirs"])

    # 5. Architecture patterns
    patterns = _detect_patterns(root, tree["key_dirs"])

    # 6. Health score
    health_score, health_breakdown = _compute_health_score(root)

    # 7. Summary
    summary = _generate_summary(root, project_info)

    # Assemble full map
    project_map_data = {
        "root": str(root),
        "type": project_info["type"],
        "language": project_info["language"],
        "framework": project_info["framework"],
        "files": {
            "total": tree["total_files"],
            "by_extension": tree["ext_counts"],
            "key_dirs": tree["key_dirs"],
        },
        "deps": deps,
        "entry_points": entry_points,
        "test_setup": test_setup,
        "patterns": patterns,
        "health_score": health_score,
        "health_breakdown": health_breakdown,
        "summary": summary,
    }

    # 8. Write project_map.json
    map_path = _write_project_map(root, project_map_data)
    project_map_data["project_map"] = map_path

    elapsed = round(time.time() - start, 2)

    return {
        "status": "done",
        "type": project_info["type"],
        "language": project_info["language"],
        "framework": project_info["framework"],
        "files": project_map_data["files"],
        "deps": deps,
        "entry_points": entry_points,
        "test_setup": test_setup,
        "patterns": patterns,
        "health_score": health_score,
        "health_breakdown": health_breakdown,
        "summary": summary,
        "project_map": map_path,
        "quality": min(100, 50 + health_score // 2),
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# run() — standard agent entry point
# ---------------------------------------------------------------------------

def run(task: dict) -> dict:
    """
    Standard agent entry point. task["path"] or task["codebase_path"] or cwd.

    Args:
        task: dict with optional "path" or "codebase_path" key.

    Returns:
        Standard agent result dict.
    """
    path = (
        task.get("path")
        or task.get("codebase_path")
        or task.get("description")
        or os.getcwd()
    )
    # If description is a path that exists, use it; otherwise use cwd
    if path and not Path(path).exists():
        path = os.getcwd()

    result = analyze(str(path))
    result.setdefault("agent", "codebase_analyzer")
    result.setdefault("tokens_used", 0)
    return result


# ---------------------------------------------------------------------------
# CLI usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys
    target = _sys.argv[1] if len(_sys.argv) > 1 else os.getcwd()
    out = analyze(target)
    print(json.dumps(out, indent=2, default=str))
