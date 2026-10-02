#!/usr/bin/env python3
"""Verify and inventory bounded ARM64 native libraries without executing APK code."""

from __future__ import annotations

import argparse
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
from typing import Any, BinaryIO
import zipfile

try:  # Supports both module imports and Windows `py tools/inspect_native_apk.py`.
    from .create_research_pack import (
        Limits, PackError, _hash, _metadata_guard, _read_entry, _verify_entry,
        _zip_entries, read_report, sha256_file,
    )
except ImportError:
    from create_research_pack import (
        Limits, PackError, _hash, _metadata_guard, _read_entry, _verify_entry,
        _zip_entries, read_report, sha256_file,
    )


MAX_APK_BYTES = 30 * 1024 * 1024
MAX_LIBRARY_BYTES = 80 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
NATIVE_PATH = re.compile(r"lib/arm64-v8a/[A-Za-z0-9_+.-]+\.so\Z")
ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")


def _range(offset: int, length: int, total: int, label: str) -> None:
    if offset > total or length > total - offset:
        raise PackError(f"ELF {label} is outside the library byte range")


def _read_at(stream: BinaryIO, offset: int, size: int, total: int, label: str) -> bytes:
    _range(offset, size, total, label)
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise PackError(f"ELF {label} is truncated")
    return data


def inspect_elf64(source: bytes | BinaryIO, size: int | None = None) -> dict[str, Any]:
    """Inspect only fixed ELF tables; never load a library or interpret its code."""
    if isinstance(source, bytes):
        stream: BinaryIO = io.BytesIO(source)
        size = len(source)
    else:
        stream = source
        if size is None:
            stream.seek(0, 2)
            size = stream.tell()
    if size < ELF_HEADER.size or size > MAX_LIBRARY_BYTES:
        raise PackError("ELF library is truncated or exceeds the byte limit")
    fields = ELF_HEADER.unpack(_read_at(stream, 0, ELF_HEADER.size, size, "header"))
    (ident, kind, machine, version, entry, phoff, shoff, flags, header_size,
     phentsize, phnum, shentsize, shnum, shstrndx) = fields
    if ident[:4] != b"\x7fELF" or ident[4:7] != b"\x02\x01\x01":
        raise PackError("Expected ELF64 little-endian version 1 library")
    if kind != 3 or machine != 183 or version != 1 or header_size != 64:
        raise PackError("Expected an ARM64 ELF shared library with a 64-byte header")
    if phnum == 0xFFFF or (shnum == 0 and shoff != 0) or shstrndx == 0xFFFF:
        raise PackError("Extended ELF table numbering is unsupported")
    if phnum > 4096 or shnum > 4096:
        raise PackError("ELF table count exceeds inspection limit")
    if phnum and phentsize != PROGRAM_HEADER.size:
        raise PackError("ELF program-header entry size is unsupported")
    if shnum and shentsize != SECTION_HEADER.size:
        raise PackError("ELF section-header entry size is unsupported")
    if (phnum and phoff < header_size) or (shnum and shoff < header_size):
        raise PackError("ELF table overlaps the fixed header")
    if shstrndx and shstrndx >= shnum:
        raise PackError("ELF section-name table index is outside the section table")
    _range(phoff, phnum * phentsize, size, "program-header table")
    _range(shoff, shnum * shentsize, size, "section-header table")
    programs = []
    for index in range(phnum):
        (ptype, pflags, offset, address, physical, file_size, memory_size,
         alignment) = PROGRAM_HEADER.unpack(_read_at(
            stream, phoff + index * phentsize, phentsize, size, "program header"))
        _range(offset, file_size, size, f"program {index}")
        if ptype == 1 and file_size > memory_size:
            raise PackError("ELF load segment has more file bytes than memory bytes")
        programs.append({"index": index, "type": ptype, "flags": pflags,
                         "offset": offset, "bytes": file_size,
                         "memory_bytes": memory_size, "address_hex": hex(address),
                         "alignment": alignment})
    sections = []
    for index in range(shnum):
        (name, stype, sflags, address, offset, length, link, info,
         alignment, entry_size) = SECTION_HEADER.unpack(_read_at(
            stream, shoff + index * shentsize, shentsize, size, "section header"))
        # SHT_NOBITS occupies memory only; its nominal offset may exceed EOF.
        if stype != 8:
            _range(offset, length, size, f"section {index}")
        if link >= shnum and link:
            raise PackError("ELF section link is outside the section table")
        sections.append({"index": index, "type": stype, "flags": sflags,
                         "offset": offset, "bytes": length,
                         "stored_in_file": stype != 8,
                         "address_hex": hex(address), "alignment": alignment,
                         "entry_bytes": entry_size, "link": link, "info": info})
    return {"format": "ELF64", "byte_order": "little", "machine": machine,
            "architecture": "AArch64", "elf_type": kind,
            "entry_point_hex": hex(entry), "flags": flags,
            "program_header_count": phnum, "section_header_count": shnum,
            "section_name_table_index": shstrndx,
            "programs": programs, "sections": sections,
            "inspection": "fixed_headers_and_byte_ranges_only"}


def _empty_output(output: Path) -> None:
    if output.is_symlink() or (os.path.lexists(output) and
                              (not output.is_dir() or any(output.iterdir()))):
        raise PackError("Output must be a new or empty directory; existing research is preserved")


