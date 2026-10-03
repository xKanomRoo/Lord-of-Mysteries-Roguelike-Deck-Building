#!/usr/bin/env python3
"""Verify resumable batches of inert resources from one pinned SSRA manifest.

Archive names and resource paths are labels, never extraction destinations.
Every fragment selector is rederived from the actual pinned manifest. Stored
SHA-256 and decoded FHSH establish internal consistency, not CDN signatures.
No game scripts, native code, account files or network requests are executed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import struct
import sys
import tempfile
import zipfile

try:
    from . import read_ssra_manifest as ssra
    from . import extract_ssra_resources as resources
except ImportError:
    import read_ssra_manifest as ssra
    import extract_ssra_resources as resources

PROFILE = "chaos-all-static-resources-45a009358972-v1"
PACKAGE = "com.smilegate.chaoszero.stove.google"
MANIFEST_SHA256 = "45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15"
MANIFEST_BYTES = 7_506_387
PRIVATE_ROOT = Path(__file__).resolve().parents[1] / ".local"
INDEX_NAME = "research-index.json"
MANIFEST_MEMBER = "manifest/00.bin"
MAX_ZIP_BYTES = 30 * 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_PART_BYTES = 1024 * 1024
MAX_BATCH_PARTS = 2000
MAX_RESOURCE_BYTES = 512 * 1024 * 1024
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_STORED_TOTAL_BYTES = 16 * 1024**3
MAX_DECODED_TOTAL_BYTES = 16 * 1024**3
MAX_CATALOG_BYTES = 128 * 1024 * 1024
MAX_REJECTIONS = 1000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PART_NAME = re.compile(r"parts/([0-9]{6})-([0-9]{12})\.bin\Z")
BATCH_NAME = re.compile(r"chaos-all-[0-9]{6}\.zip\Z")
FILE_FIELDS = {"path", "row", "group_id", "offset", "stored_length", "decoded_length",
               "compression", "encryption", "flags", "file_hash64"}
COMMON_FIELDS = {"schema_version", "profile", "package", "kind", "source_manifest_sha256"}


class AllReadError(ValueError):
    """Changed lineage, unsafe archives, or invalid bounded resource content."""


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _keys(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise AllReadError(f"{label} has unexpected or missing fields")


def _integer(value, label: str, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise AllReadError(f"Invalid bounded integer: {label}")
    return value


def _digest(value) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise AllReadError("Invalid fragment SHA-256")
    return value


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AllReadError("Duplicate JSON object key")
        value[key] = item
    return value


def _nonfinite(value):
    raise AllReadError("Nonfinite JSON numbers are rejected")


def _json(data: bytes) -> dict:
    if len(data) > MAX_INDEX_BYTES:
        raise AllReadError("Index exceeds 2 MiB")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
        pending, count = [value], 0
        while pending:
            item = pending.pop()
            count += 1
            if count > 200_000:
                raise AllReadError("Index structure exceeds its bound")
            if isinstance(item, str):
                item.encode("utf-8")
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, AllReadError):
            raise
        raise AllReadError("Index must be bounded strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise AllReadError("Index must be an object")
    return value


def _exact(value, expected, label: str) -> None:
    if json.dumps(value, sort_keys=True, separators=(",", ":")) != json.dumps(expected, sort_keys=True, separators=(",", ":")):
        raise AllReadError(f"{label} disagrees with the pinned manifest")


def _regular_bytes(path: Path, maximum: int) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
        raise AllReadError("Input must be a bounded regular nonsymlink file")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) != metadata.st_size or len(data) > maximum:
        raise AllReadError("Input changed size or exceeded its limit")
    return data


def _common(index: dict, kind: str) -> None:
    _exact({key: index.get(key) for key in COMMON_FIELDS}, {
        "schema_version": 1, "profile": PROFILE, "package": PACKAGE, "kind": kind,
        "source_manifest_sha256": MANIFEST_SHA256}, "Source profile")


def _zip_members(archive: zipfile.ZipFile, expected: dict[str, int | None]) -> None:
    infos = archive.infolist()
    names = [item.filename for item in infos]
    if len(infos) != len(expected) or len(set(names)) != len(names) or set(names) != set(expected):
        raise AllReadError("ZIP must contain exactly its derived ordinal members without duplicates")
    total = 0
    for info in infos:
        mode = stat.S_IFMT(info.external_attr >> 16)
        if (info.flag_bits & 1 or mode not in (0, stat.S_IFREG) or info.is_dir()
                or info.external_attr & 0x10 or info.orig_filename != info.filename
                or info.compress_type != zipfile.ZIP_STORED or info.file_size != info.compress_size):
            raise AllReadError("ZIP members must be regular, unencrypted, ZIP_STORED files")
        required = expected[info.filename]
        maximum = MAX_INDEX_BYTES if info.filename == INDEX_NAME else MAX_PART_BYTES
        if info.filename == MANIFEST_MEMBER:
            maximum = MANIFEST_BYTES
        if info.file_size > maximum or required is not None and info.file_size != required:
            raise AllReadError("ZIP member has an unexpected bounded length")
        total += info.file_size
    if total > MAX_ZIP_BYTES:
        raise AllReadError("ZIP decoded aggregate exceeds 30 MiB")


def source_manifest(source: Path) -> tuple[bytes, dict]:
    """Read only the two exact source ZIP members, checking CRC and source pin."""
    data = _regular_bytes(Path(source), MAX_ZIP_BYTES)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _zip_members(archive, {INDEX_NAME: None, MANIFEST_MEMBER: MANIFEST_BYTES})
            index = _json(archive.read(INDEX_NAME))
            _keys(index, COMMON_FIELDS | {"manifest"}, "Source index")
            _common(index, "source")
            _exact(index["manifest"], {"archive_path": MANIFEST_MEMBER, "bytes": MANIFEST_BYTES,
                  "sha256": MANIFEST_SHA256}, "Manifest identity")
            manifest_data = archive.read(MANIFEST_MEMBER)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise AllReadError("Source ZIP CRC or structure failed") from error
    if _hash(manifest_data) != MANIFEST_SHA256:
        raise AllReadError("Source manifest SHA-256 differs from the fixed pin")
    try:
        manifest = ssra.parse_ssra(manifest_data)
    except ssra.SSRAError as error:
        raise AllReadError(str(error)) from error
    if (any(item["stored_length"] > MAX_RESOURCE_BYTES or item["decoded_length"] > MAX_RESOURCE_BYTES
            for item in manifest["files"]) or any(item["file_hash64"] is None for item in manifest["files"])
            or sum(item["stored_length"] for item in manifest["files"]) > MAX_STORED_TOTAL_BYTES
            or sum(item["decoded_length"] for item in manifest["files"]) > MAX_DECODED_TOTAL_BYTES):
        raise AllReadError("Manifest resources exceed bounds or lack FHSH checksums")
    return manifest_data, manifest


def resource_identity(item: dict) -> dict:
    return {**{key: item[key] for key in FILE_FIELDS - {"file_hash64"}},
            "file_hash64": f"{item['file_hash64']:016x}"}


def fragment_segments(manifest: dict, item: dict, offset: int, length: int) -> list[dict]:
    """Independently derive exact fragment intersections, excluding SSRC footers."""
    cursor = start = item["offset"] + offset
    end = start + length
    segments = []
    for chunk in manifest["chunks"]:
        if chunk["group_id"] != item["group_id"]:
            continue
        chunk_start = chunk["logical_start"]
        overlap_start = max(start, chunk_start)
        overlap_end = min(end, chunk_start + chunk["logical_length"])
        if overlap_start >= overlap_end:
            continue
        filename = chunk["filename"]
        if (overlap_start != cursor or not isinstance(filename, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ssrc", filename)
                or chunk["physical_length"] < 16
                or chunk["logical_length"] > chunk["physical_length"] - 16):
            raise AllReadError("Fragment has unsafe, missing or discontinuous physical chunk mapping")
        segments.append({"chunk_row": chunk["row"], "chunk_filename": filename,
                         "physical_offset": overlap_start - chunk_start,
                         "bytes": overlap_end - overlap_start})
        cursor = overlap_end
    if cursor != end:
        raise AllReadError("Fragment is not fully covered by source chunks")
    return segments


def verify_batch(path: Path, manifest: dict) -> tuple[str, dict, list[tuple[dict, bytes]]]:
    """Validate a complete pack before exposing any member to the output store."""
    data = _regular_bytes(Path(path), MAX_ZIP_BYTES)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            # Bound index before reading it; no arbitrary entries are extracted.
            infos = archive.infolist()
            if len(infos) > MAX_BATCH_PARTS + 1:
                raise AllReadError("ZIP member count exceeds 2001")
            index_infos = [info for info in infos if info.filename == INDEX_NAME]
            if len(index_infos) != 1 or index_infos[0].file_size > MAX_INDEX_BYTES:
                raise AllReadError("ZIP must have one bounded index")
            info = index_infos[0]
            if (info.flag_bits & 1 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                    or info.is_dir() or info.external_attr & 0x10 or info.orig_filename != info.filename
                    or info.compress_type != zipfile.ZIP_STORED or info.file_size != info.compress_size):
                raise AllReadError("ZIP index must be regular, unencrypted and ZIP_STORED")
            index = _json(archive.read(INDEX_NAME))
            _keys(index, COMMON_FIELDS | {"batch_number", "files"}, "Batch index")
            _common(index, "resources")
            _integer(index["batch_number"], "batch number", 1_000_000)
            if index["batch_number"] == 0:
                raise AllReadError("Batch numbering starts at one")
            records = index["files"]
            if not isinstance(records, list) or not 1 <= len(records) <= MAX_BATCH_PARTS:
                raise AllReadError("Batch must contain one to 2000 fragments")
            expected, seen = {INDEX_NAME: None}, set()
            for record in records:
                _keys(record, {"resource", "part_offset", "archive_path", "bytes", "sha256", "segments"}, "Fragment")
                identity = record["resource"]
                _keys(identity, FILE_FIELDS, "Resource identity")
                row = _integer(identity["row"], "resource row", len(manifest["files"]) - 1)
                item = manifest["files"][row]
                _exact(identity, resource_identity(item), "Resource identity")
                if item["flags"] or item["encryption"] or not item["stored_length"]:
                    raise AllReadError("Absent, encrypted or empty resource fragments are unsupported")
                offset = _integer(record["part_offset"], "fragment offset", item["stored_length"] - 1)
                length = min(MAX_PART_BYTES, item["stored_length"] - offset)
                if offset % MAX_PART_BYTES or type(record["bytes"]) is not int or record["bytes"] != length:
                    raise AllReadError("Fragment must use the deterministic one MiB grid")
                label = f"parts/{row:06d}-{offset:012d}.bin"
                if record["archive_path"] != label or label in seen:
                    raise AllReadError("Unexpected or duplicate ordinal fragment")
                seen.add(label)
                expected[label] = length
                _digest(record["sha256"])
                _exact(record["segments"], fragment_segments(manifest, item, offset, length), "Physical segments")
            _zip_members(archive, expected)
            fragments = []
            for record in records:
                payload = archive.read(record["archive_path"])
                if _hash(payload) != record["sha256"]:
                    raise AllReadError("Fragment SHA-256 differs from its index")
                fragments.append((record, payload))
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise AllReadError("Batch ZIP CRC or structure failed") from error
    return _hash(data), index, fragments


class StreamingXXH64:
    """Incremental standard XXH64; carries at most 31 bytes between updates."""

    def __init__(self):
        p1, p2, _, _, _ = ssra.PRIMES
        self.lanes = [(p1 + p2) & ssra.MASK64, p2, 0, (-p1) & ssra.MASK64]
        self.buffer = bytearray()
        self.length = 0

    @staticmethod
    def _round(acc, value):
        p1, p2, _, _, _ = ssra.PRIMES
        return (ssra._rotate(acc + value * p2, 31) * p1) & ssra.MASK64

    def update(self, data: bytes) -> None:
        self.length += len(data)
        value = bytes(self.buffer) + data
        cursor = 0
        while cursor <= len(value) - 32:
            for lane, integer in enumerate(struct.unpack_from("<4Q", value, cursor)):
                self.lanes[lane] = self._round(self.lanes[lane], integer)
            cursor += 32
        self.buffer = bytearray(value[cursor:])

    def intdigest(self) -> int:
        p1, p2, p3, p4, p5 = ssra.PRIMES
        if self.length >= 32:
            result = sum(ssra._rotate(value, bits) for value, bits in zip(self.lanes, (1, 7, 12, 18))) & ssra.MASK64
            for value in self.lanes:
                result = ((result ^ self._round(0, value)) * p1 + p4) & ssra.MASK64
        else:
            result = p5
        result = (result + self.length) & ssra.MASK64
        cursor, data = 0, self.buffer
        while cursor <= len(data) - 8:
            result ^= self._round(0, struct.unpack_from("<Q", data, cursor)[0])
            result = (ssra._rotate(result, 27) * p1 + p4) & ssra.MASK64
            cursor += 8
        if cursor <= len(data) - 4:
            result ^= struct.unpack_from("<I", data, cursor)[0] * p1 & ssra.MASK64
            result = (ssra._rotate(result, 23) * p2 + p3) & ssra.MASK64
            cursor += 4
        while cursor < len(data):
            result ^= data[cursor] * p5 & ssra.MASK64
            result = ssra._rotate(result, 11) * p1 & ssra.MASK64
            cursor += 1
        result ^= result >> 33
        result = result * p2 & ssra.MASK64
        result ^= result >> 29
        result = result * p3 & ssra.MASK64
        return (result ^ (result >> 32)) & ssra.MASK64


def _private_output(output: Path) -> Path:
    output = Path(os.path.abspath(output))
    private = Path(os.path.abspath(PRIVATE_ROOT))
    if output == private or not output.is_relative_to(private):
        raise AllReadError("Research output must be a subdirectory of this repository's .local")
    if any(ord(char) < 32 or ord(char) == 127 for char in str(output)):
        raise AllReadError("Output path has control characters")
    current = private
    for part in ("", *output.relative_to(private).parts):
        if part:
            current /= part
        if os.path.lexists(current) and not stat.S_ISDIR(current.lstat().st_mode):
            raise AllReadError("Output parents must be nonsymlink directories")
    return output


def _open_store(output: Path, manifest_data: bytes) -> sqlite3.Connection:
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    _recover_stages(output)
    for directory in (output / "parts", output / "files"):
        if os.path.lexists(directory) and not stat.S_ISDIR(directory.lstat().st_mode):
            raise AllReadError("Research directories must not be symlinks")
        directory.mkdir(mode=0o700, exist_ok=True)
    manifest_path = output / "manifest.bin"
    if os.path.lexists(manifest_path):
        if _regular_bytes(manifest_path, MANIFEST_BYTES) != manifest_data:
            raise AllReadError("Existing store has a changed manifest")
    else:
        with manifest_path.open("xb") as stream:
            stream.write(manifest_data)
        manifest_path.chmod(0o600)
    db_path = output / "state.sqlite3"
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        if os.path.lexists(path) and not stat.S_ISREG(path.lstat().st_mode):
            raise AllReadError("State and SQLite sidecars must be regular nonsymlink files")
        if os.path.lexists(path) and path.lstat().st_size > MAX_CATALOG_BYTES:
            raise AllReadError("SQLite state exceeds 128 MiB")
    new = not db_path.exists()
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA max_page_count=32768")
        if new:
            connection.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE batches(number INTEGER PRIMARY KEY, sha256 TEXT NOT NULL);
                CREATE TABLE parts(row INTEGER NOT NULL, offset INTEGER NOT NULL, bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, PRIMARY KEY(row,offset));
                CREATE TABLE results(row INTEGER PRIMARY KEY, status TEXT NOT NULL,
                    stored_sha256 TEXT, decoded_sha256 TEXT, reason TEXT);
                CREATE TABLE rejections(sha256 TEXT PRIMARY KEY, reason TEXT NOT NULL);
            """)
            connection.execute("INSERT INTO metadata VALUES('manifest_sha256',?)", (MANIFEST_SHA256,))
            connection.execute("INSERT INTO metadata VALUES('profile',?)", (PROFILE,))
            connection.commit()
        actual_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if actual_tables != {"metadata", "batches", "parts", "results", "rejections"}:
            raise AllReadError("State has unexpected tables")
        objects = list(connection.execute("SELECT type FROM sqlite_master WHERE type NOT IN ('table','index')"))
        if objects or connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise AllReadError("State schema or integrity failed")
        if dict(connection.execute("SELECT key,value FROM metadata")) != {"manifest_sha256": MANIFEST_SHA256, "profile": PROFILE}:
            raise AllReadError("State lineage differs from the pinned source")
        db_path.chmod(0o600)
        return connection
    except BaseException:
        connection.close()
        raise


