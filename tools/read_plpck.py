#!/usr/bin/env python3
"""Index a validated compact PLPcK v1 container without loading its scripts.

This schema was recovered from one native Yuna CDBM reader and checked against
the supplied init.jbin. Fragmented stores and other versions are not supported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import sys

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_BUCKETS = 65_536
MAX_RECORDS = 20_000
MAX_INDEX_BYTES = 16 * 1024 * 1024
HEADER_BYTES = 38
RECORD_HEADER_BYTES = 15
V8_CACHE_MAGIC = b"\xb7\x05\xde\xc0"
HASH = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA_REFERENCE = {
    "status": "native_inferred_and_checked_against_supplied_compact_container",
    "library_sha256": "a790283a8f283b767425feaab8281281c46b352a93c02da79f3baaf6065f04b0",
    "architecture": "ELF64 little-endian AArch64",
    "functions": [
        {"name": "cocos2d::createScriptPackFromBytes", "virtual_address": "0x2096e8c"},
        {"name": "yuna::cdbm::_init", "virtual_address": "0x1c52ec4"},
    ],
    "scope": "PLPcK version 1, 38-byte header, compact complete record coverage",
    "u40_encoding": "high byte followed by little-endian uint32",
    "header_fields": {"header_bytes": 6, "record_count": 17,
                      "bucket_count": 21, "bucket_table_pointer": 25},
    "record_fields": {"total_bytes": 0, "flag": 4, "key_bytes": 5,
                      "payload_bytes": 6, "next_record_pointer": 10, "key": 15},
}


class PLPcKError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _span(data: bytes, offset: int, size: int) -> None:
    if offset < 0 or size < 0 or offset > len(data) - size:
        raise PLPcKError(f"Truncated or out-of-bounds span at byte {offset}")


def _u32(data: bytes, offset: int) -> int:
    _span(data, offset, 4)
    return struct.unpack_from("<I", data, offset)[0]


def _u40(data: bytes, offset: int) -> int:
    _span(data, offset, 5)
    return (data[offset] << 32) | _u32(data, offset + 1)


def _check_coverage(spans: list[tuple[int, int, str]], file_bytes: int) -> None:
    cursor = 0
    for start, end, label in sorted(spans):
        if start < cursor:
            raise PLPcKError(f"Overlapping metadata or records at {label}")
        if start != cursor:
            raise PLPcKError("Incomplete compact-container coverage: unindexed bytes")
        cursor = end
    if cursor != file_bytes:
        raise PLPcKError("Incomplete compact-container coverage: trailing bytes")


def parse_plpck(data: bytes) -> dict:
    """Validate the entire compact container and return bounded metadata only."""
    if len(data) > MAX_FILE_BYTES:
        raise PLPcKError("PLPcK file exceeds 32 MiB")
    _span(data, 0, HEADER_BYTES)
    if data[:5] != b"PLPcK":
        raise PLPcKError("Missing PLPcK signature")
    if data[5] != 1 or struct.unpack_from("<H", data, 6)[0] != HEADER_BYTES:
        raise PLPcKError("Unsupported PLPcK version or header size")
    record_count = _u32(data, 17)
    bucket_count = _u32(data, 21)
    if record_count > MAX_RECORDS or not 1 <= bucket_count <= MAX_BUCKETS:
        raise PLPcKError("Record or bucket count exceeds limits")
    table_offset = _u40(data, 25)
    table_bytes = 5 + 5 * bucket_count
    _span(data, table_offset, table_bytes)
    if table_offset < HEADER_BYTES:
        raise PLPcKError("Bucket table overlaps header metadata")
    if _u32(data, table_offset) != table_bytes or data[table_offset + 4] != 1:
        raise PLPcKError("Unsupported bucket table flag or size")
    spans = [(0, HEADER_BYTES, "header"),
             (table_offset, table_offset + table_bytes, "bucket table")]
    records = []
    seen_offsets = set()
    seen_keys = set()
    indexed_bytes = HEADER_BYTES + table_bytes
    for bucket in range(bucket_count):
        offset = _u40(data, table_offset + 5 + bucket * 5)
        while offset:
            if offset in seen_offsets:
                raise PLPcKError("Duplicate or cyclic record pointer")
            if len(seen_offsets) >= MAX_RECORDS:
                raise PLPcKError("Record count exceeds limit")
            if len(seen_offsets) >= record_count:
                raise PLPcKError("Header record count disagrees with linked records")
            seen_offsets.add(offset)
            _span(data, offset, RECORD_HEADER_BYTES)
            if offset < HEADER_BYTES or table_offset <= offset < table_offset + table_bytes:
                raise PLPcKError("Record pointer overlaps metadata")
            total_bytes = _u32(data, offset)
            if data[offset + 4] != 2:
                raise PLPcKError("Unsupported record flag")
            key_bytes = data[offset + 5]
            payload_bytes = _u32(data, offset + 6)
            if total_bytes != RECORD_HEADER_BYTES + key_bytes + payload_bytes:
                raise PLPcKError("Record byte lengths disagree")
            _span(data, offset, total_bytes)
            indexed_bytes += total_bytes
            if indexed_bytes > len(data):
                raise PLPcKError("Overlapping record spans exceed source byte budget")
            key_offset = offset + RECORD_HEADER_BYTES
            try:
                key = data[key_offset:key_offset + key_bytes].decode("utf-8")
            except UnicodeError as error:
                raise PLPcKError("Record key is not valid UTF-8") from error
            if not key or any(ord(char) < 32 or ord(char) == 127 for char in key):
                raise PLPcKError("Record key is empty or contains control characters")
            if key in seen_keys:
                raise PLPcKError("Duplicate record key")
            seen_keys.add(key)
            payload_offset = key_offset + key_bytes
            payload = data[payload_offset:payload_offset + payload_bytes]
            next_offset = _u40(data, offset + 10)
            kind = "uninterpreted_binary"
            if payload.startswith(V8_CACHE_MAGIC):
                kind = "v8_cached_data_magic_observed"
            elif key == "@gitsha" and re.fullmatch(rb"[0-9a-f]{40}", payload):
                kind = "git_commit_metadata"
            records.append({
                "bucket": bucket, "record_offset": offset, "record_bytes": total_bytes,
                "key": key, "key_offset": key_offset, "key_bytes": key_bytes,
                "payload_offset": payload_offset, "payload_bytes": payload_bytes,
                "payload_sha256": digest(payload), "payload_kind": kind,
                "next_offset": next_offset,
            })
            spans.append((offset, offset + total_bytes, f"record {offset}"))
            offset = next_offset
    if len(records) != record_count:
        raise PLPcKError("Header record count disagrees with linked records")
    _check_coverage(spans, len(data))
    records.sort(key=lambda record: record["record_offset"])
    return {
        "schema_version": 1, "format": "compact_plpck_v1", "static_only": True,
        "schema_reference": SCHEMA_REFERENCE,
        "source": {"bytes": len(data), "sha256": digest(data)},
        "header": {"version": 1, "header_bytes": HEADER_BYTES,
                   "record_count": record_count, "bucket_count": bucket_count,
                   "table_offset": table_offset, "table_bytes": table_bytes},
        "coverage": {"status": "complete_nonoverlapping", "covered_bytes": len(data)},
        "records": records,
        "limitations": [
            "Only the observed compact PLPcK v1 layout is supported; other stores may differ.",
            "Record names are untrusted labels, not filesystem paths to execute or import.",
            "V8 cache magic identifies a payload prefix, not verified bytecode or source code.",
            "No scripts or native code are executed; no server data is requested.",
        ],
    }


def read_plpck(path: Path, expected_sha256: str | None = None) -> tuple[dict, bytes]:
    path = Path(path)
    with path.open("rb") as source:
        data = source.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise PLPcKError("PLPcK file exceeds 32 MiB")
    if expected_sha256 is not None:
        if not HASH.fullmatch(expected_sha256):
            raise PLPcKError("Expected SHA-256 must be 64 lowercase hexadecimal characters")
        if digest(data) != expected_sha256:
            raise PLPcKError("Source SHA-256 mismatch")
    result = parse_plpck(data)
    result["source"]["path"] = str(path)
    return result, data


def write_index(path: Path, output: Path, expected_sha256: str | None = None,
                extract_payloads: bool = False) -> dict:
    """Validate before writing. Preserve existing research and use hashed .bin names."""
    result, data = read_plpck(path, expected_sha256)
    output = Path(output)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise PLPcKError("Output must be new or empty; existing research is preserved")
    for record in result["records"]:
        if extract_payloads:
            record["stored_path"] = "payloads/" + record["payload_sha256"] + ".bin"
    result["payloads_extracted"] = bool(extract_payloads)
    index_bytes = (json.dumps(result, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if len(index_bytes) > MAX_INDEX_BYTES:
        raise PLPcKError("Generated index exceeds 16 MiB")
    output.mkdir(parents=True, exist_ok=True)
    if extract_payloads and result["records"]:
        payload_dir = output / "payloads"
        payload_dir.mkdir()
        for record in result["records"]:
            stored = output / record["stored_path"]
            if stored.exists():
                continue  # Identical payload hashes share one file.
            start = record["payload_offset"]
            with stored.open("xb") as target:
                target.write(data[start:start + record["payload_bytes"]])
            stored.chmod(stat.S_IRUSR | stat.S_IWUSR)
    index_path = output / "index.json"
    with index_path.open("xb") as target:
        target.write(index_bytes)
    index_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="PLPcK .jbin container")
    parser.add_argument("--output", required=True, type=Path, help="New or empty directory")
    parser.add_argument("--expected-sha256", help="Verify source SHA-256 before indexing")
    parser.add_argument("--extract-payloads", action="store_true",
                        help="Save inert payload bytes to hashed .bin files; never execute")
    args = parser.parse_args(argv)
    try:
        result = write_index(args.input, args.output, args.expected_sha256, args.extract_payloads)
    except (PLPcKError, OSError) as error:
        print(f"PLPcK indexing failed: {error}", file=sys.stderr)
        return 1
    print(f"Indexed {len(result['records'])} records; SHA-256 {result['source']['sha256']}")
    print(f"Created {args.output / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
