"""
Lossless text compression for token transmission/storage.
Supports LZ4 (fast) and zstd (high ratio) with automatic codec selection.
"""

import json
import struct
import time
from enum import IntEnum
from typing import Optional

try:
    import lz4.frame as lz4_frame
    import lz4.block as lz4_block
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False

try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

import zlib  # stdlib fallback


class Codec(IntEnum):
    ZLIB = 0
    LZ4_FRAME = 1
    LZ4_BLOCK = 2
    ZSTD = 3


# 4-byte magic + 1-byte codec + 4-byte original length
HEADER_FMT = "!4sBL"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAGIC = b"TC01"


class TokenCompressor:
    """Compress and decompress text/token payloads with selectable codec."""

    def __init__(self, codec: str = "zstd", level: Optional[int] = None):
        self.codec_name = codec.lower()
        if self.codec_name == "lz4":
            if not HAS_LZ4:
                raise ImportError("lz4 package required: pip install lz4")
            self.codec = Codec.LZ4_FRAME
            self.level = level  # lz4 frame default is fine
        elif self.codec_name == "lz4_block":
            if not HAS_LZ4:
                raise ImportError("lz4 package required: pip install lz4")
            self.codec = Codec.LZ4_BLOCK
            self.level = level
        elif self.codec_name == "zstd":
            if not HAS_ZSTD:
                raise ImportError("zstandard package required: pip install zstandard")
            self.codec = Codec.ZSTD
            self.level = level if level is not None else 3
            self._cctx = zstd.ZstdCompressor(level=self.level)
            self._dctx = zstd.ZstdDecompressor()
        elif self.codec_name == "zlib":
            self.codec = Codec.ZLIB
            self.level = level if level is not None else 6
        else:
            raise ValueError(f"Unknown codec: {codec}. Use 'lz4', 'lz4_block', 'zstd', or 'zlib'.")

    def compress(self, data: bytes) -> bytes:
        original_len = len(data)
        if self.codec == Codec.LZ4_FRAME:
            compressed = lz4_frame.compress(data)
        elif self.codec == Codec.LZ4_BLOCK:
            compressed = lz4_block.compress(data, store_size=True)
        elif self.codec == Codec.ZSTD:
            compressed = self._cctx.compress(data)
        else:
            compressed = zlib.compress(data, self.level)

        header = struct.pack(HEADER_FMT, MAGIC, int(self.codec), original_len)
        return header + compressed

    def decompress(self, blob: bytes) -> bytes:
        if len(blob) < HEADER_SIZE:
            raise ValueError("Data too short to contain header")
        magic, codec_id, original_len = struct.unpack(HEADER_FMT, blob[:HEADER_SIZE])
        if magic != MAGIC:
            raise ValueError(f"Bad magic: {magic!r}")
        payload = blob[HEADER_SIZE:]
        codec = Codec(codec_id)

        if codec == Codec.LZ4_FRAME:
            if not HAS_LZ4:
                raise ImportError("lz4 required to decompress this payload")
            result = lz4_frame.decompress(payload)
        elif codec == Codec.LZ4_BLOCK:
            if not HAS_LZ4:
                raise ImportError("lz4 required to decompress this payload")
            result = lz4_block.decompress(payload, uncompressed_size=-1)
        elif codec == Codec.ZSTD:
            if not HAS_ZSTD:
                raise ImportError("zstandard required to decompress this payload")
            dctx = getattr(self, "_dctx", None) or zstd.ZstdDecompressor()
            result = dctx.decompress(payload, max_output_size=original_len)
        else:
            result = zlib.decompress(payload)

        if len(result) != original_len:
            raise ValueError(f"Length mismatch: expected {original_len}, got {len(result)}")
        return result

    def compress_text(self, text: str, encoding: str = "utf-8") -> bytes:
        return self.compress(text.encode(encoding))

    def decompress_text(self, blob: bytes, encoding: str = "utf-8") -> str:
        return self.decompress(blob).decode(encoding)

    def compress_tokens(self, tokens: list) -> bytes:
        return self.compress(json.dumps(tokens, separators=(",", ":")).encode("utf-8"))

    def decompress_tokens(self, blob: bytes) -> list:
        return json.loads(self.decompress(blob).decode("utf-8"))


