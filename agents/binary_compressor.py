#!/usr/bin/env python3
"""
binary_compressor.py — Lossless Binary Text Compression (LZ4 + zstd)
=====================================================================
Compress token strings for transmission/storage using LZ4 (fast) or
zstd (high ratio). All operations are lossless — decompressed output
is byte-identical to the original.

Key functions:
  - compress_text(text, algorithm="zstd", level=3) -> bytes
  - decompress_text(data, algorithm="zstd") -> str
  - auto_compress(text) -> CompressedPayload
  - batch_compress(texts, algorithm="zstd") -> list[CompressedPayload]
  - compress_tokens(tokens, algorithm="zstd") -> CompressedPayload

CompressedPayload is a dataclass holding compressed bytes + metadata
(algorithm, original size, compressed size, ratio).
"""

import json
import struct
import time
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Union

import lz4.frame
import zstandard as zstd


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Algorithm = Literal["lz4", "zstd"]

HEADER_MAGIC = b"TXTC"  # 4-byte magic for serialized payloads
HEADER_VERSION = 1
# Header layout: MAGIC(4) + VERSION(1) + ALGO(1) + ORIG_SIZE(4) + COMP_SIZE(4) = 14 bytes
HEADER_FMT = "!4sBBII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

ALGO_ID = {"lz4": 0, "zstd": 1}
ID_ALGO = {v: k for k, v in ALGO_ID.items()}


@dataclass
class CompressedPayload:
    """Container for compressed text with metadata."""

    data: bytes
    algorithm: Algorithm
    original_size: int
    compressed_size: int
    ratio: float  # compressed / original (lower is better)
    compression_time_ms: float = 0.0

    @property
    def savings_pct(self) -> float:
        """Percentage of bytes saved."""
        return round((1.0 - self.ratio) * 100, 2)

    def serialize(self) -> bytes:
        """Serialize payload to a self-describing binary format with header."""
        header = struct.pack(
            HEADER_FMT,
            HEADER_MAGIC,
            HEADER_VERSION,
            ALGO_ID[self.algorithm],
            self.original_size,
            len(self.data),
        )
        return header + self.data

    @classmethod
    def deserialize(cls, raw: bytes) -> "CompressedPayload":
        """Reconstruct a CompressedPayload from serialized bytes."""
        if len(raw) < HEADER_SIZE:
            raise ValueError(f"Data too short for header ({len(raw)} < {HEADER_SIZE})")
        magic, version, algo_id, orig_size, comp_size = struct.unpack(
            HEADER_FMT, raw[:HEADER_SIZE]
        )
        if magic != HEADER_MAGIC:
            raise ValueError(f"Invalid magic bytes: {magic!r}")
        if version != HEADER_VERSION:
            raise ValueError(f"Unsupported version: {version}")
        if algo_id not in ID_ALGO:
            raise ValueError(f"Unknown algorithm ID: {algo_id}")
        data = raw[HEADER_SIZE : HEADER_SIZE + comp_size]
        if len(data) != comp_size:
            raise ValueError(
                f"Truncated data: expected {comp_size}, got {len(data)}"
            )
        algorithm = ID_ALGO[algo_id]
        ratio = comp_size / orig_size if orig_size > 0 else 0.0
        return cls(
            data=data,
            algorithm=algorithm,
            original_size=orig_size,
            compressed_size=comp_size,
            ratio=round(ratio, 4),
        )


# ---------------------------------------------------------------------------
# Core compression / decompression
# ---------------------------------------------------------------------------


def compress_text(
    text: str,
    algorithm: Algorithm = "zstd",
    level: int = 3,
) -> bytes:
    """Compress a UTF-8 text string to bytes using the chosen algorithm.

    Args:
        text: Input text.
        algorithm: "lz4" or "zstd".
        level: Compression level (lz4: 0-16, zstd: 1-22).

    Returns:
        Compressed bytes.
    """
    raw = text.encode("utf-8")
    if algorithm == "lz4":
        return lz4.frame.compress(raw, compression_level=level)
    elif algorithm == "zstd":
        cctx = zstd.ZstdCompressor(level=level)
        return cctx.compress(raw)
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm!r}")


