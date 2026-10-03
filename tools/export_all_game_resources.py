#!/usr/bin/env python3
"""Export all accessible manifest-described CZN resources as inert upload batches.

Run on the user's Windows PC with its local LDPlayer. This reads the fixed
external gameres manifest/chunks only. It never launches game code, elevates
Android permissions, reads player accounts, or contacts a resource server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile

try:
    from . import export_ssra_ranges as ranges
    from . import export_android_research as existing
    from . import inventory_android_resources as android
    from . import read_ssra_manifest as ssra
except ImportError:
    import export_ssra_ranges as ranges
    import export_android_research as existing
    import inventory_android_resources as android
    import read_ssra_manifest as ssra

PROFILE = "chaos-all-static-resources-45a009358972-v1"
PACKAGE = ranges.PACKAGE
RESOURCE_ROOT = ranges.RESOURCE_ROOT
MANIFEST_PATH = ranges.MANIFEST_PATH
MANIFEST_BYTES = ranges.MANIFEST_BYTES
MANIFEST_SHA256 = ranges.MANIFEST_SHA256
MAX_PART_BYTES = 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_BATCH_PARTS = 2000
MAX_ZIP_BYTES = 30 * 1024 * 1024
DEFAULT_BATCH_BYTES = 28 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024**3
DEFAULT_TOTAL_BYTES = 12 * 1024**3
MAX_RESOURCE_BYTES = 512 * 1024 * 1024
SOURCE_PACK = "chaos-all-source.zip"
INDEX_MEMBER = "research-index.json"
SOURCE_MEMBER = "manifest/00.bin"
STATE_NAME = "export-state.sqlite3"
REPORT_NAME = "all-export-report.json"
BATCH_PATTERN = re.compile(r"chaos-all-([0-9]{6})\.zip")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}")


class AllExportError(ValueError):
    """A changed source, unsupported metadata or incomplete local transfer."""


def encode_json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode()


def common_index(kind: str) -> dict:
    return {"schema_version": 1, "profile": PROFILE, "package": PACKAGE,
            "kind": kind, "source_manifest_sha256": MANIFEST_SHA256}


def canonical_resource(item: dict) -> dict:
    return ranges.file_selection(item)


def derive_segments(manifest: dict, item: dict, part_offset: int, length: int) -> list[dict]:
    """Map a stored-resource fragment back to physical, source-pinned chunks."""
    if (type(part_offset) is not int or type(length) is not int or part_offset < 0
            or not 0 < length <= MAX_RESOURCE_BYTES
            or part_offset + length > item["stored_length"]):
        raise AllExportError("Fragment lies outside its manifest resource")
    start = item["offset"] + part_offset
    end, cursor, result = start + length, start, []
    for chunk in manifest["chunks"]:
        if chunk["group_id"] != item["group_id"]:
            continue
        left = max(start, chunk["logical_start"])
        right = min(end, chunk["logical_start"] + chunk["logical_length"])
        if left >= right:
            continue
        name = chunk["filename"]
        if (left != cursor or not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ssrc", name)
                or chunk["physical_length"] != chunk["logical_length"] + 16):
            raise AllExportError("Manifest has unsupported chunk coverage or filename")
        result.append({"chunk_row": chunk["row"], "chunk_filename": name,
                       "physical_offset": left - chunk["logical_start"], "bytes": right - left})
        cursor = right
    if cursor != end:
        raise AllExportError("Manifest resource has incomplete physical chunk coverage")
    return result


def validate_manifest(manifest: dict, maximum_bytes: int) -> list[dict]:
    """No arbitrary path list is accepted; every selection is an observed row."""
    if (not 0 < len(manifest["files"]) <= ssra.MAX_FILES
            or sum(item["stored_length"] for item in manifest["files"]) > maximum_bytes):
        raise AllExportError("Manifest resource total exceeds the declared export budget")
    for item in manifest["files"]:
        if (item["flags"] != 0 or item["encryption"] != 0
                or item["compression"] not in (0, 1)
                or item["stored_length"] > MAX_RESOURCE_BYTES
                or item["decoded_length"] > MAX_RESOURCE_BYTES):
            raise AllExportError("Manifest has unsupported flags/encryption/size; no false full-export claim")
        if item["stored_length"]:
            derive_segments(manifest, item, 0, item["stored_length"])
    return sorted(manifest["files"], key=lambda item: (item["group_id"], item["offset"], item["row"]))


class AllAdbRunner(ranges.RangeAdbRunner):
    def __init__(self, executable: Path, maximum_bytes: int):
        super().__init__(executable)
        self.binary_remaining = maximum_bytes


class ChunkCache:
    """A single aligned 1 MiB window is shared by adjacent resource reads."""

    def __init__(self, runner, serial: str, reader, chunks: list[dict], maximum_bytes: int):
        self.runner, self.serial, self.reader = runner, serial, reader
        self.chunks = {item["row"]: item for item in chunks}
        self.maximum_bytes = maximum_bytes
        self.transfer_bytes = 0
        self.read_calls = 0
        self.key = None
        self.data = b""

    def read_segment(self, segment: dict):
        chunk = self.chunks[segment["chunk_row"]]
        cursor = segment["physical_offset"]
        end = cursor + segment["bytes"]
        while cursor < end:
            block_start = cursor // MAX_PART_BYTES * MAX_PART_BYTES
            key = (chunk["row"], block_start)
            if key != self.key:
                count = min(MAX_PART_BYTES, chunk["physical_length"] - block_start)
                if self.transfer_bytes + count > self.maximum_bytes:
                    raise AllExportError("Aligned ADB reads exceed the declared transfer budget")
                read = {"chunk_filename": chunk["filename"],
                        "chunk_physical_length": chunk["physical_length"],
                        "physical_offset": block_start, "bytes": count,
                        "skip_blocks": block_start // ranges.BLOCK_BYTES,
                        "count_blocks": (count + ranges.BLOCK_BYTES - 1) // ranges.BLOCK_BYTES}
                command = ranges.dd_command(read, self.reader)
                result = self.runner.run_binary(["-s", self.serial, "exec-out", command], count)
                if result.returncode or len(result.stdout) != count:
                    raise AllExportError(f"Incomplete binary read: {chunk['filename']} at {block_start}")
                self.data, self.key = result.stdout, key
                self.transfer_bytes += count
                self.read_calls += 1
            take = min(end - cursor, len(self.data) - (cursor - block_start))
            if take <= 0:
                raise AllExportError("Chunk window did not cover the requested fragment")
            yield self.data[cursor - block_start:cursor - block_start + take]
            cursor += take


def _hash_file(path: Path) -> str:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_ZIP_BYTES:
        raise AllExportError("Upload batch must be a bounded regular nonsymlink file")
    return existing._file_hash(path, metadata.st_size)


def _read_json(data: bytes) -> dict:
    if len(data) > MAX_INDEX_BYTES:
        raise AllExportError("Batch index exceeds 2 MiB")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=ranges._unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise AllExportError("Invalid batch index JSON") from error
    if not isinstance(value, dict):
        raise AllExportError("Batch index must be an object")
    return value


def _validate_common(index: dict, kind: str) -> None:
    for key, value in common_index(kind).items():
        if index.get(key) != value or (key == "schema_version" and type(index.get(key)) is not int):
            raise AllExportError("Batch has another source, package, profile or kind")


def _regular_member(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1
            or info.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))):
        raise AllExportError("Batch has compressed, encrypted or nonregular members")


def _member(archive: zipfile.ZipFile, name: str) -> zipfile.ZipInfo:
    try:
        return archive.getinfo(name)
    except KeyError as error:
        raise AllExportError("Batch is missing a declared ZIP member") from error


def verify_batch(path: Path, manifest: dict) -> tuple[dict, dict]:
    """Fully verify completed batches before trusting them for resume."""
    match = BATCH_PATTERN.fullmatch(path.name)
    if not match:
        raise AllExportError("Unexpected upload batch filename")
    digest = _hash_file(path)
    by_row = {item["row"]: item for item in manifest["files"]}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_BATCH_PARTS + 1 or len({i.filename for i in infos}) != len(infos):
            raise AllExportError("Batch has too many or duplicate ZIP members")
        for info in infos:
            _regular_member(info)
        info = _member(archive, INDEX_MEMBER)
        if info.file_size > MAX_INDEX_BYTES:
            raise AllExportError("Batch index exceeds 2 MiB")
        index = _read_json(archive.read(info))
        _validate_common(index, "resources")
        if (set(index) != set(common_index("resources")) | {"batch_number", "files"}
                or type(index["batch_number"]) is not int
                or index["batch_number"] != int(match.group(1))
                or not isinstance(index["files"], list)
                or not 1 <= len(index["files"]) <= MAX_BATCH_PARTS):
            raise AllExportError("Invalid resource batch structure")
        expected_members = {INDEX_MEMBER}
        for entry in index["files"]:
            if not isinstance(entry, dict) or set(entry) != {"resource", "part_offset", "archive_path", "bytes", "sha256", "segments"}:
                raise AllExportError("Invalid stored fragment entry")
            resource = entry["resource"]
            item = by_row.get(resource.get("row")) if isinstance(resource, dict) else None
            if item is None or encode_json(resource) != encode_json(canonical_resource(item)):
                raise AllExportError("Fragment resource differs from pinned manifest")
            offset, length = entry["part_offset"], entry["bytes"]
            if (type(length) is not int or type(offset) is not int or offset < 0
                    or offset % MAX_PART_BYTES
                    or length != min(MAX_PART_BYTES, item["stored_length"] - offset)
                    or not 0 < length <= MAX_PART_BYTES):
                raise AllExportError("Fragment byte count exceeds 1 MiB")
            segments = derive_segments(manifest, item, offset, length)
            name = f"parts/{item['row']:06d}-{offset:012d}.bin"
            if (encode_json(entry["segments"]) != encode_json(segments) or entry["archive_path"] != name
                    or name in expected_members or not isinstance(entry["sha256"], str)
                    or not SHA_PATTERN.fullmatch(entry["sha256"])):
                raise AllExportError("Fragment mapping, identity or hash label is invalid")
            expected_members.add(name)
            member = _member(archive, name)
            if member.file_size != length:
                raise AllExportError("Fragment ZIP size disagrees with index")
            data = archive.read(member)
            if len(data) != length or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise AllExportError("Fragment hash/CRC verification failed")
        if set(i.filename for i in infos) != expected_members:
            raise AllExportError("Batch has undeclared members")
    return index, {"name": path.name, "bytes": path.stat().st_size, "sha256": digest,
                   "batch_number": index["batch_number"], "parts": len(index["files"])}


def _state(output: Path) -> sqlite3.Connection:
    path = output / STATE_NAME
    if os.path.lexists(path) and not stat.S_ISREG(path.lstat().st_mode):
        raise AllExportError("Resume state cannot be a symlink or nonregular file")
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS parts (
            row INTEGER NOT NULL, offset INTEGER NOT NULL, bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL, batch TEXT NOT NULL, member TEXT NOT NULL,
            PRIMARY KEY (row, offset));
        CREATE TABLE IF NOT EXISTS resources (
            row INTEGER PRIMARY KEY, status TEXT NOT NULL, bytes INTEGER NOT NULL,
            sha256 TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS batches (
            number INTEGER PRIMARY KEY, name TEXT NOT NULL, bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL, parts INTEGER NOT NULL);
    """)
    # Disk resume state is an optimization, never source authority. Rebuild it
    # from verified source-indexed ZIPs, so altered/incomplete state is harmless.
    db.executescript("DELETE FROM parts; DELETE FROM resources; DELETE FROM batches;")
    db.commit()
    return db