def inspect_native_apk(input_path: Path, output: Path, expected_sha256: str | None = None,
                       report_path: Path | None = None) -> dict[str, Any]:
    """Verify all selected entries in staging before publishing the inventory."""
    input_path, output = Path(input_path), Path(output)
    _empty_output(output)
    if expected_sha256 is not None:
        _hash(expected_sha256, "expected APK")
    limits = replace(Limits(), max_input_bytes=MAX_APK_BYTES,
                     max_file_bytes=MAX_LIBRARY_BYTES, max_selected_bytes=MAX_TOTAL_BYTES,
                     max_entries=4096)
    size = input_path.stat().st_size
    if size > MAX_APK_BYTES:
        raise PackError("Input APK exceeds the 30 MiB limit")
    apk_hash = sha256_file(input_path)
    if expected_sha256 is not None and expected_sha256 != apk_hash:
        raise PackError("APK SHA-256 does not match the expected identity")
    report = indexed = expected_apk = None
    report_hash = None
    if report_path is not None:
        report_path = Path(report_path)
        report, indexed = read_report(report_path, limits)
        report_hash = sha256_file(report_path)
        matches = [entry for entry in indexed.values()
                   if entry["container"] == report["input"]["filename"]
                   and entry.get("status") == "nested_archive"
                   and entry.get("sha256") == apk_hash and entry["bytes"] == size]
        if len(matches) != 1:
            raise PackError("APK identity is not a unique root nested APK in the report")
        expected_apk = matches[0]

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="native-inventory-", dir=output.parent))
    try:
        (staging / "files").mkdir()
        files = []
        total_bytes = 0
        with input_path.open("rb") as stream:
            _metadata_guard(stream, limits)
            with zipfile.ZipFile(stream) as archive:
                entries = _zip_entries(archive, limits)
                selected = [entry for entry in entries if not entry.is_dir()
                            and NATIVE_PATH.fullmatch(entry.filename)]
                if not selected:
                    raise PackError("APK contains no allowlisted ARM64 native libraries")
                selected.sort(key=lambda entry: entry.filename)
                if sum(entry.file_size for entry in selected) > MAX_TOTAL_BYTES:
                    raise PackError("Selected native libraries exceed the 96 MiB limit")
                for number, entry in enumerate(selected):
                    expected = None
                    evidence = input_path.name + "!" + entry.filename
                    if expected_apk is not None:
                        evidence = expected_apk["evidence_path"] + "!" + entry.filename
                        expected = indexed.get(evidence)
                        if expected is None:
                            raise PackError("Native library is missing from the supplied report")
                        _verify_entry(entry, expected)
                    partial = staging / "files" / f"{number}.partial"
                    with partial.open("w+b") as destination:
                        _, digest = _read_entry(archive, entry, MAX_LIBRARY_BYTES, destination)
                        if expected and expected.get("sha256") is not None:
                            if digest != expected["sha256"]:
                                raise PackError("Native library SHA-256 disagrees with report")
                        destination.flush()
                        elf = inspect_elf64(destination, entry.file_size)
                    stored = "files/" + digest + ".so"
                    final_path = staging / stored
                    if final_path.exists():
                        partial.unlink()  # Identical bytes may have multiple source names.
                    else:
                        partial.rename(final_path)
                        final_path.chmod(0o600)
                    total_bytes += entry.file_size
                    files.append({"original_path": entry.filename, "evidence_path": evidence,
                                  "stored_path": stored, "sha256": digest,
                                  "bytes": entry.file_size, "compressed_bytes": entry.compress_size,
                                  "crc32": f"{entry.CRC:08x}", "elf": elf,
                                  "transformation": "unchanged_static_binary",
                                  "report_sha256_verified": bool(expected and expected.get("sha256"))})
        result = {"schema_version": 1, "analysis_type": "static_native_apk_inventory",
                  "input": {"filename": input_path.name, "bytes": size, "sha256": apk_hash},
                  "report_sha256": report_hash,
                  "source": ({"input": report["input"],
                              "apk_evidence_path": expected_apk["evidence_path"]}
                             if report is not None else None),
                  "library_count": len(files), "library_bytes": total_bytes,
                  "files": files, "static_only": True,
                  "limitations": ["No APK or native-library code was executed.",
                                  "Fixed ELF headers and byte ranges do not recover gameplay or APIs.",
                                  "Outer XAPK bytes are not independently verified by this tool."]}
        (staging / "native-index.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _empty_output(output)  # Recheck immediately before publishing staged files.
        if output.exists():
            output.rmdir()  # Fails safely if contents appeared since the check.
        staging.rename(output)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="ARM64 split APK; never executed")
    parser.add_argument("--output", type=Path, required=True, help="New or empty research directory")
    parser.add_argument("--expected-sha256", help="Optional expected APK SHA-256")
    parser.add_argument("--report", type=Path, help="Optional completed analyze_apk.py report")
    args = parser.parse_args(argv)
    try:
        result = inspect_native_apk(args.input, args.output, args.expected_sha256, args.report)
    except (PackError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(f"Native APK inventory failed: {error}", file=sys.stderr)
        return 1
    print(f"Verified {result['library_count']} ARM64 libraries ({result['library_bytes']} bytes).")
    print(f"APK SHA-256: {result['input']['sha256']}")
    print(f"Inventory: {args.output / 'native-index.json'}")
    print("Static research only; no APK or native-library code was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
