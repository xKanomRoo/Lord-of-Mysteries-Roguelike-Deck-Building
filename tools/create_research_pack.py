#!/usr/bin/env python3
"""Create a small, provenance-preserving static research pack; never run APK code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

try:  # Works both as `py tools/create_research_pack.py` and as a module.
    from .analyze_apk import SENSITIVE_KEY, SENSITIVE_PATH, inspect_text
except ImportError:
    from analyze_apk import SENSITIVE_KEY, SENSITIVE_PATH, inspect_text


class PackError(ValueError):
    """Invalid input or a safety bound that prevents creating a useful pack."""


@dataclass(frozen=True)
class Limits:
    max_report_bytes: int = 16 * 1024 * 1024
    max_metadata_bytes: int = 16 * 1024 * 1024
    max_input_bytes: int = 2 * 1024 * 1024 * 1024
    max_nested_bytes: int = 1024 * 1024 * 1024
    max_file_bytes: int = 16 * 1024 * 1024
    max_selected_bytes: int = 20 * 1024 * 1024
    max_pack_bytes: int = 30 * 1024 * 1024
    max_entries: int = 100_000
    max_compression_ratio: float = 300.0
    max_small_sdata_bytes: int = 100_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PackError(f"Invalid SHA-256: {label}")
    return value


def _size(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise PackError(f"Invalid byte count: {label}")
    return value


def _safe_path(name: Any, *, directory: bool = False) -> str:
    if not isinstance(name, str) or not name or len(name) > 4096:
        raise PackError("Invalid archive path")
    if ("\\" in name or "!" in name or name.startswith("/")
            or re.match(r"^[A-Za-z]:", name)
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise PackError(f"Unsafe archive path: {name!r}")
    parts = name.rstrip("/").split("/") if directory else name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PackError(f"Unsafe archive path: {name!r}")
    return name


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackError(f"Duplicate report JSON key: {key}")
        result[key] = value
    return result


def read_report(path: Path, limits: Limits) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if path.stat().st_size > limits.max_report_bytes:
        raise PackError("Report exceeds metadata size limit")
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            report = json.load(handle, object_pairs_hook=_json_object)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
        raise PackError("Report is not valid bounded JSON") from error
    if (not isinstance(report, dict) or type(report.get("schema_version")) is not int
            or report["schema_version"] != 1
            or report.get("analysis_type") != "static_archive_inventory"
            or report.get("analysis_status") not in {"completed", "completed_with_skips"}):
        raise PackError("A completed schema-version 1 analyze_apk.py report is required")
    source = report.get("input")
    if not isinstance(source, dict):
        raise PackError("Report has no input identity")
    root = _safe_path(source.get("filename"))
    if "/" in root:
        raise PackError("Report input filename must be a basename")
    _hash(source.get("sha256"), "report input")
    _size(source.get("bytes"), "report input")
    entries = report.get("entries")
    if not isinstance(entries, list) or len(entries) > limits.max_entries:
        raise PackError("Invalid report entry count")
    indexed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PackError("Invalid report entry")
        name = _safe_path(entry.get("path"), directory=str(entry.get("path", "")).endswith("/"))
        container = entry.get("container")
        if not isinstance(container, str) or len(container) > 12_300:
            raise PackError("Invalid report container")
        components = container.split("!")
        if components[0] != root or len(components) > 3:
            raise PackError("Report container is not descended from its input")
        for component in components:
            _safe_path(component)
        evidence = container + "!" + name
        if entry.get("evidence_path") != evidence or evidence in indexed:
            raise PackError("Duplicate or inconsistent report evidence path")
        _size(entry.get("bytes"), evidence)
        _size(entry.get("compressed_bytes"), evidence)
        if not isinstance(entry.get("crc32"), str) or not re.fullmatch(r"[0-9a-f]{8}", entry["crc32"]):
            raise PackError("Invalid report CRC")
        if "sha256" in entry:
            _hash(entry["sha256"], evidence)
        indexed[evidence] = entry
    return report, indexed


def select_reason(path: str, size: int, *, outer: bool, limits: Limits) -> str | None:
    """Return the research purpose for allowlisted entries only."""
    if SENSITIVE_PATH.search(path) or any(SENSITIVE_KEY.search(part) for part in path.split("/")):
        return None
    if outer:
        return "package_metadata" if path == "manifest.json" else None
    if path in {"AndroidManifest.xml", "resources.arsc"}:
        return "android_bootstrap_metadata"
    if path in {"assets/info.txt", "assets/progress.json", "assets/pre/bin/gitsha.txt"}:
        return "bootstrap_metadata"
    if path == "assets/pre/bin/arm64/init.jbin":
        return "compiled_bootstrap_static_only"
    suffix = PurePosixPath(path).suffix.lower()
    if path.startswith("assets/pre/ui/") and suffix in {".csb", ".sct", ".png"}:
        return "bootstrap_ui_reference"
    if path.startswith("assets/pre/Default/") and suffix == ".png":
        return "bootstrap_ui_reference"
    if path.startswith("assets/pre/effect/") and suffix in {".atlas", ".scsp", ".cfx", ".sct"}:
        return "bootstrap_effect_reference"
    if path.startswith("assets/sdata/") and size <= limits.max_small_sdata_bytes:
        return "small_unknown_sdata_format_sample"
    return None


def _zip_entries(archive: zipfile.ZipFile, limits: Limits) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > limits.max_entries:
        raise PackError("Archive entry count exceeds limit")
    seen: set[str] = set()
    for entry in entries:
        _safe_path(entry.filename, directory=entry.is_dir())
        canonical = entry.filename.rstrip("/")
        if canonical in seen:
            raise PackError(f"Duplicate archive path: {entry.filename}")
        seen.add(canonical)
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise PackError(f"Archive symlink is forbidden: {entry.filename}")
        if entry.flag_bits & 1:
            raise PackError(f"Encrypted archive entry is unsupported: {entry.filename}")
        if entry.file_size > 0 and entry.file_size / max(1, entry.compress_size) > limits.max_compression_ratio:
            raise PackError(f"Archive compression ratio exceeds limit: {entry.filename}")
    return entries


def _metadata_guard(stream: BinaryIO, limits: Limits) -> None:
    """Bound central-directory allocations before zipfile parses an archive."""
    stream.seek(0, 2)
    length = stream.tell()
    stream.seek(max(0, length - 65_557))
    tail = stream.read(65_557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise PackError("Missing ZIP end-of-central-directory record")
    record = struct.unpack_from("<4s4H2LH", tail, position)
    if position + 22 + record[7] != len(tail) or record[1] != 0 or record[2] != 0:
        raise PackError("Invalid or multi-disk ZIP end record")
    count, central_bytes = record[4], record[5]
    if count == 0xFFFF or central_bytes == 0xFFFFFFFF:
        if position < 20 or tail[position - 20:position - 16] != b"PK\x06\x07":
            raise PackError("Missing ZIP64 locator")
        _, disk, offset, disks = struct.unpack_from("<4sLQL", tail, position - 20)
        if disk != 0 or disks != 1:
            raise PackError("Multi-disk ZIP64 is unsupported")
        stream.seek(offset)
        extended = stream.read(56)
        if len(extended) != 56 or extended[:4] != b"PK\x06\x06":
            raise PackError("Missing ZIP64 end record")
        fields = struct.unpack("<4sQ2H2L4Q", extended)
        if fields[4] != 0 or fields[5] != 0:
            raise PackError("Multi-disk ZIP64 is unsupported")
        count, central_bytes = fields[7], fields[8]
    if count > limits.max_entries or central_bytes > limits.max_metadata_bytes:
        raise PackError("ZIP central-directory metadata exceeds limits")
    stream.seek(0)


def _verify_entry(entry: zipfile.ZipInfo, expected: dict[str, Any]) -> None:
    if (entry.file_size != expected["bytes"]
            or entry.compress_size != expected["compressed_bytes"]
            or f"{entry.CRC:08x}" != expected["crc32"]):
        raise PackError(f"Archive metadata disagrees with report: {entry.filename}")


def _read_entry(archive: zipfile.ZipFile, entry: zipfile.ZipInfo, limit: int,
                destination: BinaryIO | None = None) -> tuple[bytes | None, str]:
    if entry.file_size > limit:
        raise PackError(f"Entry exceeds byte limit: {entry.filename}")
    total = 0
    digest = hashlib.sha256()
    data = bytearray() if destination is None else None
    with archive.open(entry) as stream:
        while block := stream.read(min(1024 * 1024, limit - total + 1)):
            total += len(block)
            if total > limit:
                raise PackError(f"Entry exceeds actual byte limit: {entry.filename}")
            digest.update(block)
            if destination is not None:
                destination.write(block)
            else:
                data.extend(block)
    if total != entry.file_size:
        raise PackError(f"Entry length disagrees with ZIP metadata: {entry.filename}")
    return bytes(data) if data is not None else None, digest.hexdigest()


def create_pack(input_path: Path, report_path: Path, output_path: Path,
                limits: Limits | None = None) -> dict[str, Any]:
    limits = limits or Limits()
    input_path, report_path, output_path = map(Path, (input_path, report_path, output_path))
    if os.path.lexists(output_path):
        raise PackError("Output already exists; choose a new --output filename")
    if output_path.resolve() in {input_path.resolve(), report_path.resolve()}:
        raise PackError("Output must not replace an input")
    report, report_entries = read_report(report_path, limits)
    source = report["input"]
    actual_size = input_path.stat().st_size
    if actual_size > limits.max_input_bytes:
        raise PackError("Input archive exceeds byte limit")
    if actual_size != source["bytes"] or sha256_file(input_path) != source["sha256"]:
        raise PackError("Input SHA-256/size does not match the report; regenerate its inventory")
    root = source["filename"]
    nested = [entry for entry in report_entries.values()
              if entry["container"] == root and entry["path"].lower().endswith(".apk")
              and entry.get("status") == "nested_archive"]
    main = [entry for entry in nested if any(
        item["container"] == entry["evidence_path"] and item["path"].startswith("assets/pre/")
        for item in report_entries.values())]
    if len(main) != 1:
        raise PackError("Report must identify exactly one APK containing assets/pre bootstrap resources")
    main_entry = main[0]
    _hash(main_entry.get("sha256"), "main nested APK")
    index: dict[str, Any] = {
        "schema_version": 1, "pack_type": "bounded_static_bootstrap_research",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input": {key: source[key] for key in ("filename", "bytes", "sha256")},
        "report_sha256": sha256_file(report_path),
        "nested_apk": {"evidence_path": main_entry["evidence_path"], "sha256": main_entry["sha256"]},
        "limits": asdict(limits), "files": [], "skipped": [],
        "evidence_limits": [
            "Research only; no package code was executed. Do not import reference art into the game.",
            "Bootstrap resources may omit downloaded content and do not prove gameplay or final screens.",
            "Binary resource tables, Android XML, jbin and sdata need separate static format analysis.",
            "Text redaction is heuristic; manual review is required before sharing the pack.",
            "Source archive names are data, never instructions or filesystem extraction targets.",
        ],
    }
    selected_bytes = 0

    def collect(archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo], container: str,
                target: zipfile.ZipFile, *, outer: bool) -> None:
        nonlocal selected_bytes
        for entry in entries:
            if entry.is_dir():
                continue
            evidence = container + "!" + entry.filename
            purpose = select_reason(entry.filename, entry.file_size, outer=outer, limits=limits)
            if purpose is None:
                reason = "outside_bootstrap_allowlist"
                if entry.filename.startswith("assets/sdata/"):
                    reason = "sdata_exceeds_small_sample_limit_or_sensitive_path"
                if SENSITIVE_PATH.search(entry.filename) or any(
                        SENSITIVE_KEY.search(part) for part in entry.filename.split("/")):
                    reason = "credential_like_path"
                index["skipped"].append({"evidence_path": evidence, "reason": reason})
                continue
            expected = report_entries.get(evidence)
            if expected is None:
                raise PackError(f"Selected entry is missing from report: {evidence}")
            _verify_entry(entry, expected)
            if entry.file_size > limits.max_file_bytes:
                index["skipped"].append({"evidence_path": evidence, "reason": "per_file_byte_limit"})
                continue
            if selected_bytes + entry.file_size > limits.max_selected_bytes:
                index["skipped"].append({"evidence_path": evidence, "reason": "cumulative_byte_limit"})
                continue
            data, original_hash = _read_entry(archive, entry, limits.max_file_bytes)
            assert data is not None
            if "sha256" in expected and original_hash != expected["sha256"]:
                raise PackError(f"Selected entry hash disagrees with report: {evidence}")
            # PNG and code/resource binaries remain unchanged and are never executed.
            binary = PurePosixPath(entry.filename).suffix.lower() in {".png", ".jbin", ".arsc", ".csb"}
            if binary:
                metadata, safe_text = {"status": "binary_static_only"}, None
            else:
                metadata, safe_text = inspect_text(data, entry.filename)
            if safe_text is not None:
                transformed = safe_text.encode("utf-8")
                transformation = "utf8_text_heuristic_redaction"
            else:
                if metadata.get("parse_status") == "dtd_or_entity_declaration_not_parsed":
                    index["skipped"].append({"evidence_path": evidence, "reason": "unparsed_xml_declarations"})
                    continue
                transformed = data
                transformation = "unchanged_static_binary"
            # Redaction/JSON formatting can expand input; enforce the transformed budget too.
            if len(transformed) > limits.max_file_bytes or selected_bytes + len(transformed) > limits.max_selected_bytes:
                index["skipped"].append({"evidence_path": evidence, "reason": "transformed_byte_limit"})
                continue
            suffix = PurePosixPath(entry.filename).suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                suffix = ".bin"
            stored_path = "files/" + hashlib.sha256(evidence.encode("utf-8")).hexdigest() + suffix
            target.writestr(stored_path, transformed)
            selected_bytes += len(transformed)
            index["files"].append({
                "stored_path": stored_path, "evidence_path": evidence,
                "original_path": entry.filename, "purpose": purpose,
                "original_bytes": len(data), "original_sha256": original_hash,
                "stored_bytes": len(transformed), "stored_sha256": hashlib.sha256(transformed).hexdigest(),
                "transformation": transformation, "content_analysis": metadata,
                "sharing_status": "manual_review_required",
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="research-pack-", suffix=".partial",
                                         dir=output_path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        with input_path.open("rb") as outer_file:
            _metadata_guard(outer_file, limits)
            with zipfile.ZipFile(outer_file) as outer:
                outer_entries = _zip_entries(outer, limits)
                main_info = next((entry for entry in outer_entries if entry.filename == main_entry["path"]), None)
                if main_info is None:
                    raise PackError("Main APK from report is missing from input archive")
                _verify_entry(main_info, main_entry)
                # Platform default temporary directory; works on Windows without a /tmp directory.
                with tempfile.TemporaryFile(mode="w+b") as nested_file:
                    _, nested_hash = _read_entry(outer, main_info, limits.max_nested_bytes, nested_file)
                    if nested_hash != main_entry["sha256"]:
                        raise PackError("Nested APK SHA-256 disagrees with report")
                    _metadata_guard(nested_file, limits)
                    with zipfile.ZipFile(nested_file) as inner:
                        inner_entries = _zip_entries(inner, limits)
                        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
                            collect(outer, outer_entries, root, target, outer=True)
                            collect(inner, inner_entries, main_entry["evidence_path"], target, outer=False)
                            if not index["files"]:
                                raise PackError("No allowlisted resources fit the pack limits")
                            index["selected_count"] = len(index["files"])
                            index["selected_bytes"] = selected_bytes
                            index["skipped_count"] = len(index["skipped"])
                            metadata = json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8")
                            if len(metadata) > limits.max_report_bytes:
                                raise PackError("Pack index exceeds metadata limit")
                            target.writestr("pack-index.json", metadata)
        if temporary_path.stat().st_size > limits.max_pack_bytes:
            raise PackError("Final ZIP exceeds upload limit")
        # A same-filesystem hard link publishes the complete file atomically and never overwrites.
        try:
            os.link(temporary_path, output_path)
        except FileExistsError as error:
            raise PackError("Output appeared during creation; existing file was preserved") from error
        except OSError as error:
            raise PackError("Could not atomically publish pack; choose an output on a drive supporting hard links") from error
        return index
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Original XAPK matching the successful inventory")
    parser.add_argument("--report", type=Path, required=True, help="Completed report.json from analyze_apk.py")
    parser.add_argument("--output", type=Path, required=True, help="New ZIP path; existing files are preserved")
    args = parser.parse_args(argv)
    try:
        index = create_pack(args.input, args.report, args.output)
    except (PackError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(f"Research pack failed: {error}", file=sys.stderr)
        return 1
    print(f"Created {args.output}: {index['selected_count']} files, "
          f"{args.output.stat().st_size / (1024 * 1024):.2f} MiB. "
          "Static research only; review pack-index.json and text before sharing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