def decompress_text(
    data: bytes,
    algorithm: Algorithm = "zstd",
) -> str:
    """Decompress bytes back to a UTF-8 text string.

    Args:
        data: Compressed bytes.
        algorithm: Algorithm used during compression.

    Returns:
        Original text.
    """
    if algorithm == "lz4":
        raw = lz4.frame.decompress(data)
    elif algorithm == "zstd":
        dctx = zstd.ZstdDecompressor()
        raw = dctx.decompress(data, max_output_size=128 * 1024 * 1024)  # 128 MB cap
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm!r}")
    return raw.decode("utf-8")


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------


def auto_compress(
    text: str,
    level: int = 3,
    size_threshold: int = 64,
) -> CompressedPayload:
    """Compress text with the best algorithm (tries both, picks smaller).

    Texts shorter than `size_threshold` bytes are stored uncompressed under
    the "lz4" tag since compression overhead exceeds savings.

    Args:
        text: Input text.
        level: Compression level for both algorithms.
        size_threshold: Minimum byte length to attempt compression.

    Returns:
        CompressedPayload with the best result.
    """
    raw = text.encode("utf-8")
    orig_size = len(raw)

    if orig_size < size_threshold:
        # For tiny/empty inputs, compress with zstd (handles empty gracefully)
        compressed = compress_text(text, algorithm="zstd", level=1)
        return CompressedPayload(
            data=compressed,
            algorithm="zstd",
            original_size=orig_size,
            compressed_size=len(compressed),
            ratio=round(len(compressed) / max(orig_size, 1), 4),
        )

    best: Optional[CompressedPayload] = None

    for algo in ("lz4", "zstd"):
        t0 = time.perf_counter()
        compressed = compress_text(text, algorithm=algo, level=level)
        elapsed = (time.perf_counter() - t0) * 1000
        payload = CompressedPayload(
            data=compressed,
            algorithm=algo,
            original_size=orig_size,
            compressed_size=len(compressed),
            ratio=round(len(compressed) / orig_size, 4),
            compression_time_ms=round(elapsed, 3),
        )
        if best is None or payload.compressed_size < best.compressed_size:
            best = payload

    return best  # type: ignore[return-value]


def compress_tokens(
    tokens: Union[List[str], str],
    algorithm: Algorithm = "zstd",
    level: int = 3,
    separator: str = "\x00",
) -> CompressedPayload:
    """Compress a list of token strings (or a single string) for storage.

    Tokens are joined with a null separator before compression so they can
    be losslessly split on decompression.

    Args:
        tokens: Single string or list of token strings.
        algorithm: Compression algorithm.
        level: Compression level.
        separator: Delimiter between tokens (default NUL).

    Returns:
        CompressedPayload.
    """
    if isinstance(tokens, str):
        text = tokens
    else:
        text = separator.join(tokens)

    t0 = time.perf_counter()
    compressed = compress_text(text, algorithm=algorithm, level=level)
    elapsed = (time.perf_counter() - t0) * 1000

    orig_size = len(text.encode("utf-8"))
    return CompressedPayload(
        data=compressed,
        algorithm=algorithm,
        original_size=orig_size,
        compressed_size=len(compressed),
        ratio=round(len(compressed) / max(orig_size, 1), 4),
        compression_time_ms=round(elapsed, 3),
    )


def decompress_tokens(
    payload: CompressedPayload,
    separator: str = "\x00",
) -> List[str]:
    """Decompress a CompressedPayload back to a list of token strings."""
    text = decompress_text(payload.data, algorithm=payload.algorithm)
    return text.split(separator)