def _part_path(output: Path, row: int, offset: int) -> Path:
    return output / "parts" / f"{row:06d}-{offset:012d}.bin"


def _recover_stages(output: Path) -> None:
    """Remove only this reader's bounded, flat staging family after a crash."""
    for path in output.iterdir():
        match = re.fullmatch(r"\.all-(ingest|decode)-[a-z0-9_]{8}", path.name)
        file_match = re.fullmatch(r"\.(catalog|receipt)-[a-z0-9_]{8}", path.name)
        if not match and not file_match:
            continue
        metadata = path.lstat()
        if file_match:
            maximum = MAX_CATALOG_BYTES if file_match.group(1) == "catalog" else MAX_INDEX_BYTES
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
                raise AllReadError("Unsafe or oversized interrupted report temporary")
            path.unlink()
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise AllReadError("Interrupted staging directory must be nonsymlink")
        files, total = [], 0
        for child in path.iterdir():
            child_metadata = child.lstat()
            maximum = MAX_PART_BYTES if match.group(1) == "ingest" else MAX_RESOURCE_BYTES
            valid_name = bool(PART_NAME.fullmatch("parts/" + child.name)) if match.group(1) == "ingest" else child.name == "decoded.bin"
            if not valid_name or not stat.S_ISREG(child_metadata.st_mode) or child_metadata.st_size > maximum:
                raise AllReadError("Unsafe interrupted staging member")
            total += child_metadata.st_size
            files.append(child)
            if len(files) > (MAX_BATCH_PARTS if match.group(1) == "ingest" else 1) or total > (MAX_ZIP_BYTES if match.group(1) == "ingest" else MAX_RESOURCE_BYTES):
                raise AllReadError("Interrupted staging aggregate exceeds its bound")
        for child in files:
            child.unlink()
        path.rmdir()


