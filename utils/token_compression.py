"""
Lossless text compression for token transmission/storage.
Supports LZ4 (fast) and Zstandard (high ratio) algorithms.
"""

import json
import struct
import time
from enum import Enum
from typing import Union


try:
    import lz4.frame
except ImportError:
    lz4 = None

try:
    import zstandard as zstd
except ImportError:
    zstd = None


class Algorithm(Enum):
    LZ4 = "lz4"
    ZSTD = "zstd"


# 4-byte magic headers to identify algorithm on decompress
_MAGIC = {
    Algorithm.LZ4: b"\x00TL4",
    Algorithm.ZSTD: b"\x00TZS",
}


class CompressionResult:
    __slots__ = ("data", "algorithm", "original_size", "compressed_size", "elapsed_ms")

    def __init__(self, data: bytes, algorithm: Algorithm, original_size: int,
                 compressed_size: int, elapsed_ms: float):
        self.data = data
        self.algorithm = algorithm
        self.original_size = original_size
        self.compressed_size = compressed_size
        self.elapsed_ms = elapsed_ms

    @property
    def ratio(self) -> float:
        if self.compressed_size == 0:
            return 0.0
        return self.original_size / self.compressed_size

    def __repr__(self) -> str:
        return (f"CompressionResult(algo={self.algorithm.value}, "
                f"orig={self.original_size}B, compressed={self.compressed_size}B, "
                f"ratio={self.ratio:.2f}x, time={self.elapsed_ms:.2f}ms)")


class TokenCompressor:
    """Compresses text/token payloads with LZ4 or Zstandard."""

    def __init__(self, algorithm: Algorithm = Algorithm.ZSTD, zstd_level: int = 3):
        self.algorithm = algorithm
        self.zstd_level = zstd_level
        self._validate_backend()

    def _validate_backend(self) -> None:
        if self.algorithm == Algorithm.LZ4 and lz4 is None:
            raise ImportError("lz4 package required: pip install lz4")
        if self.algorithm == Algorithm.ZSTD and zstd is None:
            raise ImportError("zstandard package required: pip install zstandard")

    def compress(self, text: Union[str, bytes]) -> CompressionResult:
        raw = text.encode("utf-8") if isinstance(text, str) else text
        original_size = len(raw)
        t0 = time.monotonic()

        if self.algorithm == Algorithm.LZ4:
            compressed = lz4.frame.compress(raw, compression_level=0)
        else:
            cctx = zstd.ZstdCompressor(level=self.zstd_level)
            compressed = cctx.compress(raw)

        elapsed = (time.monotonic() - t0) * 1000
        magic = _MAGIC[self.algorithm]
        # Frame: magic(4) + original_size(4, big-endian) + compressed payload
        frame = magic + struct.pack(">I", original_size) + compressed
        return CompressionResult(
            data=frame,
            algorithm=self.algorithm,
            original_size=original_size,
            compressed_size=len(frame),
            elapsed_ms=elapsed,
        )

    @staticmethod
    def decompress(frame: bytes) -> bytes:
        if len(frame) < 8:
            raise ValueError("Frame too short to contain header")
        magic = frame[:4]
        original_size = struct.unpack(">I", frame[4:8])[0]
        payload = frame[8:]

        if magic == _MAGIC[Algorithm.LZ4]:
            if lz4 is None:
                raise ImportError("lz4 package required: pip install lz4")
            raw = lz4.frame.decompress(payload)
        elif magic == _MAGIC[Algorithm.ZSTD]:
            if zstd is None:
                raise ImportError("zstandard package required: pip install zstandard")
            dctx = zstd.ZstdDecompressor()
            raw = dctx.decompress(payload, max_output_size=original_size + 1024)
        else:
            raise ValueError(f"Unknown frame magic: {magic!r}")

        if len(raw) != original_size:
            raise ValueError(
                f"Size mismatch: expected {original_size}, got {len(raw)}"
            )
        return raw

    @staticmethod
    def decompress_text(frame: bytes) -> str:
        return TokenCompressor.decompress(frame).decode("utf-8")


def compress_tokens(tokens: list[str], algorithm: Algorithm = Algorithm.ZSTD,
                    zstd_level: int = 3) -> CompressionResult:
    """Compress a list of token strings for storage/transmission."""
    payload = json.dumps(tokens, separators=(",", ":")).encode("utf-8")
    compressor = TokenCompressor(algorithm=algorithm, zstd_level=zstd_level)
    return compressor.compress(payload)


def decompress_tokens(frame: bytes) -> list[str]:
    """Decompress a frame back into a list of token strings."""
    raw = TokenCompressor.decompress(frame)
    return json.loads(raw.decode("utf-8"))


