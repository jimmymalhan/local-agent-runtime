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
# 11b. SymbolTable - global string interning across entire payloads
# ---------------------------------------------------------------------------

class SymbolTable:
    """
    Deduplicate all string values across a nested structure by assigning
    each unique string a short varint code.  Particularly effective when
    the same strings appear in many different fields (e.g. agent names,
    status values, error codes repeated in logs, events, and state).

    Wire format: varint(num_symbols) + [len-prefixed strings] +
                 interned payload (strings replaced with varint codes).
    """

    @classmethod
    def encode(cls, obj: Any) -> bytes:
        symbols: dict[str, int] = {}
        cls._collect_strings(obj, symbols)
        buf = BytesIO()
        buf.write(encode_varint(len(symbols)))
        ordered = sorted(symbols.items(), key=lambda x: x[1])
        for s, _ in ordered:
            sb = s.encode("utf-8")
            buf.write(encode_varint(len(sb)))
            buf.write(sb)
        cls._write_interned(obj, symbols, buf)
        return buf.getvalue()

    @classmethod
    def _collect_strings(cls, obj: Any, symbols: dict[str, int]) -> None:
        if isinstance(obj, str):
            if obj not in symbols:
                symbols[obj] = len(symbols)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k not in symbols:
                    symbols[k] = len(symbols)
                cls._collect_strings(v, symbols)
        elif isinstance(obj, list):
            for item in obj:
                cls._collect_strings(item, symbols)

    @classmethod
    def _write_interned(cls, obj: Any, symbols: dict[str, int],
                        buf: BytesIO) -> None:
        if obj is None:
            buf.write(b"\x00")
        elif isinstance(obj, bool):
            buf.write(b"\x01" if obj else b"\x02")
        elif isinstance(obj, int):
            buf.write(b"\x03")
            buf.write(encode_varint(zigzag_encode(obj)))
        elif isinstance(obj, float):
            buf.write(b"\x04")
            buf.write(struct.pack("<d", obj))
        elif isinstance(obj, str):
            buf.write(b"\x05")
            buf.write(encode_varint(symbols[obj]))
        elif isinstance(obj, list):
            buf.write(b"\x06")
            buf.write(encode_varint(len(obj)))
            for item in obj:
                cls._write_interned(item, symbols, buf)
        elif isinstance(obj, dict):
            buf.write(b"\x07")
            buf.write(encode_varint(len(obj)))
            for k, v in obj.items():
                buf.write(encode_varint(symbols[k]))
                cls._write_interned(v, symbols, buf)
        else:
            cls._write_interned(str(obj), symbols, buf)

    @classmethod
    def decode(cls, data: bytes) -> Any:
        off = 0
        num_sym, off = decode_varint(data, off)
        symbols: list[str] = []
        for _ in range(num_sym):
            slen, off = decode_varint(data, off)
            symbols.append(data[off:off + slen].decode("utf-8"))
            off += slen
        val, _ = cls._read_interned(data, off, symbols)
        return val

    @classmethod
    def _read_interned(cls, data: bytes, off: int,
                       symbols: list[str]) -> tuple[Any, int]:
        tag = data[off]; off += 1
        if tag == 0x00:
            return None, off
        elif tag == 0x01:
            return True, off
        elif tag == 0x02:
            return False, off
        elif tag == 0x03:
            zz, off = decode_varint(data, off)
            return zigzag_decode(zz), off
        elif tag == 0x04:
            return struct.unpack_from("<d", data, off)[0], off + 8
        elif tag == 0x05:
            idx, off = decode_varint(data, off)
            return symbols[idx], off
        elif tag == 0x06:
            count, off = decode_varint(data, off)
            items = []
            for _ in range(count):
                item, off = cls._read_interned(data, off, symbols)
                items.append(item)
            return items, off
        elif tag == 0x07:
            count, off = decode_varint(data, off)
            d: dict = {}
            for _ in range(count):
                kidx, off = decode_varint(data, off)
                v, off = cls._read_interned(data, off, symbols)
                d[symbols[kidx]] = v
            return d, off
        else:
            raise ValueError(f"Unknown interned tag: {tag}")


# ---------------------------------------------------------------------------
# 11c. MultiCodecSelector - try multiple encoders, pick smallest
# ---------------------------------------------------------------------------

class MultiCodecSelector:
    """
    For list data, try every applicable encoder and return whichever
    produces the smallest output.  Adds a 1-byte strategy tag prefix
    so the decoder knows which codec was used.

    Strategy tags: 0=json, 1=dict_coded, 2=delta, 3=trie, 4=columnar,
                   5=rle, 6=sparse, 7=symbol_table
    """

    TAG_JSON = 0
    TAG_DICT = 1
    TAG_DELTA = 2
    TAG_TRIE = 3
    TAG_COLUMNAR = 4
    TAG_RLE = 5
    TAG_SPARSE = 6
    TAG_SYMBOL = 7

    @classmethod
    def encode(cls, data: Any) -> bytes:
        candidates: list[tuple[int, bytes]] = []

        # Always try JSON baseline
        jb = json.dumps(data, separators=(",", ":")).encode("utf-8")
        candidates.append((cls.TAG_JSON, jb))

        # Always try symbol table (works on any structure)
        try:
            st = SymbolTable.encode(data)
            candidates.append((cls.TAG_SYMBOL, st))
        except Exception:
            pass

        if isinstance(data, list) and len(data) > 0:
            sample = data[0]

            if all(isinstance(v, int) and not isinstance(v, bool) for v in data):
                try:
                    candidates.append((cls.TAG_DELTA, DeltaEncoder.encode(data)))
                except Exception:
                    pass
                # Check if sparse
                zeros = sum(1 for v in data if v == 0)
                if zeros > len(data) * 0.5:
                    try:
                        candidates.append((cls.TAG_SPARSE, SparseEncoder.encode(data)))
                    except Exception:
                        pass

            if all(isinstance(v, str) for v in data):
                card = len(set(data))
                if card < len(data) * 0.5:
                    try:
                        candidates.append((cls.TAG_DICT, DictCodec.encode(data)))
                    except Exception:
                        pass
                try:
                    candidates.append((cls.TAG_TRIE, TrieCompressor.encode(sorted(data))))
                except Exception:
                    pass

            if all(isinstance(v, dict) for v in data):
                keys0 = set(data[0].keys())
                if all(set(v.keys()) == keys0 for v in data):
                    try:
                        candidates.append((cls.TAG_COLUMNAR, ColumnarStore.encode(data)))
                    except Exception:
                        pass

            # RLE
            runs = 1
            for i in range(1, len(data)):
                if data[i] != data[i - 1]:
                    runs += 1
            if runs < len(data) * 0.3:
                try:
                    candidates.append((cls.TAG_RLE, RunLengthEncoder.encode(data)))
                except Exception:
                    pass

        # Pick smallest
        best_tag, best_payload = min(candidates, key=lambda x: len(x[1]))
        return bytes([best_tag]) + best_payload

    @classmethod
    def decode(cls, data: bytes) -> Any:
        tag = data[0]
        payload = data[1:]
        if tag == cls.TAG_JSON:
            return json.loads(payload.decode("utf-8"))
        elif tag == cls.TAG_DICT:
            return DictCodec.decode(payload)
        elif tag == cls.TAG_DELTA:
            return DeltaEncoder.decode(payload)
        elif tag == cls.TAG_TRIE:
            return TrieCompressor.decode(payload)
        elif tag == cls.TAG_COLUMNAR:
            return ColumnarStore.decode(payload)
        elif tag == cls.TAG_RLE:
            return RunLengthEncoder.decode(payload)
        elif tag == cls.TAG_SPARSE:
            return SparseEncoder.decode(payload)
        elif tag == cls.TAG_SYMBOL:
            return SymbolTable.decode(payload)
        else:
            raise ValueError(f"Unknown MultiCodec tag: {tag}")


