#!/usr/bin/env python3
"""Bounded, dependency-free static ZIP/APK inventory; never executes package code."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import stat
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from xml.etree import ElementTree


TEXT_EXTENSIONS = {".json", ".xml", ".csv", ".tsv", ".txt"}
ARCHIVE_EXTENSIONS = {".apk", ".xapk", ".apks", ".zip"}
SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|(?:^|_)pwd(?:$|_)|secret|credential|authorization|"
    r"api[_\s-]?key|current[_\s-]?key|private[_\s-]?key|"
    r"(?:access|refresh|auth|session)[_\s-]?token|(?:^|[_\s-])token(?:$|[_\s-]))", re.I
)
SENSITIVE_PATH = re.compile(
    r"(?:^|/)(?:\.env(?:\.[^/]*)?|credentials?(?:\.[^/]*)?|"
    r"secrets?(?:\.[^/]*)?|(?:id_rsa|id_ed25519)(?:\.[^/]*)?|"
    r"[^/]*\.(?:pem|p12|pfx|jks|keystore|key))$", re.I
)
REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class Limits:
    max_text_bytes: int = 1 * 1024 * 1024
    max_nested_bytes: int = 1024 * 1024 * 1024
    max_total_read_bytes: int = 2048 * 1024 * 1024
    max_entries: int = 100_000
    max_depth: int = 2
    max_compression_ratio: float = 300.0
    max_metadata_bytes: int = 64 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def path_problem(name: str, info: zipfile.ZipInfo | None = None) -> str | None:
    """Reject hostile names even though extraction never uses archive paths."""
    if "\x00" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        return "unsafe_control_character"
    if "\\" in name:
        return "unsafe_backslash_path"
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return "unsafe_absolute_path"
    if ".." in PurePosixPath(name).parts:
        return "unsafe_parent_traversal"
    if info is not None and stat.S_ISLNK(info.external_attr >> 16):
        return "unsafe_symlink"
    return None


def engine_hint(name: str) -> dict[str, str] | None:
    normalized = name.lower()
    if (normalized.endswith("/libunity.so")
            or normalized.endswith("/global-metadata.dat")
            or normalized.endswith("/globalgamemanagers")
            or normalized.startswith("assets/bin/data/")):
        return {"engine": "Unity", "basis": "file_path_hint"}
    if (normalized.endswith("/libgodot_android.so")
            or normalized.endswith("/libgodot.so")
            or normalized.endswith("/project.godot")
            or normalized.endswith(".pck")):
        return {"engine": "Godot", "basis": "file_path_hint"}
    if (normalized.endswith("/libue4.so")
            or normalized.endswith("/libunreal.so")
            or normalized.startswith("assets/unrealgame/")):
        return {"engine": "Unreal", "basis": "file_path_hint"}
    return None


def redact_text(text: str, json_value: Any = None) -> tuple[str, int]:
    """Conservative best-effort redaction, not a proof that content is public."""
    count = 0

    def redact_value(value: Any) -> Any:
        nonlocal count
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if SENSITIVE_KEY.search(str(key)):
                    result[key] = REDACTED
                    count += 1
                else:
                    result[key] = redact_value(item)
            return result
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        return value

    if json_value is not None:
        text = json.dumps(redact_value(json_value), ensure_ascii=False, indent=2)

    patterns = [
        (re.compile(r"-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*?"
                    r"-----END [^-\n]*PRIVATE KEY-----"), REDACTED),
        (re.compile(r"\bBearer\s+[^\s\"'<>]+", re.I), "Bearer " + REDACTED),
        (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\."
                    r"[A-Za-z0-9_-]+\b"), REDACTED),
        (re.compile(r"(?i)((?:password|passwd|secret|api[_-]?key|current_key|"
                    r"access[_-]?token|refresh[_-]?token|authorization|"
                    r"client_secret|token)\s*[\"']?\s*[:=]\s*)"
                    r"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,<>\n]+)"),
         lambda match: match.group(1) + '"' + REDACTED + '"'),
        (re.compile(r"(?is)(<(?:password|passwd|secret|api[_-]?key|"
                    r"access[_-]?token|refresh[_-]?token|authorization)\b[^>]*>)"
                    r".*?(</[^>]+>)"),
         lambda match: match.group(1) + REDACTED + match.group(2)),
        (re.compile(r"(?is)(<[^>]+\bname\s*=\s*[\"'](?:password|passwd|"
                    r"secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
                    r"authorization)[\"'][^>]*>).*?(</[^>]+>)"),
         lambda match: match.group(1) + REDACTED + match.group(2)),
    ]
    for pattern, replacement in patterns:
        text, matches = pattern.subn(replacement, text)
        count += matches
    return text, count


def inspect_text(data: bytes, name: str) -> tuple[dict[str, Any], str | None]:
    """Return structural metadata; never guess binary Android XML is text."""
    if b"\x00" in data:
        return {"status": "binary_or_encoded", "reason": "decoder_required"}, None
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {"status": "binary_or_encoded", "reason": "not_utf8_text"}, None
    if any(ord(char) < 32 and char not in "\n\r\t" for char in decoded):
        return {"status": "binary_or_encoded", "reason": "control_bytes"}, None
    suffix = PurePosixPath(name).suffix.lower()
    metadata: dict[str, Any] = {"status": "text", "format": suffix.lstrip("."),
                                "utf8_bytes": len(data)}
    parsed = None
    if suffix == ".json":
        try:
            parsed = json.loads(decoded)
            metadata["root_type"] = type(parsed).__name__
            if isinstance(parsed, dict):
                metadata["top_level_keys"] = [str(key) for key in list(parsed)[:100]]
            elif isinstance(parsed, list):
                metadata["item_count"] = len(parsed)
        except (ValueError, RecursionError):
            metadata["parse_status"] = "invalid_or_too_deep_json"
    elif suffix == ".xml":
        # Do not parse DTD/entity declarations from an untrusted archive.
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, re.I):
            metadata["parse_status"] = "dtd_or_entity_declaration_not_parsed"
            return metadata, None
        try:
            root = ElementTree.fromstring(decoded)
            metadata["root_tag"] = root.tag[:200]
            metadata["child_count"] = len(root)
        except (ElementTree.ParseError, RecursionError):
            metadata["parse_status"] = "invalid_xml"
    elif suffix in {".csv", ".tsv"}:
        try:
            delimiter = "\t" if suffix == ".tsv" else ","
            rows = csv.reader(io.StringIO(decoded), delimiter=delimiter)
            first = next(rows, [])
            metadata["column_count"] = len(first)
            secret_columns = [index for index, name in enumerate(first) if SENSITIVE_KEY.search(name)]
            if secret_columns:
                safe_buffer = io.StringIO()
                writer = csv.writer(safe_buffer, delimiter=delimiter)
                writer.writerow(first)
                row_count = 1
                csv_redactions = 0
                for row in rows:
                    row_count += 1
                    for index in secret_columns:
                        if index < len(row):
                            row[index] = REDACTED
                            csv_redactions += 1
                    writer.writerow(row)
                metadata["row_count"] = row_count
                metadata["credential_column_redactions"] = csv_redactions
                decoded = safe_buffer.getvalue()
            else:
                metadata["row_count"] = (1 if first else 0) + sum(1 for _ in rows)
        except csv.Error:
            metadata["parse_status"] = "invalid_csv"
    safe_text, redactions = redact_text(decoded, parsed)
    metadata["redaction_matches"] = redactions
    metadata["sharing_status"] = "manual_review_required"
    return metadata, safe_text


class Analyzer:
    def __init__(self, limits: Limits | None = None, output: Path | None = None,
                 extract_text: bool = False):
        self.limits = limits or Limits()
        self.output = output
        self.extract_text = extract_text
        self.read_bytes = 0
        self.entry_count = 0
        self.report: dict[str, Any] = {
            "schema_version": 1,
            "analysis_type": "static_archive_inventory",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "limits": asdict(self.limits),
            "archives": [], "entries": [], "engine_hints": [], "errors": [],
            "evidence_limits": [
                "File paths are hints; they do not prove visible screens or gameplay.",
                "Server-delivered content and runtime behavior may be absent.",
                "No package code was executed and no original art was copied.",
                "Binary Android manifests/resources require a supported decoder.",
                "Text redaction is heuristic; inspect before sharing extracted text.",
            ],
        }

    def _metadata_guard(self, handle: BinaryIO) -> None:
        """Bound ordinary ZIP central directory allocations before zipfile opens."""
        handle.seek(0, 2)
        length = handle.tell()
        handle.seek(max(0, length - 65_557))
        tail = handle.read(65_557)
        import struct
        position = tail.rfind(b"PK\x05\x06")
        if position < 0 or len(tail) - position < 22:
            raise zipfile.BadZipFile("end_of_central_directory_missing")
        record = struct.unpack_from("<4s4H2LH", tail, position)
        if position + 22 + record[7] != len(tail):
            raise zipfile.BadZipFile("unexpected_trailing_data_or_invalid_eocd")
        count, central_bytes = record[4], record[5]
        if count == 0xFFFF or central_bytes == 0xFFFFFFFF:
            # ZIP64 locator immediately precedes the ordinary EOCD.
            if position < 20 or tail[position - 20:position - 16] != b"PK\x06\x07":
                raise zipfile.BadZipFile("zip64_locator_missing")
            _, disk, zip64_offset, disks = struct.unpack_from("<4sLQL", tail, position - 20)
            if disk != 0 or disks != 1:
                raise zipfile.BadZipFile("multi_disk_zip_not_supported")
            handle.seek(zip64_offset)
            record64 = handle.read(56)
            if len(record64) != 56 or record64[:4] != b"PK\x06\x06":
                raise zipfile.BadZipFile("zip64_end_record_missing")
            fields = struct.unpack("<4sQ2H2L4Q", record64)
            count, central_bytes = fields[7], fields[8]
        if count > self.limits.max_entries - self.entry_count:
            raise ValueError("entry_count_limit")
        if central_bytes > self.limits.max_metadata_bytes:
            raise ValueError("central_directory_size_limit")
        handle.seek(0)

    def _skip_reason(self, info: zipfile.ZipInfo, maximum: int) -> str | None:
        if info.flag_bits & 0x1:
            return "encrypted_entry"
        if info.file_size > maximum:
            return "member_size_limit"
        if info.file_size > self.limits.max_total_read_bytes - self.read_bytes:
            return "cumulative_read_limit"
        ratio = info.file_size / max(1, info.compress_size)
        if ratio > self.limits.max_compression_ratio:
            return "compression_ratio_limit"
        return None

    def _read(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo,
              maximum: int, sink: BinaryIO) -> str:
        digest = hashlib.sha256()
        read = 0
        with archive.open(info, "r") as source:
            while True:
                remaining = min(maximum - read,
                                self.limits.max_total_read_bytes - self.read_bytes)
                block = source.read(min(1024 * 1024, remaining + 1))
                if not block:
                    break
                if len(block) > remaining:
                    raise ValueError("stream_read_limit")
                read += len(block)
                self.read_bytes += len(block)
                digest.update(block)
                sink.write(block)
        if read != info.file_size:
            raise ValueError("declared_size_mismatch")
        sink.seek(0)
        return digest.hexdigest()

    def _scan(self, handle: BinaryIO, evidence: str, depth: int, digest: str) -> bool:
        archive_record: dict[str, Any] = {"evidence_path": evidence,
                                          "sha256": digest, "depth": depth}
        self.report["archives"].append(archive_record)
        try:
            self._metadata_guard(handle)
            with zipfile.ZipFile(handle) as archive:
                infos = archive.infolist()
                archive_record["entry_count"] = len(infos)
                self.entry_count += len(infos)
                names = Counter(info.filename for info in infos)
                for info in infos:
                    entry_path = evidence + "!" + info.filename
                    entry: dict[str, Any] = {
                        "container": evidence, "path": info.filename,
                        "evidence_path": entry_path, "bytes": info.file_size,
                        "compressed_bytes": info.compress_size,
                        "compression": info.compress_type,
                        "crc32": f"{info.CRC:08x}", "status": "inventory_only",
                    }
                    self.report["entries"].append(entry)
                    if depth == 0 and info.filename == "manifest.json":
                        entry["role_hint"] = "possible_container_manifest"
                    if names[info.filename] > 1:
                        entry["duplicate_name"] = True
                    unsafe = path_problem(info.filename, info)
                    if unsafe:
                        entry.update(status="skipped", reason=unsafe)
                        continue
                    if info.is_dir():
                        entry["status"] = "directory"
                        continue
                    hint = engine_hint(info.filename)
                    if hint:
                        self.report["engine_hints"].append({**hint, "evidence_path": entry_path})
                    if SENSITIVE_PATH.search(info.filename):
                        entry.update(status="skipped", reason="credential_or_key_filename")
                        continue
                    suffix = PurePosixPath(info.filename).suffix.lower()
                    if suffix in ARCHIVE_EXTENSIONS:
                        if depth >= self.limits.max_depth:
                            entry.update(status="skipped", reason="nesting_depth_limit")
                            continue
                        reason = self._skip_reason(info, self.limits.max_nested_bytes)
                        if reason:
                            entry.update(status="skipped", reason=reason)
                            continue
                        try:
                            with tempfile.TemporaryFile(prefix="apk-analysis-", dir="/tmp") as nested:
                                content_hash = self._read(archive, info, self.limits.max_nested_bytes, nested)
                                entry.update(status="nested_archive", sha256=content_hash)
                                if not self._scan(nested, entry_path, depth + 1, content_hash):
                                    entry.update(status="skipped", reason="nested_archive_invalid_or_limited")
                        except (ValueError, RuntimeError, OSError, zipfile.BadZipFile,
                                NotImplementedError, EOFError) as error:
                            entry.update(status="skipped", reason="nested_read_failed",
                                         error_type=type(error).__name__)
                        continue
                    if info.filename.lower().endswith("resources.arsc"):
                        entry.update(status="binary_resource_table", reason="decoder_required")
                        continue
                    if suffix not in TEXT_EXTENSIONS:
                        continue
                    reason = self._skip_reason(info, self.limits.max_text_bytes)
                    if reason:
                        entry.update(status="skipped", reason=reason)
                        continue
                    try:
                        buffer = io.BytesIO()
                        entry["sha256"] = self._read(archive, info, self.limits.max_text_bytes, buffer)
                        metadata, safe_text = inspect_text(buffer.getvalue(), info.filename)
                        entry.update(status="inspected_text", text_analysis=metadata)
                        if safe_text is not None and self.extract_text and self.output:
                            text_dir = self.output / "text"
                            text_dir.mkdir(exist_ok=True)
                            # Archive names never become filesystem paths.
                            reference_hash = hashlib.sha256(entry_path.encode("utf-8")).hexdigest()[:16]
                            destination = text_dir / (reference_hash + suffix)
                            destination.write_text(safe_text, encoding="utf-8")
                            entry["extracted_text"] = str(destination.relative_to(self.output))
                            entry["extracted_sha256"] = sha256_file(destination)
                    except (ValueError, RuntimeError, OSError, zipfile.BadZipFile,
                            NotImplementedError, EOFError, RecursionError) as error:
                        entry.update(status="skipped", reason="text_read_failed",
                                     error_type=type(error).__name__)
                archive_record["status"] = "inventoried"
                return True
        except (ValueError, OSError, zipfile.BadZipFile, RuntimeError) as error:
            archive_record.update(status="skipped", reason=str(error))
            self.report["errors"].append({"evidence_path": evidence,
                                          "reason": str(error),
                                          "error_type": type(error).__name__})
            return False

    def analyze(self, path: Path) -> dict[str, Any]:
        digest = sha256_file(path)
        self.report["input"] = {"filename": path.name, "bytes": path.stat().st_size,
                                "sha256": digest}
        with path.open("rb") as handle:
            self._scan(handle, path.name, 0, digest)
        self.report["read_bytes"] = self.read_bytes
        counts = Counter(entry["status"] for entry in self.report["entries"])
        self.report["status_counts"] = dict(counts)
        return self.report


def markdown_summary(report: dict[str, Any]) -> str:
    def code(value: Any) -> str:
        # Backtick code spans cannot contain hostile filenames verbatim.
        return "`" + str(value).replace("`", "\\u0060").replace("\n", "\\n") + "`"

    source = report["input"]
    lines = ["# Static APK/XAPK evidence", "",
             f"Input: {code(source['filename'])}", "",
             f"SHA-256: {code(source['sha256'])}", "",
             f"Archive entries: {len(report['entries'])}; bytes read: {report['read_bytes']}", "",
             "## What this report establishes", "",
             "Archive paths and bounded text structure only. Engine matches are file-path hints.", "",
             "## Engine hints", ""]
    if report["engine_hints"]:
        for hint in report["engine_hints"][:100]:
            lines.append(f"- {hint['engine']}: {code(hint['evidence_path'])}")
        if len(report["engine_hints"]) > 100:
            lines.append("- Additional hints are in report.json.")
    else:
        lines.append("No supported engine path hints found; engine remains unknown.")
    lines.extend(["", "## Readable text evidence", ""])
    inspected = [entry for entry in report["entries"] if entry.get("text_analysis", {}).get("status") == "text"]
    if inspected:
        for entry in inspected[:100]:
            lines.append(f"- {code(entry['evidence_path'])}; SHA-256 {code(entry['sha256'])}")
        if len(inspected) > 100:
            lines.append("- Additional text records are in report.json.")
    else:
        lines.append("No eligible UTF-8 text was inspected.")
    lines.extend(["", "## Limits and unresolved questions", ""])
    lines.extend("- " + limitation for limitation in report["evidence_limits"])
    lines.append("- Filenames do not establish a screen layout, card rule, balance value, or story fact.")
    reasons = Counter(entry.get("reason") for entry in report["entries"] if entry.get("reason"))
    if reasons:
        lines.extend(["", "## Skipped entries", ""])
        lines.extend(f"- {reason}: {count}" for reason, count in sorted(reasons.items()))
    if report["errors"]:
        lines.extend(["", "## Archive errors", ""])
        lines.extend(f"- {code(error['evidence_path'])}: {code(error['reason'])}"
                     for error in report["errors"])
    return "\n".join(lines) + "\n"


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="APK, XAPK, APKS, or ZIP")
    parser.add_argument("--output", type=Path,
                        help="new/empty report directory; default /workspace/game-research/<name>-<hash>")
    parser.add_argument("--extract-text", action="store_true",
                        help="opt in to bounded, redacted UTF-8 JSON/XML/CSV/TSV/TXT copies")
    parser.add_argument("--max-text-mib", type=positive_int, default=1)
    parser.add_argument("--max-nested-mib", type=positive_int, default=1024)
    parser.add_argument("--max-total-mib", type=positive_int, default=2048)
    parser.add_argument("--max-entries", type=positive_int, default=100_000)
    parser.add_argument("--max-depth", type=positive_int, default=2)
    args = parser.parse_args(argv)
    path = args.archive.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in ARCHIVE_EXTENSIONS:
        parser.error("input must be an existing .apk, .xapk, .apks, or .zip file")
    output = args.output.expanduser().resolve() if args.output else (
        Path("/workspace/game-research") /
        (re.sub(r"[^A-Za-z0-9_.-]", "_", path.stem)[:70] + "-" + sha256_file(path)[:12]))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("output must be new or empty; existing research is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    limits = Limits(max_text_bytes=args.max_text_mib * 1024 * 1024,
                    max_nested_bytes=args.max_nested_mib * 1024 * 1024,
                    max_total_read_bytes=args.max_total_mib * 1024 * 1024,
                    max_entries=args.max_entries, max_depth=args.max_depth)
    analyzer = Analyzer(limits=limits, output=output, extract_text=args.extract_text)
    try:
        report = analyzer.analyze(path)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        (output / "summary.md").write_text(markdown_summary(report), encoding="utf-8")
    except OSError as error:
        print(f"Analysis failed: {type(error).__name__}; no package code was executed.", file=sys.stderr)
        return 1
    print(f"Report: {output / 'report.json'}")
    print(f"Summary: {output / 'summary.md'}")
    print(f"Inventoried {len(report['entries'])} entries; archive errors: {len(report['errors'])}.")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
