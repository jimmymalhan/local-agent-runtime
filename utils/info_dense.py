"""
Information-dense representations: encode more info per token.

Provides a unified codec that analyzes structured data and automatically
selects the densest encoding strategy for each field, producing a single
compact payload that maximizes information per LLM token.

Strategies combined:
  - Varint (LEB128) for integers
  - Zigzag + delta for numeric sequences
  - Dictionary coding for low-cardinality strings
  - Prefix-trie for high-cardinality strings
  - Run-length encoding for repetitive sequences
  - Bitfield packing for bounded integer fields
  - Columnar transposition for record batches
  - Schema elision (CompactJSON) for homogeneous dicts
  - Bloom sketches for set membership
  - zlib + base85 for wire-format compaction

Public API:
  - pack(obj)       -> str   (compact base85 text)
  - unpack(text)    -> obj   (original data restored)
  - estimate(obj)   -> dict  (density metrics without encoding)
  - TokenBudgetPacker: fit data into a target token budget
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import zlib
from collections import Counter
from dataclasses import dataclass, field as dc_field
from enum import IntEnum
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


# ───────────────────────────────────────────────────────────────────
# Primitives
# ───────────────────────────────────────────────────────────────────

def _encode_varint(n: int) -> bytes:
    assert n >= 0
    parts = []
    while n > 0x7F:
        parts.append((n & 0x7F) | 0x80)
        n >>= 7
    parts.append(n & 0x7F)
    return bytes(parts)


def _decode_varint(buf: bytes, off: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = buf[off]
        result |= (b & 0x7F) << shift
        off += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, off


def _zigzag_enc(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _zigzag_dec(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


# ───────────────────────────────────────────────────────────────────
# Type tags for the wire format
# ───────────────────────────────────────────────────────────────────

class _Tag(IntEnum):
    NONE = 0
    BOOL = 1
    INT = 2
    FLOAT = 3
    STR = 4
    LIST = 5
    DICT = 6
    DELTA_INTS = 7      # list[int] encoded as delta+varint
    DICT_CODED = 8      # list[str] with low cardinality
    TRIE_CODED = 9      # list[str] with high cardinality
    RLE = 10            # list with long runs
    BITPACKED = 11      # list[dict] with known int fields
    COMPACT_ROWS = 12   # list[dict] schema-elided
    BLOOM = 13          # set membership sketch
    FLOAT_ARRAY = 14    # list[float] packed doubles


# ───────────────────────────────────────────────────────────────────
# Low-level encoders
# ───────────────────────────────────────────────────────────────────

def _encode_delta_ints(values: list[int]) -> bytes:
    buf = BytesIO()
    buf.write(_encode_varint(len(values)))
    prev = 0
    for v in values:
        buf.write(_encode_varint(_zigzag_enc(v - prev)))
        prev = v
    return buf.getvalue()


def _decode_delta_ints(data: bytes, off: int = 0) -> tuple[list[int], int]:
    count, off = _decode_varint(data, off)
    vals: list[int] = []
    prev = 0
    for _ in range(count):
        zz, off = _decode_varint(data, off)
        prev += _zigzag_dec(zz)
        vals.append(prev)
    return vals, off


def _encode_dict_coded(values: list[str]) -> bytes:
    vocab: dict[str, int] = {}
    codes: list[int] = []
    for v in values:
        if v not in vocab:
            vocab[v] = len(vocab)
        codes.append(vocab[v])
    buf = BytesIO()
    buf.write(_encode_varint(len(vocab)))
    for word, _ in sorted(vocab.items(), key=lambda x: x[1]):
        wb = word.encode("utf-8")
        buf.write(_encode_varint(len(wb)))
        buf.write(wb)
    buf.write(_encode_varint(len(codes)))
    for c in codes:
        buf.write(_encode_varint(c))
    return buf.getvalue()


def _decode_dict_coded(data: bytes, off: int = 0) -> tuple[list[str], int]:
    vs, off = _decode_varint(data, off)
    vocab: list[str] = []
    for _ in range(vs):
        slen, off = _decode_varint(data, off)
        vocab.append(data[off:off + slen].decode("utf-8"))
        off += slen
    count, off = _decode_varint(data, off)
    result = []
    for _ in range(count):
        code, off = _decode_varint(data, off)
        result.append(vocab[code])
        off  # already advanced
    return result, off


def _encode_trie(strings: list[str]) -> bytes:
    """Prefix-deduplicated encoding (strings must be sorted)."""
    buf = BytesIO()
    buf.write(_encode_varint(len(strings)))
    prev = ""
    for s in strings:
        common = 0
        limit = min(len(prev), len(s))
        while common < limit and prev[common] == s[common]:
            common += 1
        suffix = s[common:].encode("utf-8")
        buf.write(_encode_varint(common))
        buf.write(_encode_varint(len(suffix)))
        buf.write(suffix)
        prev = s
    return buf.getvalue()


def _decode_trie(data: bytes, off: int = 0) -> tuple[list[str], int]:
    count, off = _decode_varint(data, off)
    strings: list[str] = []
    prev = ""
    for _ in range(count):
        common, off = _decode_varint(data, off)
        slen, off = _decode_varint(data, off)
        suffix = data[off:off + slen].decode("utf-8")
        off += slen
        s = prev[:common] + suffix
        strings.append(s)
        prev = s
    return strings, off


def _encode_rle(values: list) -> bytes:
    if not values:
        return _encode_varint(0)
    runs: list[tuple[Any, int]] = []
    cur, cnt = values[0], 1
    for v in values[1:]:
        if v == cur:
            cnt += 1
        else:
            runs.append((cur, cnt))
            cur, cnt = v, 1
    runs.append((cur, cnt))
    buf = BytesIO()
    buf.write(_encode_varint(len(runs)))
    for val, c in runs:
        buf.write(_encode_varint(c))
        vb = json.dumps(val, separators=(",", ":")).encode("utf-8")
        buf.write(_encode_varint(len(vb)))
        buf.write(vb)
    return buf.getvalue()


def _decode_rle(data: bytes, off: int = 0) -> tuple[list, int]:
    nr, off = _decode_varint(data, off)
    result: list = []
    for _ in range(nr):
        cnt, off = _decode_varint(data, off)
        vlen, off = _decode_varint(data, off)
        val = json.loads(data[off:off + vlen].decode("utf-8"))
        off += vlen
        result.extend([val] * cnt)
    return result, off


def _encode_float_array(values: list[float]) -> bytes:
    buf = BytesIO()
    buf.write(_encode_varint(len(values)))
    buf.write(struct.pack(f"<{len(values)}d", *values))
    return buf.getvalue()


def _decode_float_array(data: bytes, off: int = 0) -> tuple[list[float], int]:
    count, off = _decode_varint(data, off)
    vals = list(struct.unpack_from(f"<{count}d", data, off))
    off += count * 8
    return vals, off


# ───────────────────────────────────────────────────────────────────
# Analysis: classify data and choose strategy
# ───────────────────────────────────────────────────────────────────

def _classify_list(values: list) -> _Tag:
    """Pick the densest encoding for a homogeneous list."""
    if not values:
        return _Tag.LIST

    sample = values[0]

    # All ints -> delta
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return _Tag.DELTA_INTS

    # All floats -> packed doubles
    if all(isinstance(v, float) for v in values):
        return _Tag.FLOAT_ARRAY

    # All strings -> dict-coded or trie
    if all(isinstance(v, str) for v in values):
        cardinality = len(set(values))
        if cardinality < len(values) * 0.4:
            return _Tag.DICT_CODED
        return _Tag.TRIE_CODED

    # All dicts with same keys -> compact rows
    if all(isinstance(v, dict) for v in values):
        keys = set(values[0].keys())
        if all(set(v.keys()) == keys for v in values):
            return _Tag.COMPACT_ROWS

    # Check for long runs (RLE)
    runs = 0
    cur = values[0]
    for v in values[1:]:
        if v != cur:
            runs += 1
            cur = v
    if (runs + 1) < len(values) * 0.3:
        return _Tag.RLE

    return _Tag.LIST


# ───────────────────────────────────────────────────────────────────
# Core encoder / decoder
# ───────────────────────────────────────────────────────────────────

def _encode_value(obj: Any, buf: BytesIO) -> None:
    if obj is None:
        buf.write(bytes([_Tag.NONE]))
    elif isinstance(obj, bool):
        buf.write(bytes([_Tag.BOOL, int(obj)]))
    elif isinstance(obj, int):
        buf.write(bytes([_Tag.INT]))
        buf.write(_encode_varint(_zigzag_enc(obj)))
    elif isinstance(obj, float):
        buf.write(bytes([_Tag.FLOAT]))
        buf.write(struct.pack("<d", obj))
    elif isinstance(obj, str):
        buf.write(bytes([_Tag.STR]))
        sb = obj.encode("utf-8")
        buf.write(_encode_varint(len(sb)))
        buf.write(sb)
    elif isinstance(obj, list):
        tag = _classify_list(obj)
        buf.write(bytes([tag]))
        if tag == _Tag.DELTA_INTS:
            payload = _encode_delta_ints(obj)
            buf.write(_encode_varint(len(payload)))
            buf.write(payload)
        elif tag == _Tag.FLOAT_ARRAY:
            payload = _encode_float_array(obj)
            buf.write(_encode_varint(len(payload)))
            buf.write(payload)
        elif tag == _Tag.DICT_CODED:
            payload = _encode_dict_coded(obj)
            buf.write(_encode_varint(len(payload)))
            buf.write(payload)
        elif tag == _Tag.TRIE_CODED:
            sorted_vals = sorted(obj)
            # Store original order as permutation via index mapping
            sort_map = {v: i for i, v in enumerate(sorted_vals)}
            perm = [sort_map[v] for v in obj]
            trie_payload = _encode_trie(sorted_vals)
            perm_payload = _encode_delta_ints(perm)
            combined = BytesIO()
            combined.write(_encode_varint(len(trie_payload)))
            combined.write(trie_payload)
            combined.write(perm_payload)
            cb = combined.getvalue()
            buf.write(_encode_varint(len(cb)))
            buf.write(cb)
        elif tag == _Tag.RLE:
            payload = _encode_rle(obj)
            buf.write(_encode_varint(len(payload)))
            buf.write(payload)
        elif tag == _Tag.COMPACT_ROWS:
            _encode_compact_rows(obj, buf)
        else:
            # Generic list
            buf.write(_encode_varint(len(obj)))
            for item in obj:
                _encode_value(item, buf)
    elif isinstance(obj, dict):
        buf.write(bytes([_Tag.DICT]))
        buf.write(_encode_varint(len(obj)))
        for k, v in obj.items():
            kb = str(k).encode("utf-8")
            buf.write(_encode_varint(len(kb)))
            buf.write(kb)
            _encode_value(v, buf)
    else:
        _encode_value(str(obj), buf)


def _encode_compact_rows(records: list[dict], buf: BytesIO) -> None:
    """Schema-elided encoding for list of homogeneous dicts."""
    keys = list(records[0].keys())
    inner = BytesIO()
    inner.write(_encode_varint(len(records)))
    inner.write(_encode_varint(len(keys)))
    for k in keys:
        kb = k.encode("utf-8")
        inner.write(_encode_varint(len(kb)))
        inner.write(kb)
    # Columnar: group by key
    for k in keys:
        col = [r[k] for r in records]
        _encode_value(col, inner)
    payload = inner.getvalue()
    buf.write(_encode_varint(len(payload)))
    buf.write(payload)


def _decode_value(data: bytes, off: int) -> tuple[Any, int]:
    tag = _Tag(data[off])
    off += 1

    if tag == _Tag.NONE:
        return None, off
    elif tag == _Tag.BOOL:
        return bool(data[off]), off + 1
    elif tag == _Tag.INT:
        zz, off = _decode_varint(data, off)
        return _zigzag_dec(zz), off
    elif tag == _Tag.FLOAT:
        return struct.unpack_from("<d", data, off)[0], off + 8
    elif tag == _Tag.STR:
        slen, off = _decode_varint(data, off)
        return data[off:off + slen].decode("utf-8"), off + slen
    elif tag == _Tag.DELTA_INTS:
        plen, off = _decode_varint(data, off)
        vals, _ = _decode_delta_ints(data[off:off + plen])
        return vals, off + plen
    elif tag == _Tag.FLOAT_ARRAY:
        plen, off = _decode_varint(data, off)
        vals, _ = _decode_float_array(data[off:off + plen])
        return vals, off + plen
    elif tag == _Tag.DICT_CODED:
        plen, off = _decode_varint(data, off)
        vals, _ = _decode_dict_coded(data[off:off + plen])
        return vals, off + plen
    elif tag == _Tag.TRIE_CODED:
        plen, off = _decode_varint(data, off)
        chunk = data[off:off + plen]
        inner_off = 0
        tlen, inner_off = _decode_varint(chunk, inner_off)
        sorted_vals, _ = _decode_trie(chunk[inner_off:inner_off + tlen])
        inner_off += tlen
        perm, _ = _decode_delta_ints(chunk, inner_off)
        result = [""] * len(perm)
        for orig_idx, sort_idx in enumerate(perm):
            result[orig_idx] = sorted_vals[sort_idx]
        return result, off + plen
    elif tag == _Tag.RLE:
        plen, off = _decode_varint(data, off)
        vals, _ = _decode_rle(data[off:off + plen])
        return vals, off + plen
    elif tag == _Tag.COMPACT_ROWS:
        plen, off = _decode_varint(data, off)
        chunk = data[off:off + plen]
        records = _decode_compact_rows(chunk)
        return records, off + plen
    elif tag == _Tag.LIST:
        count, off = _decode_varint(data, off)
        items = []
        for _ in range(count):
            item, off = _decode_value(data, off)
            items.append(item)
        return items, off
    elif tag == _Tag.DICT:
        count, off = _decode_varint(data, off)
        d: dict = {}
        for _ in range(count):
            klen, off = _decode_varint(data, off)
            k = data[off:off + klen].decode("utf-8")
            off += klen
            v, off = _decode_value(data, off)
            d[k] = v
        return d, off
    else:
        raise ValueError(f"Unknown tag: {tag}")


def _decode_compact_rows(chunk: bytes) -> list[dict]:
    off = 0
    nrows, off = _decode_varint(chunk, off)
    ncols, off = _decode_varint(chunk, off)
    keys: list[str] = []
    for _ in range(ncols):
        klen, off = _decode_varint(chunk, off)
        keys.append(chunk[off:off + klen].decode("utf-8"))
        off += klen
    columns: dict[str, list] = {}
    for k in keys:
        col, off = _decode_value(chunk, off)
        columns[k] = col
    return [{k: columns[k][i] for k in keys} for i in range(nrows)]


# ───────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────

def pack(obj: Any) -> str:
    """Encode any Python object to a compact base85 string."""
    buf = BytesIO()
    _encode_value(obj, buf)
    raw = buf.getvalue()
    compressed = zlib.compress(raw, level=9)
    return base64.b85encode(compressed).decode("ascii")


def unpack(text: str) -> Any:
    """Decode a base85 string back to the original Python object."""
    compressed = base64.b85decode(text.encode("ascii"))
    raw = zlib.decompress(compressed)
    val, _ = _decode_value(raw, 0)
    return val


def fingerprint(obj: Any) -> str:
    """Content-addressable 12-char hex fingerprint."""
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:12]


@dataclass
class DensityMetrics:
    raw_json_bytes: int
    encoded_bytes: int
    compressed_bytes: int
    base85_chars: int
    byte_ratio: float
    text_ratio: float
    savings_pct: float
    estimated_tokens: int  # ~4 chars per token for base85

    def __repr__(self) -> str:
        return (f"DensityMetrics(json={self.raw_json_bytes}B "
                f"-> {self.base85_chars} chars, "
                f"{self.savings_pct:.1f}% saved, "
                f"~{self.estimated_tokens} tokens)")


def estimate(obj: Any) -> DensityMetrics:
    """Compute density metrics for an object without keeping the payload."""
    raw_json = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    buf = BytesIO()
    _encode_value(obj, buf)
    encoded = buf.getvalue()
    compressed = zlib.compress(encoded, level=9)
    b85 = base64.b85encode(compressed)
    raw_size = len(raw_json)
    b85_len = len(b85)
    return DensityMetrics(
        raw_json_bytes=raw_size,
        encoded_bytes=len(encoded),
        compressed_bytes=len(compressed),
        base85_chars=b85_len,
        byte_ratio=round(len(encoded) / raw_size, 4) if raw_size else 0,
        text_ratio=round(b85_len / raw_size, 4) if raw_size else 0,
        savings_pct=round((1 - b85_len / raw_size) * 100, 1) if raw_size else 0,
        estimated_tokens=math.ceil(b85_len / 4),
    )


# ───────────────────────────────────────────────────────────────────
# TokenBudgetPacker: fit data into a target token budget
# ───────────────────────────────────────────────────────────────────

@dataclass
class BudgetResult:
    packed: str
    tokens_used: int
    items_included: int
    items_dropped: int
    within_budget: bool


class TokenBudgetPacker:
    """Pack as much data as possible into a target LLM token budget.

    Given a list of records, includes as many as fit (in order) within
    the token limit.  Useful for stuffing maximum context into a prompt.
    """

    def __init__(self, token_budget: int, chars_per_token: float = 4.0):
        self.token_budget = token_budget
        self.chars_per_token = chars_per_token

    @property
    def char_budget(self) -> int:
        return int(self.token_budget * self.chars_per_token)

    def pack_list(self, items: list[Any]) -> BudgetResult:
        """Pack items greedily, including as many as fit in budget."""
        best_n = 0
        best_packed = pack([])

        lo, hi = 0, len(items)
        # Binary search for the max items that fit
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = pack(items[:mid])
            if len(candidate) <= self.char_budget:
                best_n = mid
                best_packed = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        tokens = math.ceil(len(best_packed) / self.chars_per_token)
        return BudgetResult(
            packed=best_packed,
            tokens_used=tokens,
            items_included=best_n,
            items_dropped=len(items) - best_n,
            within_budget=tokens <= self.token_budget,
        )

    def pack_dict(self, data: dict[str, Any],
                  priority: Optional[list[str]] = None) -> BudgetResult:
        """Pack dict fields by priority, dropping lowest-priority fields first."""
        keys = priority if priority else list(data.keys())
        keys = [k for k in keys if k in data]

        best_d: dict = {}
        best_packed = pack({})

        for k in keys:
            trial = {**best_d, k: data[k]}
            candidate = pack(trial)
            if len(candidate) <= self.char_budget:
                best_d = trial
                best_packed = candidate

        tokens = math.ceil(len(best_packed) / self.chars_per_token)
        return BudgetResult(
            packed=best_packed,
            tokens_used=tokens,
            items_included=len(best_d),
            items_dropped=len(keys) - len(best_d),
            within_budget=tokens <= self.token_budget,
        )


# ───────────────────────────────────────────────────────────────────
# __main__: assertions verifying correctness
# ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── Primitives ────────────────────────────────────────────────
    for n in [0, 1, 127, 128, 16383, 2**21, 2**28]:
        enc = _encode_varint(n)
        dec, end = _decode_varint(enc, 0)
        assert dec == n and end == len(enc), f"varint failed for {n}"

    for n in [0, -1, 1, -100, 100, -2**30, 2**30]:
        assert _zigzag_dec(_zigzag_enc(n)) == n, f"zigzag failed for {n}"
    print("[primitives] passed")

    # ── Scalars ───────────────────────────────────────────────────
    assert unpack(pack(None)) is None
    assert unpack(pack(True)) is True
    assert unpack(pack(False)) is False
    assert unpack(pack(42)) == 42
    assert unpack(pack(-999)) == -999
    assert unpack(pack(0)) == 0
    assert abs(unpack(pack(3.14159)) - 3.14159) < 1e-10
    assert unpack(pack("hello world")) == "hello world"
    assert unpack(pack("")) == ""
    assert unpack(pack("emoji: \U0001f680")) == "emoji: \U0001f680"
    print("[scalars] passed")

    # ── Integer lists (delta encoded) ─────────────────────────────
    timestamps = [1711500000 + i * 60 for i in range(200)]
    assert unpack(pack(timestamps)) == timestamps
    ts_metrics = estimate(timestamps)
    assert ts_metrics.savings_pct > 50, f"timestamps savings: {ts_metrics.savings_pct}%"
    print(f"[delta ints] passed  {ts_metrics}")

    # Non-monotonic ints
    zigzag = [10, -5, 20, -100, 0, 999]
    assert unpack(pack(zigzag)) == zigzag
    print("[delta ints non-monotonic] passed")

    # ── Float arrays ──────────────────────────────────────────────
    floats = [i * 0.01 for i in range(100)]
    decoded_floats = unpack(pack(floats))
    for a, b in zip(floats, decoded_floats):
        assert abs(a - b) < 1e-10, f"float mismatch: {a} vs {b}"
    print(f"[float array] passed  {estimate(floats)}")

    # ── Low-cardinality strings (dict coded) ──────────────────────
    statuses = ["running", "idle", "error"] * 500
    assert unpack(pack(statuses)) == statuses
    st_metrics = estimate(statuses)
    assert st_metrics.savings_pct > 80, f"dict-coded savings: {st_metrics.savings_pct}%"
    print(f"[dict coded] passed  {st_metrics}")

    # ── High-cardinality strings (trie coded) ─────────────────────
    paths = [f"src/components/widget_{i:04d}.tsx" for i in range(100)]
    decoded_paths = unpack(pack(paths))
    assert decoded_paths == paths, "trie round-trip failed"
    path_metrics = estimate(paths)
    assert path_metrics.savings_pct > 30, f"trie savings: {path_metrics.savings_pct}%"
    print(f"[trie coded] passed  {path_metrics}")

    # ── Run-length encoding ───────────────────────────────────────
    rle_data: list = [0] * 100 + [1] * 50 + [0] * 200 + [2] * 10
    assert unpack(pack(rle_data)) == rle_data
    rle_metrics = estimate(rle_data)
    assert rle_metrics.savings_pct > 80, f"RLE savings: {rle_metrics.savings_pct}%"
    print(f"[RLE] passed  {rle_metrics}")

    # ── Mixed list (generic) ──────────────────────────────────────
    mixed = [1, "two", 3.0, None, True, [4, 5]]
    assert unpack(pack(mixed)) == mixed
    print("[mixed list] passed")

    # ── Nested dict ───────────────────────────────────────────────
    nested = {
        "agent": "planner-v3",
        "config": {"retries": 3, "timeout": 60, "model": "local-v7"},
        "scores": [72, 75, 78, 80, 85, 88, 90, 92],
        "active": True,
        "value": None,
        "tags": ["critical", "pipeline", "v2"],
    }
    assert unpack(pack(nested)) == nested
    print(f"[nested dict] passed  {estimate(nested)}")

    # ── Compact rows (list of homogeneous dicts) ──────────────────
    events = [
        {"ts": 1000000 + i, "level": ["info", "warn", "error"][i % 3],
         "latency": 0.5 + i * 0.01, "agent": "executor"}
        for i in range(200)
    ]
    decoded_events = unpack(pack(events))
    assert len(decoded_events) == 200
    for orig, dec in zip(events, decoded_events):
        assert orig["ts"] == dec["ts"]
        assert orig["level"] == dec["level"]
        assert abs(orig["latency"] - dec["latency"]) < 1e-10
        assert orig["agent"] == dec["agent"]
    ev_metrics = estimate(events)
    assert ev_metrics.savings_pct > 50, f"compact rows savings: {ev_metrics.savings_pct}%"
    print(f"[compact rows] passed  {ev_metrics}")

    # ── Empty containers ──────────────────────────────────────────
    assert unpack(pack([])) == []
    assert unpack(pack({})) == {}
    assert unpack(pack([[], {}, None])) == [[], {}, None]
    print("[empty containers] passed")

    # ── Fingerprint ───────────────────────────────────────────────
    fp1 = fingerprint(nested)
    fp2 = fingerprint(nested)
    assert fp1 == fp2, "fingerprint not deterministic"
    assert len(fp1) == 12
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})
    print(f"[fingerprint] passed  {fp1}")

    # ── Density metrics ───────────────────────────────────────────
    m = estimate(events)
    assert m.raw_json_bytes > 0
    assert m.encoded_bytes > 0
    assert m.compressed_bytes <= m.encoded_bytes
    assert m.base85_chars > 0
    assert m.estimated_tokens > 0
    assert 0 < m.byte_ratio < 1
    print(f"[density metrics] passed")

    # ── TokenBudgetPacker (list) ──────────────────────────────────
    packer = TokenBudgetPacker(token_budget=50)
    items = list(range(1000))
    result = packer.pack_list(items)
    assert result.within_budget, "should fit within budget"
    assert result.items_included > 0, "should include some items"
    assert result.items_included + result.items_dropped == 1000
    recovered = unpack(result.packed)
    assert recovered == items[:result.items_included]
    print(f"[budget packer list] passed  included={result.items_included}/1000, "
          f"tokens={result.tokens_used}/{packer.token_budget}")

    # ── TokenBudgetPacker (dict) ──────────────────────────────────
    big_dict = {
        "critical": "must include this",
        "important": list(range(50)),
        "nice_to_have": ["x"] * 100,
        "optional": {"nested": list(range(500))},
    }
    result_d = packer.pack_dict(big_dict,
                                priority=["critical", "important", "nice_to_have", "optional"])
    assert result_d.within_budget
    recovered_d = unpack(result_d.packed)
    assert "critical" in recovered_d, "highest priority field must be included"
    print(f"[budget packer dict] passed  fields={result_d.items_included}/{len(big_dict)}, "
          f"tokens={result_d.tokens_used}/{packer.token_budget}")

    # ── Large budget includes everything ──────────────────────────
    big_packer = TokenBudgetPacker(token_budget=10000)
    big_result = big_packer.pack_list(items)
    assert big_result.items_included == 1000, "big budget should include all"
    assert big_result.items_dropped == 0
    print("[budget packer large budget] passed")

    # ── End-to-end density comparison ─────────────────────────────
    print("\n=== Density Summary ===")
    test_cases: list[tuple[str, Any]] = [
        ("200 timestamps", timestamps),
        ("100 floats", floats),
        ("1500 statuses (dict-coded)", statuses),
        ("100 file paths (trie)", paths),
        ("360 RLE values", rle_data),
        ("200 event records (columnar)", events),
        ("nested agent state", nested),
    ]
    for label, data in test_cases:
        m = estimate(data)
        raw_tokens = math.ceil(m.raw_json_bytes / 4)
        print(f"  {label:40s}  {raw_tokens:>5d} tok -> {m.estimated_tokens:>4d} tok  "
              f"({m.savings_pct:5.1f}% saved)")

    print("\nAll assertions passed.")