# ---------------------------------------------------------------------------
# 11d. pack_dense / unpack_dense - top-level API with zlib + base85
# ---------------------------------------------------------------------------

import zlib as _zlib


def pack_dense(obj: Any) -> str:
    """Encode any Python object to a maximally dense base85 string.

    Uses MultiCodecSelector to pick the best binary encoding, then
    zlib-compresses and base85-encodes the result.  This is the
    recommended single entry point for maximum info per token.
    """
    raw = MultiCodecSelector.encode(obj)
    compressed = _zlib.compress(raw, level=9)
    return base64.b85encode(compressed).decode("ascii")


def unpack_dense(text: str) -> Any:
    """Decode a pack_dense() string back to the original object."""
    compressed = base64.b85decode(text.encode("ascii"))
    raw = _zlib.decompress(compressed)
    return MultiCodecSelector.decode(raw)


def density_compare(obj: Any) -> dict[str, int]:
    """Compare sizes across all available encoding strategies."""
    raw_json = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    results: dict[str, int] = {"raw_json": len(raw_json)}

    dense_text = pack_dense(obj)
    results["pack_dense_chars"] = len(dense_text)
    results["pack_dense_tokens"] = math.ceil(len(dense_text) / 4)
    results["raw_json_tokens"] = math.ceil(len(raw_json) / 4)
    results["token_savings_pct"] = round(
        (1 - results["pack_dense_tokens"] / results["raw_json_tokens"]) * 100, 1
    ) if results["raw_json_tokens"] else 0

    return results


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


# ---------------------------------------------------------------------------
# 14. SparseEncoder - compact encoding for arrays with many zeros/defaults
# ---------------------------------------------------------------------------

class SparseEncoder:
    """
    Encode sparse arrays (mostly zeros/default values) using coordinate format.
    Stores only non-default positions + values.  Far denser than raw when
    density < 50%.

    Wire format: varint(length) + varint(num_nonzero) +
                 for each: varint(index) + value_bytes
    """

    @staticmethod
    def encode(values: list, default: Any = 0) -> bytes:
        buf = BytesIO()
        buf.write(encode_varint(len(values)))
        nonzero = [(i, v) for i, v in enumerate(values) if v != default]
        buf.write(encode_varint(len(nonzero)))

        # Store default as JSON
        db = json.dumps(default, separators=(",", ":")).encode("utf-8")
        buf.write(encode_varint(len(db)))
        buf.write(db)

        prev_idx = 0
        for idx, val in nonzero:
            # Delta-encode indices for better compression
            buf.write(encode_varint(idx - prev_idx))
            prev_idx = idx
            vb = json.dumps(val, separators=(",", ":")).encode("utf-8")
            buf.write(encode_varint(len(vb)))
            buf.write(vb)
        return buf.getvalue()

    @staticmethod
    def decode(data: bytes) -> list:
        off = 0
        length, off = decode_varint(data, off)
        num_nz, off = decode_varint(data, off)

        dlen, off = decode_varint(data, off)
        default = json.loads(data[off : off + dlen].decode("utf-8"))
        off += dlen

        result = [default] * length
        prev_idx = 0
        for _ in range(num_nz):
            delta, off = decode_varint(data, off)
            idx = prev_idx + delta
            prev_idx = idx
            vlen, off = decode_varint(data, off)
            result[idx] = json.loads(data[off : off + vlen].decode("utf-8"))
            off += vlen
        return result


# ---------------------------------------------------------------------------
# 15. QuantizedFloatEncoder - reduce float precision for dense packing
# ---------------------------------------------------------------------------

class QuantizedFloatEncoder:
    """
    Quantize floats to fewer bits for storage.  Supports 8-bit and 16-bit
    modes. Lossy but round-trips within quantization error.

    8-bit:  1 byte per float,  range mapped linearly to [0, 255]
    16-bit: 2 bytes per float, range mapped linearly to [0, 65535]

    Wire format: mode(1) + min_val(8, double) + max_val(8, double) +
                 varint(count) + packed_values
    """

    MODE_8 = 0
    MODE_16 = 1

    @classmethod
    def encode(cls, values: list[float], bits: int = 16) -> bytes:
        if not values:
            return bytes([cls.MODE_16]) + struct.pack("<dd", 0.0, 0.0) + encode_varint(0)

        mode = cls.MODE_8 if bits <= 8 else cls.MODE_16
        min_v = min(values)
        max_v = max(values)
        span = max_v - min_v if max_v != min_v else 1.0
        max_q = 255 if mode == cls.MODE_8 else 65535

        buf = BytesIO()
        buf.write(bytes([mode]))
        buf.write(struct.pack("<dd", min_v, max_v))
        buf.write(encode_varint(len(values)))

        if mode == cls.MODE_8:
            buf.write(bytes(
                min(max_q, max(0, round((v - min_v) / span * max_q))) for v in values
            ))
        else:
            for v in values:
                q = min(max_q, max(0, round((v - min_v) / span * max_q)))
                buf.write(struct.pack("<H", q))
        return buf.getvalue()

    @classmethod
    def decode(cls, data: bytes) -> list[float]:
        off = 0
        mode = data[off]; off += 1
        min_v, max_v = struct.unpack_from("<dd", data, off); off += 16
        count, off = decode_varint(data, off)
        if count == 0:
            return []

        span = max_v - min_v if max_v != min_v else 1.0
        max_q = 255 if mode == cls.MODE_8 else 65535

        result = []
        for _ in range(count):
            if mode == cls.MODE_8:
                q = data[off]; off += 1
            else:
                q = struct.unpack_from("<H", data, off)[0]; off += 2
            result.append(min_v + (q / max_q) * span)
        return result


