#!/usr/bin/env python3
"""Read bounded SSRA v4 metadata without decoding or executing game resources.

The layout is supported by static ARM64 reader evidence and the received
2026-10-02 manifest. Unknown fields remain uninterpreted. Paths are labels only;
this tool never uses them as extraction destinations.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import sys
import unicodedata

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CHUNKS = 10_000
MAX_FILES = 200_000
MAX_STRING_BYTES = 1024
MAX_INDEX_BYTES = 128 * 1024 * 1024
MAX_PATH_INVENTORY_BYTES = 32 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
MASK64 = (1 << 64) - 1
PRIMES = (11400714785074694791, 14029467366897019727, 1609587929392839161,
          9650029242287828579, 2870177450012600261)
SCHEMA_REFERENCE = {
    "library_sha256": "a790283a8f283b767425feaab8281281c46b352a93c02da79f3baaf6065f04b0",
    "reader_virtual_address": "0x1bf17bc",
    "chunk_name_reader_virtual_address": "0x1bf2cbc",
    "sample_manifest_sha256": "45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15",
    "scope": "SSRA version 4; raw path blob and observed GRPS/CNAM/META/FHSH sections",
}


class SSRAError(ValueError):
    pass


def _rotate(value: int, bits: int) -> int:
    value &= MASK64
    return ((value << bits) | (value >> (64 - bits))) & MASK64


def xxh64(data: bytes, seed: int = 0) -> int:
    """Standard XXH64, used for observed path and chunk checksums, not signatures."""
    p1, p2, p3, p4, p5 = PRIMES

    def round64(acc: int, value: int) -> int:
        return (_rotate(acc + value * p2, 31) * p1) & MASK64

    length, cursor = len(data), 0
    if length >= 32:
        lanes = [(seed + p1 + p2) & MASK64, (seed + p2) & MASK64,
                 seed & MASK64, (seed - p1) & MASK64]
        while cursor <= length - 32:
            for lane, value in enumerate(struct.unpack_from("<4Q", data, cursor)):
                lanes[lane] = round64(lanes[lane], value)
            cursor += 32
        result = sum(_rotate(value, bits) for value, bits in zip(lanes, (1, 7, 12, 18))) & MASK64
        for value in lanes:
            result = ((result ^ round64(0, value)) * p1 + p4) & MASK64
    else:
        result = (seed + p5) & MASK64
    result = (result + length) & MASK64
    while cursor <= length - 8:
        result ^= round64(0, struct.unpack_from("<Q", data, cursor)[0])
        result = (_rotate(result, 27) * p1 + p4) & MASK64
        cursor += 8
    if cursor <= length - 4:
        result ^= struct.unpack_from("<I", data, cursor)[0] * p1 & MASK64
        result = (_rotate(result, 23) * p2 + p3) & MASK64
        cursor += 4
    while cursor < length:
        result ^= data[cursor] * p5 & MASK64
        result = _rotate(result, 11) * p1 & MASK64
        cursor += 1
    result ^= result >> 33
    result = result * p2 & MASK64
    result ^= result >> 29
    result = result * p3 & MASK64
    return (result ^ (result >> 32)) & MASK64


def _span(data: bytes, offset: int, length: int) -> None:
    if offset < 0 or length < 0 or offset > len(data) - length:
        raise SSRAError(f"Truncated or out-of-bounds span at byte {offset}")


def _unpack(fmt: str, data: bytes, offset: int) -> tuple:
    _span(data, offset, struct.calcsize(fmt))
    return struct.unpack_from(fmt, data, offset)


def _string(blob: bytes, offset: int, *, path: bool = False, filename: bool = False) -> str:
    if not 0 <= offset < len(blob) or (offset and blob[offset - 1] != 0):
        raise SSRAError("String offset does not point to a NUL-delimited string start")
    end = blob.find(b"\0", offset, min(len(blob), offset + MAX_STRING_BYTES + 1))
    if end < 0:
        raise SSRAError("String is unterminated or exceeds the string size limit")
    try:
        value = blob[offset:end].decode("utf-8")
    except UnicodeError as error:
        raise SSRAError("String is not valid UTF-8") from error
    # Two paths in the supplied manifest contain U+200B. Preserve this observed
    # label byte-for-byte for checksums; it is never a filesystem destination.
    if not value or any(unicodedata.category(char) in ("Cc", "Cf", "Cs") and char != "\u200b"
                        for char in value):
        raise SSRAError("String is empty or contains control characters")
    if path or filename:
        if "\\" in value or ":" in value or value.startswith("/"):
            raise SSRAError("Unsafe resource path")
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise SSRAError("Unsafe resource path components")
        if filename and "/" in value:
            raise SSRAError("Chunk filename must be a basename")
    return value


def _coverage(spans: list[tuple[int, int, str]], source_bytes: int) -> None:
    cursor = 0
    for start, end, label in sorted(spans):
        if start < cursor:
            raise SSRAError(f"Overlapping manifest sections: {label}")
        if start != cursor:
            raise SSRAError("Unindexed bytes between manifest sections")
        cursor = end
    if cursor != source_bytes:
        raise SSRAError("Unindexed trailing manifest bytes")


def parse_ssra(data: bytes) -> dict:
    """Return validated metadata only; no Zstd, encryption or asset extraction."""
    if len(data) > MAX_FILE_BYTES:
        raise SSRAError("Manifest exceeds 32 MiB")
    _span(data, 0, 64)
    if data[:4] != b"SSRA":
        raise SSRAError("Missing SSRA magic")
    version, unknown8, chunk_count, file_count, flags = _unpack("<5I", data, 4)
    if version != 4:
        raise SSRAError("Unsupported SSRA version")
    if chunk_count > MAX_CHUNKS or file_count > MAX_FILES:
        raise SSRAError("Manifest record count exceeds limits")
    if flags & ~7:
        raise SSRAError("Unsupported manifest extension flags")
    path_offset, path_length, chunk_offset, file_offset = _unpack("<4Q", data, 24)
    unknown56, extra_count = _unpack("<2I", data, 56)
    if extra_count:
        raise SSRAError("Unsupported optional compressed extra records")
    spans = [(0, 64, "header")]
    for offset, length, label in ((chunk_offset, chunk_count * 32, "chunks"),
                                  (file_offset, file_count * 40, "files"),
                                  (path_offset, path_length, "paths")):
        _span(data, offset, length)
        if length:
            spans.append((offset, offset + length, label))
    # Validate base sections before interpreting record bytes.
    _coverage(spans, path_offset + path_length)
    blob = data[path_offset:path_offset + path_length]
    chunks, files, groups, sections = [], [], [], []
    seen_chunks, seen_paths = set(), set()
    group_ends: dict[int, int] = {}
    for row in range(chunk_count):
        offset = chunk_offset + row * 32
        index, group_id, unknown6, logical, physical, hash64 = _unpack("<IHHQQQ", data, offset)
        identity = (group_id, index)
        if identity in seen_chunks:
            raise SSRAError("Duplicate chunk group/index")
        seen_chunks.add(identity)
        if logical > physical:
            raise SSRAError("Logical chunk span exceeds physical length")
        start = group_ends.get(group_id, 0)
        if start + logical > MASK64:
            raise SSRAError("Logical group span overflows uint64")
        group_ends[group_id] = start + logical
        chunks.append({"row": row, "record_offset": offset, "index": index,
                       "group_id": group_id, "logical_start": start,
                       "logical_length": logical, "physical_length": physical,
                       "hash64": hash64, "filename": None,
                       "unknown6": unknown6})
    for row in range(file_count):
        offset = file_offset + row * 40
        path_hash, logical_offset, stored, decoded, unknown24, name_offset = _unpack("<QQ4I", data, offset)
        compression, encryption, group_id, file_flags = _unpack("<BBHB", data, offset + 32)
        if compression not in (0, 1) or encryption not in (0, 1):
            raise SSRAError("Unsupported file compression or encryption selector")
        if file_flags & ~1:
            raise SSRAError("Unsupported file flags")
        name = _string(blob, name_offset, path=True)
        if name in seen_paths:
            raise SSRAError("Duplicate resource path")
        seen_paths.add(name)
        if path_hash != xxh64(name.encode("utf-8")):
            raise SSRAError("Resource path XXH64 checksum mismatch")
        if not file_flags & 1:
            if group_id not in group_ends or logical_offset > group_ends[group_id] - stored:
                raise SSRAError("Resource file range exceeds its logical group span")
            if compression == 0 and decoded != stored:
                raise SSRAError("Uncompressed stored and decoded lengths disagree")
        files.append({"row": row, "record_offset": offset, "path": name,
                      "path_offset": name_offset, "path_hash64": path_hash,
                      "group_id": group_id, "offset": logical_offset,
                      "stored_length": stored, "decoded_length": decoded,
                      "compression": compression, "encryption": encryption,
                      "flags": file_flags, "unknown24": unknown24,
                      "unknown37_hex": data[offset + 37:offset + 40].hex(),
                      "file_hash64": None})
        if "\u200b" in name:
            files[-1]["path_format_characters"] = ["U+200B ZERO WIDTH SPACE"]
    cursor = path_offset + path_length
    file_group_counts = Counter(item["group_id"] for item in files)
    chunk_group_rows: dict[int, list[int]] = {}
    for item in chunks:
        chunk_group_rows.setdefault(item["group_id"], []).append(item["row"])

    def section_header(tag: bytes) -> tuple[int, int, int, int]:
        _span(data, cursor, 16)
        if data[cursor:cursor + 4] != tag:
            raise SSRAError(f"Missing expected {tag.decode()} section")
        return _unpack("<4I", data, cursor)

    if flags & 1:
        _, count, string_length, reserved = section_header(b"GRPS")
        if count > MAX_CHUNKS:
            raise SSRAError("Group count exceeds limit")
        length = 16 + count * 24 + string_length
        _span(data, cursor, length)
        group_blob = data[cursor + 16 + count * 24:cursor + length]
        group_ids, group_names = set(), set()
        for row in range(count):
            offset = cursor + 16 + row * 24
            identity, unknown2, name_offset, selector_offset, first_row, group_chunks, group_files = _unpack("<HH5I", data, offset)
            name = _string(group_blob, name_offset, filename=True)
            selector = _string(group_blob, selector_offset)
            if identity in group_ids or name in group_names:
                raise SSRAError("Duplicate group id or name")
            group_ids.add(identity)
            group_names.add(name)
            actual_rows = chunk_group_rows.get(identity, [])
            if first_row > chunk_count or group_chunks > chunk_count:
                raise SSRAError("GRPS chunk row mapping exceeds chunk count")
            if actual_rows != list(range(first_row, first_row + group_chunks)):
                raise SSRAError("GRPS chunk row mapping disagrees with chunk records")
            if group_files != file_group_counts[identity]:
                raise SSRAError("GRPS file count disagrees with file records")
            groups.append({"row": row, "record_offset": offset, "id": identity,
                           "name": name, "selector": selector, "first_chunk_row": first_row,
                           "chunk_count": group_chunks, "file_count": group_files,
                           "logical_length": group_ends.get(identity, 0), "unknown2": unknown2})
        if set(group_ends) - group_ids or {item["group_id"] for item in files} - group_ids:
            raise SSRAError("A chunk or file refers to an undeclared GRPS group")
        sections.append({"tag": "GRPS", "offset": cursor, "bytes": length,
                         "count": count, "string_bytes": string_length, "reserved": reserved})
        spans.append((cursor, cursor + length, "GRPS"))
        cursor += length
    if flags & 2:
        _, count, unknown8_cnam, unknown12_cnam = section_header(b"CNAM")
        if count > chunk_count:
            raise SSRAError("CNAM count exceeds chunk count")
        length = 16 + count * 8
        _span(data, cursor, length)
        previous = -1
        seen_names = set()
        for row in range(count):
            target, name_offset = _unpack("<2I", data, cursor + 16 + row * 8)
            if target <= previous or target >= chunk_count:
                raise SSRAError("CNAM chunk row indices must be unique, sorted and in bounds")
            previous = target
            name = _string(blob, name_offset, filename=True)
            if name in seen_names:
                raise SSRAError("Duplicate CNAM chunk filename")
            seen_names.add(name)
            chunks[target]["filename"] = name
            chunks[target]["filename_path_offset"] = name_offset
        sections.append({"tag": "CNAM", "offset": cursor, "bytes": length,
                         "count": count, "unknown8": unknown8_cnam, "unknown12": unknown12_cnam})
        spans.append((cursor, cursor + length, "CNAM"))
        cursor += length
    metadata = None
    if data[cursor:cursor + 4] == b"META":
        _, length, target_offset, build_offset = section_header(b"META")
        _span(data, cursor, 16 + length)
        metadata_blob = data[cursor + 16:cursor + 16 + length]
        metadata = {"target_label": _string(metadata_blob, target_offset),
                    "build_label": _string(metadata_blob, build_offset)}
        sections.append({"tag": "META", "offset": cursor, "bytes": 16 + length,
                         "target_offset": target_offset, "build_offset": build_offset})
        spans.append((cursor, cursor + 16 + length, "META"))
        cursor += 16 + length
    if flags & 4:
        _, count, hash_version, reserved = section_header(b"FHSH")
        if count != file_count or hash_version != 1:
            raise SSRAError("Unsupported FHSH version or file count")
        length = 16 + count * 8
        _span(data, cursor, length)
        for row, item in enumerate(files):
            item["file_hash64"] = _unpack("<Q", data, cursor + 16 + row * 8)[0]
        sections.append({"tag": "FHSH", "offset": cursor, "bytes": length,
                         "count": count, "version": hash_version, "reserved": reserved,
                         "algorithm": "uninterpreted_until_decoded_payload_validation"})
        spans.append((cursor, cursor + length, "FHSH"))
        cursor += length
    _coverage(spans, len(data))
    return {
        "schema_version": 1, "format": "ssra_v4_observed_metadata", "static_only": True,
        "schema_reference": SCHEMA_REFERENCE,
        "source": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "header": {"version": version, "chunk_count": chunk_count, "file_count": file_count,
                   "extension_flags": flags, "path_offset": path_offset,
                   "path_length": path_length, "chunk_offset": chunk_offset,
                   "file_offset": file_offset, "unknown8": unknown8, "unknown56": unknown56,
                   "extra_record_count": extra_count},
        "coverage": {"status": "complete_nonoverlapping", "covered_bytes": len(data)},
        "groups": groups, "chunks": chunks, "files": files, "sections": sections,
        "build_metadata": metadata,
        "summary": {"path_hashes_verified": file_count,
                    "chunk_filenames_observed": sum(item["filename"] is not None for item in chunks),
                    "compression_counts": dict(Counter(str(item["compression"]) for item in files)),
                    "encryption_counts": dict(Counter(str(item["encryption"]) for item in files))},
        "limitations": [
            "Metadata labels and native schema do not prove resource contents or gameplay behavior.",
            "No resource payload is decoded, decrypted, extracted or executed by this reader.",
            "XXH64 checksums detect changes; they are not authentication signatures.",
            "FHSH values are inventoried without claiming a payload hash algorithm.",
            "Unknown fields remain uninterpreted; optional compressed extra records are unsupported.",
            "CNAM omissions remain unknown filenames; no filesystem paths are guessed.",
        ],
    }


def read_ssra(path: Path, expected_sha256: str | None = None) -> dict:
    with Path(path).open("rb") as source:
        data = source.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise SSRAError("Manifest exceeds 32 MiB")
    if expected_sha256 is not None:
        if not HASH.fullmatch(expected_sha256):
            raise SSRAError("Expected SHA-256 must contain 64 lowercase hexadecimal characters")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise SSRAError("Source SHA-256 mismatch")
    return parse_ssra(data)


def write_index(path: Path, output: Path, expected_sha256: str | None = None) -> dict:
    result = read_ssra(path, expected_sha256)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise SSRAError("Output must be a new directory; existing research is preserved")
    index = (json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    paths = ("row\tgroup_id\tpath\n" + "".join(
        f"{item['row']}\t{item['group_id']}\t{json.dumps(item['path'], ensure_ascii=True)}\n"
        for item in result["files"])).encode("utf-8")
    if len(index) > MAX_INDEX_BYTES or len(paths) > MAX_PATH_INVENTORY_BYTES:
        raise SSRAError("Generated metadata exceeds bounded output limits")
    output.mkdir(parents=True)
    for filename, content in (("manifest-index.json", index), ("paths.tsv", paths)):
        destination = output / filename
        with destination.open("xb") as target:
            target.write(content)
        destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="SSRA v4 manifest")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--expected-sha256", help="Verify manifest source SHA-256 before parsing")
    args = parser.parse_args(argv)
    try:
        result = write_index(args.input, args.output, args.expected_sha256)
    except (SSRAError, OSError) as error:
        print(f"SSRA indexing failed: {error}", file=sys.stderr)
        return 1
    print(f"Indexed {len(result['files'])} paths and {len(result['chunks'])} chunks")
    print(f"Manifest SHA-256: {result['source']['sha256']}")
    print(f"Created {args.output / 'manifest-index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
