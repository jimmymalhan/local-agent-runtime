#!/usr/bin/env python3
import json
import pathlib
import sys


def text_from_item(item):
    if not isinstance(item, dict):
        return str(item)
    metadata = item.get("metadata") or {}
    for key in ("text", "chunk_text", "content", "passage", "document", "snippet"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("text", "chunk_text", "content", "passage", "document", "snippet"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(item, ensure_ascii=True)


def metadata_from_item(item):
    if not isinstance(item, dict):
        return {}
    metadata = item.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def score_from_item(item):
    if not isinstance(item, dict):
        return None
    for key in ("score", "similarity", "_score"):
        value = item.get(key)
        if value is not None:
            return value
    return None


def normalize(body):
    if isinstance(body, list):
        results = body
    else:
        results = body.get("results", body)
    if isinstance(results, dict):
        if isinstance(results.get("matches"), list):
            results = results["matches"]
        elif isinstance(results.get("results"), list):
            results = results["results"]
        else:
            results = []
    if not isinstance(results, list):
        results = []

    normalized = []
    for idx, item in enumerate(results, start=1):
        normalized.append(
            {
                "id": idx,
                "score": score_from_item(item),
                "text": text_from_item(item),
                "metadata": metadata_from_item(item),
                "raw": item,
            }
        )
    return normalized


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: normalize_retrieval_results.py <retrieval-json-file>")
    path = pathlib.Path(sys.argv[1])
    try:
        body = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} does not contain valid JSON: {exc}") from exc
    print(json.dumps({"results": normalize(body)}, indent=2))


if __name__ == "__main__":
    main()