def _record_batch(db, index, descriptor) -> None:
    with db:
        db.execute("INSERT INTO batches VALUES (?, ?, ?, ?, ?)",
                   (descriptor["batch_number"], descriptor["name"], descriptor["bytes"], descriptor["sha256"], descriptor["parts"]))
        for entry in index["files"]:
            try:
                db.execute("INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?)",
                           (entry["resource"]["row"], entry["part_offset"], entry["bytes"], entry["sha256"],
                            descriptor["name"], entry["archive_path"]))
            except sqlite3.IntegrityError as error:
                raise AllExportError("Resume batches contain duplicate fragment offsets") from error


class BatchWriter:
    def __init__(self, output: Path, manifest: dict, db, batch_bytes: int):
        self.output, self.manifest, self.db, self.batch_bytes = output, manifest, db, batch_bytes
        self.number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM batches").fetchone()[0]
        self.archive = None
        self.entries = []
        self.payload_bytes = 0
        self.index_bytes = 512

    def _open(self):
        if self.number > 999999:
            raise AllExportError("Batch count exceeds its bounded filename space")
        self.name = f"chaos-all-{self.number:06d}.zip"
        self.path = self.output / (self.name + ".part")
        if os.path.lexists(self.path) or os.path.lexists(self.output / self.name):
            raise AllExportError("Refusing to overwrite an existing upload batch")
        self.archive = zipfile.ZipFile(self.path, "x", compression=zipfile.ZIP_STORED)

    def add(self, item: dict, offset: int, length: int, cache: ChunkCache, digest) -> None:
        segments = derive_segments(self.manifest, item, offset, length)
        entry = {"resource": canonical_resource(item), "part_offset": offset,
                 "archive_path": f"parts/{item['row']:06d}-{offset:012d}.bin",
                 "bytes": length, "sha256": "0" * 64, "segments": segments}
        estimated = len(encode_json(entry)) + 1
        # Reserve both ZIP headers/central records, filenames and the actual
        # index. Payload+index limits alone do not bound the final ZIP.
        overhead = sum(76 + 2 * len(e["archive_path"].encode()) for e in self.entries)
        predicted_zip = (self.payload_bytes + length + self.index_bytes + estimated
                         + overhead + 76 + 2 * len(entry["archive_path"].encode())
                         + 76 + 2 * len(INDEX_MEMBER) + 22)
        if (self.entries and (self.payload_bytes + length > self.batch_bytes
                            or len(self.entries) >= MAX_BATCH_PARTS
                            or self.index_bytes + estimated > MAX_INDEX_BYTES
                            or predicted_zip > MAX_ZIP_BYTES)):
            self.flush()
        if self.archive is None:
            self._open()
        part_digest, copied = hashlib.sha256(), 0
        info = zipfile.ZipInfo(entry["archive_path"])
        info.external_attr = (stat.S_IFREG | 0o600) << 16
        info.compress_type = zipfile.ZIP_STORED
        with self.archive.open(info, "w") as target:
            for segment in segments:
                for block in cache.read_segment(segment):
                    target.write(block)
                    part_digest.update(block)
                    digest.update(block)
                    copied += len(block)
        if copied != length:
            raise AllExportError("Stored fragment assembly has incomplete byte coverage")
        entry["sha256"] = part_digest.hexdigest()
        self.entries.append(entry)
        self.payload_bytes += length
        self.index_bytes += estimated

    def flush(self) -> None:
        if self.archive is None:
            return
        index = {**common_index("resources"), "batch_number": self.number, "files": self.entries}
        encoded = encode_json(index)
        if len(encoded) > MAX_INDEX_BYTES:
            raise AllExportError("Actual batch index exceeds its budget")
        self.archive.writestr(INDEX_MEMBER, encoded)
        self.archive.close()
        self.archive = None
        if self.path.stat().st_size > MAX_ZIP_BYTES:
            raise AllExportError("Actual upload ZIP exceeds 30 MiB")
        final = self.output / self.name
        self.path.rename(final)
        # Written bytes have already been hashed on their way into ZIP. The
        # whole upload hash identifies the final index and every stored member.
        descriptor = {"batch_number": self.number, "name": self.name,
                      "bytes": final.stat().st_size, "sha256": _hash_file(final), "parts": len(self.entries)}
        _record_batch(self.db, index, descriptor)
        print(f"Ready: {self.name} ({descriptor['bytes']:,} bytes; {len(self.entries)} parts)", flush=True)
        self.number += 1
        self.entries, self.payload_bytes, self.index_bytes = [], 0, 512

    def abort(self) -> None:
        if self.archive is not None:
            self.archive.close()
            self.archive = None
        if hasattr(self, "path") and self.path.exists():
            self.path.unlink()


