#!/usr/bin/env python3
"""Verify and decode the fixed card/battle range ZIP without executing resources.

The tracked selection and pinned manifest determine every accepted member,
resource identity, and physical read selector. Exporter scope and capability
claims are untrusted metadata. Partial range hashes and decoded FHSH establish
internal content consistency, not original CDN or whole-chunk authenticity.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import zipfile

try:
    from . import export_ssra_ranges as export
    from . import extract_ssra_resources as resources
    from . import read_ssra_manifest as ssra
except ImportError:
    import export_ssra_ranges as export
    import extract_ssra_resources as resources
    import read_ssra_manifest as ssra


PLAN_PATH = Path(__file__).resolve().parents[1] / "docs/research/profiles/chaos-card-battle-ranges-45a009358972.json"
INDEX_NAME = "research-index.json"
MANIFEST_MEMBER = "manifest/00.bin"
MAX_INDEX_BYTES = export.MAX_INDEX_BYTES
MAX_ZIP_BYTES = export.MAX_ZIP_BYTES
MAX_DECODED_FILE_BYTES = 64 * 1024 * 1024
MAX_DECODED_TOTAL_BYTES = 128 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class RangeReadError(ValueError):
    """Invalid source identities, range metadata, or decoded inert content."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash(value, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RangeReadError(f"Invalid {label} SHA-256")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RangeReadError("Range index contains a duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise RangeReadError("Range index contains a nonfinite JSON number")


def _index(data: bytes) -> dict:
    if len(data) > MAX_INDEX_BYTES:
        raise RangeReadError("Range index exceeds 256 KiB")
    try:
        index = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        pending = [index]
        nodes = 0
        while pending:
            value = pending.pop()
            nodes += 1
            if nodes > 40_000:
                raise RangeReadError("Range index exceeds its structure limit")
            if isinstance(value, str):
                value.encode("utf-8")
            elif isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
    except RangeReadError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise RangeReadError("Range index is not bounded strict UTF-8 JSON") from error
    if not isinstance(index, dict):
        raise RangeReadError("Range index must be an object")
    return index


def _exact(value, expected, label: str) -> None:
    # Canonical JSON distinguishes booleans and floats from integer selectors,
    # unlike Python's True == 1 and 1.0 == 1 metadata comparisons.
    if json.dumps(value, sort_keys=True, separators=(",", ":")) != json.dumps(expected, sort_keys=True, separators=(",", ":")):
        raise RangeReadError(f"{label} disagrees with the fixed manifest selection")