# ---------------------------------------------------------------------------
# 16. FrequencyTable - build + apply byte-level frequency tables for text
# ---------------------------------------------------------------------------

class FrequencyTable:
    """
    Analyze text corpus to build a frequency-ranked symbol table.
    High-frequency tokens get shorter codes (1-byte), low-frequency get
    2-byte escape sequences.  Think simplified Huffman at token level.

    Encoding: top-127 tokens get codes 0x01-0x7F (1 byte each).
    Others get 0x00 (escape) + varint(original_index).
    The table itself is stored as header.
    """

    @classmethod
    def build(cls, corpus: list[str]) -> "FrequencyTable":
        counts = Counter(corpus)
        ranked = [tok for tok, _ in counts.most_common()]
        obj = cls.__new__(cls)
        obj.ranked = ranked
        obj.tok_to_code = {}
        obj.code_to_tok = {}
        for i, tok in enumerate(ranked[:127]):
            code = i + 1  # 1-127
            obj.tok_to_code[tok] = code
            obj.code_to_tok[code] = tok
        obj.overflow = {tok: i for i, tok in enumerate(ranked[127:])}
        obj.overflow_list = ranked[127:]
        return obj

    def encode(self, tokens: list[str]) -> bytes:
        buf = BytesIO()
        # Header: table size + entries
        buf.write(encode_varint(len(self.ranked)))
        for tok in self.ranked:
            tb = tok.encode("utf-8")
            buf.write(encode_varint(len(tb)))
            buf.write(tb)
        # Body: encoded token stream
        buf.write(encode_varint(len(tokens)))
        for tok in tokens:
            if tok in self.tok_to_code:
                buf.write(bytes([self.tok_to_code[tok]]))
            elif tok in self.overflow:
                buf.write(b"\x00")
                buf.write(encode_varint(self.overflow[tok]))
            else:
                # Unknown token: escape + inline
                buf.write(b"\x00")
                buf.write(encode_varint(len(self.overflow_list)))  # sentinel
                tb = tok.encode("utf-8")
                buf.write(encode_varint(len(tb)))
                buf.write(tb)
        return buf.getvalue()

    @classmethod
    def decode(cls, data: bytes) -> list[str]:
        off = 0
        table_size, off = decode_varint(data, off)
        ranked = []
        for _ in range(table_size):
            tlen, off = decode_varint(data, off)
            ranked.append(data[off : off + tlen].decode("utf-8"))
            off += tlen

        fast_lookup = {}
        for i, tok in enumerate(ranked[:127]):
            fast_lookup[i + 1] = tok
        overflow_list = ranked[127:]

        count, off = decode_varint(data, off)
        tokens = []
        for _ in range(count):
            b = data[off]; off += 1
            if b != 0:
                tokens.append(fast_lookup[b])
            else:
                idx, off = decode_varint(data, off)
                if idx < len(overflow_list):
                    tokens.append(overflow_list[idx])
                else:
                    # Inline unknown
                    tlen, off = decode_varint(data, off)
                    tokens.append(data[off : off + tlen].decode("utf-8"))
                    off += tlen
        return tokens


# ---------------------------------------------------------------------------
# 17. PipelineEncoder - chain multiple encoders for compound compression
# ---------------------------------------------------------------------------

class PipelineEncoder:
    """
    Compose encoders in sequence.  Each stage transforms data; the pipeline
    applies them left-to-right on encode, right-to-left on decode.

    Useful for e.g.: records -> CompactJSON -> UTF-8 bytes -> base85 text.
    """

    def __init__(self, stages: list[tuple[str, Any]]):
        """
        stages: list of (name, encoder) where encoder has .encode() / .decode()
                or is a callable pair (encode_fn, decode_fn).
        """
        self.stages = stages

    def encode(self, data: Any) -> Any:
        result = data
        for name, stage in self.stages:
            if hasattr(stage, "encode"):
                result = stage.encode(result) if not callable(stage) else stage.encode(result)
            else:
                enc_fn, _ = stage
                result = enc_fn(result)
        return result

    def decode(self, data: Any) -> Any:
        result = data
        for name, stage in reversed(self.stages):
            if hasattr(stage, "decode"):
                result = stage.decode(result) if not callable(stage) else stage.decode(result)
            else:
                _, dec_fn = stage
                result = dec_fn(result)
        return result

    def measure(self, original: Any) -> dict:
        """Run encode and measure size at each stage."""
        sizes = {}
        raw = json.dumps(original, separators=(",", ":")).encode("utf-8")
        sizes["raw_json"] = len(raw)
        current = original
        for name, stage in self.stages:
            if hasattr(stage, "encode"):
                current = stage.encode(current)
            else:
                enc_fn, _ = stage
                current = enc_fn(current)
            if isinstance(current, bytes):
                sizes[name] = len(current)
            elif isinstance(current, str):
                sizes[name] = len(current.encode("utf-8"))
        return sizes


# ---------------------------------------------------------------------------
# 18. BitmaskSet - encode set membership for known universes as bitmask
# ---------------------------------------------------------------------------

class BitmaskSet:
    """
    Given a fixed universe of items, encode any subset as a compact bitmask.
    Far denser than listing items when universe is small-to-medium (< 10K).

    Wire: varint(universe_size) + ceil(universe_size/8) bytes of bitmask.
    """

    def __init__(self, universe: list[str]):
        self.universe = list(universe)
        self.index = {item: i for i, item in enumerate(self.universe)}
        self.nbytes = (len(self.universe) + 7) // 8

    def encode(self, subset: set[str]) -> bytes:
        mask = bytearray(self.nbytes)
        for item in subset:
            if item in self.index:
                pos = self.index[item]
                mask[pos >> 3] |= 1 << (pos & 7)
        buf = BytesIO()
        buf.write(encode_varint(len(self.universe)))
        for item in self.universe:
            ib = item.encode("utf-8")
            buf.write(encode_varint(len(ib)))
            buf.write(ib)
        buf.write(bytes(mask))
        return buf.getvalue()

    @classmethod
    def decode(cls, data: bytes) -> tuple[list[str], set[str]]:
        off = 0
        usize, off = decode_varint(data, off)
        universe = []
        for _ in range(usize):
            ilen, off = decode_varint(data, off)
            universe.append(data[off : off + ilen].decode("utf-8"))
            off += ilen
        nbytes = (usize + 7) // 8
        mask = data[off : off + nbytes]
        subset = set()
        for i, item in enumerate(universe):
            if mask[i >> 3] & (1 << (i & 7)):
                subset.add(item)
        return universe, subset


