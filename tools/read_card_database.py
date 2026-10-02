#!/usr/bin/env python3
"""Read the observed unencrypted Yuna card/effect DB shards as inert research data.

This reader verifies complete PLPcK byte coverage and explicit row/column metadata.
It preserves serialized string values; enum behavior and formulas are not executed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

try:
    from . import read_game_text as resource
except ImportError:
    import read_game_text as resource

MAX_ROWS = 20_000
MAX_COLUMNS = 256
MAX_CELLS = 1_000_000
MAX_RECORDS = 50_000
MAX_BUCKETS = 50_000
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")


class CardDatabaseError(ValueError):
    pass


def _label(value: bytes) -> str:
    try:
        result = value.decode("utf-8")
    except UnicodeError as error:
        raise CardDatabaseError("Database label is not valid UTF-8") from error
    if not result or any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise CardDatabaseError("Database label is empty or contains control characters")
    return result


def _metadata_count(records: dict[bytes, dict], key: bytes, maximum: int) -> int:
    record = records.get(key)
    if record is None or len(record["payload"]) != 4:
        raise CardDatabaseError("Missing or malformed row/column count metadata")
    value = struct.unpack("<I", record["payload"])[0]
    if value > maximum:
        raise CardDatabaseError("Database row/column count exceeds limits")
    return value


def parse_database(data: bytes) -> dict:
    """Read only the fully covered, zero-seed, NUL-separated observed DB subset."""
    if len(data) > resource.MAX_FILE_BYTES:
        raise CardDatabaseError("Database exceeds 64 MiB")
    try:
        resource._span(data, 0, 38)
        if data[:8] != b"PLPcK\x01\x26\x00":
            raise CardDatabaseError("Unsupported database signature, version or header size")
        header_counter, buckets, table_offset = resource._u32(data, 17), resource._u32(data, 21), resource._u40(data, 25)
        if header_counter != 0:
            raise CardDatabaseError("Unobserved nonzero database header counter")
        if not 1 <= buckets <= MAX_BUCKETS:
            raise CardDatabaseError("Database bucket count exceeds limits")
        table_bytes = 5 + buckets * 5
        resource._span(data, table_offset, table_bytes)
        if table_offset < 38 or resource._u32(data, table_offset) != table_bytes or data[table_offset + 4] != 1:
            raise CardDatabaseError("Unsupported or overlapping database bucket table")
        spans = [(0, 38), (table_offset, table_offset + table_bytes)]
        records = {}
        offsets = set()
        covered_bytes = 38 + table_bytes
        for bucket in range(buckets):
            offset = resource._u40(data, table_offset + 5 + bucket * 5)
            while offset:
                if offset in offsets:
                    raise CardDatabaseError("Duplicate or cyclic database record pointer")
                if len(offsets) >= MAX_RECORDS:
                    raise CardDatabaseError("Database record count exceeds limit")
                offsets.add(offset)
                resource._span(data, offset, 15)
                total, key_size, payload_size = resource._u32(data, offset), data[offset + 5], resource._u32(data, offset + 6)
                if data[offset + 4] != 2 or total != 15 + key_size + payload_size:
                    raise CardDatabaseError("Unsupported database record flag or inconsistent byte lengths")
                resource._span(data, offset, total)
                covered_bytes += total
                if covered_bytes > len(data):
                    raise CardDatabaseError("Database records exceed source byte budget")
                key = data[offset + 15:offset + 15 + key_size]
                if not key or key in records:
                    raise CardDatabaseError("Empty or duplicate database record key")
                key_hash = 0
                for byte in key:
                    folded_byte = byte + 32 if 65 <= byte <= 90 else byte
                    key_hash = (43 * key_hash + folded_byte) & 0xffffffff
                if key_hash % buckets != bucket:
                    raise CardDatabaseError("Database record is linked from the wrong hash bucket")
                payload_offset = offset + 15 + key_size
                records[key] = {"record_offset": offset, "record_bytes": total,
                                "payload_offset": payload_offset, "payload_bytes": payload_size,
                                "payload": data[payload_offset:payload_offset + payload_size]}
                spans.append((offset, offset + total))
                offset = resource._u40(data, offset + 10)
        # All observed shards append a 38-byte header with the updated linked
        # record count. Verify every byte; its writer/runtime purpose is unknown.
        footer = None
        expected_footer = bytearray(data[:38])
        struct.pack_into("<I", expected_footer, 17, len(records))
        footer_offset = len(data) - 38
        if footer_offset < table_offset + table_bytes or data[footer_offset:] != bytes(expected_footer):
            raise CardDatabaseError("Unsupported appended header or trailing bytes")
        spans.append((footer_offset, len(data)))
        footer = {"offset": footer_offset, "bytes": 38,
                  "updated_counter": len(records), "sha256": resource.digest(data[footer_offset:]),
                  "status": "verified_duplicate_header_with_updated_counter",
                  "purpose": "unresolved"}
        cursor = 0
        for start, end in sorted(spans):
            if start != cursor:
                raise CardDatabaseError("Database has overlapping or unindexed bytes")
            cursor = end
        if cursor != len(data):
            raise CardDatabaseError("Database has unindexed trailing bytes")
        # The observed shards leave this CDBM counter at zero. Their authoritative
        # row/column metadata and one-to-one index keys are verified below.
        if b"\x1b\x01" in records:
            raise CardDatabaseError("Encrypted row metadata is outside the supported subset")
        row_count = _metadata_count(records, b"\trows", MAX_ROWS)
        column_count = _metadata_count(records, b"\tcols", MAX_COLUMNS)
        if not column_count:
            raise CardDatabaseError("Database has no column schema")
        if row_count * column_count > MAX_CELLS:
            raise CardDatabaseError("Database row/column product exceeds the cell budget")
        count_metadata = {}
        for label, key in [("rows", b"\trows"), ("columns", b"\tcols")]:
            record = records[key]
            count_metadata[label] = {**{name: value for name, value in record.items() if name != "payload"},
                                     "key_hex": key.hex(), "payload_sha256": resource.digest(record["payload"])}
        columns = []
        column_metadata = []
        consumed = {b"\trows", b"\tcols"}
        for index in range(column_count):
            key = b"\t" + str(index).encode("ascii")
            record = records.get(key)
            if record is None:
                raise CardDatabaseError("Missing sequential column schema key")
            name = _label(record["payload"])
            if name in columns:
                raise CardDatabaseError("Duplicate column schema label")
            columns.append(name)
            column_metadata.append({"name": name, "column_index": index,
                                    "record_offset": record["record_offset"], "record_bytes": record["record_bytes"],
                                    "payload_offset": record["payload_offset"], "payload_bytes": record["payload_bytes"],
                                    "payload_sha256": resource.digest(record["payload"])})
            consumed.add(key)
        rows = []
        seen_targets = set()
        for index in range(row_count):
            index_key = b"\t\t" + str(index).encode("ascii")
            index_record = records.get(index_key)
            if index_record is None:
                raise CardDatabaseError("Missing sequential row index key")
            row_key = index_record["payload"]
            if row_key.startswith((b"\t", b"\x1b")) or row_key in seen_targets:
                raise CardDatabaseError("Invalid or duplicate row index target")
            row_label = _label(row_key)
            row_record = records.get(row_key)
            if row_record is None:
                raise CardDatabaseError("Row index points to a missing row")
            payload = row_record["payload"]
            if not payload.endswith(b"\0"):
                raise CardDatabaseError("Row lacks the final field delimiter")
            fields = payload[:-1].split(b"\0")
            if len(fields) != column_count:
                raise CardDatabaseError("Row field count disagrees with column schema")
            try:
                values = [field.decode("utf-8") for field in fields]
            except UnicodeError as error:
                raise CardDatabaseError("Row field is not valid UTF-8") from error
            if columns[0] != "id" or values[0] != row_label:
                raise CardDatabaseError("Row id does not match its record key and schema")
            positions = {}
            position = row_record["payload_offset"]
            for name, field in zip(columns, fields):
                positions[name] = position
                position += len(field) + 1
            rows.append({"id": row_label, "row_index": index,
                         "index_record_offset": index_record["record_offset"],
                         "index_payload_offset": index_record["payload_offset"],
                         "index_payload_sha256": resource.digest(index_record["payload"]),
                         **{key: value for key, value in row_record.items() if key != "payload"},
                         "payload_sha256": resource.digest(payload),
                         "field_offsets": positions, "values": dict(zip(columns, values))})
            consumed.update((index_key, row_key))
            seen_targets.add(row_key)
        if consumed != set(records):
            raise CardDatabaseError("Database contains unsupported or unindexed records")
        expected_records = 2 + column_count + 2 * row_count
        if len(records) != expected_records:
            raise CardDatabaseError("Database metadata counts disagree with linked records")
        return {"schema_version": 1, "format": "yuna_dbm_plain_rows_v1", "static_only": True,
                "source": {"bytes": len(data), "sha256": resource.digest(data)},
                "header": {"observed_counter": header_counter, "bucket_count": buckets,
                           "table_offset": table_offset, "table_bytes": table_bytes},
                "coverage": {"status": "complete_nonoverlapping", "covered_bytes": len(data)},
                "appended_header": footer, "count_metadata": count_metadata,
                "linked_record_count": len(records), "row_count": row_count,
                "column_count": column_count, "columns": column_metadata, "rows": rows}
    except resource.GameTextError as error:
        raise CardDatabaseError(str(error)) from error


def read_database(input_path: Path, native_library: Path, output: Path,
                  expected_sha256: str | None = None) -> dict:
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise CardDatabaseError("Output must be a new directory; existing research is preserved")
    try:
        source = resource._read_bounded_regular(input_path)
        if expected_sha256 is not None and (not HASH.fullmatch(expected_sha256) or resource.digest(source) != expected_sha256):
            raise CardDatabaseError("Database input SHA-256 does not match the expected hash")
        native = resource._read_bounded_regular(native_library)
        if resource.digest(native) != resource.NATIVE_SHA256:
            raise CardDatabaseError("Native source SHA-256 does not match the observed decoder")
        transformed = resource.transform_resource(source, resource.native_default_table(native))
        parsed = parse_database(transformed)
    except resource.GameTextError as error:
        raise CardDatabaseError(str(error)) from error
    rows = parsed.pop("rows")
    summary = {**parsed, "input": {"path": str(input_path), "bytes": len(source), "sha256": resource.digest(source)},
               "native_reference": {"sha256": resource.NATIVE_SHA256,
                                    "schema_reader": "0x1dfa5f4", "field_reader": "0x1dfc32c",
                                    "row_index_key_instruction": "0x1dfc710", "size_seeded_wrapper": "0x1e040d8"},
               "output_files": {"database": "database.bin", "rows": "rows.json"},
               "limitations": ["Values are serialized strings; expressions, enums and effects are not executed.",
                               "Subset rows include variants and are not a complete playable card count.",
                               "Reference data stays in private research and is not imported into the product."]}
    summary_bytes = (json.dumps(summary, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    rows_bytes = (json.dumps({"source": parsed["source"], "rows": rows}, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(summary_bytes) > MAX_OUTPUT_BYTES or len(rows_bytes) > MAX_OUTPUT_BYTES:
        raise CardDatabaseError("Database output index exceeds 64 MiB")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".card-db-stage-", dir=output.parent))
    try:
        (stage / "database.bin").write_bytes(transformed)
        (stage / "summary.json").write_bytes(summary_bytes)
        (stage / "rows.json").write_bytes(rows_bytes)
        if output.exists() or output.is_symlink():
            raise CardDatabaseError("Output appeared during decoding; existing research is preserved")
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Manifest-directed decompressed DB shard")
    parser.add_argument("--native-library", required=True, type=Path, help="Exact observed ARM64 libssr.so; never executed")
    parser.add_argument("--output", required=True, type=Path, help="New private research directory")
    parser.add_argument("--expected-sha256", help="Optional SHA-256 of decompressed input resource")
    args = parser.parse_args(argv)
    try:
        result = read_database(args.input, args.native_library, args.output, args.expected_sha256)
    except (CardDatabaseError, OSError) as error:
        print(f"Card database decoding failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated {result['row_count']} rows, {result['column_count']} columns and {result['linked_record_count']} linked records")
    print(f"Database SHA-256 {result['source']['sha256']}")
    print(f"Created {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