def _rehash_parts(connection, output: Path, manifest: dict) -> tuple[set[int], int]:
    expected = set()
    touched = set()
    total = 0
    maximum_count = sum((item["stored_length"] + MAX_PART_BYTES - 1) // MAX_PART_BYTES for item in manifest["files"])
    count = connection.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    if count > maximum_count or connection.execute("SELECT COUNT(*) FROM results").fetchone()[0] > len(manifest["files"]):
        raise AllReadError("Cumulative state exceeds manifest resource/fragment counts")
    for row, offset, length, digest in connection.execute("SELECT row,offset,bytes,sha256 FROM parts"):
        _integer(row, "stored state row", len(manifest["files"]) - 1)
        item = manifest["files"][row]
        _integer(offset, "stored state offset", max(0, item["stored_length"] - 1))
        if offset % MAX_PART_BYTES or length != min(MAX_PART_BYTES, item["stored_length"] - offset):
            raise AllReadError("Stored state has a noncanonical fragment")
        path = _part_path(output, row, offset)
        if _hash(_regular_bytes(path, MAX_PART_BYTES)) != _digest(digest) or path.stat().st_size != length:
            raise AllReadError("Existing fragment bytes changed; resume refused")
        expected.add(path.name)
        touched.add(row)
        total += length
    if total > sum(item["stored_length"] for item in manifest["files"]):
        raise AllReadError("Cumulative stored bytes exceed manifest total")
    actual = {path.name for path in (output / "parts").iterdir()}
    if not expected <= actual:
        raise AllReadError("Missing indexed fragment files in existing store")
    recovered = 0
    for name in actual - expected:
        # A hard crash between exclusive file creation and SQLite commit can
        # leave our canonical uncommitted output. Discard only that bounded,
        # regular filename family; an uploaded pack must verify it anew.
        match = PART_NAME.fullmatch("parts/" + name)
        if not match:
            raise AllReadError("Unexpected unindexed fragment filename")
        row, offset = map(int, match.groups())
        _integer(row, "orphan row", len(manifest["files"]) - 1)
        item = manifest["files"][row]
        if offset % MAX_PART_BYTES or not 0 <= offset < item["stored_length"]:
            raise AllReadError("Unexpected unindexed fragment selector")
        path = output / "parts" / name
        data = _regular_bytes(path, MAX_PART_BYTES)
        if len(data) > min(MAX_PART_BYTES, item["stored_length"] - offset):
            raise AllReadError("Uncommitted fragment has an unexpected size")
        path.unlink()
        recovered += 1
    # Results are re-established from parts; changed decoded files cannot pass
    # because every complete touched resource is verified again below.
    for row, status, stored_hash, decoded_hash, reason in connection.execute("SELECT * FROM results"):
        _integer(row, "result row", len(manifest["files"]) - 1)
        if row not in touched or status not in {"verified", "invalid", "unsupported"}:
            raise AllReadError("State has unexpected result rows")
        received = connection.execute("SELECT SUM(bytes) FROM parts WHERE row=?", (row,)).fetchone()[0]
        if received != manifest["files"][row]["stored_length"]:
            raise AllReadError("Result claims completeness for an incomplete resource")
    if (connection.execute("SELECT COUNT(*) FROM rejections").fetchone()[0] > MAX_REJECTIONS
            or connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] > maximum_count):
        raise AllReadError("Cumulative batch/rejection state exceeds its bound")
    for number, digest in connection.execute("SELECT number,sha256 FROM batches"):
        _integer(number, "prior batch number", 1_000_000)
        _digest(digest)
    return touched, recovered