# ---------------------------------------------------------------------------
# 19. StructDiff - encode only the differences between two structures
# ---------------------------------------------------------------------------

class StructDiff:
    """
    Encode the delta between two similar structures (old -> new).
    Only changed/added/removed fields are stored, dramatically reducing
    size for incremental state updates where most fields stay the same.

    Wire format (JSON):
      {"_set": {key: new_val, ...}, "_del": [removed_keys], "_nest": {key: sub_diff}}

    For lists: stores full replacement (structural list diffing is expensive
    and fragile); use StructDiff on individual records instead.
    """

    @classmethod
    def diff(cls, old: Any, new: Any) -> Any:
        """Compute minimal diff from old to new."""
        if type(old) != type(new):
            return {"_replace": new}

        if isinstance(old, dict) and isinstance(new, dict):
            result: dict[str, Any] = {}
            set_fields: dict[str, Any] = {}
            del_keys: list[str] = []
            nest_diffs: dict[str, Any] = {}

            all_keys = set(old.keys()) | set(new.keys())
            for k in all_keys:
                if k not in new:
                    del_keys.append(k)
                elif k not in old:
                    set_fields[k] = new[k]
                elif old[k] != new[k]:
                    if isinstance(old[k], dict) and isinstance(new[k], dict):
                        sub = cls.diff(old[k], new[k])
                        if sub:
                            nest_diffs[k] = sub
                    else:
                        set_fields[k] = new[k]

            if set_fields:
                result["_set"] = set_fields
            if del_keys:
                result["_del"] = del_keys
            if nest_diffs:
                result["_nest"] = nest_diffs
            return result

        if old == new:
            return {}
        return {"_replace": new}

    @classmethod
    def apply(cls, old: Any, diff: Any) -> Any:
        """Apply a diff to reconstruct the new value."""
        if not diff:
            return old
        if "_replace" in diff:
            return diff["_replace"]

        if not isinstance(old, dict):
            return old

        result = dict(old)
        if "_del" in diff:
            for k in diff["_del"]:
                result.pop(k, None)
        if "_set" in diff:
            result.update(diff["_set"])
        if "_nest" in diff:
            for k, sub in diff["_nest"].items():
                if k in result:
                    result[k] = cls.apply(result[k], sub)
        return result

    @classmethod
    def encode(cls, old: Any, new: Any) -> str:
        """Compute diff and return as compact packed string."""
        d = cls.diff(old, new)
        return pack_dense(d)

    @classmethod
    def decode_and_apply(cls, old: Any, encoded_diff: str) -> Any:
        """Decode a packed diff and apply it to old."""
        d = unpack_dense(encoded_diff)
        return cls.apply(old, d)


# ---------------------------------------------------------------------------
# 20. AdaptiveCodebook - cross-payload string interning with evolving vocab
# ---------------------------------------------------------------------------

class AdaptiveCodebook:
    """
    Maintain a shared codebook that grows as new payloads are encoded.
    Strings seen in prior messages get short codes; new strings are added
    automatically.  Each encoded message carries only new vocab entries,
    so the marginal cost of repeated strings approaches zero.

    Usage:
        cb = AdaptiveCodebook()
        enc1 = cb.encode(msg1)   # full vocab emitted
        enc2 = cb.encode(msg2)   # only new strings added to vocab
        # Decoder side:
        cb2 = AdaptiveCodebook()
        dec1 = cb2.decode(enc1)
        dec2 = cb2.decode(enc2)
    """

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}
        self._reverse: list[str] = []

    def _collect(self, obj: Any, new_strings: list[str]) -> None:
        if isinstance(obj, str):
            if obj not in self._vocab:
                self._vocab[obj] = len(self._reverse)
                self._reverse.append(obj)
                new_strings.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._collect(k, new_strings)
                self._collect(v, new_strings)
        elif isinstance(obj, list):
            for item in obj:
                self._collect(item, new_strings)

    def _write(self, obj: Any, buf: BytesIO) -> None:
        if obj is None:
            buf.write(b"\x00")
        elif isinstance(obj, bool):
            buf.write(b"\x01" if obj else b"\x02")
        elif isinstance(obj, int):
            buf.write(b"\x03")
            buf.write(encode_varint(zigzag_encode(obj)))
        elif isinstance(obj, float):
            buf.write(b"\x04")
            buf.write(struct.pack("<d", obj))
        elif isinstance(obj, str):
            buf.write(b"\x05")
            buf.write(encode_varint(self._vocab[obj]))
        elif isinstance(obj, list):
            buf.write(b"\x06")
            buf.write(encode_varint(len(obj)))
            for item in obj:
                self._write(item, buf)
        elif isinstance(obj, dict):
            buf.write(b"\x07")
            buf.write(encode_varint(len(obj)))
            for k, v in obj.items():
                buf.write(encode_varint(self._vocab[str(k)]))
                self._write(v, buf)
        else:
            self._write(str(obj), buf)

    def encode(self, obj: Any) -> bytes:
        """Encode object, emitting only new vocab entries."""
        new_strings: list[str] = []
        self._collect(obj, new_strings)

        buf = BytesIO()
        # Header: number of new vocab entries
        buf.write(encode_varint(len(new_strings)))
        for s in new_strings:
            sb = s.encode("utf-8")
            buf.write(encode_varint(len(sb)))
            buf.write(sb)
        # Payload
        self._write(obj, buf)
        return buf.getvalue()

    def _read(self, data: bytes, off: int) -> tuple[Any, int]:
        tag = data[off]; off += 1
        if tag == 0x00:
            return None, off
        elif tag == 0x01:
            return True, off
        elif tag == 0x02:
            return False, off
        elif tag == 0x03:
            zz, off = decode_varint(data, off)
            return zigzag_decode(zz), off
        elif tag == 0x04:
            return struct.unpack_from("<d", data, off)[0], off + 8
        elif tag == 0x05:
            idx, off = decode_varint(data, off)
            return self._reverse[idx], off
        elif tag == 0x06:
            count, off = decode_varint(data, off)
            items = []
            for _ in range(count):
                item, off = self._read(data, off)
                items.append(item)
            return items, off
        elif tag == 0x07:
            count, off = decode_varint(data, off)
            d: dict = {}
            for _ in range(count):
                kidx, off = decode_varint(data, off)
                v, off = self._read(data, off)
                d[self._reverse[kidx]] = v
            return d, off
        else:
            raise ValueError(f"Unknown AdaptiveCodebook tag: {tag}")

    def decode(self, data: bytes) -> Any:
        """Decode object, absorbing any new vocab entries."""
        off = 0
        n_new, off = decode_varint(data, off)
        for _ in range(n_new):
            slen, off = decode_varint(data, off)
            s = data[off:off + slen].decode("utf-8")
            off += slen
            if s not in self._vocab:
                self._vocab[s] = len(self._reverse)
                self._reverse.append(s)
        val, _ = self._read(data, off)
        return val