class ResumeArchiveCache:
    """Keep the current ZIP open across nearby verified resume fragments."""

    def __init__(self, output: Path):
        self.output, self.batch, self.archive = output, None, None

    def read(self, batch: str, member: str) -> bytes:
        if batch != self.batch:
            self.close()
            self.archive = zipfile.ZipFile(self.output / batch)
            self.batch = batch
        return self.archive.read(member)

    def close(self):
        if self.archive is not None:
            self.archive.close()
        self.batch, self.archive = None, None


def prefix_hash(output: Path, db, item: dict, archives: ResumeArchiveCache | None = None) -> tuple[int, object]:
    """Resume only a contiguous verified prefix, including very large assets."""
    cursor, digest = 0, hashlib.sha256()
    for offset, length, expected_hash, batch, member in db.execute(
            "SELECT offset,bytes,sha256,batch,member FROM parts WHERE row=? ORDER BY offset", (item["row"],)):
        if offset != cursor or cursor + length > item["stored_length"]:
            raise AllExportError("Resume fragments overlap, have gaps or exceed a resource")
        if archives is not None:
            data = archives.read(batch, member)
        else:
            with zipfile.ZipFile(output / batch) as archive:
                data = archive.read(member)
        if len(data) != length or hashlib.sha256(data).hexdigest() != expected_hash:
            raise AllExportError("Resume fragment changed after batch verification")
        digest.update(data)
        cursor += length
    return cursor, digest