def benchmark(data: bytes, codecs: Optional[list] = None) -> dict:
    """Benchmark compression across available codecs."""
    if codecs is None:
        codecs = ["zlib"]
        if HAS_LZ4:
            codecs.append("lz4")
        if HAS_ZSTD:
            codecs.append("zstd")

    results = {}
    for name in codecs:
        tc = TokenCompressor(codec=name)
        t0 = time.perf_counter()
        compressed = tc.compress(data)
        t_compress = time.perf_counter() - t0
        t0 = time.perf_counter()
        decompressed = tc.decompress(compressed)
        t_decompress = time.perf_counter() - t0
        ratio = len(compressed) / len(data) if len(data) > 0 else 0.0
        results[name] = {
            "original_bytes": len(data),
            "compressed_bytes": len(compressed),
            "ratio": round(ratio, 4),
            "compress_ms": round(t_compress * 1000, 3),
            "decompress_ms": round(t_decompress * 1000, 3),
            "lossless": decompressed == data,
        }
    return results


if __name__ == "__main__":
    # --- Test data ---
    sample_text = "The quick brown fox jumps over the lazy dog. " * 200
    sample_tokens = [
        {"id": i, "text": f"token_{i}", "logprob": -0.5 * i}
        for i in range(500)
    ]
    sample_bytes = sample_text.encode("utf-8")
    empty_data = b""
    tiny_data = b"x"

    available_codecs = ["zlib"]
    if HAS_LZ4:
        available_codecs.extend(["lz4", "lz4_block"])
    if HAS_ZSTD:
        available_codecs.append("zstd")

    print(f"Available codecs: {available_codecs}\n")

    # --- Roundtrip assertions for every codec ---
    for codec_name in available_codecs:
        tc = TokenCompressor(codec=codec_name)

        # Text roundtrip
        blob = tc.compress_text(sample_text)
        assert tc.decompress_text(blob) == sample_text, f"{codec_name}: text roundtrip failed"

        # Token list roundtrip
        blob = tc.compress_tokens(sample_tokens)
        assert tc.decompress_tokens(blob) == sample_tokens, f"{codec_name}: token roundtrip failed"

        # Raw bytes roundtrip
        blob = tc.compress(sample_bytes)
        assert tc.decompress(blob) == sample_bytes, f"{codec_name}: bytes roundtrip failed"

        # Compression actually reduces size for repetitive data
        assert len(blob) < len(sample_bytes), f"{codec_name}: no compression achieved"

        # Empty data roundtrip
        blob = tc.compress(empty_data)
        assert tc.decompress(blob) == empty_data, f"{codec_name}: empty roundtrip failed"

        # Tiny data roundtrip
        blob = tc.compress(tiny_data)
        assert tc.decompress(blob) == tiny_data, f"{codec_name}: tiny roundtrip failed"

        # Header validation
        assert blob[:4] == MAGIC, f"{codec_name}: bad magic"

        print(f"  [{codec_name}] all assertions passed")

    # --- Cross-codec: any decompressor reads its own header ---
    if HAS_ZSTD and HAS_LZ4:
        zstd_blob = TokenCompressor("zstd").compress(sample_bytes)
        lz4_blob = TokenCompressor("lz4").compress(sample_bytes)

        # Use a zstd compressor to decompress zstd blob
        assert TokenCompressor("zstd").decompress(zstd_blob) == sample_bytes
        # Use an lz4 compressor to decompress lz4 blob
        assert TokenCompressor("lz4").decompress(lz4_blob) == sample_bytes
        # Any instance can decompress any blob because header encodes codec
        assert TokenCompressor("zlib").decompress(zstd_blob) == sample_bytes
        assert TokenCompressor("zlib").decompress(lz4_blob) == sample_bytes
        print("  [cross-codec] header-based decompression passed")

    # --- Error handling ---
    try:
        TokenCompressor("zlib").decompress(b"garbage")
        assert False, "Should have raised"
    except ValueError:
        print("  [error] bad data rejected correctly")

    try:
        TokenCompressor("zlib").decompress(b"")
        assert False, "Should have raised"
    except ValueError:
        print("  [error] empty data rejected correctly")

    # --- Benchmark ---
    print("\nBenchmark (9KB repetitive text):")
    results = benchmark(sample_bytes)
    for name, r in results.items():
        print(
            f"  {name:10s}  ratio={r['ratio']:.4f}  "
            f"compress={r['compress_ms']:.3f}ms  "
            f"decompress={r['decompress_ms']:.3f}ms  "
            f"lossless={r['lossless']}"
        )
        assert r["lossless"], f"Benchmark: {name} not lossless!"
        assert r["ratio"] < 1.0, f"Benchmark: {name} didn't compress"

    print("\nAll assertions passed.")