# ---------------------------------------------------------------------------
# 21. TokenBudgetAllocator - split a token budget across multiple sources
# ---------------------------------------------------------------------------

class TokenBudgetAllocator:
    """
    Given multiple named data sources and a total token budget, allocate
    tokens proportionally based on each source's information density and
    priority weight.  Returns packed representations for each source that
    collectively fit within the budget.

    Useful for constructing LLM prompts that combine context from several
    subsystems (logs, state, config, history) under a single token limit.
    """

    def __init__(self, total_tokens: int, chars_per_token: float = 4.0):
        self.total_tokens = total_tokens
        self.chars_per_token = chars_per_token

    def allocate(
        self,
        sources: dict[str, Any],
        weights: Optional[dict[str, float]] = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Allocate budget across sources.

        Returns dict of {name: {"packed": str, "tokens": int, "included": bool}}.
        """
        if not sources:
            return {}

        w = weights or {}
        default_weight = 1.0
        total_weight = sum(w.get(k, default_weight) for k in sources)
        total_chars = int(self.total_tokens * self.chars_per_token)

        # Phase 1: estimate each source's packed size
        estimates: dict[str, tuple[str, int]] = {}
        for name, data in sources.items():
            packed = pack_dense(data)
            estimates[name] = (packed, len(packed))

        # Phase 2: allocate chars proportionally, then trim
        allocations: dict[str, int] = {}
        for name in sources:
            share = w.get(name, default_weight) / total_weight
            allocations[name] = int(total_chars * share)

        # Phase 3: if a source needs fewer chars than allocated, redistribute
        surplus = 0
        needs_more: list[str] = []
        for name in sources:
            packed_len = estimates[name][1]
            if packed_len <= allocations[name]:
                surplus += allocations[name] - packed_len
                allocations[name] = packed_len
            else:
                needs_more.append(name)

        if needs_more and surplus > 0:
            extra_each = surplus // len(needs_more)
            for name in needs_more:
                allocations[name] += extra_each

        # Phase 4: build results
        result: dict[str, dict[str, Any]] = {}
        total_used = 0
        for name in sources:
            packed, packed_len = estimates[name]
            fits = packed_len <= allocations[name]
            if fits:
                tokens = math.ceil(packed_len / self.chars_per_token)
                result[name] = {
                    "packed": packed,
                    "tokens": tokens,
                    "chars": packed_len,
                    "included": True,
                }
                total_used += tokens
            else:
                # Try to fit a truncated version (for lists)
                data = sources[name]
                if isinstance(data, list) and len(data) > 1:
                    # Binary search for max items
                    lo, hi = 1, len(data)
                    best_packed = pack_dense([])
                    best_n = 0
                    while lo <= hi:
                        mid = (lo + hi) // 2
                        trial = pack_dense(data[:mid])
                        if len(trial) <= allocations[name]:
                            best_packed = trial
                            best_n = mid
                            lo = mid + 1
                        else:
                            hi = mid - 1
                    tokens = math.ceil(len(best_packed) / self.chars_per_token)
                    result[name] = {
                        "packed": best_packed,
                        "tokens": tokens,
                        "chars": len(best_packed),
                        "included": True,
                        "truncated_to": best_n,
                        "original_count": len(data),
                    }
                    total_used += tokens
                else:
                    result[name] = {
                        "packed": packed,
                        "tokens": math.ceil(packed_len / self.chars_per_token),
                        "chars": packed_len,
                        "included": False,
                        "reason": "exceeds_allocation",
                    }

        return result


# ---------------------------------------------------------------------------
# 22. IncrementalDigest - rolling hash summary for change detection
# ---------------------------------------------------------------------------

class IncrementalDigest:
    """
    Maintain a compact rolling digest of a data stream.  Each update
    produces a short fingerprint; comparing fingerprints detects changes
    without storing or transmitting the full data.

    Useful for "has anything changed since last check?" queries that
    cost 0 tokens when nothing changed.
    """

    def __init__(self) -> None:
        self._state = hashlib.sha256()
        self._count = 0
        self._snapshots: dict[str, str] = {}

    def update(self, label: str, data: Any) -> str:
        """Hash data under label, return 12-char hex fingerprint."""
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        h = hashlib.sha256(raw).hexdigest()[:12]
        self._snapshots[label] = h
        self._state.update(raw)
        self._count += 1
        return h

    def changed(self, label: str, data: Any) -> bool:
        """Return True if data differs from last snapshot for this label."""
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        h = hashlib.sha256(raw).hexdigest()[:12]
        prev = self._snapshots.get(label)
        return prev is None or prev != h

    def global_fingerprint(self) -> str:
        """Return digest of all updates so far."""
        return self._state.hexdigest()[:16]

    @property
    def count(self) -> int:
        return self._count

    def snapshot(self) -> dict[str, str]:
        """Return all current label fingerprints."""
        return dict(self._snapshots)


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

    # --- SparseEncoder ---
    sparse_data = [0] * 1000
    for i in [3, 17, 42, 100, 555, 999]:
        sparse_data[i] = i * 10
    sparse_enc = SparseEncoder.encode(sparse_data)
    sparse_dec = SparseEncoder.decode(sparse_enc)
    assert sparse_dec == sparse_data, "SparseEncoder roundtrip failed"
    raw_sparse = json.dumps(sparse_data, separators=(",", ":")).encode()
    assert len(sparse_enc) < len(raw_sparse) * 0.1, (
        f"SparseEncoder not dense enough: {len(sparse_enc)} vs {len(raw_sparse)}"
    )
    print(f"[SparseEncoder] passed  ({len(sparse_enc)} vs {len(raw_sparse)} raw JSON bytes)")

    # SparseEncoder with string default
    sparse_str = ["none"] * 200
    sparse_str[5] = "active"
    sparse_str[50] = "error"
    sparse_str[199] = "done"
    sparse_str_enc = SparseEncoder.encode(sparse_str, default="none")
    sparse_str_dec = SparseEncoder.decode(sparse_str_enc)
    assert sparse_str_dec == sparse_str
    print("[SparseEncoder strings] passed")

    # SparseEncoder empty
    assert SparseEncoder.decode(SparseEncoder.encode([])) == []
    print("[SparseEncoder empty] passed")

    # --- QuantizedFloatEncoder ---
    floats_16 = [i * 0.001 for i in range(1000)]
    qf_enc = QuantizedFloatEncoder.encode(floats_16, bits=16)
    qf_dec = QuantizedFloatEncoder.decode(qf_enc)
    assert len(qf_dec) == len(floats_16)
    max_err_16 = max(abs(a - b) for a, b in zip(floats_16, qf_dec))
    assert max_err_16 < 0.001, f"16-bit quantization error too high: {max_err_16}"
    raw_floats = json.dumps(floats_16, separators=(",", ":")).encode()
    assert len(qf_enc) < len(raw_floats) * 0.4, (
        f"QuantizedFloat 16-bit not dense: {len(qf_enc)} vs {len(raw_floats)}"
    )
    print(f"[QuantizedFloat 16-bit] passed  ({len(qf_enc)} vs {len(raw_floats)} bytes, "
          f"max_err={max_err_16:.6f})")

    # 8-bit mode
    qf8_enc = QuantizedFloatEncoder.encode(floats_16, bits=8)
    qf8_dec = QuantizedFloatEncoder.decode(qf8_enc)
    max_err_8 = max(abs(a - b) for a, b in zip(floats_16, qf8_dec))
    assert max_err_8 < 0.005, f"8-bit quantization error too high: {max_err_8}"
    assert len(qf8_enc) < len(qf_enc), "8-bit should be smaller than 16-bit"
    print(f"[QuantizedFloat 8-bit] passed  ({len(qf8_enc)} bytes, max_err={max_err_8:.6f})")

    # Empty
    assert QuantizedFloatEncoder.decode(QuantizedFloatEncoder.encode([])) == []
    print("[QuantizedFloat empty] passed")

    # --- FrequencyTable ---
    token_corpus = (
        ["GET", "POST", "GET", "GET", "DELETE"] * 200
        + ["PATCH", "OPTIONS"] * 20
        + ["TRACE"] * 5
    )
    ft = FrequencyTable.build(token_corpus)
    ft_enc = ft.encode(token_corpus)
    ft_dec = FrequencyTable.decode(ft_enc)
    assert ft_dec == token_corpus, "FrequencyTable roundtrip failed"
    raw_ft = json.dumps(token_corpus, separators=(",", ":")).encode()
    assert len(ft_enc) < len(raw_ft) * 0.3, (
        f"FrequencyTable not dense: {len(ft_enc)} vs {len(raw_ft)}"
    )
    print(f"[FrequencyTable] passed  ({len(ft_enc)} vs {len(raw_ft)} raw JSON bytes)")

    # FrequencyTable with unknown tokens at decode time
    ft_with_unknown = ft.encode(["GET", "UNKNOWN_METHOD", "POST"])
    ft_dec_unk = FrequencyTable.decode(ft_with_unknown)
    assert ft_dec_unk == ["GET", "UNKNOWN_METHOD", "POST"]
    print("[FrequencyTable unknown tokens] passed")

    # --- PipelineEncoder ---
    pipeline = PipelineEncoder([
        ("compact_json", CompactJSON),
        ("utf8", (lambda s: s.encode("utf-8"), lambda b: b.decode("utf-8"))),
        ("base85", (to_text, from_text)),
    ])
    pipe_records = [
        {"method": "GET", "status": 200, "path": f"/api/item/{i}"}
        for i in range(50)
    ]
    pipe_enc = pipeline.encode(pipe_records)
    pipe_dec = pipeline.decode(pipe_enc)
    assert pipe_dec == pipe_records, "PipelineEncoder roundtrip failed"
    assert isinstance(pipe_enc, str), "Pipeline should output text (base85)"
    pipe_sizes = pipeline.measure(pipe_records)
    assert pipe_sizes["base85"] < pipe_sizes["raw_json"]
    print(f"[PipelineEncoder] passed  (raw={pipe_sizes['raw_json']}B -> "
          f"compact={pipe_sizes.get('compact_json', '?')} -> "
          f"base85={pipe_sizes['base85']}B)")

    # --- BitmaskSet ---
    all_agents = [f"agent_{i}" for i in range(64)]
    bm = BitmaskSet(all_agents)
    active = {"agent_0", "agent_7", "agent_15", "agent_63"}
    bm_enc = bm.encode(active)
    _, bm_dec = BitmaskSet.decode(bm_enc)
    assert bm_dec == active, f"BitmaskSet roundtrip failed: {bm_dec} != {active}"
    raw_active = json.dumps(sorted(active), separators=(",", ":")).encode()
    # The bitmask includes the universe, so compare against listing the full set
    raw_universe_and_set = json.dumps(
        {"universe": all_agents, "active": sorted(active)}, separators=(",", ":")
    ).encode()
    assert len(bm_enc) < len(raw_universe_and_set)
    print(f"[BitmaskSet] passed  ({len(bm_enc)} vs {len(raw_universe_and_set)} bytes)")

    # BitmaskSet empty subset
    _, empty_dec = BitmaskSet.decode(bm.encode(set()))
    assert empty_dec == set()
    print("[BitmaskSet empty subset] passed")

    # BitmaskSet full subset
    _, full_dec = BitmaskSet.decode(bm.encode(set(all_agents)))
    assert full_dec == set(all_agents)
    print("[BitmaskSet full subset] passed")

    # --- StructDiff ---
    old_state = {
        "agent": "executor",
        "status": "running",
        "tasks_done": 42,
        "config": {"retries": 3, "timeout": 60, "model": "local-v7"},
        "tags": ["critical", "pipeline"],
    }
    new_state = {
        "agent": "executor",
        "status": "idle",           # changed
        "tasks_done": 43,           # changed
        "config": {"retries": 3, "timeout": 120, "model": "local-v7"},  # timeout changed
        "tags": ["critical", "pipeline"],
        "last_error": None,         # added
    }
    diff = StructDiff.diff(old_state, new_state)
    assert "_set" in diff
    assert diff["_set"]["status"] == "idle"
    assert diff["_set"]["tasks_done"] == 43
    assert "_nest" in diff
    assert diff["_nest"]["config"]["_set"]["timeout"] == 120
    reconstructed = StructDiff.apply(old_state, diff)
    assert reconstructed == new_state, f"StructDiff apply failed: {reconstructed}"

    # Packed diff should be much smaller than full new_state
    diff_packed = StructDiff.encode(old_state, new_state)
    full_packed = pack_dense(new_state)
    assert len(diff_packed) < len(full_packed), (
        f"Diff ({len(diff_packed)}) should be smaller than full ({len(full_packed)})"
    )
    reconstructed2 = StructDiff.decode_and_apply(old_state, diff_packed)
    assert reconstructed2 == new_state
    print(f"[StructDiff] passed  (diff={len(diff_packed)} vs full={len(full_packed)} chars)")

    # StructDiff with no changes
    no_diff = StructDiff.diff(old_state, old_state)
    assert no_diff == {}, f"Expected empty diff, got {no_diff}"
    assert StructDiff.apply(old_state, no_diff) == old_state
    print("[StructDiff no changes] passed")

    # StructDiff with deletions
    old_with_extra = {"a": 1, "b": 2, "c": 3}
    new_without_b = {"a": 1, "c": 4}
    del_diff = StructDiff.diff(old_with_extra, new_without_b)
    assert "b" in del_diff["_del"]
    assert del_diff["_set"]["c"] == 4
    assert StructDiff.apply(old_with_extra, del_diff) == new_without_b
    print("[StructDiff deletions] passed")

    # StructDiff type change
    type_diff = StructDiff.diff({"x": 1}, {"x": "one"})
    assert StructDiff.apply({"x": 1}, type_diff) == {"x": "one"}
    print("[StructDiff type change] passed")

    # --- AdaptiveCodebook ---
    cb_enc = AdaptiveCodebook()
    cb_dec = AdaptiveCodebook()

    msg1 = {"role": "executor", "status": "running", "task": "build", "ts": 1000}
    msg2 = {"role": "executor", "status": "idle", "task": "deploy", "ts": 1001}
    msg3 = {"role": "planner", "status": "running", "task": "build", "ts": 1002}

    enc1 = cb_enc.encode(msg1)
    enc2 = cb_enc.encode(msg2)
    enc3 = cb_enc.encode(msg3)

    # Second message should be smaller (shared strings already in vocab)
    assert len(enc2) < len(enc1), (
        f"Second encode should be smaller: {len(enc2)} vs {len(enc1)}"
    )
    # Third message even smaller (most strings already known)
    assert len(enc3) <= len(enc2), (
        f"Third encode should be <= second: {len(enc3)} vs {len(enc2)}"
    )

    dec1 = cb_dec.decode(enc1)
    dec2 = cb_dec.decode(enc2)
    dec3 = cb_dec.decode(enc3)

    assert dec1 == msg1, f"AdaptiveCodebook msg1 failed: {dec1}"
    assert dec2 == msg2, f"AdaptiveCodebook msg2 failed: {dec2}"
    assert dec3 == msg3, f"AdaptiveCodebook msg3 failed: {dec3}"
    print(f"[AdaptiveCodebook] passed  (sizes: {len(enc1)}, {len(enc2)}, {len(enc3)} bytes)")

    # AdaptiveCodebook with nested data
    cb_nest_enc = AdaptiveCodebook()
    cb_nest_dec = AdaptiveCodebook()
    nested_msg = {"agents": [{"name": "exec", "ok": True}, {"name": "plan", "ok": False}]}
    ne = cb_nest_enc.encode(nested_msg)
    nd = cb_nest_dec.decode(ne)
    assert nd == nested_msg
    print("[AdaptiveCodebook nested] passed")

    # AdaptiveCodebook with None and floats
    cb_mixed_enc = AdaptiveCodebook()
    cb_mixed_dec = AdaptiveCodebook()
    mixed_msg = {"val": None, "score": 3.14, "count": -7, "ok": True}
    me = cb_mixed_enc.encode(mixed_msg)
    md = cb_mixed_dec.decode(me)
    assert md["val"] is None
    assert abs(md["score"] - 3.14) < 1e-10
    assert md["count"] == -7
    assert md["ok"] is True
    print("[AdaptiveCodebook mixed types] passed")

    # --- TokenBudgetAllocator ---
    allocator = TokenBudgetAllocator(total_tokens=200)
    alloc_sources = {
        "logs": [{"ts": 1000 + i, "msg": f"event_{i}"} for i in range(50)],
        "state": {"agent": "executor", "status": "running", "score": 85},
        "config": {"retries": 3, "timeout": 60, "model": "local-v7"},
    }
    alloc_result = allocator.allocate(alloc_sources, weights={"logs": 3, "state": 1, "config": 1})
    assert "logs" in alloc_result
    assert "state" in alloc_result
    assert "config" in alloc_result

    total_tokens_used = sum(v["tokens"] for v in alloc_result.values() if v.get("included"))
    assert total_tokens_used <= 200, f"Budget exceeded: {total_tokens_used} > 200"

    # State and config should be included (small enough)
    assert alloc_result["state"]["included"], "State should be included"
    assert alloc_result["config"]["included"], "Config should be included"
    print(f"[TokenBudgetAllocator] passed  (total={total_tokens_used} tokens)")

    # Verify packed data can be unpacked
    for name, info in alloc_result.items():
        if info.get("included"):
            decoded = unpack_dense(info["packed"])
            if name == "state":
                assert decoded == alloc_sources["state"]
            elif name == "config":
                assert decoded == alloc_sources["config"]
    print("[TokenBudgetAllocator round-trip] passed")

    # Large budget should include everything
    big_alloc = TokenBudgetAllocator(total_tokens=10000)
    big_result = big_alloc.allocate(alloc_sources)
    for name, info in big_result.items():
        assert info["included"], f"Large budget should include {name}"
    print("[TokenBudgetAllocator large budget] passed")

    # Empty sources
    empty_alloc = allocator.allocate({})
    assert empty_alloc == {}
    print("[TokenBudgetAllocator empty] passed")

    # --- IncrementalDigest ---
    digest = IncrementalDigest()
    fp1 = digest.update("state", {"status": "running", "count": 42})
    assert len(fp1) == 12
    assert digest.count == 1

    fp2 = digest.update("config", {"retries": 3})
    assert len(fp2) == 12
    assert digest.count == 2
    assert fp1 != fp2

    # Same data, same fingerprint
    fp1b = digest.update("state", {"status": "running", "count": 42})
    assert fp1b == fp1, "Same data should produce same fingerprint"

    # changed() detection
    assert not digest.changed("state", {"status": "running", "count": 42})
    assert digest.changed("state", {"status": "idle", "count": 42})
    assert digest.changed("unknown_label", {"anything": True})

    # Global fingerprint
    gfp = digest.global_fingerprint()
    assert len(gfp) == 16
    print(f"[IncrementalDigest] passed  (global={gfp})")

    # Snapshot
    snap = digest.snapshot()
    assert "state" in snap and "config" in snap
    print("[IncrementalDigest snapshot] passed")

    # --- SymbolTable ---
    sym_data = {
        "agents": [
            {"name": "executor", "status": "running", "task": "build"},
            {"name": "planner", "status": "idle", "task": "none"},
            {"name": "executor", "status": "error", "task": "deploy"},
            {"name": "monitor", "status": "running", "task": "watch"},
        ],
        "active_agent": "executor",
        "fallback_agent": "planner",
        "last_status": "running",
    }
    sym_enc = SymbolTable.encode(sym_data)
    sym_dec = SymbolTable.decode(sym_enc)
    assert sym_dec == sym_data, f"SymbolTable roundtrip failed: {sym_dec}"
    raw_sym = json.dumps(sym_data, separators=(",", ":")).encode()
    sym_savings = (1 - len(sym_enc) / len(raw_sym)) * 100
    assert sym_savings > 20, f"SymbolTable savings too low: {sym_savings:.1f}%"
    print(f"[SymbolTable] passed  ({len(sym_enc)} vs {len(raw_sym)} bytes, "
          f"{sym_savings:.1f}% saved)")

    # SymbolTable with scalars
    assert SymbolTable.decode(SymbolTable.encode(42)) == 42
    assert SymbolTable.decode(SymbolTable.encode(None)) is None
    assert SymbolTable.decode(SymbolTable.encode(True)) is True
    assert SymbolTable.decode(SymbolTable.encode("hello")) == "hello"
    assert abs(SymbolTable.decode(SymbolTable.encode(3.14)) - 3.14) < 1e-10
    print("[SymbolTable scalars] passed")

    # SymbolTable with repeated strings across nested structure
    deep = {"a": ["x", "y", "x"], "b": {"c": "x", "d": "y"}, "e": "x"}
    assert SymbolTable.decode(SymbolTable.encode(deep)) == deep
    print("[SymbolTable nested dedup] passed")

    # --- MultiCodecSelector ---
    # Should pick best strategy automatically
    mc_ints = list(range(500))
    mc_enc = MultiCodecSelector.encode(mc_ints)
    mc_dec = MultiCodecSelector.decode(mc_enc)
    assert mc_dec == mc_ints, "MultiCodec ints roundtrip failed"
    assert mc_enc[0] == MultiCodecSelector.TAG_DELTA, "Should pick delta for sequential ints"
    print(f"[MultiCodecSelector -> delta] passed  tag={mc_enc[0]}")

    mc_strs = ["error", "warn", "info"] * 500
    mc_str_enc = MultiCodecSelector.encode(mc_strs)
    mc_str_dec = MultiCodecSelector.decode(mc_str_enc)
    assert mc_str_dec == mc_strs
    print(f"[MultiCodecSelector -> dict/rle] passed  tag={mc_str_enc[0]}")

    mc_records = [
        {"ts": 1000 + i, "level": "info", "agent": "exec"}
        for i in range(100)
    ]
    mc_rec_enc = MultiCodecSelector.encode(mc_records)
    mc_rec_dec = MultiCodecSelector.decode(mc_rec_enc)
    assert len(mc_rec_dec) == 100
    for orig, dec in zip(mc_records, mc_rec_dec):
        assert orig["ts"] == dec["ts"]
        assert orig["level"] == dec["level"]
    print(f"[MultiCodecSelector -> columnar/symbol] passed  tag={mc_rec_enc[0]}")

    # Sparse data should pick sparse encoding
    mc_sparse = [0] * 500
    mc_sparse[10] = 42
    mc_sparse[200] = 99
    mc_sp_enc = MultiCodecSelector.encode(mc_sparse)
    mc_sp_dec = MultiCodecSelector.decode(mc_sp_enc)
    assert mc_sp_dec == mc_sparse
    print(f"[MultiCodecSelector sparse] passed  tag={mc_sp_enc[0]}")

    # Scalar fallback
    mc_scalar = {"key": "value", "n": 42}
    mc_sc_enc = MultiCodecSelector.encode(mc_scalar)
    mc_sc_dec = MultiCodecSelector.decode(mc_sc_enc)
    assert mc_sc_dec == mc_scalar
    print(f"[MultiCodecSelector scalar] passed  tag={mc_sc_enc[0]}")

    # --- pack_dense / unpack_dense ---
    assert unpack_dense(pack_dense(42)) == 42
    assert unpack_dense(pack_dense("hello")) == "hello"
    assert unpack_dense(pack_dense(None)) is None
    assert unpack_dense(pack_dense(mc_ints)) == mc_ints
    assert unpack_dense(pack_dense(mc_strs)) == mc_strs

    dense_events = [
        {"ts": 1000000 + i, "level": ["info", "warn", "error"][i % 3],
         "latency": 0.5 + i * 0.01, "agent": "executor"}
        for i in range(200)
    ]
    dense_packed = pack_dense(dense_events)
    dense_unpacked = unpack_dense(dense_packed)
    assert len(dense_unpacked) == 200
    for orig, dec in zip(dense_events, dense_unpacked):
        assert orig["ts"] == dec["ts"]
        assert orig["level"] == dec["level"]
        assert abs(orig["latency"] - dec["latency"]) < 1e-10
    raw_dense = json.dumps(dense_events, separators=(",", ":"))
    dense_ratio = len(dense_packed) / len(raw_dense)
    assert dense_ratio < 0.5, f"pack_dense ratio too high: {dense_ratio:.2f}"
    print(f"[pack_dense] passed  ({len(dense_packed)} chars vs {len(raw_dense)} JSON chars, "
          f"ratio={dense_ratio:.2f})")

    # --- density_compare ---
    dc = density_compare(dense_events)
    assert dc["pack_dense_tokens"] < dc["raw_json_tokens"]
    assert dc["token_savings_pct"] > 40
    print(f"[density_compare] passed  {dc['raw_json_tokens']} tok -> "
          f"{dc['pack_dense_tokens']} tok  ({dc['token_savings_pct']}% saved)")

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
        ("1000 sparse ints (6 nonzero)", sparse_data, sparse_enc),
        ("1000 floats (16-bit quant)", floats_16, qf_enc),
        ("1000 floats (8-bit quant)", floats_16, qf8_enc),
        ("1045 HTTP methods (freq table)", token_corpus, ft_enc),
        ("64 agents bitmask (4 active)", sorted(active), bm_enc),
        ("nested agent state (symbol table)", sym_data, sym_enc),
    ]
    for label, orig, enc in test_cases:
        r = density_report(orig, enc)
        print(f"  {label:40s}  {r['raw_json_bytes']:>6d}B -> {r['encoded_bytes']:>5d}B  "
              f"({r['savings_pct']:5.1f}% saved)")

    # pack_dense summary
    print("\n=== pack_dense (best-of + zlib + base85) ===")
    dense_cases: list[tuple[str, Any]] = [
        ("200 events", dense_events),
        ("500 sequential ints", mc_ints),
        ("1500 status strings", mc_strs),
        ("500 sparse ints (2 nonzero)", mc_sparse),
        ("nested agent state", sym_data),
    ]
    for label, data in dense_cases:
        dc = density_compare(data)
        print(f"  {label:40s}  {dc['raw_json_tokens']:>5d} tok -> "
              f"{dc['pack_dense_tokens']:>4d} tok  "
              f"({dc['token_savings_pct']:5.1f}% saved)")

    print("\nAll assertions passed.")
