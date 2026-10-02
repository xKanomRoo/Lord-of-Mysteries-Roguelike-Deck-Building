#!/usr/bin/env python3
"""Extract selected inert SSRA resources from six verified Android payloads.

Only the fixed received resource profile is read. Paths from manifests and
receipts are data labels, never local destinations. No game code is executed,
and encryption is unsupported. SHA-256 and observed XXH64 checks identify the
received content; they do not establish original CDN authenticity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile

try:
    from . import read_android_research as packs
    from . import read_ssra_manifest as ssra
except ImportError:
    import read_android_research as packs
    import read_ssra_manifest as ssra


TARGETS = packs.TARGETS
PROFILE = packs.PROFILE
PACKAGE = packs.PACKAGE
MAX_RECEIPT_BYTES = 64 * 1024
MAX_SELECTED_PATHS = 64
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


class ResourceExtractError(ValueError):
    """Invalid verified inputs, unavailable resources, or unsupported encodings."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular_directory(path: Path, label: str) -> None:
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise ResourceExtractError(f"{label} must be a regular directory, not a symlink")


def _regular_bytes(path: Path, maximum: int, expected: int | None = None) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ResourceExtractError("Receipt and resource payloads must be regular nonsymlink files")
    if metadata.st_size > maximum or expected is not None and metadata.st_size != expected:
        raise ResourceExtractError("Receipt or resource payload has an unexpected bounded size")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) != metadata.st_size or len(data) > maximum:
        raise ResourceExtractError("Receipt or resource payload changed size while being read")
    return data


def _load_resources(root: Path) -> tuple[dict, str, dict[str, bytes]]:
    _regular_directory(root, "Resources root")
    _regular_directory(root / "files", "Resources files directory")
    encoded = _regular_bytes(root / "receipt-index.json", MAX_RECEIPT_BYTES)
    try:
        receipt = packs._read_index(encoded)
        lineage = packs._hash(receipt.get("source_inventory_sha256"), "source inventory")
    except packs.AndroidReadError as error:
        raise ResourceExtractError(str(error)) from error
    if (type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or receipt.get("profile") != PROFILE or receipt.get("package") != PACKAGE):
        raise ResourceExtractError("Receipt schema, profile, or package differs from the fixed selection")
    total = sum(target.bytes for target in TARGETS)
    if (type(receipt.get("verified_file_count")) is not int
            or receipt["verified_file_count"] != len(TARGETS)
            or type(receipt.get("verified_bytes")) is not int or receipt["verified_bytes"] != total):
        raise ResourceExtractError("Receipt selected file count or byte total is inconsistent")
    records = receipt.get("files")
    if not isinstance(records, list) or len(records) != len(TARGETS):
        raise ResourceExtractError("Receipt must contain the exact six selected resources")
    expected = {f"files/{ordinal:02d}.bin": target for ordinal, target in enumerate(TARGETS)}
    indexed = {}
    for record in records:
        if not isinstance(record, dict):
            raise ResourceExtractError("Receipt file must be an object")
        label = record.get("archive_path")
        if not isinstance(label, str) or label not in expected or label in indexed:
            raise ResourceExtractError("Receipt has a duplicate or unexpected resource label")
        target = expected[label]
        if (record.get("relative_path") != target.relative_path
                or record.get("remote_path") != packs.RESOURCE_ROOT + "/" + target.relative_path
                or record.get("archive") != target.pack
                or type(record.get("bytes")) is not int or record["bytes"] != target.bytes):
            raise ResourceExtractError("Receipt resource path, archive, or size differs from the fixed selection")
        try:
            packs._hash(record.get("sha256"), "payload")
        except packs.AndroidReadError as error:
            raise ResourceExtractError(str(error)) from error
        indexed[label] = record
    archives = receipt.get("packs")
    if not isinstance(archives, list) or len(archives) != len(packs.PACK_NAMES):
        raise ResourceExtractError("Receipt must identify the two selected source ZIPs")
    seen = set()
    sanitized_archives = []
    for item in archives:
        if not isinstance(item, dict) or item.get("filename") not in packs.PACK_NAMES or item["filename"] in seen:
            raise ResourceExtractError("Receipt has an unexpected or duplicate source ZIP")
        name = item["filename"]
        seen.add(name)
        subset = [target for target in TARGETS if target.pack == name]
        if (type(item.get("bytes")) is not int or not 0 < item["bytes"] <= packs.MAX_ZIP_BYTES
                or type(item.get("payload_files")) is not int or item["payload_files"] != len(subset)
                or type(item.get("payload_bytes")) is not int
                or item["payload_bytes"] != sum(target.bytes for target in subset)):
            raise ResourceExtractError("Receipt source ZIP size or selected counts are invalid")
        try:
            pack_hash = packs._hash(item.get("sha256"), "ZIP")
            index_hash = packs._hash(item.get("research_index_sha256"), "ZIP index")
        except packs.AndroidReadError as error:
            raise ResourceExtractError(str(error)) from error
        sanitized_archives.append({"filename": name, "bytes": item["bytes"], "sha256": pack_hash,
                                   "research_index_sha256": index_hash})
    payloads = {}
    identities = []
    for label, target in expected.items():
        # Construct local paths only from constant ordinal labels, never metadata.
        data = _regular_bytes(root / label, target.bytes, target.bytes)
        actual_hash = _sha256(data)
        if actual_hash != indexed[label]["sha256"]:
            raise ResourceExtractError("Actual resource payload SHA-256 differs from receipt")
        payloads[label] = data
        identities.append({"archive_path": label, "relative_path": target.relative_path,
                           "bytes": len(data), "sha256": actual_hash, "archive": target.pack})
    source = {"profile": PROFILE, "package": PACKAGE, "source_inventory_sha256": lineage,
              "receipt_bytes": len(encoded), "receipt_sha256": _sha256(encoded),
              "source_zip_identities": sanitized_archives,
              "source_zip_hashes_rechecked": False, "payloads": identities,
              "original_resource_authenticity": "unknown"}
    return source, _sha256(payloads["files/00.bin"]), payloads


