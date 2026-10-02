#!/usr/bin/env python3
"""Extract one bounded, report-verified APK for static research; never run it."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

try:  # Both module imports and `py tools/extract_nested_apk.py` work.
    from .create_research_pack import (
        Limits, PackError, _metadata_guard, _read_entry, _verify_entry,
        _zip_entries, read_report, sha256_file,
    )
except ImportError:
    from create_research_pack import (
        Limits, PackError, _metadata_guard, _read_entry, _verify_entry,
        _zip_entries, read_report, sha256_file,
    )


MAX_OUTPUT_BYTES = 30 * 1024 * 1024
DEFAULT_ENTRY = "config.arm64_v8a.apk"


def extract_nested_apk(input_path: Path, report_path: Path, output_path: Path,
                       entry: str = DEFAULT_ENTRY,
                       limits: Limits | None = None) -> dict[str, Any]:
    """Publish verified bytes to a new file only after all static checks pass."""
    limits = limits or Limits()
    input_path, report_path, output_path = map(Path, (input_path, report_path, output_path))
    if os.path.lexists(output_path):
        raise PackError("Output already exists; choose a new --output filename")
    if output_path.resolve() in {input_path.resolve(), report_path.resolve()}:
        raise PackError("Output must not replace an input")
    if (not isinstance(entry, str) or not entry.lower().endswith(".apk")
            or any(character in entry for character in "/\\!")
            or any(ord(character) < 32 or ord(character) == 127 for character in entry)
            or re.match(r"^[A-Za-z]:", entry)):
        raise PackError("Select a root APK basename from the completed report")

    report, indexed = read_report(report_path, limits)
    report_hash = sha256_file(report_path)
    source = report["input"]
    evidence = source["filename"] + "!" + entry
    expected = indexed.get(evidence)
    if (expected is None or expected["container"] != source["filename"]
            or expected.get("status") != "nested_archive"):
        raise PackError("Selected entry must be a root nested_archive APK in the completed report")
    expected_hash = expected.get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise PackError("Selected nested APK needs a SHA-256 in the report")
    byte_limit = min(MAX_OUTPUT_BYTES, limits.max_nested_bytes, limits.max_pack_bytes)
    if expected["bytes"] > byte_limit:
        raise PackError("Selected APK exceeds the 30 MiB upload or configured byte limit")
    input_bytes = input_path.stat().st_size
    if input_bytes > limits.max_input_bytes:
        raise PackError("Input archive exceeds byte limit")
    if input_bytes != source["bytes"] or sha256_file(input_path) != source["sha256"]:
        raise PackError("Input SHA-256/size does not match the report; regenerate its inventory")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        # Own unique temp file: do not consume, replace or remove a user's .partial file.
        with tempfile.NamedTemporaryFile(mode="w+b", prefix="nested-apk-", suffix=".partial",
                                         dir=output_path.parent, delete=False) as destination:
            temporary_path = Path(destination.name)
            with input_path.open("rb") as outer_file:
                _metadata_guard(outer_file, limits)
                with zipfile.ZipFile(outer_file) as outer:
                    entries = _zip_entries(outer, limits)
                    selected = next((info for info in entries if info.filename == entry), None)
                    if selected is None or selected.is_dir():
                        raise PackError("Selected APK from report is missing from the input archive")
                    _verify_entry(selected, expected)
                    _, actual_hash = _read_entry(outer, selected, byte_limit, destination)
                    if actual_hash != expected_hash:
                        raise PackError("Nested APK SHA-256 disagrees with report")
            destination.flush()
            _metadata_guard(destination, limits)
            with zipfile.ZipFile(destination) as nested:
                nested_entries = _zip_entries(nested, limits)
                nested_count = sum(not item.is_dir() for item in nested_entries)
        # A same-filesystem hard link is atomic and never replaces an existing path.
        # This works on NTFS; unsupported drives fail safely without publishing bytes.
        try:
            os.link(temporary_path, output_path)
        except FileExistsError as error:
            raise PackError("Output appeared during extraction; existing file was preserved") from error
        except OSError as error:
            raise PackError("Could not atomically publish APK; choose a drive supporting hard links") from error
        return {
            "analysis_type": "static_verified_nested_apk_extraction",
            "input": {key: source[key] for key in ("filename", "bytes", "sha256")},
            "report_sha256": report_hash,
            "evidence_path": evidence,
            "bytes": expected["bytes"],
            "sha256": actual_hash,
            "nested_file_count": nested_count,
            "output": str(output_path),
            "static_only": True,
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Original XAPK matching report.json")
    parser.add_argument("--report", type=Path, required=True, help="Completed analyze_apk.py report")
    parser.add_argument("--entry", default=DEFAULT_ENTRY, help="Root APK basename; default: %(default)s")
    parser.add_argument("--output", type=Path, required=True, help="New file path; existing files are preserved")
    args = parser.parse_args(argv)
    try:
        result = extract_nested_apk(args.input, args.report, args.output, args.entry)
    except (PackError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(f"APK extraction failed: {error}", file=sys.stderr)
        return 1
    print(f"Created {result['output']}: {result['bytes']} bytes, "
          f"{result['bytes'] / (1024 * 1024):.2f} MiB, {result['nested_file_count']} nested files.")
    print(f"Source: {result['evidence_path']}")
    print(f"SHA-256: {result['sha256']}")
    print(f"XAPK SHA-256: {result['input']['sha256']}")
    print(f"Report SHA-256: {result['report_sha256']}")
    print("Static research only; no APK code was executed or decrypted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
