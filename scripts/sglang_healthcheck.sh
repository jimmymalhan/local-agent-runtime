#!/bin/bash
set -euo pipefail

SGLANG_BASE_URL=${SGLANG_BASE_URL:-http://127.0.0.1:30000}
SGLANG_HEALTHCHECK_DEEP=${SGLANG_HEALTHCHECK_DEEP:-0}
SGLANG_MODEL=${SGLANG_MODEL:-qwen2.5-coder:7b}

python3 - "$SGLANG_BASE_URL" "$SGLANG_HEALTHCHECK_DEEP" "$SGLANG_MODEL" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base_url, deep, model = sys.argv[1:]
paths = [
    ("health", "/health"),
    ("server_info", "/get_server_info"),
    ("models", "/v1/models"),
]
report = {"base_url": base_url, "checks": []}
ok = False

for label, path in paths:
    req = urllib.request.Request(base_url + path, method="GET")
    item = {"name": label, "path": path}
    try:
      with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read().decode(errors="ignore")
      item["ok"] = True
      item["status"] = 200
      item["preview"] = body[:400]
      ok = True
    except urllib.error.HTTPError as exc:
      item["ok"] = False
      item["status"] = exc.code
      item["error"] = str(exc)
    except Exception as exc:
      item["ok"] = False
      item["status"] = None
      item["error"] = str(exc)
    report["checks"].append(item)

if deep == "1":
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
            "temperature": 0,
            "max_tokens": 8,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        base_url + "/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    item = {"name": "chat_smoke", "path": "/v1/chat/completions"}
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode(errors="ignore")
        item["ok"] = True
        item["status"] = 200
        item["preview"] = body[:400]
        ok = True
    except urllib.error.HTTPError as exc:
        item["ok"] = False
        item["status"] = exc.code
        item["error"] = str(exc)
    except Exception as exc:
        item["ok"] = False
        item["status"] = None
        item["error"] = str(exc)
    report["checks"].append(item)

print(json.dumps(report, indent=2))
raise SystemExit(0 if ok else 1)
PY