def _publish_batch(connection, output: Path, pack_hash: str, index: dict, fragments) -> set[int]:
    number = index["batch_number"]
    prior = connection.execute("SELECT sha256 FROM batches WHERE number=?", (number,)).fetchone()
    if prior and prior[0] != pack_hash:
        raise AllReadError("Batch number was reused with changed ZIP bytes")
    touched, additions = set(), []
    for record, data in fragments:
        row, offset = record["resource"]["row"], record["part_offset"]
        touched.add(row)
        present = connection.execute("SELECT bytes,sha256 FROM parts WHERE row=? AND offset=?", (row, offset)).fetchone()
        if present:
            if present != (len(data), record["sha256"]):
                raise AllReadError("Conflicting bytes for an existing fragment")
            # Recheck even an idempotent duplicate during this invocation.
            if _regular_bytes(_part_path(output, row, offset), MAX_PART_BYTES) != data:
                raise AllReadError("Existing fragment differs from duplicate pack")
        else:
            additions.append((record, data))
    if not prior and not additions:
        raise AllReadError("New batch number contains no new fragments")
    published = []
    with tempfile.TemporaryDirectory(prefix=".all-ingest-", dir=output) as temporary:
        stage = Path(temporary)
        for record, data in additions:
            path = stage / Path(record["archive_path"]).name
            path.write_bytes(data)
            path.chmod(0o600)
        try:
            with connection:
                for record, data in additions:
                    row, offset = record["resource"]["row"], record["part_offset"]
                    target = _part_path(output, row, offset)
                    if os.path.lexists(target):
                        raise AllReadError("Unindexed fragment destination already exists")
                    # Exclusive creation prevents a replacement/symlink target.
                    with target.open("xb") as destination, (stage / Path(record["archive_path"]).name).open("rb") as source:
                        published.append(target)
                        shutil.copyfileobj(source, destination, MAX_PART_BYTES)
                    target.chmod(0o600)
                    connection.execute("INSERT INTO parts VALUES(?,?,?,?)", (row, offset, len(data), record["sha256"]))
                connection.execute("INSERT OR IGNORE INTO batches VALUES(?,?)", (number, pack_hash))
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            raise
    return touched