def auto_compress(text: Union[str, bytes], size_threshold: int = 512) -> Union[bytes, CompressionResult]:
    """Pick best algorithm automatically based on payload size.
    - < threshold: return raw bytes (no compression overhead)
    - >= threshold and < 8KB: LZ4 (speed)
    - >= 8KB: zstd (ratio)
    """
    raw = text.encode("utf-8") if isinstance(text, str) else text
    if len(raw) < size_threshold:
        return raw
    algo = Algorithm.LZ4 if len(raw) < 8192 else Algorithm.ZSTD
    return TokenCompressor(algorithm=algo).compress(raw)


if __name__ == "__main__":
    # --- Test 1: Round-trip with zstd ---
    sample = "The quick brown fox jumps over the lazy dog. " * 200
    comp_zstd = TokenCompressor(Algorithm.ZSTD)
    result = comp_zstd.compress(sample)
    assert result.ratio > 1.0, f"zstd should compress, got ratio {result.ratio}"
    recovered = TokenCompressor.decompress_text(result.data)
    assert recovered == sample, "zstd round-trip failed"
    print(f"[PASS] zstd round-trip: {result}")

    # --- Test 2: Round-trip with lz4 ---
    comp_lz4 = TokenCompressor(Algorithm.LZ4)
    result_lz4 = comp_lz4.compress(sample)
    assert result_lz4.ratio > 1.0, f"lz4 should compress, got ratio {result_lz4.ratio}"
    recovered_lz4 = TokenCompressor.decompress_text(result_lz4.data)
    assert recovered_lz4 == sample, "lz4 round-trip failed"
    print(f"[PASS] lz4 round-trip: {result_lz4}")

    # --- Test 3: Token list compression ---
    tokens = ["hello", "world", "foo", "bar", "baz"] * 100
    frame = compress_tokens(tokens, Algorithm.ZSTD)
    restored = decompress_tokens(frame.data)
    assert restored == tokens, "Token list round-trip failed"
    print(f"[PASS] token list round-trip: {frame}")

    # --- Test 4: Token list with lz4 ---
    frame_lz4 = compress_tokens(tokens, Algorithm.LZ4)
    restored_lz4 = decompress_tokens(frame_lz4.data)
    assert restored_lz4 == tokens, "Token list lz4 round-trip failed"
    print(f"[PASS] token list lz4 round-trip: {frame_lz4}")

    # --- Test 5: Binary payload ---
    binary = bytes(range(256)) * 50
    comp = TokenCompressor(Algorithm.ZSTD)
    r = comp.compress(binary)
    assert TokenCompressor.decompress(r.data) == binary, "Binary round-trip failed"
    print(f"[PASS] binary round-trip: {r}")

    # --- Test 6: auto_compress below threshold returns raw ---
    short = b"hi"
    out = auto_compress(short, size_threshold=512)
    assert out == short, "auto_compress should return raw for small input"
    print("[PASS] auto_compress small payload returns raw")

    # --- Test 7: auto_compress medium selects lz4 ---
    medium = "token " * 200  # ~1200 bytes
    out_med = auto_compress(medium, size_threshold=512)
    assert isinstance(out_med, CompressionResult), "auto_compress should compress medium"
    assert out_med.algorithm == Algorithm.LZ4, f"Expected LZ4, got {out_med.algorithm}"
    assert TokenCompressor.decompress_text(out_med.data) == medium
    print(f"[PASS] auto_compress medium -> LZ4: {out_med}")

    # --- Test 8: auto_compress large selects zstd ---
    large = "token " * 5000  # ~30KB
    out_lg = auto_compress(large, size_threshold=512)
    assert isinstance(out_lg, CompressionResult), "auto_compress should compress large"
    assert out_lg.algorithm == Algorithm.ZSTD, f"Expected ZSTD, got {out_lg.algorithm}"
    assert TokenCompressor.decompress_text(out_lg.data) == large
    print(f"[PASS] auto_compress large -> ZSTD: {out_lg}")

    # --- Test 9: Empty string ---
    comp_empty = TokenCompressor(Algorithm.ZSTD)
    r_empty = comp_empty.compress("")
    assert TokenCompressor.decompress_text(r_empty.data) == ""
    print(f"[PASS] empty string round-trip: {r_empty}")

    # --- Test 10: Invalid frame ---
    try:
        TokenCompressor.decompress(b"bad")
        assert False, "Should have raised ValueError"
    except ValueError:
        print("[PASS] invalid frame raises ValueError")

    # --- Test 11: Unknown magic ---
    try:
        TokenCompressor.decompress(b"\xff\xff\xff\xff\x00\x00\x00\x05hello")
        assert False, "Should have raised ValueError"
    except ValueError:
        print("[PASS] unknown magic raises ValueError")

    # --- Test 12: Unicode ---
    unicode_text = "Sch\u00f6ne Gr\u00fc\u00dfe \u2014 \U0001f680\U0001f30d\U0001f4a1" * 100
    r_uni = TokenCompressor(Algorithm.ZSTD).compress(unicode_text)
    assert TokenCompressor.decompress_text(r_uni.data) == unicode_text
    print(f"[PASS] unicode round-trip: {r_uni}")

    print("\nAll 12 tests passed.")