def _bounded_zip(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RangeReadError("Input ZIP must be a regular nonsymlink file")
    if metadata.st_size > MAX_ZIP_BYTES:
        raise RangeReadError("Input ZIP exceeds 30 MiB")
    with path.open("rb") as stream:
        data = stream.read(MAX_ZIP_BYTES + 1)
    if len(data) != metadata.st_size or len(data) > MAX_ZIP_BYTES:
        raise RangeReadError("Input ZIP changed size or exceeded its bounded limit")
    return data


def _members(archive: zipfile.ZipFile, selected: list[dict]) -> None:
    expected = {INDEX_NAME: None, MANIFEST_MEMBER: export.MANIFEST_BYTES,
                **{f"files/{ordinal:02d}.bin": item["stored_length"] for ordinal, item in enumerate(selected)}}
    infos = archive.infolist()
    names = [item.filename for item in infos]
    if len(infos) != len(expected) or len(set(names)) != len(names) or set(names) != set(expected):
        raise RangeReadError("ZIP must contain exactly the fixed members without duplicates")
    for info in infos:
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (info.flag_bits & 1 or kind not in (0, stat.S_IFREG) or info.is_dir()
                or info.external_attr & 0x10 or info.orig_filename != info.filename):
            raise RangeReadError("Encrypted, unsafe, and nonregular ZIP members are rejected")
        if info.compress_type != zipfile.ZIP_STORED or info.file_size != info.compress_size:
            raise RangeReadError("The fixed range profile requires consistent ZIP_STORED members")
        size = expected[info.filename]
        if size is None:
            if info.file_size > MAX_INDEX_BYTES:
                raise RangeReadError("Range index exceeds 256 KiB")
        elif info.file_size != size:
            raise RangeReadError("ZIP member size disagrees with the fixed manifest selection")


def _verify_index(index: dict, plan_hash: str, items: list[dict], reads: list[dict]) -> tuple[list[dict], list[dict], str]:
    if (type(index.get("schema_version")) is not int or index["schema_version"] != 1
            or index.get("profile") != export.PROFILE or index.get("package") != export.PACKAGE):
        raise RangeReadError("Range schema, profile, or package differs from the fixed selection")
    if (_hash(index.get("source_plan_sha256"), "plan") != plan_hash
            or _hash(index.get("source_manifest_sha256"), "manifest") != export.MANIFEST_SHA256):
        raise RangeReadError("Range source plan or manifest SHA-256 differs from the pinned profile")
    expected_manifest = {"archive_path": MANIFEST_MEMBER, "relative_path": export.MANIFEST_PATH,
                         "bytes": export.MANIFEST_BYTES, "sha256": export.MANIFEST_SHA256}
    _exact(index.get("manifest"), expected_manifest, "Manifest identity")
    records = index.get("files")
    if not isinstance(records, list) or len(records) != len(items):
        raise RangeReadError("Range index must contain the exact selected resources")
    verified = []
    for ordinal, (record, expected) in enumerate(zip(records, items)):
        if not isinstance(record, dict):
            raise RangeReadError("Indexed resource must be an object")
        fields = set(expected) | {"archive_path", "bytes", "expected_decoded_xxh64"}
        required = {**expected, "archive_path": f"files/{ordinal:02d}.bin",
                    "bytes": expected["stored_length"], "expected_decoded_xxh64": expected["file_hash64"]}
        _exact({key: record.get(key) for key in fields}, required, "Resource row, identity, or physical segments")
        verified.append({**required, "sha256": _hash(record.get("sha256"), "stored payload")})
    aligned = index.get("aligned_reads")
    if not isinstance(aligned, list) or len(aligned) != len(reads):
        raise RangeReadError("Aligned read count disagrees with the derived selection")
    declared_reads = []
    for record, expected in zip(aligned, reads):
        if not isinstance(record, dict):
            raise RangeReadError("Aligned read metadata must be an object")
        _exact({key: record.get(key) for key in expected}, expected, "Aligned physical read selectors")
        claimed_hash = _hash(record.get("actual_span_sha256"), "declared aligned span")
        declared_reads.append({**expected, "declared_span_sha256": claimed_hash, "span_sha256_rechecked": False})
    aligned_bytes = sum(item["bytes"] for item in reads)
    _exact(index.get("transfer_bytes"), {"manifest": export.MANIFEST_BYTES, "aligned_chunks": aligned_bytes,
           "total": export.MANIFEST_BYTES + aligned_bytes}, "Transfer byte counts")
    reader = index.get("range_reader")
    if not isinstance(reader, str) or reader not in {item.identity for item in export.READERS}:
        raise RangeReadError("Declared range reader is outside this fixed export profile")
    # Capability probes and scope booleans are deliberately ignored as evidence.
    return verified, declared_reads, reader


def read_ranges(path: Path, output: Path) -> dict:
    """Verify the pinned range pack and publish only decoded ordinal resources."""
    output = Path(output)
    if os.path.lexists(output):
        raise RangeReadError("Output already exists; choose a new directory to preserve research")
    if any(ord(character) < 32 or ord(character) == 127 for character in str(output)):
        raise RangeReadError("Output path contains control characters")
    try:
        plan, plan_hash = export.read_plan(PLAN_PATH)
    except export.RangeExportError as error:
        raise RangeReadError(str(error)) from error
    # The tracked plan supplies the exact ordered identity set; the archive
    # cannot request a different subset or substitute card variants.
    if len(plan["selected_files"]) != len(export.APPROVED_PATHS) or {item["path"] for item in plan["selected_files"]} != set(export.APPROVED_PATHS):
        raise RangeReadError("Tracked profile does not select the complete approved resource set")
    data = _bounded_zip(Path(path))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ssra-ranges-read-", dir=output.parent) as temporary:
        stage = Path(temporary)
        (stage / "files").mkdir()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _members(archive, plan["selected_files"])
            index_data = archive.read(INDEX_NAME)  # ZIP CRC is checked too.
            index = _index(index_data)
            manifest_data = archive.read(MANIFEST_MEMBER)
            if _sha256(manifest_data) != export.MANIFEST_SHA256:
                raise RangeReadError("Received manifest SHA-256 differs from the pinned profile")
            try:
                manifest = ssra.parse_ssra(manifest_data)
                items, reads = export.derive_selection(manifest, plan["selected_files"])
            except (ssra.SSRAError, export.RangeExportError) as error:
                raise RangeReadError(str(error)) from error
            records, declared_reads, declared_reader = _verify_index(index, plan_hash, items, reads)
            decoded_total = sum(item["decoded_length"] for item in items)
            if (any(item["decoded_length"] > MAX_DECODED_FILE_BYTES for item in items)
                    or decoded_total > MAX_DECODED_TOTAL_BYTES):
                raise RangeReadError("Decoded resource selection exceeds its per-file or combined bounds")
            extracted = []
            for record, item in zip(records, items):
                label = record["archive_path"]  # Already matched the fixed ordinal.
                stored = archive.read(label)
                actual_stored_hash = _sha256(stored)
                if len(stored) != item["stored_length"] or actual_stored_hash != record["sha256"]:
                    raise RangeReadError("Received stored payload size or SHA-256 disagrees with its index")
                decode_item = {**item, "file_hash64": int(item["file_hash64"], 16)}
                try:
                    decoded = resources._decode_resource(stored, decode_item)
                except resources.ResourceExtractError as error:
                    raise RangeReadError(str(error)) from error
                actual_fhsh = ssra.xxh64(decoded)
                if actual_fhsh != decode_item["file_hash64"]:
                    raise RangeReadError("Decoded resource FHSH XXH64 disagrees with the pinned manifest")
                (stage / label).write_bytes(decoded)
                (stage / label).chmod(0o600)
                extracted.append({"archive_path": label, "resource_path": item["path"],
                                  "manifest_file_row": item["row"], "group_id": item["group_id"],
                                  "logical_offset": item["offset"], "stored_bytes": len(stored),
                                  "stored_sha256": actual_stored_hash, "decoded_bytes": len(decoded),
                                  "decoded_sha256": _sha256(decoded), "decoded_xxh64": f"{actual_fhsh:016x}",
                                  "fhsh_xxh64": item["file_hash64"], "fhsh_verified": True,
                                  "compression": item["compression"], "encryption": item["encryption"],
                                  "segments": item["segments"]})
        result = {"schema_version": 1, "format": "verified_ssra_card_battle_ranges",
                  "profile": export.PROFILE, "package": export.PACKAGE,
                  "source_zip": {"filename": export.PACK_NAME, "bytes": len(data), "sha256": _sha256(data)},
                  "source_index_sha256": _sha256(index_data), "source_plan_sha256": plan_hash,
                  "source_manifest": {"archive_path": MANIFEST_MEMBER, "relative_path": export.MANIFEST_PATH,
                                      "bytes": len(manifest_data), "sha256": _sha256(manifest_data)},
                  "declared_range_reader": declared_reader, "reader_capabilities_verified": False,
                  "declared_aligned_reads": declared_reads,
                  "whole_chunk_hashes_verified": False, "original_resource_authenticity": "unknown",
                  "selected_count": len(extracted), "stored_payload_bytes": sum(item["stored_bytes"] for item in extracted),
                  "decoded_bytes": decoded_total, "files": extracted,
                  "limitations": "ZIP CRC, SHA-256, pinned manifest rows, strict decoding, and decoded FHSH "
                  "verify received resource identity and internal consistency. Surrounding aligned bytes and "
                  "whole chunks are absent, so their declared hashes, reader probes, and export scope "
                  "are not independently verified. Resource code is never executed; CDN authenticity remains unknown."}
        (stage / "resource-index.json").write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        output.mkdir()
        promoted = []
        try:
            for name in ("files", "resource-index.json"):
                shutil.move(str(stage / name), str(output / name))
                promoted.append(name)
        except OSError:
            for name in promoted:
                destination = output / name
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink(missing_ok=True)
            try:
                output.rmdir()
            except OSError:
                pass
            raise
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="Fixed selected card/battle range ZIP")
    parser.add_argument("--output", type=Path, required=True, help="New directory for inert decoded resources")
    args = parser.parse_args(argv)
    try:
        result = read_ranges(args.pack, args.output)
    except (RangeReadError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(f"SSRA range verification failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