def _selected_paths(paths: list[str]) -> list[str]:
    if not 1 <= len(paths) <= MAX_SELECTED_PATHS or len(set(paths)) != len(paths):
        raise ResourceExtractError("Select between one and 64 distinct resource paths")
    for path in paths:
        try:
            encoded = path.encode("utf-8")
        except (AttributeError, UnicodeError) as error:
            raise ResourceExtractError("Selected resource path is not valid UTF-8 text") from error
        if (not encoded or len(encoded) > ssra.MAX_STRING_BYTES or path.startswith("/")
                or "\\" in path or ":" in path
                or any(ord(character) < 32 or ord(character) == 127 for character in path)
                or any(part in ("", ".", "..") for part in path.split("/"))):
            raise ResourceExtractError("Selected resource path is unsafe or exceeds its text limit")
    return paths


def _verify_chunk(chunk: dict, raw: bytes) -> None:
    if len(raw) != chunk["physical_length"] or len(raw) < 16:
        raise ResourceExtractError("Required chunk physical size disagrees with manifest")
    if chunk["logical_length"] > len(raw) - 16:
        raise ResourceExtractError("Required logical span overlaps the SSRC footer")
    magic, index, hash64 = struct.unpack_from("<4sIQ", raw, len(raw) - 16)
    if magic != b"SSRC" or index != chunk["index"] or hash64 != chunk["hash64"]:
        raise ResourceExtractError("Required SSRC footer magic, index, or checksum disagrees with manifest")
    if ssra.xxh64(raw[:chunk["logical_length"]]) != chunk["hash64"]:
        raise ResourceExtractError("Required chunk logical payload XXH64 mismatch")


