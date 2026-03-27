"""Information-dense representations: encode more info per token.

Strategies implemented:
1. BitfieldPacker  — pack multiple typed fields into compact integers
2. DeltaEncoder    — store sequences as base + deltas
3. DictCoder       — map repeated values to short variable-length codes
4. RunLengthCoder  — collapse consecutive identical items
5. StructPacker    — schema-aware binary serialization for state dicts
6. DenseStateCodec — combines all strategies for agent state payloads
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import zlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# 1. Bitfield Packer
# ---------------------------------------------------------------------------

@dataclass
class FieldSpec:
    name: str
    bits: int
    signed: bool = False

    @property
    def max_unsigned(self) -> int:
        return (1 << self.bits) - 1

    @property
    def range(self) -> Tuple[int, int]:
        if self.signed:
            half = 1 << (self.bits - 1)
            return (-half, half - 1)
        return (0, self.max_unsigned)


class BitfieldPacker:
    """Pack multiple integer fields into a single compact int / bytes."""

    def __init__(self, specs: List[FieldSpec]):
        self.specs = specs
        self.total_bits = sum(s.bits for s in specs)

    def pack(self, values: Dict[str, int]) -> int:
        packed = 0
        offset = 0
        for spec in self.specs:
            v = values[spec.name]
            lo, hi = spec.range
            if not (lo <= v <= hi):
                raise ValueError(f"{spec.name}={v} out of range [{lo},{hi}]")
            if spec.signed:
                v = v & ((1 << spec.bits) - 1)
            packed |= (v & ((1 << spec.bits) - 1)) << offset
            offset += spec.bits
        return packed

    def unpack(self, packed: int) -> Dict[str, int]:
        result = {}
        offset = 0
        for spec in self.specs:
            mask = (1 << spec.bits) - 1
            v = (packed >> offset) & mask
            if spec.signed and v >= (1 << (spec.bits - 1)):
                v -= (1 << spec.bits)
            result[spec.name] = v
            offset += spec.bits
        return result

    def pack_bytes(self, values: Dict[str, int]) -> bytes:
        n = self.pack(values)
        byte_len = (self.total_bits + 7) // 8
        return n.to_bytes(byte_len, "little")

    def unpack_bytes(self, data: bytes) -> Dict[str, int]:
        n = int.from_bytes(data, "little")
        return self.unpack(n)

    @property
    def density(self) -> float:
        """Bits used vs naive 32-bit-per-field."""
        return self.total_bits / (len(self.specs) * 32)


# ---------------------------------------------------------------------------
# 2. Delta Encoder
# ---------------------------------------------------------------------------

class DeltaEncoder:
    """Encode numeric sequences as base + deltas for smaller magnitude values."""

    @staticmethod
    def encode(values: Sequence[Union[int, float]]) -> Dict[str, Any]:
        if not values:
            return {"count": 0, "base": 0, "deltas": [], "is_float": False}
        is_float = any(isinstance(v, float) for v in values)
        base = values[0]
        deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
        return {"count": len(values), "base": base, "deltas": deltas, "is_float": is_float}

    @staticmethod
    def decode(encoded: Dict[str, Any]) -> List[Union[int, float]]:
        if encoded.get("count", 0) == 0:
            return []
        base = encoded["base"]
        values = [base]
        for d in encoded["deltas"]:
            values.append(values[-1] + d)
        if not encoded.get("is_float", False):
            values = [int(v) for v in values]
        return values

    @staticmethod
    def savings_ratio(values: Sequence[Union[int, float]]) -> float:
        """Estimate size reduction: sum(|deltas|) / sum(|values|)."""
        if not values or all(v == 0 for v in values):
            return 1.0
        enc = DeltaEncoder.encode(values)
        original_cost = sum(abs(v) for v in values) or 1
        delta_cost = abs(enc["base"]) + sum(abs(d) for d in enc["deltas"])
        return delta_cost / original_cost


# ---------------------------------------------------------------------------
# 3. Dictionary Coder (variable-length codes)
# ---------------------------------------------------------------------------

class DictCoder:
    """Map repeated string values to short integer codes (frequency-ordered)."""

    def __init__(self):
        self.codebook: Dict[str, int] = {}
        self.reverse: Dict[int, str] = {}

    def fit(self, values: Sequence[str]) -> "DictCoder":
        freq = Counter(values)
        for idx, (val, _) in enumerate(freq.most_common()):
            self.codebook[val] = idx
            self.reverse[idx] = val
        return self

    def encode(self, values: Sequence[str]) -> List[int]:
        return [self.codebook[v] for v in values]

    def decode(self, codes: Sequence[int]) -> List[str]:
        return [self.reverse[c] for c in codes]

    def encode_single(self, value: str) -> int:
        return self.codebook[value]

    def decode_single(self, code: int) -> str:
        return self.reverse[code]

    def serialize(self) -> Dict[str, Any]:
        return {"codebook": self.codebook}

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> "DictCoder":
        coder = cls()
        coder.codebook = data["codebook"]
        coder.reverse = {v: k for k, v in coder.codebook.items()}
        return coder

    @property
    def bits_per_code(self) -> float:
        n = len(self.codebook)
        return math.log2(n) if n > 1 else 0

    def compression_ratio(self, values: Sequence[str]) -> float:
        if not values:
            return 1.0
        orig_bytes = sum(len(v.encode()) for v in values)
        code_bytes = len(values) * max(1, math.ceil(self.bits_per_code / 8))
        book_bytes = sum(len(k.encode()) + 4 for k in self.codebook)
        return (code_bytes + book_bytes) / orig_bytes if orig_bytes else 1.0


# ---------------------------------------------------------------------------
# 4. Run-Length Encoder
# ---------------------------------------------------------------------------

class RunLengthCoder:
    """Collapse consecutive identical items into (value, count) pairs."""

    @staticmethod
    def encode(values: Sequence[Any]) -> List[Tuple[Any, int]]:
        if not values:
            return []
        runs = []
        current, count = values[0], 1
        for v in values[1:]:
            if v == current:
                count += 1
            else:
                runs.append((current, count))
                current, count = v, 1
        runs.append((current, count))
        return runs

    @staticmethod
    def decode(runs: List[Tuple[Any, int]]) -> List[Any]:
        result = []
        for val, cnt in runs:
            result.extend([val] * cnt)
        return result

    @staticmethod
    def compression_ratio(values: Sequence[Any]) -> float:
        if not values:
            return 1.0
        runs = RunLengthCoder.encode(values)
        return len(runs) / len(values)


# ---------------------------------------------------------------------------
# 5. StructPacker — schema-aware binary serialization
# ---------------------------------------------------------------------------

# Type tags for the wire format
_TYPE_NONE = 0
_TYPE_BOOL = 1
_TYPE_INT = 2
_TYPE_FLOAT = 3
_TYPE_STR = 4
_TYPE_LIST = 5
_TYPE_DICT = 6


class StructPacker:
    """Serialize arbitrary Python dicts to compact binary with type tags."""

    @staticmethod
    def pack(obj: Any) -> bytes:
        buf = bytearray()
        StructPacker._pack_value(obj, buf)
        return bytes(buf)

    @staticmethod
    def unpack(data: bytes) -> Any:
        val, _ = StructPacker._unpack_value(data, 0)
        return val

    @staticmethod
    def pack_b64(obj: Any) -> str:
        raw = StructPacker.pack(obj)
        compressed = zlib.compress(raw, level=9)
        return base64.b85encode(compressed).decode("ascii")

    @staticmethod
    def unpack_b64(s: str) -> Any:
        compressed = base64.b85decode(s.encode("ascii"))
        raw = zlib.decompress(compressed)
        return StructPacker.unpack(raw)

    # -- internal helpers --

    @staticmethod
    def _pack_value(obj: Any, buf: bytearray):
        if obj is None:
            buf.append(_TYPE_NONE)
        elif isinstance(obj, bool):
            buf.append(_TYPE_BOOL)
            buf.append(1 if obj else 0)
        elif isinstance(obj, int):
            buf.append(_TYPE_INT)
            b = obj.to_bytes((obj.bit_length() + 8) // 8, "little", signed=True) if obj != 0 else b"\x00"
            buf.extend(struct.pack("<H", len(b)))
            buf.extend(b)
        elif isinstance(obj, float):
            buf.append(_TYPE_FLOAT)
            buf.extend(struct.pack("<d", obj))
        elif isinstance(obj, str):
            buf.append(_TYPE_STR)
            encoded = obj.encode("utf-8")
            buf.extend(struct.pack("<I", len(encoded)))
            buf.extend(encoded)
        elif isinstance(obj, (list, tuple)):
            buf.append(_TYPE_LIST)
            buf.extend(struct.pack("<I", len(obj)))
            for item in obj:
                StructPacker._pack_value(item, buf)
        elif isinstance(obj, dict):
            buf.append(_TYPE_DICT)
            buf.extend(struct.pack("<I", len(obj)))
            for k, v in obj.items():
                StructPacker._pack_value(str(k), buf)
                StructPacker._pack_value(v, buf)
        else:
            StructPacker._pack_value(str(obj), buf)

    @staticmethod
    def _unpack_value(data: bytes, offset: int) -> Tuple[Any, int]:
        tag = data[offset]; offset += 1
        if tag == _TYPE_NONE:
            return None, offset
        elif tag == _TYPE_BOOL:
            return bool(data[offset]), offset + 1
        elif tag == _TYPE_INT:
            length = struct.unpack_from("<H", data, offset)[0]; offset += 2
            val = int.from_bytes(data[offset:offset + length], "little", signed=True)
            return val, offset + length
        elif tag == _TYPE_FLOAT:
            val = struct.unpack_from("<d", data, offset)[0]
            return val, offset + 8
        elif tag == _TYPE_STR:
            length = struct.unpack_from("<I", data, offset)[0]; offset += 4
            val = data[offset:offset + length].decode("utf-8")
            return val, offset + length
        elif tag == _TYPE_LIST:
            count = struct.unpack_from("<I", data, offset)[0]; offset += 4
            items = []
            for _ in range(count):
                item, offset = StructPacker._unpack_value(data, offset)
                items.append(item)
            return items, offset
        elif tag == _TYPE_DICT:
            count = struct.unpack_from("<I", data, offset)[0]; offset += 4
            d = {}
            for _ in range(count):
                k, offset = StructPacker._unpack_value(data, offset)
                v, offset = StructPacker._unpack_value(data, offset)
                d[k] = v
            return d, offset
        raise ValueError(f"Unknown type tag: {tag}")


# ---------------------------------------------------------------------------
# 6. DenseStateCodec — combines strategies for agent state payloads
# ---------------------------------------------------------------------------

@dataclass
class EncodingStats:
    original_bytes: int = 0
    encoded_bytes: int = 0
    strategy_used: List[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.encoded_bytes / self.original_bytes if self.original_bytes else 1.0

    @property
    def savings_pct(self) -> float:
        return (1 - self.ratio) * 100


class DenseStateCodec:
    """Encode agent state dicts with maximum information density.

    Pipeline:
      1. Separate numeric arrays → delta encode
      2. Separate repeated strings → dict code
      3. Pack everything with StructPacker → zlib + base85
    """

    @staticmethod
    def encode(state: Dict[str, Any]) -> Tuple[str, EncodingStats]:
        original = json.dumps(state, separators=(",", ":")).encode()
        stats = EncodingStats(original_bytes=len(original))

        processed: Dict[str, Any] = {}
        meta: Dict[str, Any] = {"_delta_keys": [], "_dict_keys": []}

        all_strings: List[str] = []
        for k, v in state.items():
            if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
                processed[k] = DeltaEncoder.encode(v)
                meta["_delta_keys"].append(k)
                stats.strategy_used.append(f"delta:{k}")
            elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                all_strings.extend(v)
                processed[k] = v  # will be dict-coded below
                meta["_dict_keys"].append(k)
                stats.strategy_used.append(f"dictcode:{k}")
            else:
                processed[k] = v

        if all_strings:
            coder = DictCoder().fit(all_strings)
            for k in meta["_dict_keys"]:
                processed[k] = coder.encode(processed[k])
            meta["_codebook"] = coder.serialize()

        processed["__meta__"] = meta
        encoded = StructPacker.pack_b64(processed)
        stats.encoded_bytes = len(encoded.encode())
        stats.strategy_used.append("structpack+zlib+b85")
        return encoded, stats

    @staticmethod
    def decode(encoded: str) -> Dict[str, Any]:
        processed = StructPacker.unpack_b64(encoded)
        meta = processed.pop("__meta__", {})

        coder = None
        if "_codebook" in meta:
            coder = DictCoder.deserialize(meta["_codebook"])

        for k in meta.get("_delta_keys", []):
            processed[k] = DeltaEncoder.decode(processed[k])

        for k in meta.get("_dict_keys", []):
            if coder:
                processed[k] = coder.decode([int(c) for c in processed[k]])

        return processed

    @staticmethod
    def fingerprint(state: Dict[str, Any]) -> str:
        """Content-addressable 8-char fingerprint for dedup."""
        raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()[:8]


# ---------------------------------------------------------------------------
# __main__: assertions verifying correctness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # ── 1. BitfieldPacker ──────────────────────────────────────────────
    specs = [
        FieldSpec("status", 3),        # 0-7
        FieldSpec("priority", 4),      # 0-15
        FieldSpec("retries", 3),       # 0-7
        FieldSpec("confidence", 7),    # 0-127
        FieldSpec("temperature", 8, signed=True),  # -128..127
    ]
    packer = BitfieldPacker(specs)
    vals = {"status": 5, "priority": 12, "retries": 3, "confidence": 94, "temperature": -10}
    packed_int = packer.pack(vals)
    assert packer.unpack(packed_int) == vals, "Bitfield int round-trip failed"

    packed_bytes = packer.pack_bytes(vals)
    assert packer.unpack_bytes(packed_bytes) == vals, "Bitfield bytes round-trip failed"
    assert len(packed_bytes) == 4, f"Expected 4 bytes, got {len(packed_bytes)}"  # 25 bits → 4 bytes
    assert packer.density < 1.0, "Density should be < 1 (more compact than naive)"
    print(f"[BitfieldPacker] 5 fields → {packer.total_bits} bits ({len(packed_bytes)} bytes), "
          f"density={packer.density:.2%} of naive 32-bit-per-field")

    # ── 2. DeltaEncoder ────────────────────────────────────────────────
    timestamps = [1711500000, 1711500060, 1711500120, 1711500180, 1711500240]
    enc = DeltaEncoder.encode(timestamps)
    assert DeltaEncoder.decode(enc) == timestamps, "Delta round-trip failed"
    assert all(d == 60 for d in enc["deltas"]), "Deltas should all be 60"
    ratio = DeltaEncoder.savings_ratio(timestamps)
    assert ratio < 0.25, f"Expected large savings, got ratio={ratio:.4f}"
    print(f"[DeltaEncoder] {timestamps} → base={enc['base']}, deltas={enc['deltas']}, "
          f"savings_ratio={ratio:.4f}")

    floats = [1.0, 1.1, 1.3, 1.6, 2.0]
    enc_f = DeltaEncoder.encode(floats)
    dec_f = DeltaEncoder.decode(enc_f)
    for a, b in zip(floats, dec_f):
        assert abs(a - b) < 1e-9, f"Float delta mismatch: {a} vs {b}"
    print(f"[DeltaEncoder] float round-trip OK, deltas={enc_f['deltas']}")

    # ── 3. DictCoder ───────────────────────────────────────────────────
    statuses = ["running", "idle", "running", "error", "idle", "running",
                "idle", "running", "running", "idle"]
    coder = DictCoder().fit(statuses)
    codes = coder.encode(statuses)
    assert coder.decode(codes) == statuses, "DictCoder round-trip failed"
    assert codes[0] == 0, "Most frequent ('running') should get code 0"
    cr = coder.compression_ratio(statuses)
    assert cr < 1.0, f"Expected compression, got ratio={cr:.4f}"

    ser = coder.serialize()
    coder2 = DictCoder.deserialize(ser)
    assert coder2.decode(codes) == statuses, "DictCoder serialize round-trip failed"
    print(f"[DictCoder] {len(set(statuses))} unique vals → {coder.bits_per_code:.1f} bits/code, "
          f"compression={cr:.4f}")

    # ── 4. RunLengthCoder ──────────────────────────────────────────────
    seq = [0, 0, 0, 1, 1, 2, 2, 2, 2, 0, 0]
    runs = RunLengthCoder.encode(seq)
    assert RunLengthCoder.decode(runs) == seq, "RLE round-trip failed"
    assert runs == [(0, 3), (1, 2), (2, 4), (0, 2)], f"Unexpected runs: {runs}"
    rle_ratio = RunLengthCoder.compression_ratio(seq)
    assert rle_ratio < 0.5, f"Expected significant RLE compression, got {rle_ratio}"
    print(f"[RunLengthCoder] {len(seq)} items → {len(runs)} runs, ratio={rle_ratio:.2f}")

    # ── 5. StructPacker ────────────────────────────────────────────────
    complex_obj = {
        "task_id": "t-abc123",
        "scores": [98, 87, 92, 100],
        "metadata": {"model": "local-v5", "retries": 2, "success": True},
        "tags": ["critical", "pipeline"],
        "value": None,
        "temperature": -0.5,
        "big_int": 10**18,
    }
    packed = StructPacker.pack(complex_obj)
    unpacked = StructPacker.unpack(packed)
    assert unpacked["task_id"] == "t-abc123"
    assert unpacked["scores"] == [98, 87, 92, 100]
    assert unpacked["metadata"]["model"] == "local-v5"
    assert unpacked["metadata"]["retries"] == 2
    assert unpacked["metadata"]["success"] is True
    assert unpacked["value"] is None
    assert abs(unpacked["temperature"] - (-0.5)) < 1e-9
    assert unpacked["big_int"] == 10**18

    b64 = StructPacker.pack_b64(complex_obj)
    unpacked_b64 = StructPacker.unpack_b64(b64)
    assert unpacked_b64["task_id"] == "t-abc123"
    json_size = len(json.dumps(complex_obj, separators=(",", ":")).encode())
    b64_size = len(b64.encode())
    print(f"[StructPacker] JSON={json_size}B → binary={len(packed)}B → b85+zlib={b64_size}B "
          f"({b64_size/json_size:.0%} of JSON)")

    # ── 6. DenseStateCodec ─────────────────────────────────────────────
    agent_state = {
        "agent_id": "planner-v3",
        "task_ids": ["t-001", "t-002", "t-003", "t-004", "t-005"],
        "scores": [72, 75, 78, 80, 85, 88, 90, 92],
        "timestamps": [1711500000 + i * 60 for i in range(8)],
        "statuses": ["pending", "running", "running", "done", "done",
                     "done", "running", "pending"],
        "config": {"max_retries": 3, "timeout": 60, "model": "local-v5"},
        "active": True,
    }

    encoded_str, stats = DenseStateCodec.encode(agent_state)
    decoded_state = DenseStateCodec.decode(encoded_str)

    assert decoded_state["agent_id"] == "planner-v3"
    assert decoded_state["scores"] == agent_state["scores"]
    assert decoded_state["timestamps"] == agent_state["timestamps"]
    assert decoded_state["statuses"] == agent_state["statuses"]
    assert decoded_state["config"]["max_retries"] == 3
    assert decoded_state["active"] is True
    assert decoded_state["task_ids"] == agent_state["task_ids"]

    fp = DenseStateCodec.fingerprint(agent_state)
    assert len(fp) == 8
    assert DenseStateCodec.fingerprint(agent_state) == fp  # deterministic

    print(f"[DenseStateCodec] {stats.original_bytes}B → {stats.encoded_bytes}B "
          f"({stats.savings_pct:.1f}% savings)")
    print(f"  strategies: {stats.strategy_used}")
    print(f"  fingerprint: {fp}")
    # Small payloads may expand due to metadata overhead; verify round-trip is exact
    print(f"  ratio: {stats.ratio:.2f} (overhead expected for small payloads)")

    # Larger payload to demonstrate real savings
    large_state = {
        "agent_id": "executor-v7",
        "scores": list(range(100, 200)),  # 100 incrementing ints → perfect delta
        "timestamps": [1711500000 + i * 30 for i in range(100)],
        "statuses": (["running"] * 30 + ["done"] * 50 + ["idle"] * 20),
        "log_levels": (["info"] * 60 + ["warn"] * 25 + ["error"] * 15),
        "config": {"max_retries": 5, "timeout": 120, "model": "local-v7",
                   "fallback": "local-v5", "batch_size": 32},
    }
    lg_enc, lg_stats = DenseStateCodec.encode(large_state)
    lg_dec = DenseStateCodec.decode(lg_enc)
    assert lg_dec["scores"] == large_state["scores"]
    assert lg_dec["timestamps"] == large_state["timestamps"]
    assert lg_dec["statuses"] == large_state["statuses"]
    assert lg_stats.savings_pct > 0, f"Expected savings on large payload, got {lg_stats.savings_pct:.1f}%"
    print(f"[DenseStateCodec-large] {lg_stats.original_bytes}B → {lg_stats.encoded_bytes}B "
          f"({lg_stats.savings_pct:.1f}% savings)")

    # ── Edge cases ─────────────────────────────────────────────────────
    empty_enc, empty_stats = DenseStateCodec.encode({})
    assert DenseStateCodec.decode(empty_enc) == {}

    single = {"x": 42}
    s_enc, _ = DenseStateCodec.encode(single)
    assert DenseStateCodec.decode(s_enc) == single

    assert DeltaEncoder.decode(DeltaEncoder.encode([])) == []
    assert RunLengthCoder.decode(RunLengthCoder.encode([])) == []
    assert DictCoder().fit([]).encode([]) == []

    print("\n✅ All assertions passed — information-dense representations verified.")
