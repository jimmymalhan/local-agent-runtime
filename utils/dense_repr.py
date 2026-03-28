"""
Information-dense representations: encode more information per token.

Provides multiple strategies for compacting structured data into minimal
token footprints while preserving lossless round-trip fidelity:

1.  BitPackedStruct   - pack typed fields into a minimal byte string
2.  DictCodec         - dictionary-coded compression for repeated string values
3.  DeltaEncoder      - delta + varint encoding for sorted/monotonic integers
4.  TrieCompressor    - prefix-deduplication for string lists
5.  ColumnarStore     - column-oriented encoding for record batches
6.  HybridEncoder     - auto-selects best strategy per field type
7.  RunLengthEncoder  - RLE for sequences with long runs of identical values
8.  BloomSketch       - probabilistic set membership in constant space
9.  CompactJSON       - schema-separated JSON (header + values, no key repetition)
10. MessagePacker     - fixed-schema agent message encoding (role+ts+payload)
"""

import base64
import hashlib
import json
import math
import struct
import time
from collections import Counter, defaultdict
from io import BytesIO
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 1. Variable-length integer encoding (unsigned + signed zigzag)
# ---------------------------------------------------------------------------

def encode_varint(n: int) -> bytes:
    """Encode non-negative integer as variable-length bytes (LEB128)."""
    assert n >= 0, f"encode_varint requires n >= 0, got {n}"
    parts = []
    while n > 0x7F:
        parts.append((n & 0x7F) | 0x80)
        n >>= 7
    parts.append(n & 0x7F)
    return bytes(parts)