def _stored_resource(item: dict, chunks: list[dict], supplied: dict[str, tuple[str, bytes]],
                     verified: set[int]) -> tuple[bytes, list[dict]]:
    start, end = item["offset"], item["offset"] + item["stored_length"]
    pieces, ranges = [], []
    cursor = start
    for chunk in chunks:
        if chunk["group_id"] != item["group_id"]:
            continue
        chunk_start = chunk["logical_start"]
        chunk_end = chunk_start + chunk["logical_length"]
        overlap_start, overlap_end = max(start, chunk_start), min(end, chunk_end)
        if overlap_start >= overlap_end:
            continue
        if overlap_start != cursor:
            raise ResourceExtractError("Selected resource has a gap in its logical chunk mapping")
        filename = chunk["filename"]
        if filename is None or filename not in supplied:
            raise ResourceExtractError(f"Required chunk is not supplied: {filename or 'unknown filename'}")
        label, raw = supplied[filename]
        if chunk["row"] not in verified:
            _verify_chunk(chunk, raw)
            verified.add(chunk["row"])
        local_start = overlap_start - chunk_start
        length = overlap_end - overlap_start
        pieces.append(raw[local_start:local_start + length])
        ranges.append({"chunk_row": chunk["row"], "chunk_index": chunk["index"],
                       "group_id": chunk["group_id"], "chunk_filename": filename,
                       "source_archive_path": label, "logical_group_offset": overlap_start,
                       "physical_offset": local_start, "bytes": length,
                       "chunk_logical_length": chunk["logical_length"],
                       "chunk_physical_length": chunk["physical_length"],
                       "chunk_xxh64": f"{chunk['hash64']:016x}"})
        cursor = overlap_end
    if cursor != end:
        raise ResourceExtractError("Selected resource is not fully covered by supplied chunks")
    return b"".join(pieces), ranges


def _decode_resource(stored: bytes, item: dict) -> bytes:
    if item["encryption"] != 0:
        raise ResourceExtractError("Encrypted resources are unsupported; no decryption is performed")
    if item["compression"] == 0:
        if len(stored) != item["decoded_length"]:
            raise ResourceExtractError("Uncompressed stored and decoded resource sizes disagree")
        return stored
    if item["compression"] != 1:
        raise ResourceExtractError("Unsupported resource compression")
    try:
        import zstandard
    except ImportError as error:
        raise ResourceExtractError("Zstd extraction requires optional trusted zstandard==0.25.0") from error
    if zstandard.__version__ != "0.25.0":
        raise ResourceExtractError("Zstd extraction requires trusted zstandard==0.25.0")
    try:
        parameters = zstandard.get_frame_parameters(stored)
        if parameters.dict_id != 0:
            raise ResourceExtractError("Zstd dictionaries are unsupported")
        if parameters.window_size > MAX_FILE_BYTES:
            raise ResourceExtractError("Zstd frame window exceeds 64 MiB")
        if parameters.content_size != item["decoded_length"] or parameters.content_size > MAX_FILE_BYTES:
            raise ResourceExtractError("Zstd frame content size differs from bounded manifest length")
        decoded = zstandard.ZstdDecompressor().decompress(
            stored, max_output_size=item["decoded_length"], read_across_frames=False, allow_extra_data=False)
    except zstandard.ZstdError as error:
        raise ResourceExtractError("Invalid or non-single-frame bounded Zstd resource") from error
    if len(decoded) != item["decoded_length"]:
        raise ResourceExtractError("Decoded resource length disagrees with manifest")
    return decoded