def _publish_source(output: Path, manifest_data: bytes) -> None:
    path = output / SOURCE_PACK
    expected = {**common_index("source"), "manifest": {"archive_path": SOURCE_MEMBER,
                "bytes": MANIFEST_BYTES, "sha256": MANIFEST_SHA256}}
    if path.exists():
        _hash_file(path)
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) != 2 or {i.filename for i in infos} != {INDEX_MEMBER, SOURCE_MEMBER}:
                raise AllExportError("Existing source ZIP has unexpected members")
            for info in infos:
                _regular_member(info)
            if _read_json(archive.read(INDEX_MEMBER)) != expected:
                raise AllExportError("Existing source index differs from this profile")
            if archive.getinfo(SOURCE_MEMBER).file_size != MANIFEST_BYTES or archive.read(SOURCE_MEMBER) != manifest_data:
                raise AllExportError("Existing source ZIP does not contain the pinned manifest")
        return
    stage = output / (SOURCE_PACK + ".part")
    with zipfile.ZipFile(stage, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(INDEX_MEMBER, encode_json(expected))
        archive.writestr(SOURCE_MEMBER, manifest_data)
    if stage.stat().st_size > MAX_ZIP_BYTES:
        stage.unlink()
        raise AllExportError("Source ZIP exceeds the upload limit")
    stage.rename(path)


def _availability(runner, serial: str, chunks: list[dict]) -> tuple[set[int], list[dict]]:
    available, missing = set(), []
    for chunk in chunks:
        name = chunk["filename"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ssrc", name):
            raise AllExportError("Manifest has no safe observed chunk filename")
        result = runner.run(["-s", serial, "shell", ranges.chunk_stat_command(name)])
        size = result.stdout.strip()
        if result.returncode or not re.fullmatch(rb"[0-9]{1,19}", size):
            missing.append({"chunk_row": chunk["row"], "filename": name,
                            "status": "not_accessible_regular_file", "expected_bytes": chunk["physical_length"]})
        elif int(size) != chunk["physical_length"]:
            missing.append({"chunk_row": chunk["row"], "filename": name,
                            "status": "size_mismatch", "expected_bytes": chunk["physical_length"], "observed_bytes": int(size)})
        else:
            available.add(chunk["row"])
    return available, missing


def _write_report(output: Path, manifest: dict, db, missing: list[dict], cache, status: str, detail: str | None) -> dict:
    counts = dict(db.execute("SELECT status,COUNT(*) FROM resources GROUP BY status"))
    complete = counts.get("exported", 0)
    batches = [{"batch_number": n, "name": name, "bytes": size, "sha256": digest, "parts": parts}
               for n, name, size, digest, parts in db.execute("SELECT * FROM batches ORDER BY number")]
    unavailable = [{"row": row, "path": manifest["files"][row]["path"], "status": state, "detail": why}
                   for row, state, why in db.execute("SELECT row,status,detail FROM resources WHERE status!='exported' ORDER BY row")]
    report = {**common_index("report"), "status": status, "detail": detail,
              "manifest_resource_count": len(manifest["files"]), "exported_resource_count": complete,
              "manifest_stored_bytes": sum(item["stored_length"] for item in manifest["files"]),
              "exported_stored_bytes": db.execute("SELECT COALESCE(SUM(bytes),0) FROM resources WHERE status='exported'").fetchone()[0],
              "all_manifest_resources_exported": complete == len(manifest["files"]) and status == "complete",
              "resource_status_counts": counts, "unavailable_resources": unavailable, "missing_chunks": missing,
              "exported_resources": [{"row": row, "path": manifest["files"][row]["path"], "bytes": size, "sha256": digest}
                                     for row, size, digest in db.execute(
                                         "SELECT row,bytes,sha256 FROM resources WHERE status='exported' ORDER BY row")],
              "source_pack": {"name": SOURCE_PACK, "bytes": (output / SOURCE_PACK).stat().st_size,
                              "sha256": _hash_file(output / SOURCE_PACK)},
              "batches": batches,
              "this_run": {"aligned_read_bytes": cache.transfer_bytes, "binary_read_calls": cache.read_calls},
              "scope": {"all_manifest_rows_selected": True, "static_resource_chunks_only": True,
                        "root_elevation_requested": False, "account_data_exported": False,
                        "game_code_executed": False, "network_requests_made": False,
                        "decoded_FHSH_verified": False, "whole_chunk_hashes_verified": False,
                        "stored_fragments_sha256_verified": True,
                        "source_authenticity": "unknown; source pin and SHA identify the local bytes",
                        "missing_assets_downloaded": False}}
    encoded = encode_json(report)
    if len(encoded) > ssra.MAX_INDEX_BYTES:
        raise AllExportError("Export report exceeds its bounded metadata budget")
    stage = output / (REPORT_NAME + ".part")
    with stage.open("xb") as stream:
        stream.write(encoded)
    stage.replace(output / REPORT_NAME)
    return report


def export_all(output: Path, adb: Path | None = None, serial: str = "emulator-5554", *,
               resume: bool = False, maximum_bytes: int = DEFAULT_TOTAL_BYTES,
               batch_bytes: int = DEFAULT_BATCH_BYTES, runner=None) -> dict:
    output = Path(output)
    if (type(maximum_bytes) is not int or not MANIFEST_BYTES <= maximum_bytes <= MAX_TOTAL_BYTES
            or type(batch_bytes) is not int or not MAX_PART_BYTES <= batch_bytes <= DEFAULT_BATCH_BYTES):
        raise AllExportError("Invalid transfer or upload batch budget")
    if android._control_text(str(output)) or not android.local_serial(serial):
        raise AllExportError("Output path or local emulator serial is invalid")
    if os.path.lexists(output):
        if not resume or not stat.S_ISDIR(output.lstat().st_mode):
            raise AllExportError("Output exists; use --resume on the same regular directory")
    executable = android.locate_adb(adb)
    runner = runner or AllAdbRunner(executable, maximum_bytes)
    devices = runner.run(["devices", "-l"])
    if devices.returncode:
        raise AllExportError("Cannot list local ADB devices")
    serial = android.select_device(android.parse_devices(devices.stdout), serial)
    android.validate_package_query(runner.run(["-s", serial, "shell", f"pm path {PACKAGE}"]), serial)
    reader, _ = ranges.select_reader(runner, serial)
    target = existing.TARGETS[0]
    existing._check_remote(runner, serial, target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chaos-all-manifest-", dir=output.parent) as temporary:
        manifest_file = Path(temporary) / "manifest.bin"
        result = runner.run(["-s", serial, "pull", RESOURCE_ROOT + "/" + MANIFEST_PATH, str(manifest_file)],
                            destination=manifest_file, maximum_bytes=MANIFEST_BYTES)
        if result.returncode or existing._file_hash(manifest_file, MANIFEST_BYTES) != MANIFEST_SHA256:
            raise AllExportError("Installed manifest differs from the pinned version; export stopped")
        data = manifest_file.read_bytes()
    existing._check_remote(runner, serial, target)
    manifest = ssra.parse_ssra(data)
    items = validate_manifest(manifest, maximum_bytes)
    # One copy of stored bytes, ZIP/index overhead, and bounded metadata state.
    expected_disk = sum(item["stored_length"] for item in items) + MANIFEST_BYTES + 256 * 1024**2
    existing_bytes = (sum(p.lstat().st_size for p in output.iterdir() if stat.S_ISREG(p.lstat().st_mode))
                      if output.exists() else 0)
    if shutil.disk_usage(output.parent).free < max(64 * 1024**2, expected_disk - existing_bytes):
        raise AllExportError(f"Insufficient free disk: allow approximately {expected_disk / 1024**3:.2f} GiB for this export")
    output.mkdir(exist_ok=resume)
    # Only our unfinished staging names may be removed during explicit resume.
    for path in output.glob("*.part"):
        if path.name in (SOURCE_PACK + ".part", REPORT_NAME + ".part") or re.fullmatch(r"chaos-all-[0-9]{6}\.zip\.part", path.name):
            if not stat.S_ISREG(path.lstat().st_mode):
                raise AllExportError("Unfinished export path is not a regular file")
            path.unlink()
    _publish_source(output, data)
    db = _state(output)
    writer = None
    archives = ResumeArchiveCache(output)
    cache = ChunkCache(runner, serial, reader, manifest["chunks"], maximum_bytes)
    missing = []
    try:
        for path in sorted(output.glob("chaos-all-*.zip")):
            if BATCH_PATTERN.fullmatch(path.name):
                index, descriptor = verify_batch(path, manifest)
                _record_batch(db, index, descriptor)
        available, missing = _availability(runner, serial, manifest["chunks"])
        writer = BatchWriter(output, manifest, db, batch_bytes)
        for ordinal, item in enumerate(items):
            if ordinal and ordinal % 1000 == 0:
                db.commit()
                print(f"Resources checked: {ordinal:,}/{len(items):,}; reads {cache.read_calls:,}", flush=True)
            offset, digest = prefix_hash(output, db, item, archives)
            if offset < item["stored_length"]:
                segments = derive_segments(manifest, item, offset, item["stored_length"] - offset)
                absent = sorted({segment["chunk_row"] for segment in segments} - available)
                if absent:
                    db.execute("INSERT OR REPLACE INTO resources VALUES (?, 'missing', ?, NULL, ?)",
                               (item["row"], offset, "missing chunk rows: " + ",".join(map(str, absent))))
                    continue
            while offset < item["stored_length"]:
                length = min(MAX_PART_BYTES, item["stored_length"] - offset)
                writer.add(item, offset, length, cache, digest)
                offset += length
            db.execute("INSERT OR REPLACE INTO resources VALUES (?, 'exported', ?, ?, NULL)",
                       (item["row"], offset, digest.hexdigest()))
        writer.flush()
        db.commit()
        # Recheck source sizes after reads; no whole-chunk authenticity claim.
        after_available, after_missing = _availability(runner, serial, manifest["chunks"])
        if after_available != available or after_missing != missing:
            raise AllExportError("Resource chunk availability/size changed during export")
        status = "partial" if missing else "complete"
        return _write_report(output, manifest, db, missing, cache, status, None)
    except (AllExportError, ranges.RangeExportError, existing.ExportError, android.InventoryError,
            OSError, zipfile.BadZipFile, sqlite3.DatabaseError, KeyboardInterrupt) as error:
        if writer:
            writer.abort()
        # A resource marked complete in RAM can still have its last part in the
        # aborted batch. Reconcile statuses against committed fragment coverage.
        for item in items:
            actual = db.execute("SELECT COALESCE(SUM(bytes),0) FROM parts WHERE row=?", (item["row"],)).fetchone()[0]
            if actual != item["stored_length"]:
                db.execute("INSERT OR REPLACE INTO resources VALUES (?, 'pending', ?, NULL, ?)",
                           (item["row"], actual, "rerun the same command with --resume"))
        db.commit()
        try:
            _write_report(output, manifest, db, missing, cache, "interrupted", android.diagnostic(str(error))[:512])
        except (OSError, AllExportError):
            pass
        raise AllExportError(f"Export interrupted; completed ZIPs were preserved. Use --resume. {error}") from error
    finally:
        archives.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--list-only", action="store_true", help="Inspect the pinned local manifest without connecting to Android")
    parser.add_argument("--manifest", type=Path, help="Local manifest; accepted only with --list-only")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-gib", type=float, default=12, help="Cumulative aligned-read budget (hard limit 16 GiB)")
    parser.add_argument("--batch-mib", type=int, default=28, help="Stored bytes per batch, 1–28 MiB; final ZIP <=30 MiB")
    args = parser.parse_args(argv)
    try:
        if args.list_only:
            if args.manifest is None:
                raise AllExportError("--list-only requires the already received --manifest file")
            manifest = ssra.read_ssra(args.manifest, MANIFEST_SHA256)
            items = validate_manifest(manifest, int(args.max_gib * 1024**3))
            print(json.dumps({**common_index("metadata_only"), "resources": len(items),
                  "chunks": len(manifest["chunks"]), "stored_bytes": sum(i["stored_length"] for i in items),
                  "decoded_bytes": sum(i["decoded_length"] for i in items),
                  "maximum_resource_bytes": max(i["stored_length"] for i in items),
                  "deterministic_fragments": sum((i["stored_length"] + MAX_PART_BYTES - 1) // MAX_PART_BYTES for i in items),
                  "payloads_received_by_this_command": False}, ensure_ascii=True, indent=2))
            return 0
        if args.manifest is not None or args.output is None:
            raise AllExportError("Export requires --output; --manifest is only accepted with --list-only")
        report = export_all(args.output, args.adb, args.serial, resume=args.resume,
                            maximum_bytes=int(args.max_gib * 1024**3), batch_bytes=args.batch_mib * 1024**2)
    except (ValueError, OverflowError, OSError) as error:
        print(f"All-resource export failed: {error}", file=sys.stderr)
        return 1
    print(f"Export {report['status']}: {report['exported_resource_count']:,}/{report['manifest_resource_count']:,} resources")
    print(f"Upload {SOURCE_PACK}, {REPORT_NAME}, and the {len(report['batches'])} chaos-all-NNNNNN.zip batches.")
    print("These are stored reference bytes, not decoded pictures or game screenshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