def batch_compress(
    texts: List[str],
    algorithm: Algorithm = "zstd",
    level: int = 3,
) -> List[CompressedPayload]:
    """Compress multiple texts independently.

    Args:
        texts: List of text strings.
        algorithm: Compression algorithm.
        level: Compression level.

    Returns:
        List of CompressedPayload, one per input text.
    """
    return [compress_tokens(t, algorithm=algorithm, level=level) for t in texts]


def compress_json(
    obj: object,
    algorithm: Algorithm = "zstd",
    level: int = 3,
) -> CompressedPayload:
    """Serialize a Python object to JSON and compress it.

    Args:
        obj: Any JSON-serializable object.
        algorithm: Compression algorithm.
        level: Compression level.

    Returns:
        CompressedPayload containing compressed JSON bytes.
    """
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return compress_tokens(text, algorithm=algorithm, level=level)


def decompress_json(
    payload: CompressedPayload,
) -> object:
    """Decompress a CompressedPayload and parse the JSON within."""
    text = decompress_text(payload.data, algorithm=payload.algorithm)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Streaming compression for large texts
# ---------------------------------------------------------------------------


class StreamCompressor:
    """Incrementally compress chunks of text using zstd streaming."""

    def __init__(self, level: int = 3):
        self._cctx = zstd.ZstdCompressor(level=level)
        self._compressor = self._cctx.compressobj()
        self._original_size = 0
        self._compressed_chunks: List[bytes] = []

    def feed(self, text: str) -> bytes:
        """Feed a chunk of text, returning any compressed output available."""
        raw = text.encode("utf-8")
        self._original_size += len(raw)
        out = self._compressor.compress(raw)
        if out:
            self._compressed_chunks.append(out)
        return out

    def finish(self) -> CompressedPayload:
        """Flush remaining data and return final CompressedPayload."""
        out = self._compressor.flush()
        if out:
            self._compressed_chunks.append(out)
        data = b"".join(self._compressed_chunks)
        return CompressedPayload(
            data=data,
            algorithm="zstd",
            original_size=self._original_size,
            compressed_size=len(data),
            ratio=round(len(data) / max(self._original_size, 1), 4),
        )


class StreamDecompressor:
    """Incrementally decompress zstd-compressed chunks."""

    def __init__(self):
        self._dctx = zstd.ZstdDecompressor()
        self._decompressor = self._dctx.decompressobj()
        self._chunks: List[str] = []

    def feed(self, data: bytes) -> str:
        """Feed compressed bytes, returning any decompressed text available."""
        raw = self._decompressor.decompress(data)
        text = raw.decode("utf-8")
        if text:
            self._chunks.append(text)
        return text

    def result(self) -> str:
        """Return all decompressed text accumulated so far."""
        return "".join(self._chunks)