def extract_resources(resources: Path, paths: list[str], output: Path) -> dict:
    paths = _selected_paths(paths)
    output = Path(output)
    if os.path.lexists(output):
        raise ResourceExtractError("Output already exists; choose a new directory to preserve research")
    if any(ord(character) < 32 or ord(character) == 127 for character in str(output)):
        raise ResourceExtractError("Output path contains control characters")
    source, manifest_hash, payloads = _load_resources(Path(resources))
    try:
        manifest = ssra.parse_ssra(payloads["files/00.bin"])
    except ssra.SSRAError as error:
        raise ResourceExtractError(str(error)) from error
    files = {item["path"]: item for item in manifest["files"]}
    selected, total = [], 0
    for path in paths:
        if path not in files:
            raise ResourceExtractError(f"Selected resource is absent from manifest: {path}")
        item = files[path]
        if item["flags"] & 1:
            raise ResourceExtractError("Selected resource is a tombstone")
        if item["encryption"] != 0:
            raise ResourceExtractError("Encrypted resources are unsupported; no decryption is performed")
        if item["compression"] not in (0, 1):
            raise ResourceExtractError("Unsupported resource compression")
        if item["stored_length"] > MAX_FILE_BYTES or item["decoded_length"] > MAX_FILE_BYTES:
            raise ResourceExtractError("Selected stored or decoded resource exceeds 64 MiB")
        total += item["decoded_length"]
        if total > MAX_TOTAL_BYTES:
            raise ResourceExtractError("Selected decoded resources exceed 128 MiB combined")
        selected.append(item)
    supplied = {Path(target.relative_path).name: (f"files/{ordinal:02d}.bin", payloads[f"files/{ordinal:02d}.bin"])
                for ordinal, target in enumerate(TARGETS) if ordinal > 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ssra-resource-extract-", dir=output.parent) as temporary:
        stage = Path(temporary)
        (stage / "files").mkdir()
        verified_chunks, extracted = set(), []
        for ordinal, item in enumerate(selected):
            stored, ranges = _stored_resource(item, manifest["chunks"], supplied, verified_chunks)
            decoded = _decode_resource(stored, item)
            decoded_xxh64 = ssra.xxh64(decoded)
            expected_hash = item["file_hash64"]
            if expected_hash is not None and decoded_xxh64 != expected_hash:
                raise ResourceExtractError("Decoded resource FHSH XXH64 mismatch")
            label = f"files/{ordinal:02d}.bin"
            (stage / label).write_bytes(decoded)
            (stage / label).chmod(0o600)
            extracted.append({"archive_path": label, "resource_path": item["path"],
                              "manifest_file_row": item["row"], "group_id": item["group_id"],
                              "logical_offset": item["offset"], "stored_bytes": len(stored),
                              "stored_sha256": _sha256(stored), "decoded_bytes": len(decoded),
                              "decoded_sha256": _sha256(decoded), "decoded_xxh64": f"{decoded_xxh64:016x}",
                              "fhsh_xxh64": f"{expected_hash:016x}" if expected_hash is not None else None,
                              "fhsh_verified": expected_hash is not None,
                              "compression": item["compression"], "encryption": item["encryption"],
                              "ranges": ranges})
        result = {"schema_version": 1, "format": "selected_ssra_v4_resource_extraction",
                  "source": source, "source_manifest": {"archive_path": "files/00.bin",
                  "bytes": len(payloads["files/00.bin"]), "sha256": manifest_hash},
                  "selected_count": len(extracted), "decoded_bytes": total,
                  "verified_required_chunks": len(verified_chunks), "files": extracted,
                  "limitations": "Resources remain inert reference bytes. SHA-256, SSRC, and FHSH "
                  "XXH64 checks establish content identity and internal consistency, not CDN authenticity. "
                  "Receipt ZIP hashes are preserved declared identities; source ZIPs are not reread here. "
                  "No resource code is executed and encryption is unsupported."}
        (stage / "resource-index.json").write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n",
                                                  encoding="utf-8")
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
    parser.add_argument("--resources", type=Path, required=True, help="Verified Android receipt directory")
    parser.add_argument("--path", action="append", required=True, help="Exact manifest resource path; repeat up to 64 times")
    parser.add_argument("--output", type=Path, required=True, help="New directory for ordinal inert output files")
    args = parser.parse_args(argv)
    try:
        result = extract_resources(args.resources, args.path, args.output)
    except (ResourceExtractError, OSError) as error:
        print(f"SSRA extraction failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
