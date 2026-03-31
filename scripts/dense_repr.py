"""
Information-dense representations: encode more info per token.

Techniques implemented:
1. SymbolTable   — map repeated strings to short aliases (§0, §1, ...)
2. DeltaEncoder  — store sequences as base + deltas
3. BitPackedFlags — pack boolean flags into single integers
4. TrieCompressor — deduplicate shared prefixes across keys
5. RunLengthEncoder — collapse repeated adjacent values
6. StructPacker  — schema-aware record packing (row→dense string)
7. HuffmanCoder  — variable-length encoding by frequency
8. DenseMatrix   — sparse-to-dense matrix serialization
9. ContextDiff   — represent updates as minimal diffs against prior state
10. MultiEncoder — compose encoders for maximum density
"""

from __future__ import annotations

import heapq
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence


# ─── 1. SymbolTable ─────────────────────────────────────────────────────────

class SymbolTable:
    """Replace repeated substrings with short aliases to reduce token count."""

    def __init__(self, prefix: str = "§"):
        self.prefix = prefix
        self._str_to_sym: dict[str, str] = {}
        self._sym_to_str: dict[str, str] = {}
        self._counter = 0

    def register(self, value: str) -> str:
        if value in self._str_to_sym:
            return self._str_to_sym[value]
        sym = f"{self.prefix}{self._counter}"
        self._counter += 1
        self._str_to_sym[value] = sym
        self._sym_to_str[sym] = value
        return sym

    def encode(self, text: str, min_occurrences: int = 2, min_len: int = 4) -> tuple[str, dict[str, str]]:
        words = re.findall(r'\b\w{' + str(min_len) + r',}\b', text)
        freq = Counter(words)
        candidates = sorted(
            [(w, c) for w, c in freq.items() if c >= min_occurrences],
            key=lambda x: x[1] * len(x[0]),
            reverse=True,
        )
        table: dict[str, str] = {}
        result = text
        for word, _ in candidates:
            sym = self.register(word)
            table[sym] = word
            result = result.replace(word, sym)
        return result, table

    def decode(self, text: str, table: dict[str, str]) -> str:
        result = text
        for sym, word in sorted(table.items(), key=lambda x: len(x[0]), reverse=True):
            result = result.replace(sym, word)
        return result

    @property
    def density_ratio(self) -> float:
        if not self._str_to_sym:
            return 1.0
        orig = sum(len(s) for s in self._str_to_sym)
        compressed = sum(len(s) for s in self._sym_to_str)
        return orig / compressed if compressed else 1.0


# ─── 2. DeltaEncoder ────────────────────────────────────────────────────────

class DeltaEncoder:
    """Store numeric sequences as base + deltas for compact representation."""

    @staticmethod
    def encode(values: list[int | float]) -> dict[str, Any]:
        if not values:
            return {"base": 0, "deltas": []}
        base = values[0]
        deltas = [round(values[i] - values[i - 1], 10) for i in range(1, len(values))]
        return {"base": base, "deltas": deltas}

    @staticmethod
    def decode(encoded: dict[str, Any]) -> list[int | float]:
        base = encoded["base"]
        deltas = encoded["deltas"]
        result = [base]
        for d in deltas:
            result.append(round(result[-1] + d, 10))
        return result

    @staticmethod
    def savings(values: list[int | float]) -> float:
        orig = sum(len(str(v)) for v in values)
        enc = DeltaEncoder.encode(values)
        compressed = len(str(enc["base"])) + sum(len(str(d)) for d in enc["deltas"])
        return 1 - compressed / orig if orig else 0.0


# ─── 3. BitPackedFlags ──────────────────────────────────────────────────────

class BitPackedFlags:
    """Pack N boolean flags into a single integer."""

    @staticmethod
    def pack(flags: list[bool]) -> int:
        result = 0
        for i, flag in enumerate(flags):
            if flag:
                result |= (1 << i)
        return result

    @staticmethod
    def unpack(packed: int, count: int) -> list[bool]:
        return [bool(packed & (1 << i)) for i in range(count)]

    @staticmethod
    def density(count: int) -> float:
        packed_chars = len(str(BitPackedFlags.pack([True] * count)))
        unpacked_chars = count * 5  # "True," or "False"
        return unpacked_chars / packed_chars if packed_chars else 1.0