def _assemble(connection, output: Path, item: dict) -> bool:
    row = item["row"]
    parts = list(connection.execute("SELECT offset,bytes,sha256 FROM parts WHERE row=? ORDER BY offset", (row,)))
    if sum(part[1] for part in parts) != item["stored_length"]:
        return False
    cursor = 0
    for offset, length, digest in parts:
        if offset != cursor:
            return False
        cursor += length
    status, reason, decoded_hash, stored_hash = "verified", None, None, None
    destination = output / "files" / f"{row:06d}.bin"
    if os.path.lexists(destination) and not stat.S_ISREG(destination.lstat().st_mode):
        raise AllReadError("Decoded destination must be a regular nonsymlink file")
    with tempfile.TemporaryDirectory(prefix=".all-decode-", dir=output) as temporary:
        stage = Path(temporary) / "decoded.bin"
        try:
            stored_digest = hashlib.sha256()
            if item["encryption"] or item["flags"]:
                raise AllReadError("Encrypted or absent resources are unsupported")
            if item["compression"] == 0:
                decoded_digest, fhsh = hashlib.sha256(), StreamingXXH64()
                with stage.open("xb") as result:
                    for offset, length, digest in parts:
                        data = _regular_bytes(_part_path(output, row, offset), MAX_PART_BYTES)
                        if len(data) != length or _hash(data) != digest:
                            raise AllReadError("Stored fragment changed during resource assembly")
                        stored_digest.update(data)
                        decoded_digest.update(data)
                        fhsh.update(data)
                        result.write(data)
                if cursor != item["decoded_length"] or fhsh.intdigest() != item["file_hash64"]:
                    raise AllReadError("Decoded resource length or FHSH XXH64 mismatch")
                decoded_hash = decoded_digest.hexdigest()
            else:
                if item["stored_length"] > MAX_COMPRESSED_BYTES or item["decoded_length"] > MAX_COMPRESSED_BYTES:
                    status = "unsupported"
                    raise AllReadError("Compressed resource exceeds the 64 MiB decoder/window bound")
                stored = bytearray()
                for offset, length, digest in parts:
                    data = _regular_bytes(_part_path(output, row, offset), MAX_PART_BYTES)
                    if len(data) != length or _hash(data) != digest:
                        raise AllReadError("Stored fragment changed during resource assembly")
                    stored_digest.update(data)
                    stored.extend(data)
                try:
                    decoded = resources._decode_resource(bytes(stored), item)
                except resources.ResourceExtractError as error:
                    if "requires" in str(error):
                        status = "unsupported"
                    raise AllReadError(str(error)) from error
                if ssra.xxh64(decoded) != item["file_hash64"]:
                    raise AllReadError("Decoded resource FHSH XXH64 mismatch")
                stage.write_bytes(decoded)
                decoded_hash = _hash(decoded)
            stored_hash = stored_digest.hexdigest()
            stage.chmod(0o600)
            # Re-establish result from source bytes; changed prior output is
            # restored atomically, without trusting its saved hash alone.
            os.replace(stage, destination)
        except AllReadError as error:
            if status == "verified":
                status = "invalid"
            reason = str(error)[:256]
            stored_hash = stored_digest.hexdigest()
            destination.unlink(missing_ok=True)
    with connection:
        connection.execute("INSERT OR REPLACE INTO results VALUES(?,?,?,?,?)", (row, status, stored_hash, decoded_hash, reason))
    return True


