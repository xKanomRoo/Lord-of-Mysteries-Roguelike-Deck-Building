#!/usr/bin/env python3
"""Verify and unpack a bounded static research pack without executing its contents."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import zipfile

MAX_PACK_BYTES = 30 * 1024 * 1024
MAX_UNPACKED_BYTES = 32 * 1024 * 1024
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_FILES = 1000
STORED_PATH = re.compile(r"files/[0-9a-f]{64}\.[a-z0-9]{1,10}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


class PackReadError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackReadError("Duplicate metadata key")
        result[key] = value
    return result


def valid_hash(value, label):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise PackReadError(f"Invalid {label} SHA-256")
    return value


def read_pack(path: Path, expected_input_hash: str | None = None):
    """Return verified data in memory; validate everything before writing anything."""
    if path.stat().st_size > MAX_PACK_BYTES:
        raise PackReadError("Pack exceeds 30 MiB")
    pack_hash = digest(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) > MAX_FILES + 1 or len(names) != len(set(names)):
            raise PackReadError("Duplicate or excessive ZIP entries")
        if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise PackReadError("Unpacked data exceeds limit")
        for info in infos:
            if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                raise PackReadError("Encrypted entries and symlinks are not accepted")
            if info.filename != "pack-index.json" and not STORED_PATH.fullmatch(info.filename):
                raise PackReadError("Unsafe or unexpected stored path")
            maximum = MAX_INDEX_BYTES if info.filename == "pack-index.json" else MAX_FILE_BYTES
            if info.file_size > maximum or info.file_size / max(1, info.compress_size) > 300:
                raise PackReadError("Member size or compression ratio exceeds limit")
        if "pack-index.json" not in names:
            raise PackReadError("Missing pack index")
        try:
            index = json.loads(archive.read("pack-index.json").decode("utf-8"), object_pairs_hook=unique_object)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise PackReadError("Invalid pack index JSON") from error
        if (not isinstance(index, dict) or index.get("schema_version") != 1
                or index.get("pack_type") != "bounded_static_bootstrap_research"):
            raise PackReadError("Unsupported research pack")
        identity = index.get("input")
        if not isinstance(identity, dict):
            raise PackReadError("Missing source identity")
        source_hash = valid_hash(identity.get("sha256"), "source")
        if expected_input_hash and source_hash != valid_hash(expected_input_hash, "expected source"):
            raise PackReadError("Source identity does not match expected XAPK")
        valid_hash(index.get("report_sha256"), "source report")
        nested = index.get("nested_apk")
        if not isinstance(nested, dict):
            raise PackReadError("Missing nested APK identity")
        valid_hash(nested.get("sha256"), "nested APK")
        files = index.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
            raise PackReadError("Invalid indexed file count")
        if type(index.get("selected_count")) is not int or index["selected_count"] != len(files):
            raise PackReadError("Selected count disagrees with index")
        verified = {}
        sources = set()
        for item in files:
            if not isinstance(item, dict):
                raise PackReadError("Invalid indexed file")
            stored = item.get("stored_path")
            evidence = item.get("evidence_path")
            original = item.get("original_path")
            if not isinstance(stored, str) or not STORED_PATH.fullmatch(stored) or stored in verified:
                raise PackReadError("Duplicate or invalid indexed path")
            if not isinstance(evidence, str) or not evidence or len(evidence) > 16000 or evidence in sources:
                raise PackReadError("Duplicate or invalid evidence path")
            if not isinstance(original, str) or not original or len(original) > 16000 or "\x00" in original:
                raise PackReadError("Invalid original path")
            sources.add(evidence)
            if stored not in names:
                raise PackReadError("Indexed file is missing")
            data = archive.read(stored)  # ZIP validates the member CRC too.
            if type(item.get("stored_bytes")) is not int or len(data) != item["stored_bytes"]:
                raise PackReadError("Stored size disagrees with index")
            if digest(data) != valid_hash(item.get("stored_sha256"), "stored file"):
                raise PackReadError("Stored content SHA-256 mismatch")
            valid_hash(item.get("original_sha256"), "original file")
            if item.get("transformation") == "unchanged_static_binary":
                if item["original_sha256"] != item["stored_sha256"] or item.get("original_bytes") != len(data):
                    raise PackReadError("Unchanged source content disagrees with index")
            verified[stored] = data
        if set(names) != {"pack-index.json", *verified}:
            raise PackReadError("ZIP contains files absent from index")
        if type(index.get("selected_bytes")) is not int or index["selected_bytes"] != sum(map(len, verified.values())):
            raise PackReadError("Selected byte count disagrees with files")
    return index, verified, pack_hash


def unpack_pack(path: Path, output: Path, expected_input_hash: str | None = None):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise PackReadError("Output must be new or empty; existing research is preserved")
    index, files, pack_hash = read_pack(path, expected_input_hash)
    summary = {
        "pack_sha256": pack_hash,
        "verified_file_count": len(files),
        "verified_bytes": sum(map(len, files.values())),
        "formats": dict(Counter(Path(item["original_path"]).suffix for item in index["files"])),
        "source_identity": index["input"],
        "limits": "Hashes verify packed bytes and reported lineage, not the unavailable complete XAPK or semantic gameplay.",
    }
    output.mkdir(parents=True, exist_ok=True)
    for stored, data in files.items():
        target = output / stored
        target.parent.mkdir(exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    with (output / "pack-index.json").open("x", encoding="utf-8") as stream:
        json.dump(index, stream, ensure_ascii=False, indent=2)
    with (output / "verification.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-input-sha256")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(unpack_pack(args.pack, args.output, args.expected_input_sha256), ensure_ascii=False, indent=2))
    except (PackReadError, OSError, zipfile.BadZipFile, RuntimeError) as error:
        print(f"Pack verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