# ─── 4. TrieCompressor ──────────────────────────────────────────────────────

class TrieCompressor:
    """Deduplicate shared prefixes in a set of strings using front-coding."""

    @staticmethod
    def encode(keys: list[str]) -> str:
        if not keys:
            return ""
        sorted_keys = sorted(keys)
        parts = [sorted_keys[0]]
        for i in range(1, len(sorted_keys)):
            prev, cur = sorted_keys[i - 1], sorted_keys[i]
            shared = 0
            while shared < len(prev) and shared < len(cur) and prev[shared] == cur[shared]:
                shared += 1
            parts.append(f"{shared}:{cur[shared:]}")
        return "\n".join(parts)

    @staticmethod
    def decode(encoded: str) -> list[str]:
        if not encoded:
            return []
        lines = encoded.split("\n")
        result = [lines[0]]
        for line in lines[1:]:
            colon = line.index(":")
            shared = int(line[:colon])
            suffix = line[colon + 1:]
            result.append(result[-1][:shared] + suffix)
        return result

    @staticmethod
    def savings(keys: list[str]) -> float:
        orig = sum(len(k) for k in keys)
        compressed = len(TrieCompressor.encode(keys))
        return 1 - compressed / orig if orig else 0.0


# ─── 5. RunLengthEncoder ────────────────────────────────────────────────────

class RunLengthEncoder:
    """Collapse repeated adjacent values into (value, count) pairs."""

    @staticmethod
    def encode(values: Sequence) -> list[tuple[Any, int]]:
        if not values:
            return []
        runs = []
        current = values[0]
        count = 1
        for v in values[1:]:
            if v == current:
                count += 1
            else:
                runs.append((current, count))
                current = v
                count = 1
        runs.append((current, count))
        return runs

    @staticmethod
    def decode(runs: list[tuple[Any, int]]) -> list:
        result = []
        for value, count in runs:
            result.extend([value] * count)
        return result

    @staticmethod
    def density(values: Sequence) -> float:
        if not values:
            return 1.0
        encoded = RunLengthEncoder.encode(values)
        return len(values) / len(encoded)


# ─── 6. StructPacker ────────────────────────────────────────────────────────