def _report(connection, output: Path, manifest: dict, rejected: list[dict], recovered: int) -> dict:
    results = {row: (status, stored_hash, decoded_hash, reason)
               for row, status, stored_hash, decoded_hash, reason in connection.execute("SELECT * FROM results")}
    received = dict(connection.execute("SELECT row,SUM(bytes) FROM parts GROUP BY row"))
    statuses, extensions = Counter(), Counter()
    verified_decoded, received_total = 0, sum(received.values())
    catalog = output / "resource-index.json"
    if os.path.lexists(catalog) and not stat.S_ISREG(catalog.lstat().st_mode):
        raise AllReadError("Catalog destination must be a regular nonsymlink file")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".catalog-", dir=output, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write('{"schema_version":1,"profile":' + json.dumps(PROFILE) + ',"manifest_sha256":' + json.dumps(MANIFEST_SHA256) + ',"files":[\n')
            for ordinal, item in enumerate(manifest["files"]):
                row = item["row"]
                result = results.get(row)
                status = result[0] if result else ("partial" if received.get(row) else "missing")
                if item["flags"]:
                    status = "absent_in_manifest"
                elif item["encryption"]:
                    status = "unsupported_encryption"
                statuses[status] += 1
                extensions[Path(item["path"]).suffix.lower() or "(none)"] += 1
                if status == "verified":
                    verified_decoded += item["decoded_length"]
                record = {**resource_identity(item), "status": status, "received_stored_bytes": received.get(row, 0),
                          "decoded_archive_path": f"files/{row:06d}.bin" if status == "verified" else None,
                          "stored_sha256": result[1] if result else None,
                          "decoded_sha256": result[2] if result else None, "reason": result[3] if result else None,
                          "format_parsed": False, "rendered": False, "executed": False}
                stream.write(("," if ordinal else "") + json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
                if stream.tell() > MAX_CATALOG_BYTES:
                    raise AllReadError("Resource catalog exceeds 128 MiB")
            stream.write("]}\n")
            stream.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.chmod(0o600)
    os.replace(temporary, catalog)
    summary = {"schema_version": 1, "profile": PROFILE, "source_manifest_sha256": MANIFEST_SHA256,
               "manifest_resource_count": len(manifest["files"]), "resource_status_counts": dict(statuses),
               "manifest_stored_bytes": sum(item["stored_length"] for item in manifest["files"]),
               "manifest_decoded_bytes": sum(item["decoded_length"] for item in manifest["files"]),
               "received_unique_stored_bytes": received_total, "verified_decoded_bytes": verified_decoded,
               "verified_batch_count": connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
               "discarded_uncommitted_fragment_count": recovered,
               "rejected_input_batches": rejected, "historical_rejected_zip_count": connection.execute("SELECT COUNT(*) FROM rejections").fetchone()[0],
               "all_manifest_resources_verified": statuses["verified"] == len(manifest["files"]),
               "manifest_extension_counts": dict(extensions), "catalog": "resource-index.json",
               "scope": {"whole_chunk_hashes_verified": False, "original_cdn_authenticity": "unknown",
                         "decoded_means": "inert container payload with manifest length and FHSH verified; format interpretation and rendering remain separate",
                         "scripts_executed": False, "account_data_requested": False, "network_used": False}}
    target = output / "receipt.json"
    if os.path.lexists(target) and not stat.S_ISREG(target.lstat().st_mode):
        raise AllReadError("Receipt destination must be a regular nonsymlink file")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".receipt-", dir=output, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    temporary.chmod(0o600)
    os.replace(temporary, target)
    return summary


def read_resources(source: Path, batches: list[Path], output: Path) -> dict:
    """Ingest independently verified packs; preserve and recheck prior coverage.

Each bad input pack is rejected as a whole and recorded without accepting any
of its fragments. Valid other packs remain reviewable. The source pin, manifest
limits and deterministic fragment set apply cumulatively across every resume.
"""
    manifest_data, manifest = source_manifest(Path(source))
    output = _private_output(Path(output))
    connection = _open_store(output, manifest_data)
    rejected = []
    try:
        touched, recovered = _rehash_parts(connection, output, manifest)
        expected_files = {f"{row:06d}.bin" for row in touched}
        if any(path.name not in expected_files or not stat.S_ISREG(path.lstat().st_mode)
               for path in (output / "files").iterdir()):
            raise AllReadError("Unexpected decoded filenames or filesystem objects")
        for ordinal, path in enumerate(batches):
            try:
                pack_hash, index, fragments = verify_batch(Path(path), manifest)
                touched.update(_publish_batch(connection, output, pack_hash, index, fragments))
            except (AllReadError, OSError) as error:
                reason = str(error)[:256]
                # Names supplied by the host are not retained in the receipt.
                identity = None
                try:
                    identity = _hash(_regular_bytes(Path(path), MAX_ZIP_BYTES))
                except (AllReadError, OSError):
                    pass
                rejected.append({"input_ordinal": ordinal, "zip_sha256": identity, "reason": reason})
                if identity:
                    if connection.execute("SELECT COUNT(*) FROM rejections").fetchone()[0] >= MAX_REJECTIONS:
                        raise AllReadError("Historical rejection count exceeded its bounded limit")
                    with connection:
                        connection.execute("INSERT OR REPLACE INTO rejections VALUES(?,?)", (identity, reason))
        for row in sorted(touched):
            _assemble(connection, output, manifest["files"][row])
        return _report(connection, output, manifest, rejected, recovered)
    finally:
        connection.close()


def batch_directory(directory: Path) -> list[Path]:
    """Select flat exporter pack names; no source ZIP or unrelated file is read."""
    directory = Path(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise AllReadError("Batch directory must be a nonsymlink directory")
    selected = []
    for path in directory.iterdir():
        if not BATCH_NAME.fullmatch(path.name):
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_ZIP_BYTES:
            raise AllReadError("Selected batch must be a bounded regular nonsymlink file")
        selected.append(path)
        if len(selected) > ssra.MAX_FILES + MAX_STORED_TOTAL_BYTES // MAX_PART_BYTES:
            raise AllReadError("Batch directory selection exceeds its cumulative count bound")
    if not selected:
        raise AllReadError("Batch directory contains no chaos-all-NNNNNN.zip packs")
    return sorted(selected, key=lambda path: path.name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Pinned chaos-all-source.zip")
    parser.add_argument("--output", required=True, type=Path, help="Private .local research directory; supports verified resume")
    parser.add_argument("--batch-dir", type=Path, help="Read all flat chaos-all-NNNNNN.zip packs in this directory; excludes source ZIP")
    parser.add_argument("batches", nargs="*", type=Path, help="One or more chaos-all-NNNNNN.zip packs")
    args = parser.parse_args(argv)
    try:
        batches = [*args.batches, *(batch_directory(args.batch_dir) if args.batch_dir else [])]
        result = read_resources(args.source, batches, args.output)
        print(json.dumps({key: result[key] for key in ("manifest_resource_count", "resource_status_counts", "received_unique_stored_bytes", "verified_batch_count", "all_manifest_resources_verified")}, indent=2))
        return 1 if result["rejected_input_batches"] else 0
    except (AllReadError, OSError, sqlite3.Error) as error:
        print(f"All-resource read failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