# ---------------------------------------------------------------------------
# __main__ — correctness assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # ==================================================================
    # Test 1: Basic roundtrip — LZ4
    # ==================================================================
    original = "The quick brown fox jumps over the lazy dog. " * 100
    compressed_lz4 = compress_text(original, algorithm="lz4")
    decompressed_lz4 = decompress_text(compressed_lz4, algorithm="lz4")
    assert decompressed_lz4 == original, "LZ4 roundtrip failed"
    assert len(compressed_lz4) < len(original.encode("utf-8")), "LZ4 should compress"
    print(f"Test 1  — LZ4 roundtrip: {len(original.encode())} -> {len(compressed_lz4)} bytes "
          f"({100 - len(compressed_lz4)*100//len(original.encode())}% saved)")

    # ==================================================================
    # Test 2: Basic roundtrip — zstd
    # ==================================================================
    compressed_zstd = compress_text(original, algorithm="zstd")
    decompressed_zstd = decompress_text(compressed_zstd, algorithm="zstd")
    assert decompressed_zstd == original, "zstd roundtrip failed"
    assert len(compressed_zstd) < len(compressed_lz4), "zstd should beat lz4 on repetitive text"
    print(f"Test 2  — zstd roundtrip: {len(original.encode())} -> {len(compressed_zstd)} bytes "
          f"({100 - len(compressed_zstd)*100//len(original.encode())}% saved)")

    # ==================================================================
    # Test 3: auto_compress picks the best
    # ==================================================================
    payload = auto_compress(original)
    assert payload.algorithm == "zstd", f"Expected zstd for repetitive text, got {payload.algorithm}"
    restored = decompress_text(payload.data, algorithm=payload.algorithm)
    assert restored == original, "auto_compress roundtrip failed"
    assert payload.savings_pct > 90, f"Expected >90% savings, got {payload.savings_pct}%"
    print(f"Test 3  — auto_compress: algo={payload.algorithm}, "
          f"ratio={payload.ratio}, savings={payload.savings_pct}%")

    # ==================================================================
    # Test 4: Token list compression
    # ==================================================================
    tokens = ["def", "hello", "(", "world", ")", ":", "return", '"hi"']
    token_payload = compress_tokens(tokens, algorithm="zstd")
    recovered_tokens = decompress_tokens(token_payload)
    assert recovered_tokens == tokens, f"Token roundtrip failed: {recovered_tokens}"
    print(f"Test 4  — Token list: {len(tokens)} tokens, "
          f"{token_payload.original_size} -> {token_payload.compressed_size} bytes")

    # ==================================================================
    # Test 5: Single string token compression
    # ==================================================================
    single = "A long agent response that needs to be stored efficiently. " * 50
    sp = compress_tokens(single, algorithm="lz4")
    recovered = decompress_tokens(sp)
    assert recovered == [single], "Single-string token roundtrip failed"
    assert sp.savings_pct > 50, f"Expected >50% savings, got {sp.savings_pct}%"
    print(f"Test 5  — Single string: savings={sp.savings_pct}%")

    # ==================================================================
    # Test 6: Batch compress
    # ==================================================================
    batch_texts = [
        "Error: database connection timeout after 30s" * 20,
        "Warning: retry attempt 3 of 5 for API call" * 20,
        "Info: task completed successfully in 1.2 seconds" * 20,
    ]
    batch_results = batch_compress(batch_texts, algorithm="zstd")
    assert len(batch_results) == 3, "Batch should return 3 payloads"
    for i, (txt, res) in enumerate(zip(batch_texts, batch_results)):
        restored_batch = decompress_tokens(res)
        assert restored_batch == [txt], f"Batch item {i} roundtrip failed"
    total_orig = sum(r.original_size for r in batch_results)
    total_comp = sum(r.compressed_size for r in batch_results)
    print(f"Test 6  — Batch (3 items): {total_orig} -> {total_comp} bytes "
          f"({100 - total_comp*100//total_orig}% saved)")

    # ==================================================================
    # Test 7: JSON compression
    # ==================================================================
    obj = {
        "tasks": [
            {"id": f"t-{i}", "status": "done", "result": f"Completed task {i}" * 10}
            for i in range(50)
        ],
        "meta": {"total": 50, "success_rate": 0.94},
    }
    json_payload = compress_json(obj, algorithm="zstd")
    restored_obj = decompress_json(json_payload)
    assert restored_obj == obj, "JSON roundtrip failed"
    assert json_payload.savings_pct > 60, f"Expected >60% JSON savings, got {json_payload.savings_pct}%"
    print(f"Test 7  — JSON compress: savings={json_payload.savings_pct}%, "
          f"{json_payload.original_size} -> {json_payload.compressed_size} bytes")

    # ==================================================================
    # Test 8: Serialization roundtrip (header + data)
    # ==================================================================
    p = auto_compress("Serialize me! " * 200)
    serialized = p.serialize()
    p2 = CompressedPayload.deserialize(serialized)
    assert p2.algorithm == p.algorithm
    assert p2.original_size == p.original_size
    assert p2.compressed_size == p.compressed_size
    assert p2.data == p.data
    restored_ser = decompress_text(p2.data, algorithm=p2.algorithm)
    assert restored_ser == "Serialize me! " * 200, "Serialization roundtrip failed"
    print(f"Test 8  — Serialize/deserialize: header={HEADER_SIZE} bytes, "
          f"total={len(serialized)} bytes")

    # ==================================================================
    # Test 9: Streaming compression
    # ==================================================================
    chunks = ["Hello world! " * 50, "Streaming compression test. " * 50, "Final chunk. " * 50]
    sc = StreamCompressor(level=3)
    for chunk in chunks:
        sc.feed(chunk)
    stream_payload = sc.finish()

    full_text = "".join(chunks)
    stream_restored = decompress_text(stream_payload.data, algorithm="zstd")
    assert stream_restored == full_text, "Streaming roundtrip failed"
    print(f"Test 9  — Streaming: {stream_payload.original_size} -> "
          f"{stream_payload.compressed_size} bytes, savings={stream_payload.savings_pct}%")

    # ==================================================================
    # Test 10: Unicode / emoji support
    # ==================================================================
    unicode_text = "日本語テスト 🎉🚀 résumé naïve café " * 100
    up = auto_compress(unicode_text)
    unicode_restored = decompress_text(up.data, algorithm=up.algorithm)
    assert unicode_restored == unicode_text, "Unicode roundtrip failed"
    print(f"Test 10 — Unicode/emoji: savings={up.savings_pct}%")

    # ==================================================================
    # Test 11: Empty and tiny inputs
    # ==================================================================
    empty_p = auto_compress("")
    assert decompress_text(empty_p.data, algorithm=empty_p.algorithm) == ""
    tiny_p = auto_compress("hi")
    assert decompress_text(tiny_p.data, algorithm=tiny_p.algorithm) == "hi"
    print("Test 11 — Empty/tiny inputs: passed")

    # ==================================================================
    # Test 12: Compression levels comparison
    # ==================================================================
    sample = "The server returned a 500 error during the health check. " * 500
    sizes = {}
    for algo in ("lz4", "zstd"):
        for lvl in (1, 6, 12):
            try:
                c = compress_text(sample, algorithm=algo, level=lvl)
                sizes[(algo, lvl)] = len(c)
            except Exception:
                pass  # some levels may not be supported for lz4
    # zstd level 12 should be smaller than zstd level 1
    if ("zstd", 1) in sizes and ("zstd", 12) in sizes:
        assert sizes[("zstd", 12)] <= sizes[("zstd", 1)], "Higher zstd level should compress better"
    print(f"Test 12 — Level comparison: {dict((f'{a}-L{l}', s) for (a, l), s in sizes.items())}")

    # ==================================================================
    # Test 13: Large payload (1 MB+)
    # ==================================================================
    large = "x" * (1024 * 1024)  # 1 MB of 'x'
    large_p = auto_compress(large)
    large_restored = decompress_text(large_p.data, algorithm=large_p.algorithm)
    assert large_restored == large, "1 MB roundtrip failed"
    assert large_p.savings_pct > 99, f"1 MB uniform data should compress >99%, got {large_p.savings_pct}%"
    print(f"Test 13 — 1 MB payload: {large_p.original_size} -> {large_p.compressed_size} bytes "
          f"({large_p.savings_pct}% saved)")

    # ==================================================================
    # Test 14: Deserialize invalid data raises errors
    # ==================================================================
    try:
        CompressedPayload.deserialize(b"bad")
        assert False, "Should have raised ValueError for short data"
    except ValueError as e:
        assert "too short" in str(e).lower()

    try:
        CompressedPayload.deserialize(b"BADx" + b"\x00" * 20)
        assert False, "Should have raised ValueError for bad magic"
    except ValueError as e:
        assert "magic" in str(e).lower()
    print("Test 14 — Invalid data errors: passed")

    # ==================================================================
    # Summary
    # ==================================================================
    print("\n" + "=" * 60)
    print("ALL 14 ASSERTIONS PASSED — lossless compression verified")
    print("=" * 60)
