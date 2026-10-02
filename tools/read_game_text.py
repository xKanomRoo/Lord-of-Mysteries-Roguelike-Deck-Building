#!/usr/bin/env python3
"""Decode and index the observed game text resource without executing game code.

The native source hash, ELF mapping, size-seeded XOR wrapper and PLPcK structure
must all agree. Output is private research data and must stay outside Git.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 300_000
MAX_BUCKETS = 300_000
MAX_INDEX_BYTES = 64 * 1024 * 1024
MAX_QUERY_CHARS = 200
MAX_RESULTS = 100
MAX_EXCERPT_CHARS = 1000
NATIVE_SHA256 = "a790283a8f283b767425feaab8281281c46b352a93c02da79f3baaf6065f04b0"
TABLE_VA = 0x1448D59
HEADER_BYTES = 38


class GameTextError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _span(data: bytes, offset: int, size: int) -> None:
    if offset < 0 or size < 0 or offset > len(data) - size:
        raise GameTextError(f"Out-of-bounds span at byte {offset}")


def _u32(data: bytes, offset: int) -> int:
    _span(data, offset, 4)
    return struct.unpack_from("<I", data, offset)[0]


def _u40(data: bytes, offset: int) -> int:
    _span(data, offset, 5)
    return (data[offset] << 32) | _u32(data, offset + 1)


def _read_bounded_regular(path: Path) -> bytes:
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise GameTextError("Input must be a regular file, not a symlink")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise GameTextError("Input must be a regular file no larger than 64 MiB")
        data = source.read(MAX_FILE_BYTES + 1)
        after = os.fstat(source.fileno())
    if len(data) > MAX_FILE_BYTES or len(data) != before.st_size or after.st_size != before.st_size:
        raise GameTextError("Input exceeded its bound or changed while being read")
    return data


def native_default_table(data: bytes) -> bytes:
    """Map the observed 256-byte table in a bounded ELF64 AArch64 image.

    The caller must verify the exact native source hash before using this table.
    This function never prints or writes the table.
    """
    _span(data, 0, 64)
    if data[:7] != b"\x7fELF\x02\x01\x01":
        raise GameTextError("Native source must be ELF64 little-endian")
    if struct.unpack_from("<HHI", data, 16) != (3, 183, 1):
        raise GameTextError("Native source must be an AArch64 shared ELF image")
    ph_offset = struct.unpack_from("<Q", data, 32)[0]
    eh_size, ph_size, ph_count = struct.unpack_from("<HHH", data, 52)
    if eh_size != 64 or ph_size != 56 or not 1 <= ph_count <= 1024:
        raise GameTextError("Unsupported ELF program-header layout")
    _span(data, ph_offset, ph_size * ph_count)
    candidates = []
    for ordinal in range(ph_count):
        pos = ph_offset + ordinal * ph_size
        kind, _flags, offset, address, _physical, file_size, mem_size, _alignment = struct.unpack_from("<II6Q", data, pos)
        if kind != 1:
            continue
        if file_size > mem_size:
            raise GameTextError("ELF segment file size exceeds memory size")
        _span(data, offset, file_size)
        if address <= TABLE_VA and TABLE_VA + 256 <= address + file_size:
            mapped = offset + TABLE_VA - address
            _span(data, mapped, 256)
            candidates.append(data[mapped:mapped + 256])
    if len(candidates) != 1:
        raise GameTextError("Native default table has no unique file-backed ELF mapping")
    return candidates[0]


def transform_resource(data: bytes, table: bytes) -> bytes:
    """Apply the statically observed local file wrapper; no uploaded code runs."""
    if len(data) > MAX_FILE_BYTES or len(table) != 256:
        raise GameTextError("Resource or transform table exceeds the supported bounds")
    seed = len(data) % 256
    return bytes(value ^ table[(position + seed) % 256] for position, value in enumerate(data))


def parse_game_text(data: bytes) -> dict:
    """Validate complete PLPcK coverage, with binary-safe internal index keys."""
    if len(data) > MAX_FILE_BYTES:
        raise GameTextError("Text resource exceeds 64 MiB")
    _span(data, 0, HEADER_BYTES)
    if data[:8] != b"PLPcK\x01\x26\x00":
        raise GameTextError("Unsupported text container signature, version or header size")
    record_count, bucket_count = _u32(data, 17), _u32(data, 21)
    if record_count > MAX_RECORDS or not 1 <= bucket_count <= MAX_BUCKETS:
        raise GameTextError("Record or bucket count exceeds limits")
    table_offset = _u40(data, 25)
    table_bytes = 5 + 5 * bucket_count
    _span(data, table_offset, table_bytes)
    if table_offset < HEADER_BYTES or _u32(data, table_offset) != table_bytes or data[table_offset + 4] != 1:
        raise GameTextError("Unsupported or overlapping bucket table")
    spans = [(0, HEADER_BYTES), (table_offset, table_offset + table_bytes)]
    seen_offsets, seen_keys = set(), set()
    entries, forms, categories = [], Counter(), Counter()
    metadata = []
    indexed_bytes = HEADER_BYTES + table_bytes
    for bucket in range(bucket_count):
        offset = _u40(data, table_offset + 5 + bucket * 5)
        while offset:
            if offset in seen_offsets:
                raise GameTextError("Duplicate or cyclic linked-record pointer")
            if len(seen_offsets) >= record_count:
                raise GameTextError("Linked records exceed the header record count")
            seen_offsets.add(offset)
            _span(data, offset, 15)
            total_bytes, key_bytes, payload_bytes = _u32(data, offset), data[offset + 5], _u32(data, offset + 6)
            if data[offset + 4] != 2 or total_bytes != 15 + key_bytes + payload_bytes:
                raise GameTextError("Unsupported record flag or inconsistent record byte lengths")
            _span(data, offset, total_bytes)
            indexed_bytes += total_bytes
            if indexed_bytes > len(data):
                raise GameTextError("Overlapping record spans exceed the source byte budget")
            key = data[offset + 15:offset + 15 + key_bytes]
            if not key or key in seen_keys:
                raise GameTextError("Empty or duplicate record key")
            seen_keys.add(key)
            payload_offset = offset + 15 + key_bytes
            payload = data[payload_offset:payload_offset + payload_bytes]
            next_offset = _u40(data, offset + 10)
            internal = key.startswith(b"\t\t")
            if internal:
                forms["internal_row_index"] += 1
                categories["internal_row_index"] += 1
            elif payload.startswith(key + b"\0") and payload.endswith(b"\0"):
                try:
                    key_text = key.decode("utf-8")
                    value = payload[key_bytes + 1:-1].decode("utf-8")
                except UnicodeError as error:
                    raise GameTextError("Text entry is not valid UTF-8") from error
                if any(ord(char) < 32 or ord(char) == 127 for char in key_text) or "\0" in value:
                    raise GameTextError("Invalid text key or embedded field delimiter")
                forms["utf8_key_null_value_null"] += 1
                categories[key_text.split("@", 1)[0]] += 1
                entries.append({"key": key_text, "text": value, "record_offset": offset,
                                "record_bytes": total_bytes, "payload_offset": payload_offset,
                                "payload_bytes": payload_bytes, "payload_sha256": digest(payload)})
            else:
                forms["metadata_or_uninterpreted"] += 1
                # Binary labels remain inert metadata; never become filesystem paths.
                metadata.append({"key_hex": key.hex(), "record_offset": offset,
                                 "payload_bytes": payload_bytes, "payload_sha256": digest(payload)})
            spans.append((offset, offset + total_bytes))
            offset = next_offset
    if len(seen_offsets) != record_count:
        raise GameTextError("Header record count disagrees with linked records")
    cursor = 0
    for start, end in sorted(spans):
        if start != cursor:
            raise GameTextError("Container has overlapping or unindexed bytes")
        cursor = end
    if cursor != len(data):
        raise GameTextError("Container has unindexed trailing bytes")
    if not entries:
        raise GameTextError("Container has no recognized text entries")
    entries.sort(key=lambda entry: entry["record_offset"])
    return {"schema_version": 1, "format": "game_text_plpck_v1", "static_only": True,
            "source": {"bytes": len(data), "sha256": digest(data)},
            "header": {"record_count": record_count, "bucket_count": bucket_count,
                       "table_offset": table_offset, "table_bytes": table_bytes},
            "coverage": {"status": "complete_nonoverlapping", "covered_bytes": len(data)},
            "text_entry_count": len(entries), "record_forms": dict(forms),
            "categories": dict(categories.most_common()), "uninterpreted_metadata": metadata,
            "entries": entries}


def search_entries(entries: list[dict], query: str, limit: int = 20) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise GameTextError("Query must contain 1 to 200 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise GameTextError("Query limit must be between 1 and 100")
    needle = query.casefold()
    result = []
    for entry in entries:
        text = entry["text"]
        folded_text = text.casefold()
        position = folded_text.find(needle)
        if needle not in entry["key"].casefold() and position < 0:
            continue
        if position >= 0 and len(folded_text) != len(text):
            # Case folding can expand a character (for example, ß -> ss).
            # Translate only selected matches back to original text offsets.
            folded_position = position
            folded_end = 0
            for original_position, char in enumerate(text):
                folded_end += len(char.casefold())
                if folded_position < folded_end:
                    position = original_position
                    break
        start = max(0, position - MAX_EXCERPT_CHARS // 3)
        excerpt = text[start:start + MAX_EXCERPT_CHARS]
        result.append({**{k: v for k, v in entry.items() if k != "text"}, "text": excerpt,
                       "excerpt_start": start, "text_truncated": len(excerpt) != len(text)})
        if len(result) == limit:
            break
    return result


def decode_game_text(input_path: Path, native_library: Path, output: Path,
                     query: str | None = None, limit: int = 20) -> dict:
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise GameTextError("Output must be a new directory; existing research is preserved")
    source = _read_bounded_regular(input_path)
    native = _read_bounded_regular(native_library)
    if digest(native) != NATIVE_SHA256:
        raise GameTextError("Native source SHA-256 does not match the observed decoder")
    transformed = transform_resource(source, native_default_table(native))
    parsed = parse_game_text(transformed)
    entries = parsed.pop("entries")
    selected = search_entries(entries, query, limit) if query is not None else None
    summary = {**parsed, "input": {"path": str(input_path), "bytes": len(source), "sha256": digest(source)},
               "native_reference": {"sha256": NATIVE_SHA256, "architecture": "ELF64 little-endian AArch64",
                   "wrapper_function": "0x1e040d8", "wrapper_size_seed_instruction": "0x1e042ac",
                   "read_function": "0x1c6cc6c", "xor_function": "0x1c70204"},
               "output_files": {"transformed_container": "text-db.bin", "text_entries": "entries.jsonl"},
               "limitations": ["Static text rows do not prove runtime rules, rendered UI or availability.",
                               "Tags and substitution variables remain uninterpreted.",
                               "Reference text stays in private research and is not imported into the game."]}
    if selected is not None:
        summary["query"] = {"query": query, "limit": limit, "matches_returned": len(selected), "stored_path": "query.json"}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".game-text-stage-", dir=output.parent))
    try:
        (stage / "text-db.bin").write_bytes(transformed)
        with (stage / "entries.jsonl").open("wb") as target:
            written = 0
            for entry in entries:
                row = (json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
                written += len(row)
                if written > MAX_INDEX_BYTES:
                    raise GameTextError("Text-entry index exceeds 64 MiB")
                target.write(row)
        summary_bytes = (json.dumps(summary, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        if len(summary_bytes) > MAX_INDEX_BYTES:
            raise GameTextError("Summary index exceeds 64 MiB")
        (stage / "summary.json").write_bytes(summary_bytes)
        if selected is not None:
            (stage / "query.json").write_text(json.dumps({"source": parsed["source"], "entries": selected}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise GameTextError("Output appeared during decoding; existing research is preserved")
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Manifest-directed, decompressed inert text.db resource")
    parser.add_argument("--native-library", required=True, type=Path, help="Exact observed ARM64 libssr.so; read as data only")
    parser.add_argument("--output", required=True, type=Path, help="New private research directory")
    parser.add_argument("--query", help="Optional bounded text or record-key substring search")
    parser.add_argument("--limit", type=int, default=20, help="Query result limit, 1 to 100")
    args = parser.parse_args(argv)
    try:
        result = decode_game_text(args.input, args.native_library, args.output, args.query, args.limit)
    except (GameTextError, OSError) as error:
        print(f"Game text decoding failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated {result['header']['record_count']} records and {result['text_entry_count']} text entries")
    print(f"Decoded SHA-256 {result['source']['sha256']}")
    print(f"Created {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
