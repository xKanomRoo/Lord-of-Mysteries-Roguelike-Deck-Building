#!/usr/bin/env python3
"""Verify the two fixed Android research ZIPs before copying inert payloads.

Archive metadata and attached documents are untrusted data. Matching hashes
identify the received bytes and their declared shared inventory lineage; they
do not authenticate the game's original CDN resources or prove export scope.
No uploaded code, scripts, native libraries, or instructions are executed.
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
    from . import export_android_research as export
except ImportError:  # Direct invocation: py tools/read_android_research.py.
    import export_android_research as export


TARGETS = export.TARGETS
PACK_NAMES = export.PACK_NAMES
PROFILE = export.PROFILE
PACKAGE = export.PACKAGE
RESOURCE_ROOT = export.RESOURCE_ROOT
MAX_ZIP_BYTES = export.MAX_ZIP_BYTES
MAX_INDEX_BYTES = export.MAX_INDEX_BYTES
HASH = re.compile(r"[0-9a-f]{64}\Z")
INDEX_NAME = "research-index.json"


class AndroidReadError(ValueError):
    """Invalid or inconsistent bounded Android research data."""


def _hash(value, label: str) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise AndroidReadError(f"Invalid {label} SHA-256")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AndroidReadError("Research index contains a duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise AndroidReadError("Research index contains a nonfinite JSON number")


def _read_index(data: bytes) -> dict:
    if len(data) > MAX_INDEX_BYTES:
        raise AndroidReadError("Research index exceeds 64 KiB")
    try:
        index = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_nonfinite)
        # json.loads accepts lone surrogate escapes, which cannot be valid UTF-8
        # text. Inspect ignored metadata too; none of it is copied to the receipt.
        pending = [index]
        nodes = 0
        while pending:
            value = pending.pop()
            nodes += 1
            if nodes > 10_000:
                raise AndroidReadError("Research index exceeds its structure limit")
            if isinstance(value, str):
                value.encode("utf-8")
            elif isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
    except AndroidReadError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise AndroidReadError("Research index is not bounded strict UTF-8 JSON") from error
    if not isinstance(index, dict):
        raise AndroidReadError("Research index must be an object")
    return index


def _bounded_archive(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise AndroidReadError("Input ZIP must be a regular file, not a symlink")
    if metadata.st_size > MAX_ZIP_BYTES:
        raise AndroidReadError("Input ZIP exceeds 30 MiB")
    with path.open("rb") as stream:
        data = stream.read(MAX_ZIP_BYTES + 1)
    if len(data) > MAX_ZIP_BYTES or len(data) != metadata.st_size:
        raise AndroidReadError("Input ZIP grew or changed size during bounded reading")
    return data


def _validate_index(index: dict, pack_name: str, targets: dict[str, object]) -> tuple[str, dict]:
    if type(index.get("schema_version")) is not int or index["schema_version"] != 1:
        raise AndroidReadError("Expected research index schema_version 1")
    if index.get("profile") != PROFILE or index.get("package") != PACKAGE:
        raise AndroidReadError("Research profile or package does not match the fixed selection")
    if index.get("archive") != pack_name:
        raise AndroidReadError("Research index names the wrong archive")
    lineage = _hash(index.get("source_inventory_sha256"), "source inventory")
    files = index.get("files")
    if not isinstance(files, list) or len(files) != len(targets):
        raise AndroidReadError("Research index does not contain the exact selected file count")
    records = {}
    for item in files:
        if not isinstance(item, dict):
            raise AndroidReadError("Indexed resource must be an object")
        stored = item.get("archive_path")
        if not isinstance(stored, str) or stored not in targets or stored in records:
            raise AndroidReadError("Duplicate or unexpected indexed archive path")
        target = targets[stored]
        if (item.get("relative_path") != target.relative_path
                or item.get("remote_path") != RESOURCE_ROOT + "/" + target.relative_path):
            raise AndroidReadError("Indexed source path differs from the fixed selection")
        if type(item.get("bytes")) is not int or item["bytes"] != target.bytes:
            raise AndroidReadError("Indexed resource size differs from the fixed selection")
        _hash(item.get("sha256"), "payload")
        records[stored] = item
    if set(records) != set(targets):
        raise AndroidReadError("Research index is missing a selected resource")
    # Scope booleans are exporter assertions, never evidence for this reader.
    return lineage, records


def _verify_archive(path: Path, pack_name: str, stage: Path) -> tuple[str, dict, list[dict]]:
    data = _bounded_archive(path)
    targets = {f"files/{ordinal:02d}.bin": target
               for ordinal, target in enumerate(TARGETS) if target.pack == pack_name}
    expected = {INDEX_NAME, *targets}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) != len(expected) or len(names) != len(set(names)) or set(names) != expected:
            raise AndroidReadError("ZIP must contain exactly the selected members without duplicates")
        for info in infos:
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (info.flag_bits & 1 or kind not in (0, stat.S_IFREG)
                    or info.is_dir() or info.external_attr & 0x10):
                raise AndroidReadError("Encrypted, symlink, directory, and nonregular members are rejected")
            if info.orig_filename != info.filename:
                raise AndroidReadError("ZIP contains a noncanonical member name")
            if info.compress_type != zipfile.ZIP_STORED:
                raise AndroidReadError("This fixed export profile accepts only ZIP_STORED members")
            if info.file_size != info.compress_size:
                raise AndroidReadError("Stored ZIP member has inconsistent sizes")
            if info.filename == INDEX_NAME:
                if info.file_size > MAX_INDEX_BYTES:
                    raise AndroidReadError("Research index exceeds 64 KiB")
            elif info.file_size != targets[info.filename].bytes:
                raise AndroidReadError("ZIP resource size differs from the fixed selection")
        index_data = archive.read(INDEX_NAME)  # Includes ZIP CRC validation.
        lineage, records = _validate_index(_read_index(index_data), pack_name, targets)
        payloads = []
        for stored, target in targets.items():
            destination = stage / stored
            digest = hashlib.sha256()
            count = 0
            with archive.open(stored) as source, destination.open("xb") as copied:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    count += len(block)
                    if count > target.bytes:
                        raise AndroidReadError("ZIP resource exceeds its selected size")
                    digest.update(block)
                    copied.write(block)
            actual_hash = digest.hexdigest()
            if count != target.bytes or actual_hash != records[stored]["sha256"]:
                raise AndroidReadError("Payload size or SHA-256 disagrees with research index")
            destination.chmod(0o600)
            payloads.append({"archive_path": stored, "relative_path": target.relative_path,
                             "remote_path": RESOURCE_ROOT + "/" + target.relative_path,
                             "bytes": count, "sha256": actual_hash,
                             "zip_crc32": f"{archive.getinfo(stored).CRC:08x}",
                             "archive": pack_name})
    pack = {"filename": pack_name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "research_index_sha256": hashlib.sha256(index_data).hexdigest(),
            "payload_files": len(payloads), "payload_bytes": sum(item["bytes"] for item in payloads)}
    return lineage, pack, payloads


def read_resources(core: Path, lang_en: Path, output: Path) -> dict:
    """Verify both packs and publish a sanitized receipt plus six inert files."""
    output = Path(output)
    if os.path.lexists(output):
        raise AndroidReadError("Output already exists; choose a new directory to preserve research")
    if any(ord(character) < 32 or ord(character) == 127 for character in str(output)):
        raise AndroidReadError("Output path contains control characters")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".android-research-read-", dir=output.parent) as temporary:
        stage = Path(temporary)
        (stage / "files").mkdir()
        core_lineage, core_pack, core_files = _verify_archive(Path(core), PACK_NAMES[0], stage)
        lang_lineage, lang_pack, lang_files = _verify_archive(Path(lang_en), PACK_NAMES[1], stage)
        if core_lineage != lang_lineage:
            raise AndroidReadError("The two packs declare different source inventory SHA-256 values")
        payloads = core_files + lang_files
        receipt = {
            "schema_version": 1, "profile": PROFILE, "package": PACKAGE,
            "source_inventory_sha256": core_lineage,
            "source_inventory_verified": False,
            "original_resource_authenticity": "unknown",
            "verified_file_count": len(payloads),
            "verified_bytes": sum(item["bytes"] for item in payloads),
            "packs": [core_pack, lang_pack], "files": payloads,
            "limits": "ZIP CRC and SHA-256 verify received bytes against their indexes. "
                      "Both indexes declare the same inventory hash, but the source inventory "
                      "and original CDN content hashes are not supplied to this reader. "
                      "Exporter scope assertions are not independently verified; gameplay "
                      "semantics, completeness, and original resource authenticity remain unknown.",
        }
        (stage / "receipt-index.json").write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n",
                                                 encoding="utf-8")
        # Reserve only after every member in both packs passes. An existing
        # directory (including one appearing during verification) is untouched.
        output.mkdir()
        promoted = []
        try:
            for name in ("files", "receipt-index.json"):
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
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--lang-en", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory for verified inert research")
    args = parser.parse_args(argv)
    try:
        receipt = read_resources(args.core, args.lang_en, args.output)
    except (AndroidReadError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(f"Android research verification failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