class StructPacker:
    """Schema-aware record packing: convert dicts to dense pipe-delimited rows."""

    def __init__(self, schema: list[str]):
        self.schema = schema

    def pack(self, record: dict[str, Any]) -> str:
        return "|".join(str(record.get(k, "")) for k in self.schema)

    def unpack(self, row: str) -> dict[str, Any]:
        parts = row.split("|")
        return {k: self._coerce(v) for k, v in zip(self.schema, parts)}

    def pack_many(self, records: list[dict[str, Any]]) -> str:
        header = "|".join(self.schema)
        rows = [self.pack(r) for r in records]
        return header + "\n" + "\n".join(rows)

    def unpack_many(self, packed: str) -> list[dict[str, Any]]:
        lines = packed.strip().split("\n")
        return [self.unpack(line) for line in lines[1:]]

    @staticmethod
    def _coerce(v: str) -> Any:
        if v == "":
            return None
        if v == "True":
            return True
        if v == "False":
            return False
        try:
            return int(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            return v

    def savings(self, records: list[dict[str, Any]]) -> float:
        orig = len(json.dumps(records, separators=(",", ":")))
        compressed = len(self.pack_many(records))
        return 1 - compressed / orig if orig else 0.0


# ─── 7. HuffmanCoder ────────────────────────────────────────────────────────

@dataclass(order=True)
class _HuffNode:
    freq: int
    char: Optional[str] = field(default=None, compare=False)
    left: Optional[_HuffNode] = field(default=None, compare=False)
    right: Optional[_HuffNode] = field(default=None, compare=False)


class HuffmanCoder:
    """Variable-length bit encoding weighted by character frequency."""

    def __init__(self):
        self._codes: dict[str, str] = {}
        self._root: Optional[_HuffNode] = None

    def build(self, text: str) -> dict[str, str]:
        freq = Counter(text)
        if len(freq) == 0:
            self._codes = {}
            return {}
        if len(freq) == 1:
            ch = next(iter(freq))
            self._codes = {ch: "0"}
            self._root = _HuffNode(freq[ch], left=_HuffNode(freq[ch], char=ch))
            return dict(self._codes)

        heap: list[_HuffNode] = [_HuffNode(f, ch) for ch, f in freq.items()]
        heapq.heapify(heap)
        while len(heap) > 1:
            left = heapq.heappop(heap)
            right = heapq.heappop(heap)
            merged = _HuffNode(left.freq + right.freq, left=left, right=right)
            heapq.heappush(heap, merged)
        self._root = heap[0]
        self._codes = {}
        self._build_codes(self._root, "")
        return dict(self._codes)

    def _build_codes(self, node: _HuffNode, prefix: str) -> None:
        if node.char is not None:
            self._codes[node.char] = prefix
            return
        if node.left:
            self._build_codes(node.left, prefix + "0")
        if node.right:
            self._build_codes(node.right, prefix + "1")

    def encode(self, text: str) -> str:
        if not self._codes:
            self.build(text)
        return "".join(self._codes[ch] for ch in text)

    def decode(self, bits: str) -> str:
        if not self._root:
            return ""
        if self._root.char is not None:
            return self._root.char * len(bits)
        result = []
        node = self._root
        for bit in bits:
            node = node.left if bit == "0" else node.right
            if node.char is not None:
                result.append(node.char)
                node = self._root
        return "".join(result)

    def avg_bits_per_char(self, text: str) -> float:
        if not self._codes:
            self.build(text)
        encoded = self.encode(text)
        return len(encoded) / len(text) if text else 0.0

    def density_vs_ascii(self, text: str) -> float:
        avg = self.avg_bits_per_char(text)
        return 8.0 / avg if avg else 1.0


# ─── 8. DenseMatrix ─────────────────────────────────────────────────────────

class DenseMatrix:
    """Sparse-to-dense matrix serialization for embedding/weight tables."""

    @staticmethod
    def from_sparse(sparse: dict[tuple[int, int], float], rows: int, cols: int) -> list[list[float]]:
        matrix = [[0.0] * cols for _ in range(rows)]
        for (r, c), v in sparse.items():
            matrix[r][c] = v
        return matrix

    @staticmethod
    def to_sparse(matrix: list[list[float]], threshold: float = 0.0) -> dict[tuple[int, int], float]:
        sparse = {}
        for r, row in enumerate(matrix):
            for c, v in enumerate(row):
                if abs(v) > threshold:
                    sparse[(r, c)] = v
        return sparse

    @staticmethod
    def pack(matrix: list[list[float]], precision: int = 4) -> str:
        rows = []
        for row in matrix:
            rows.append(",".join(f"{v:.{precision}f}" for v in row))
        return ";".join(rows)

    @staticmethod
    def unpack(packed: str) -> list[list[float]]:
        return [[float(v) for v in row.split(",")] for row in packed.split(";")]

    @staticmethod
    def density_ratio(sparse: dict, rows: int, cols: int) -> float:
        total = rows * cols
        nonzero = len(sparse)
        return nonzero / total if total else 0.0


# ─── 9. ContextDiff ─────────────────────────────────────────────────────────

class ContextDiff:
    """Represent updates as minimal diffs against a prior state dict."""

    @staticmethod
    def diff(old: dict, new: dict) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        all_keys = set(old) | set(new)
        for k in all_keys:
            if k not in old:
                changes[f"+{k}"] = new[k]
            elif k not in new:
                changes[f"-{k}"] = None
            elif old[k] != new[k]:
                if isinstance(old[k], dict) and isinstance(new[k], dict):
                    sub = ContextDiff.diff(old[k], new[k])
                    if sub:
                        changes[f"~{k}"] = sub
                else:
                    changes[f"~{k}"] = new[k]
        return changes

    @staticmethod
    def apply(old: dict, diff: dict[str, Any]) -> dict:
        result = dict(old)
        for key, value in diff.items():
            op, name = key[0], key[1:]
            if op == "+":
                result[name] = value
            elif op == "-":
                result.pop(name, None)
            elif op == "~":
                if isinstance(value, dict) and isinstance(result.get(name), dict):
                    result[name] = ContextDiff.apply(result[name], value)
                else:
                    result[name] = value
        return result

    @staticmethod
    def savings(old: dict, new: dict) -> float:
        full = len(json.dumps(new, separators=(",", ":")))
        d = ContextDiff.diff(old, new)
        diff_size = len(json.dumps(d, separators=(",", ":")))
        return 1 - diff_size / full if full else 0.0


# ─── 10. MultiEncoder ───────────────────────────────────────────────────────

class MultiEncoder:
    """Compose multiple encoders for maximum density on structured text."""

    def __init__(self):
        self.symbol_table = SymbolTable()
        self.rle = RunLengthEncoder()
        self.delta = DeltaEncoder()

    def encode_log_lines(self, lines: list[str]) -> dict[str, Any]:
        full_text = "\n".join(lines)
        compressed_text, table = self.symbol_table.encode(full_text)
        compressed_lines = compressed_text.split("\n")
        rle_lines = self.rle.encode(compressed_lines)
        return {
            "symbols": table,
            "runs": [(val, cnt) for val, cnt in rle_lines],
            "count": len(lines),
        }

    def decode_log_lines(self, encoded: dict[str, Any]) -> list[str]:
        runs = [(val, cnt) for val, cnt in encoded["runs"]]
        compressed_lines = self.rle.decode(runs)
        compressed_text = "\n".join(compressed_lines)
        return self.symbol_table.decode(compressed_text, encoded["symbols"]).split("\n")

    def encode_timeseries(self, timestamps: list[int], values: list[float]) -> dict[str, Any]:
        return {
            "ts": self.delta.encode(timestamps),
            "vals": self.delta.encode(values),
            "n": len(timestamps),
        }

    def decode_timeseries(self, encoded: dict[str, Any]) -> tuple[list, list]:
        ts = self.delta.decode(encoded["ts"])
        vals = self.delta.decode(encoded["vals"])
        return ts, vals

    @staticmethod
    def measure_density(original: str, compressed: str) -> dict[str, float]:
        orig_len = len(original)
        comp_len = len(compressed)
        return {
            "original_chars": orig_len,
            "compressed_chars": comp_len,
            "ratio": orig_len / comp_len if comp_len else float("inf"),
            "savings_pct": (1 - comp_len / orig_len) * 100 if orig_len else 0.0,
        }


# ─── __main__ ────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── 1. SymbolTable ──────────────────────────────────────────
    st = SymbolTable()
    text = "authentication service failed. authentication retry. authentication timeout."
    encoded_text, table = st.encode(text, min_occurrences=2, min_len=4)
    decoded_text = st.decode(encoded_text, table)
    assert decoded_text == text, f"SymbolTable round-trip failed: {decoded_text!r}"
    assert len(encoded_text) < len(text), "SymbolTable should compress"
    assert "§" in encoded_text, "SymbolTable should use aliases"

    # ── 2. DeltaEncoder ─────────────────────────────────────────
    timestamps = [1000, 1005, 1010, 1015, 1020, 1025]
    enc = DeltaEncoder.encode(timestamps)
    dec = DeltaEncoder.decode(enc)
    assert dec == timestamps, f"DeltaEncoder round-trip failed: {dec}"
    assert enc["base"] == 1000
    assert all(d == 5 for d in enc["deltas"])
    assert DeltaEncoder.savings(timestamps) > 0

    floats = [1.1, 1.2, 1.3, 1.4]
    enc_f = DeltaEncoder.encode(floats)
    dec_f = DeltaEncoder.decode(enc_f)
    assert len(dec_f) == len(floats)
    for a, b in zip(dec_f, floats):
        assert abs(a - b) < 1e-9, f"Float delta failed: {a} != {b}"

    # ── 3. BitPackedFlags ───────────────────────────────────────
    flags = [True, False, True, True, False, False, True, False, True, True]
    packed = BitPackedFlags.pack(flags)
    unpacked = BitPackedFlags.unpack(packed, len(flags))
    assert unpacked == flags, f"BitPacked round-trip failed: {unpacked}"
    assert isinstance(packed, int)
    assert BitPackedFlags.density(10) > 1.0

    all_false = [False] * 16
    assert BitPackedFlags.pack(all_false) == 0
    assert BitPackedFlags.unpack(0, 16) == all_false

    # ── 4. TrieCompressor ───────────────────────────────────────
    keys = ["api_auth_login", "api_auth_logout", "api_auth_refresh",
            "api_data_read", "api_data_write"]
    encoded_trie = TrieCompressor.encode(keys)
    decoded_keys = TrieCompressor.decode(encoded_trie)
    assert decoded_keys == sorted(keys), f"Trie round-trip failed: {decoded_keys}"
    assert len(encoded_trie) < sum(len(k) for k in keys), "Trie should compress"

    # ── 5. RunLengthEncoder ─────────────────────────────────────
    values = [0, 0, 0, 1, 1, 2, 2, 2, 2, 3]
    runs = RunLengthEncoder.encode(values)
    assert runs == [(0, 3), (1, 2), (2, 4), (3, 1)]
    assert RunLengthEncoder.decode(runs) == values
    assert RunLengthEncoder.density(values) > 1.0
    assert RunLengthEncoder.encode([]) == []
    assert RunLengthEncoder.decode([]) == []

    single = [42]
    assert RunLengthEncoder.encode(single) == [(42, 1)]
    assert RunLengthEncoder.decode([(42, 1)]) == single

    # ── 6. StructPacker ─────────────────────────────────────────
    schema = ["name", "status", "score", "active"]
    records = [
        {"name": "alice", "status": "ok", "score": 95, "active": True},
        {"name": "bob", "status": "err", "score": 42, "active": False},
        {"name": "carol", "status": "ok", "score": 88, "active": True},
    ]
    sp = StructPacker(schema)
    packed_row = sp.pack(records[0])
    assert packed_row == "alice|ok|95|True"
    unpacked_row = sp.unpack(packed_row)
    assert unpacked_row == records[0], f"StructPacker row failed: {unpacked_row}"

    packed_all = sp.pack_many(records)
    unpacked_all = sp.unpack_many(packed_all)
    assert unpacked_all == records, f"StructPacker many failed: {unpacked_all}"
    assert sp.savings(records) > 0, "StructPacker should save space vs JSON"

    # ── 7. HuffmanCoder ─────────────────────────────────────────
    hc = HuffmanCoder()
    sample = "aaaaaabbbbcccdde"
    codes = hc.build(sample)
    assert len(codes) == 5  # a, b, c, d, e
    bits = hc.encode(sample)
    decoded_huff = hc.decode(bits)
    assert decoded_huff == sample, f"Huffman round-trip failed: {decoded_huff!r}"
    assert hc.avg_bits_per_char(sample) < 8.0
    assert hc.density_vs_ascii(sample) > 1.0

    # single-char string
    hc2 = HuffmanCoder()
    hc2.build("aaaa")
    assert hc2.encode("aaaa") == "0000"
    assert hc2.decode("0000") == "aaaa"

    # empty
    hc3 = HuffmanCoder()
    hc3.build("")
    assert hc3.encode("") == ""

    # ── 8. DenseMatrix ──────────────────────────────────────────
    sparse = {(0, 0): 1.0, (1, 2): 3.5, (2, 1): -2.0}
    matrix = DenseMatrix.from_sparse(sparse, 3, 3)
    assert matrix[0][0] == 1.0
    assert matrix[1][2] == 3.5
    assert matrix[2][1] == -2.0
    assert matrix[0][1] == 0.0

    back_sparse = DenseMatrix.to_sparse(matrix)
    assert back_sparse == sparse

    packed_m = DenseMatrix.pack(matrix, precision=2)
    unpacked_m = DenseMatrix.unpack(packed_m)
    assert len(unpacked_m) == 3
    assert abs(unpacked_m[1][2] - 3.5) < 0.01

    assert 0 < DenseMatrix.density_ratio(sparse, 3, 3) < 1.0

    # ── 9. ContextDiff ──────────────────────────────────────────
    old_state = {"status": "running", "count": 5, "config": {"retry": 3, "timeout": 30}}
    new_state = {"status": "done", "count": 5, "config": {"retry": 3, "timeout": 60}, "result": "ok"}
    d = ContextDiff.diff(old_state, new_state)
    applied = ContextDiff.apply(old_state, d)
    assert applied == new_state, f"ContextDiff apply failed: {applied}"
    assert "~status" in d
    assert "+result" in d
    assert "count" not in str(d), "Unchanged fields should not appear in diff"
    assert ContextDiff.savings(old_state, new_state) > 0

    # nested diff
    old_nested = {"a": {"b": {"c": 1, "d": 2}}}
    new_nested = {"a": {"b": {"c": 1, "d": 3, "e": 4}}}
    nd = ContextDiff.diff(old_nested, new_nested)
    assert ContextDiff.apply(old_nested, nd) == new_nested

    # deletion
    old_del = {"x": 1, "y": 2}
    new_del = {"x": 1}
    dd = ContextDiff.diff(old_del, new_del)
    assert "-y" in dd
    assert ContextDiff.apply(old_del, dd) == new_del

    # ── 10. MultiEncoder ────────────────────────────────────────
    me = MultiEncoder()

    # log lines
    log_lines = [
        "INFO authentication service started",
        "INFO authentication service started",
        "WARN authentication retry attempt 1",
        "WARN authentication retry attempt 2",
        "ERROR authentication service timeout",
    ]
    enc_logs = me.encode_log_lines(log_lines)
    dec_logs = me.decode_log_lines(enc_logs)
    assert dec_logs == log_lines, f"MultiEncoder log round-trip failed: {dec_logs}"

    # timeseries
    ts_stamps = [1000, 1010, 1020, 1030, 1040]
    ts_vals = [10.0, 10.5, 11.0, 10.8, 11.2]
    enc_ts = me.encode_timeseries(ts_stamps, ts_vals)
    dec_ts, dec_vals = me.decode_timeseries(enc_ts)
    assert dec_ts == ts_stamps
    for a, b in zip(dec_vals, ts_vals):
        assert abs(a - b) < 1e-9

    # density measurement — use larger input where compression wins
    big_lines = log_lines * 20  # 100 lines with heavy repetition
    me2 = MultiEncoder()
    enc_big = me2.encode_log_lines(big_lines)
    dec_big = me2.decode_log_lines(enc_big)
    assert dec_big == big_lines, "MultiEncoder big log round-trip failed"
    orig_json = json.dumps({"lines": big_lines})
    comp_json = json.dumps(enc_big, separators=(",", ":"))
    metrics = MultiEncoder.measure_density(orig_json, comp_json)
    assert metrics["ratio"] >= 1.0, f"MultiEncoder should compress large input: {metrics}"
    assert metrics["savings_pct"] > 0

    # ── Cross-encoder composition test ──────────────────────────
    # Combine StructPacker + ContextDiff
    records_v1 = [
        {"name": "svc-a", "status": "up", "latency": 12},
        {"name": "svc-b", "status": "up", "latency": 45},
    ]
    records_v2 = [
        {"name": "svc-a", "status": "up", "latency": 13},
        {"name": "svc-b", "status": "down", "latency": 999},
    ]
    state_v1 = {r["name"]: r for r in records_v1}
    state_v2 = {r["name"]: r for r in records_v2}
    cross_diff = ContextDiff.diff(state_v1, state_v2)
    assert ContextDiff.apply(state_v1, cross_diff) == state_v2
    full_v2_size = len(json.dumps(state_v2, separators=(",", ":")))
    diff_size = len(json.dumps(cross_diff, separators=(",", ":")))
    assert diff_size < full_v2_size, "Diff should be smaller than full state"

    # ── Edge cases ──────────────────────────────────────────────
    assert SymbolTable().encode("hi", min_occurrences=2, min_len=4) == ("hi", {})
    assert DeltaEncoder.encode([]) == {"base": 0, "deltas": []}
    assert DeltaEncoder.decode({"base": 0, "deltas": []}) == [0]
    assert BitPackedFlags.pack([]) == 0
    assert BitPackedFlags.unpack(0, 0) == []
    assert RunLengthEncoder.density([]) == 1.0

    print("All 10 encoders verified. All assertions passed.")