def decode_varint(buf: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode varint from buf at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        b = buf[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, offset


def zigzag_encode(n: int) -> int:
    """Map signed int to unsigned via zigzag: 0,-1,1,-2,2,... -> 0,1,2,3,4,..."""
    return (n << 1) ^ (n >> 63)


def zigzag_decode(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


# ---------------------------------------------------------------------------
# 2. BitPackedStruct - pack typed fields into minimal bytes
# ---------------------------------------------------------------------------

class BitPackedStruct:
    """
    Define a schema of named fields with known bit widths, then pack/unpack
    records into minimal byte strings.

    schema: list of (name, bits) tuples.
    Total bits per record = sum(bits); packed into ceil(total/8) bytes.
    """

    def __init__(self, schema: list[tuple[str, int]]):
        self.schema = schema
        self.names = [s[0] for s in schema]
        self.widths = [s[1] for s in schema]
        self.total_bits = sum(self.widths)
        self.record_bytes = math.ceil(self.total_bits / 8)

    def pack(self, record: dict[str, int]) -> bytes:
        bits = 0
        pos = 0
        for name, width in self.schema:
            val = record[name]
            mask = (1 << width) - 1
            if val < 0 or val > mask:
                raise ValueError(f"Field '{name}' value {val} out of range [0, {mask}]")
            bits |= (val & mask) << pos
            pos += width
        return bits.to_bytes(self.record_bytes, "little")

    def unpack(self, data: bytes) -> dict[str, int]:
        bits = int.from_bytes(data[: self.record_bytes], "little")
        record = {}
        pos = 0
        for name, width in self.schema:
            mask = (1 << width) - 1
            record[name] = (bits >> pos) & mask
            pos += width
        return record

    def pack_many(self, records: list[dict[str, int]]) -> bytes:
        return b"".join(self.pack(r) for r in records)

    def unpack_many(self, data: bytes) -> list[dict[str, int]]:
        n = len(data) // self.record_bytes
        return [
            self.unpack(data[i * self.record_bytes : (i + 1) * self.record_bytes])
            for i in range(n)
        ]


# ---------------------------------------------------------------------------
# 3. DictCodec - dictionary-coded compression for repeated strings
# ---------------------------------------------------------------------------

class DictCodec:
    """
    Replace repeated string values with short integer codes.
    Encodes a list of strings as: [dictionary] + [code sequence].
    Achieves high compression when cardinality << count.
    """

    @staticmethod
    def encode(values: list[str]) -> bytes:
        vocab: dict[str, int] = {}
        codes: list[int] = []
        for v in values:
            if v not in vocab:
                vocab[v] = len(vocab)
            codes.append(vocab[v])

        buf = BytesIO()
        # Write vocab size
        buf.write(encode_varint(len(vocab)))
        # Write vocab entries (sorted by code)
        for word, _ in sorted(vocab.items(), key=lambda x: x[1]):
            encoded = word.encode("utf-8")
            buf.write(encode_varint(len(encoded)))
            buf.write(encoded)
        # Write code count + codes
        buf.write(encode_varint(len(codes)))
        for c in codes:
            buf.write(encode_varint(c))
        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> list[str]:
        off = 0
        vocab_size, off = decode_varint(data, off)
        vocab: list[str] = []
        for _ in range(vocab_size):
            slen, off = decode_varint(data, off)
            vocab.append(data[off : off + slen].decode("utf-8"))
            off += slen
        count, off = decode_varint(data, off)
        result = []
        for _ in range(count):
            code, off = decode_varint(data, off)
            result.append(vocab[code])
        return result


# ---------------------------------------------------------------------------
# 4. DeltaEncoder - delta + varint for sorted/monotonic integer sequences
# ---------------------------------------------------------------------------

class DeltaEncoder:
    """
    Encode sorted integer sequences as base + deltas (zigzag-varint).
    Ideal for timestamps, IDs, or any monotonically increasing data.
    """

    @staticmethod
    def encode(values: list[int]) -> bytes:
        buf = BytesIO()
        buf.write(encode_varint(len(values)))
        prev = 0
        for v in values:
            delta = v - prev
            buf.write(encode_varint(zigzag_encode(delta)))
            prev = v
        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> list[int]:
        off = 0
        count, off = decode_varint(data, off)
        values = []
        prev = 0
        for _ in range(count):
            zz, off = decode_varint(data, off)
            delta = zigzag_decode(zz)
            prev += delta
            values.append(prev)
        return values


# ---------------------------------------------------------------------------
# 5. TrieCompressor - prefix-deduplication for string lists
# ---------------------------------------------------------------------------

class TrieCompressor:
    """
    Compress a list of strings by storing shared prefixes once.
    Encoding: for each string, store (prefix_len_shared_with_prev, suffix).
    """

    @staticmethod
    def encode(strings: list[str]) -> bytes:
        buf = BytesIO()
        buf.write(encode_varint(len(strings)))
        prev = ""
        for s in strings:
            common = 0
            limit = min(len(prev), len(s))
            while common < limit and prev[common] == s[common]:
                common += 1
            suffix = s[common:].encode("utf-8")
            buf.write(encode_varint(common))
            buf.write(encode_varint(len(suffix)))
            buf.write(suffix)
            prev = s
        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> list[str]:
        off = 0
        count, off = decode_varint(data, off)
        strings = []
        prev = ""
        for _ in range(count):
            common, off = decode_varint(data, off)
            slen, off = decode_varint(data, off)
            suffix = data[off : off + slen].decode("utf-8")
            off += slen
            s = prev[:common] + suffix
            strings.append(s)
            prev = s
        return strings


# ---------------------------------------------------------------------------
# 6. ColumnarStore - column-oriented encoding for record batches
# ---------------------------------------------------------------------------

class ColumnarStore:
    """
    Transpose row-oriented records into columns, then apply per-column
    encoding: DeltaEncoder for ints, DictCodec for strings, raw for floats.

    This mirrors columnar formats (Parquet/Arrow) at a micro scale,
    maximizing compression by grouping same-type data together.
    """

    @staticmethod
    def encode(records: list[dict[str, Any]]) -> bytes:
        if not records:
            return encode_varint(0)

        keys = list(records[0].keys())
        buf = BytesIO()
        buf.write(encode_varint(len(records)))
        buf.write(encode_varint(len(keys)))

        for key in keys:
            kb = key.encode("utf-8")
            buf.write(encode_varint(len(kb)))
            buf.write(kb)

            col = [r[key] for r in records]
            sample = col[0]

            if isinstance(sample, int):
                buf.write(b"\x01")  # type tag: int
                encoded = DeltaEncoder.encode(col)
                buf.write(encode_varint(len(encoded)))
                buf.write(encoded)
            elif isinstance(sample, float):
                buf.write(b"\x02")  # type tag: float
                packed = struct.pack(f"<{len(col)}d", *col)
                buf.write(encode_varint(len(packed)))
                buf.write(packed)
            elif isinstance(sample, str):
                buf.write(b"\x03")  # type tag: str
                encoded = DictCodec.encode(col)
                buf.write(encode_varint(len(encoded)))
                buf.write(encoded)
            else:
                buf.write(b"\x04")  # type tag: json fallback
                jb = json.dumps(col, separators=(",", ":")).encode("utf-8")
                buf.write(encode_varint(len(jb)))
                buf.write(jb)

        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> list[dict[str, Any]]:
        off = 0
        nrows, off = decode_varint(data, off)
        if nrows == 0:
            return []
        ncols, off = decode_varint(data, off)

        columns: dict[str, list] = {}
        key_order: list[str] = []

        for _ in range(ncols):
            klen, off = decode_varint(data, off)
            key = data[off : off + klen].decode("utf-8")
            off += klen
            key_order.append(key)

            type_tag = data[off]
            off += 1
            dlen, off = decode_varint(data, off)
            chunk = data[off : off + dlen]
            off += dlen

            if type_tag == 0x01:
                columns[key] = DeltaEncoder.decode(chunk)
            elif type_tag == 0x02:
                columns[key] = list(struct.unpack(f"<{nrows}d", chunk))
            elif type_tag == 0x03:
                columns[key] = DictCodec.decode(chunk)
            else:
                columns[key] = json.loads(chunk.decode("utf-8"))

        return [{k: columns[k][i] for k in key_order} for i in range(nrows)]


# ---------------------------------------------------------------------------
# 7. HybridEncoder - auto-selects best strategy per data shape
# ---------------------------------------------------------------------------

class HybridEncoder:
    """
    Analyze input data and pick the densest encoding automatically.
    Returns a self-describing envelope: 1-byte strategy tag + payload.
    """

    STRAT_RAW_JSON = 0
    STRAT_DICT_CODED = 1
    STRAT_DELTA_INT = 2
    STRAT_TRIE = 3
    STRAT_COLUMNAR = 4
    STRAT_BITPACKED = 5

    @staticmethod
    def encode(data: Any) -> bytes:
        buf = BytesIO()

        if isinstance(data, list) and len(data) > 0:
            sample = data[0]

            # List of dicts -> columnar
            if isinstance(sample, dict):
                buf.write(bytes([HybridEncoder.STRAT_COLUMNAR]))
                payload = ColumnarStore.encode(data)
                buf.write(payload)
                return buf.getvalue()

            # List of ints -> delta
            if isinstance(sample, int):
                buf.write(bytes([HybridEncoder.STRAT_DELTA_INT]))
                payload = DeltaEncoder.encode(data)
                buf.write(payload)
                return buf.getvalue()

            # List of strings -> dict-coded or trie based on cardinality
            if isinstance(sample, str):
                cardinality = len(set(data))
                if cardinality < len(data) * 0.5:
                    buf.write(bytes([HybridEncoder.STRAT_DICT_CODED]))
                    payload = DictCodec.encode(data)
                else:
                    buf.write(bytes([HybridEncoder.STRAT_TRIE]))
                    payload = TrieCompressor.encode(sorted(data))
                buf.write(payload)
                return buf.getvalue()

        # Fallback: JSON
        buf.write(bytes([HybridEncoder.STRAT_RAW_JSON]))
        jb = json.dumps(data, separators=(",", ":")).encode("utf-8")
        buf.write(jb)
        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> Any:
        strat = data[0]
        payload = data[1:]

        if strat == HybridEncoder.STRAT_COLUMNAR:
            return ColumnarStore.decode(payload)
        elif strat == HybridEncoder.STRAT_DELTA_INT:
            return DeltaEncoder.decode(payload)
        elif strat == HybridEncoder.STRAT_DICT_CODED:
            return DictCodec.decode(payload)
        elif strat == HybridEncoder.STRAT_TRIE:
            return TrieCompressor.decode(payload)
        elif strat == HybridEncoder.STRAT_RAW_JSON:
            return json.loads(payload.decode("utf-8"))
        else:
            raise ValueError(f"Unknown strategy tag: {strat}")


# ---------------------------------------------------------------------------
# 8. Base85 text representation for binary payloads
# ---------------------------------------------------------------------------

def to_text(binary: bytes) -> str:
    """Encode binary payload as base85 text (25% overhead vs 33% for base64)."""
    return base64.b85encode(binary).decode("ascii")


def from_text(text: str) -> bytes:
    """Decode base85 text back to binary."""
    return base64.b85decode(text.encode("ascii"))


# ---------------------------------------------------------------------------
# 9. Density metrics
# ---------------------------------------------------------------------------

def density_report(original: Any, encoded: bytes) -> dict:
    """Compute information density metrics."""
    raw_json = json.dumps(original, separators=(",", ":")).encode("utf-8")
    raw_size = len(raw_json)
    enc_size = len(encoded)
    text_size = len(to_text(encoded))

    return {
        "raw_json_bytes": raw_size,
        "encoded_bytes": enc_size,
        "base85_chars": text_size,
        "byte_ratio": round(enc_size / raw_size, 4) if raw_size else 0,
        "text_ratio": round(text_size / raw_size, 4) if raw_size else 0,
        "savings_pct": round((1 - enc_size / raw_size) * 100, 1) if raw_size else 0,
    }


# ---------------------------------------------------------------------------
# 10. RunLengthEncoder - RLE for repetitive sequences
# ---------------------------------------------------------------------------

class RunLengthEncoder:
    """
    Run-length encode a sequence of hashable values.
    Format: varint(num_runs) then for each run: varint(length) + value.
    Values are serialized as JSON fragments (compact).
    """

    @staticmethod
    def encode(values: list) -> bytes:
        if not values:
            return encode_varint(0)
        runs: list[tuple[Any, int]] = []
        cur, count = values[0], 1
        for v in values[1:]:
            if v == cur:
                count += 1
            else:
                runs.append((cur, count))
                cur, count = v, 1
        runs.append((cur, count))

        buf = BytesIO()
        buf.write(encode_varint(len(runs)))
        for val, cnt in runs:
            buf.write(encode_varint(cnt))
            vb = json.dumps(val, separators=(",", ":")).encode("utf-8")
            buf.write(encode_varint(len(vb)))
            buf.write(vb)
        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> list:
        off = 0
        num_runs, off = decode_varint(data, off)
        result = []
        for _ in range(num_runs):
            cnt, off = decode_varint(data, off)
            vlen, off = decode_varint(data, off)
            val = json.loads(data[off : off + vlen].decode("utf-8"))
            off += vlen
            result.extend([val] * cnt)
        return result


# ---------------------------------------------------------------------------
# 11. BloomSketch - probabilistic set membership in constant space
# ---------------------------------------------------------------------------

class BloomSketch:
    """
    Space-efficient probabilistic set.  Useful for encoding "which items are
    present" in far fewer bytes than listing them, at the cost of a tunable
    false-positive rate (no false negatives).

    Bit array is stored as raw bytes. k independent hashes derived from
    double-hashing with MD5 + SHA1.
    """

    def __init__(self, capacity: int, fp_rate: float = 0.01):
        self.n = capacity
        self.fp = fp_rate
        self.m = self._optimal_bits(capacity, fp_rate)
        self.k = self._optimal_hashes(self.m, capacity)
        self._bits = bytearray((self.m + 7) // 8)
        self._count = 0

    @staticmethod
    def _optimal_bits(n: int, p: float) -> int:
        return max(8, int(-n * math.log(p) / (math.log(2) ** 2)))

    @staticmethod
    def _optimal_hashes(m: int, n: int) -> int:
        return max(1, int((m / n) * math.log(2)))

    def _hashes(self, item: str) -> list[int]:
        raw = item.encode("utf-8")
        h1 = int(hashlib.md5(raw).hexdigest(), 16)
        h2 = int(hashlib.sha1(raw).hexdigest(), 16)
        return [(h1 + i * h2) % self.m for i in range(self.k)]

    def add(self, item: str) -> None:
        for pos in self._hashes(item):
            self._bits[pos >> 3] |= 1 << (pos & 7)
        self._count += 1

    def __contains__(self, item: str) -> bool:
        return all(
            self._bits[pos >> 3] & (1 << (pos & 7))
            for pos in self._hashes(item)
        )

    def to_bytes(self) -> bytes:
        buf = BytesIO()
        buf.write(encode_varint(self.m))
        buf.write(encode_varint(self.k))
        buf.write(encode_varint(self._count))
        buf.write(bytes(self._bits))
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomSketch":
        off = 0
        m, off = decode_varint(data, off)
        k, off = decode_varint(data, off)
        count, off = decode_varint(data, off)
        nbytes = (m + 7) // 8
        obj = cls.__new__(cls)
        obj.m = m
        obj.k = k
        obj._count = count
        obj.n = count
        obj.fp = 0.01
        obj._bits = bytearray(data[off : off + nbytes])
        return obj

    @property
    def size_bytes(self) -> int:
        return len(self._bits)


# ---------------------------------------------------------------------------
# 12. CompactJSON - schema-separated JSON encoding
# ---------------------------------------------------------------------------

class CompactJSON:
    """
    For lists of dicts sharing the same keys, store the key schema once
    then pack values row-by-row. Output is valid JSON but ~40-60% smaller
    than naive json.dumps for typical agent state records.

    Wire format (JSON string):
      {"_s": ["key1","key2",...], "_v": [[val1,val2,...], ...]}
    """

    @staticmethod
    def encode(records: list[dict[str, Any]]) -> str:
        if not records:
            return json.dumps({"_s": [], "_v": []}, separators=(",", ":"))
        keys = list(records[0].keys())
        rows = [[r[k] for k in keys] for r in records]
        return json.dumps({"_s": keys, "_v": rows}, separators=(",", ":"))

    @staticmethod
    def decode(text: str) -> list[dict[str, Any]]:
        obj = json.loads(text)
        keys = obj["_s"]
        return [{k: v for k, v in zip(keys, row)} for row in obj["_v"]]


# ---------------------------------------------------------------------------
# 13. MessagePacker - fixed-schema agent message encoding
# ---------------------------------------------------------------------------

class MessagePacker:
    """
    Encode agent runtime messages (role, timestamp, payload) into a compact
    binary format. Roles are dict-coded; timestamps are delta-encoded;
    payloads are UTF-8 with length-prefix.

    This is purpose-built for the local-agent-runtime message log format.
    """

    ROLES = ["system", "router", "retriever", "skeptic", "verifier",
             "executor", "planner", "monitor", "rescue", "user"]

    @classmethod
    def encode(cls, messages: list[dict[str, Any]]) -> bytes:
        """Encode list of {role, ts, payload} dicts."""
        buf = BytesIO()
        buf.write(encode_varint(len(messages)))

        # Build role index (known roles get short codes, unknown get fallback)
        role_map = {r: i for i, r in enumerate(cls.ROLES)}

        prev_ts = 0
        for msg in messages:
            role = msg.get("role", "system")
            ts = msg.get("ts", 0)
            payload = msg.get("payload", "")

            # Role: 1 byte (0-9 known, 0xFF = custom with inline string)
            if role in role_map:
                buf.write(bytes([role_map[role]]))
            else:
                buf.write(b"\xff")
                rb = role.encode("utf-8")
                buf.write(encode_varint(len(rb)))
                buf.write(rb)

            # Timestamp: delta-varint from previous
            delta = ts - prev_ts
            buf.write(encode_varint(zigzag_encode(delta)))
            prev_ts = ts

            # Payload: length-prefixed UTF-8
            pb = payload.encode("utf-8")
            buf.write(encode_varint(len(pb)))
            buf.write(pb)

        return buf.getvalue()

    @classmethod
    def decode(cls, data: bytes) -> list[dict[str, Any]]:
        off = 0
        count, off = decode_varint(data, off)
        messages = []
        prev_ts = 0

        for _ in range(count):
            role_byte = data[off]
            off += 1
            if role_byte == 0xFF:
                rlen, off = decode_varint(data, off)
                role = data[off : off + rlen].decode("utf-8")
                off += rlen
            else:
                role = cls.ROLES[role_byte]

            zz, off = decode_varint(data, off)
            delta = zigzag_decode(zz)
            ts = prev_ts + delta
            prev_ts = ts

            plen, off = decode_varint(data, off)
            payload = data[off : off + plen].decode("utf-8")
            off += plen

            messages.append({"role": role, "ts": ts, "payload": payload})

        return messages


# ===================================================================
# __main__: comprehensive assertions
# ===================================================================

if __name__ == "__main__":

    # --- Varint ---
    for n in [0, 1, 127, 128, 255, 300, 16383, 16384, 2**21 - 1, 2**28]:
        enc = encode_varint(n)
        dec, end = decode_varint(enc)
        assert dec == n, f"varint roundtrip failed for {n}: got {dec}"
        assert end == len(enc), f"varint consumed wrong bytes for {n}"
    print("[varint] passed")

    # --- Zigzag ---
    for n in [0, -1, 1, -2, 2, -64, 64, -2**30, 2**30]:
        assert zigzag_decode(zigzag_encode(n)) == n, f"zigzag failed for {n}"
    print("[zigzag] passed")

    # --- BitPackedStruct ---
    schema = [("flags", 4), ("level", 6), ("score", 10), ("id", 12)]
    bp = BitPackedStruct(schema)
    assert bp.record_bytes == 4  # 32 bits = 4 bytes

    rec = {"flags": 0b1010, "level": 42, "score": 999, "id": 3000}
    packed = bp.pack(rec)
    assert len(packed) == 4
    unpacked = bp.unpack(packed)
    assert unpacked == rec, f"BitPacked roundtrip: {unpacked} != {rec}"

    records = [
        {"flags": i % 16, "level": i % 64, "score": i % 1024, "id": i}
        for i in range(100)
    ]
    bulk = bp.pack_many(records)
    assert len(bulk) == 400  # 100 * 4 bytes
    assert bp.unpack_many(bulk) == records
    print("[BitPackedStruct] passed")

    # --- DictCodec ---
    categories = ["error", "warn", "info"] * 1000 + ["debug"] * 200
    encoded = DictCodec.encode(categories)
    decoded = DictCodec.decode(encoded)
    assert decoded == categories
    raw_json = json.dumps(categories, separators=(",", ":")).encode()
    assert len(encoded) < len(raw_json) * 0.3, (
        f"DictCodec not dense enough: {len(encoded)} vs {len(raw_json)}"
    )
    print(f"[DictCodec] passed  ({len(encoded)} vs {len(raw_json)} raw JSON bytes)")

    # --- DeltaEncoder ---
    timestamps = list(range(1000000, 1000000 + 500))
    encoded_ts = DeltaEncoder.encode(timestamps)
    assert DeltaEncoder.decode(encoded_ts) == timestamps
    raw_ts = json.dumps(timestamps, separators=(",", ":")).encode()
    assert len(encoded_ts) < len(raw_ts) * 0.25
    print(f"[DeltaEncoder] passed  ({len(encoded_ts)} vs {len(raw_ts)} raw JSON bytes)")

    # Non-monotonic sequences
    zigzag_seq = [10, 5, 20, 3, 50, 0]
    enc_zz = DeltaEncoder.encode(zigzag_seq)
    assert DeltaEncoder.decode(enc_zz) == zigzag_seq
    print("[DeltaEncoder non-monotonic] passed")

    # --- TrieCompressor ---
    paths = sorted([
        "src/components/button.tsx",
        "src/components/card.tsx",
        "src/components/dialog.tsx",
        "src/components/dropdown.tsx",
        "src/utils/format.ts",
        "src/utils/helpers.ts",
        "src/utils/validate.ts",
        "tests/components/button.test.tsx",
        "tests/components/card.test.tsx",
        "tests/utils/format.test.ts",
    ])
    encoded_paths = TrieCompressor.encode(paths)
    decoded_paths = TrieCompressor.decode(encoded_paths)
    assert decoded_paths == paths
    raw_paths = json.dumps(paths, separators=(",", ":")).encode()
    assert len(encoded_paths) < len(raw_paths) * 0.7
    print(f"[TrieCompressor] passed  ({len(encoded_paths)} vs {len(raw_paths)} raw JSON bytes)")

    # --- ColumnarStore ---
    events = [
        {"ts": 1000000 + i, "level": ["info", "warn", "error"][i % 3],
         "latency": 0.5 + i * 0.01, "msg": f"event_{i}"}
        for i in range(200)
    ]
    col_enc = ColumnarStore.encode(events)
    col_dec = ColumnarStore.decode(col_enc)
    assert len(col_dec) == len(events)
    for orig, decoded_r in zip(events, col_dec):
        assert orig["ts"] == decoded_r["ts"]
        assert orig["level"] == decoded_r["level"]
        assert abs(orig["latency"] - decoded_r["latency"]) < 1e-10
        assert orig["msg"] == decoded_r["msg"]
    raw_events = json.dumps(events, separators=(",", ":")).encode()
    assert len(col_enc) < len(raw_events) * 0.5
    print(f"[ColumnarStore] passed  ({len(col_enc)} vs {len(raw_events)} raw JSON bytes)")

    # Empty records
    assert ColumnarStore.decode(ColumnarStore.encode([])) == []
    print("[ColumnarStore empty] passed")

    # --- HybridEncoder ---
    # Auto-selects columnar for list-of-dicts
    hyb_enc = HybridEncoder.encode(events)
    hyb_dec = HybridEncoder.decode(hyb_enc)
    assert len(hyb_dec) == len(events)
    assert hyb_enc[0] == HybridEncoder.STRAT_COLUMNAR
    print("[HybridEncoder -> columnar] passed")

    # Auto-selects delta for list-of-ints
    hyb_int = HybridEncoder.encode(timestamps)
    assert hyb_int[0] == HybridEncoder.STRAT_DELTA_INT
    assert HybridEncoder.decode(hyb_int) == timestamps
    print("[HybridEncoder -> delta] passed")

    # Auto-selects dict-coded for low-cardinality strings
    hyb_dict = HybridEncoder.encode(categories)
    assert hyb_dict[0] == HybridEncoder.STRAT_DICT_CODED
    assert HybridEncoder.decode(hyb_dict) == categories
    print("[HybridEncoder -> dict-coded] passed")

    # Auto-selects trie for high-cardinality strings
    unique_strs = [f"item_{i:04d}" for i in range(100)]
    hyb_trie = HybridEncoder.encode(unique_strs)
    assert hyb_trie[0] == HybridEncoder.STRAT_TRIE
    decoded_trie = HybridEncoder.decode(hyb_trie)
    assert sorted(decoded_trie) == sorted(unique_strs)
    print("[HybridEncoder -> trie] passed")

    # Fallback to JSON for scalar / mixed
    hyb_scalar = HybridEncoder.encode({"key": "value"})
    assert hyb_scalar[0] == HybridEncoder.STRAT_RAW_JSON
    assert HybridEncoder.decode(hyb_scalar) == {"key": "value"}
    print("[HybridEncoder -> json fallback] passed")

    # --- Base85 text encoding ---
    binary = col_enc
    text = to_text(binary)
    assert from_text(text) == binary
    # Base85 should be smaller than base64
    b64_text = base64.b64encode(binary).decode()
    assert len(text) <= len(b64_text)
    print(f"[base85] passed  (base85={len(text)} vs base64={len(b64_text)} chars)")

    # --- Density report ---
    report = density_report(events, col_enc)
    assert report["savings_pct"] > 40
    assert report["byte_ratio"] < 0.6
    print(f"[density_report] savings={report['savings_pct']}%  "
          f"byte_ratio={report['byte_ratio']}  "
          f"text_ratio={report['text_ratio']}")

    # --- RunLengthEncoder ---
    rle_input = [0] * 50 + [1] * 30 + [0] * 20 + [2] * 100
    rle_enc = RunLengthEncoder.encode(rle_input)
    rle_dec = RunLengthEncoder.decode(rle_enc)
    assert rle_dec == rle_input, "RLE roundtrip failed"
    raw_rle = json.dumps(rle_input, separators=(",", ":")).encode()
    assert len(rle_enc) < len(raw_rle) * 0.15, (
        f"RLE not dense enough: {len(rle_enc)} vs {len(raw_rle)}"
    )
    print(f"[RunLengthEncoder] passed  ({len(rle_enc)} vs {len(raw_rle)} raw JSON bytes)")

    # RLE with strings
    rle_str = ["ok"] * 100 + ["err"] * 5 + ["ok"] * 50
    assert RunLengthEncoder.decode(RunLengthEncoder.encode(rle_str)) == rle_str
    print("[RunLengthEncoder strings] passed")

    # RLE empty
    assert RunLengthEncoder.decode(RunLengthEncoder.encode([])) == []
    print("[RunLengthEncoder empty] passed")

    # --- BloomSketch ---
    bloom = BloomSketch(capacity=1000, fp_rate=0.01)
    items = [f"agent_{i}" for i in range(500)]
    for item in items:
        bloom.add(item)
    # No false negatives
    for item in items:
        assert item in bloom, f"BloomSketch false negative: {item}"
    # False positive rate within bounds
    fp_count = sum(1 for i in range(5000, 6000) if f"agent_{i}" in bloom)
    assert fp_count < 50, f"BloomSketch FP rate too high: {fp_count}/1000"
    # Serialization roundtrip
    bloom_bytes = bloom.to_bytes()
    bloom2 = BloomSketch.from_bytes(bloom_bytes)
    for item in items:
        assert item in bloom2, f"BloomSketch deserialized false negative: {item}"
    # Size is much smaller than listing all items
    raw_items = json.dumps(items, separators=(",", ":")).encode()
    assert bloom.size_bytes < len(raw_items) * 0.25, (
        f"BloomSketch not dense: {bloom.size_bytes} vs {len(raw_items)}"
    )
    print(f"[BloomSketch] passed  (filter={bloom.size_bytes}B vs list={len(raw_items)}B, "
          f"fp={fp_count}/1000)")

    # --- CompactJSON ---
    cj_records = [
        {"task_id": f"t-{i:04d}", "status": ["pending", "done", "fail"][i % 3],
         "score": i * 0.1, "agent": "executor"}
        for i in range(100)
    ]
    cj_text = CompactJSON.encode(cj_records)
    cj_dec = CompactJSON.decode(cj_text)
    assert cj_dec == cj_records
    raw_cj = json.dumps(cj_records, separators=(",", ":"))
    savings = (1 - len(cj_text) / len(raw_cj)) * 100
    assert savings > 25, f"CompactJSON savings too low: {savings:.1f}%"
    print(f"[CompactJSON] passed  ({len(cj_text)} vs {len(raw_cj)} chars, "
          f"{savings:.1f}% saved)")

    # CompactJSON empty
    assert CompactJSON.decode(CompactJSON.encode([])) == []
    print("[CompactJSON empty] passed")

    # --- MessagePacker ---
    base_ts = 1711500000
    messages = [
        {"role": "router", "ts": base_ts, "payload": "classify: db timeout"},
        {"role": "retriever", "ts": base_ts + 2, "payload": "found 3 similar incidents"},
        {"role": "skeptic", "ts": base_ts + 5, "payload": "alternative: network partition"},
        {"role": "verifier", "ts": base_ts + 8, "payload": "confirmed: connection pool exhaustion"},
        {"role": "custom_agent", "ts": base_ts + 10, "payload": "escalated to oncall"},
    ]
    msg_enc = MessagePacker.encode(messages)
    msg_dec = MessagePacker.decode(msg_enc)
    assert msg_dec == messages, f"MessagePacker roundtrip failed: {msg_dec}"
    raw_msg = json.dumps(messages, separators=(",", ":")).encode()
    msg_savings = (1 - len(msg_enc) / len(raw_msg)) * 100
    assert msg_savings > 30, f"MessagePacker savings too low: {msg_savings:.1f}%"
    print(f"[MessagePacker] passed  ({len(msg_enc)} vs {len(raw_msg)} bytes, "
          f"{msg_savings:.1f}% saved)")

    # MessagePacker empty
    assert MessagePacker.decode(MessagePacker.encode([])) == []
    print("[MessagePacker empty] passed")

    # MessagePacker with all known roles
    all_role_msgs = [
        {"role": r, "ts": base_ts + i, "payload": f"test {r}"}
        for i, r in enumerate(MessagePacker.ROLES)
    ]
    assert MessagePacker.decode(MessagePacker.encode(all_role_msgs)) == all_role_msgs
    print("[MessagePacker all roles] passed")

    # --- Overall density comparison ---
    print("\n=== Density Summary ===")
    test_cases = [
        ("200 events (columnar)", events, col_enc),
        ("3200 categories (dict-coded)", categories, DictCodec.encode(categories)),
        ("500 timestamps (delta)", timestamps, DeltaEncoder.encode(timestamps)),
        ("10 file paths (trie)", paths, TrieCompressor.encode(paths)),
        ("100 bitpacked records", records, bp.pack_many(records)),
        ("200 RLE ints", rle_input, rle_enc),
        ("500 bloom items", items, bloom.to_bytes()),
        ("100 compact JSON records", cj_records, cj_text.encode()),
        ("5 agent messages", messages, msg_enc),
    ]
    for label, orig, enc in test_cases:
        r = density_report(orig, enc)
        print(f"  {label:40s}  {r['raw_json_bytes']:>6d}B -> {r['encoded_bytes']:>5d}B  "
              f"({r['savings_pct']:5.1f}% saved)")

    print("\nAll assertions passed.")
