#!/usr/bin/env python3
"""Copy bounded card/battle resource ranges from the user's local LDPlayer.

The fixed SSRA manifest is copied and SHA-256 verified before its selected rows
are used. Only aligned spans covering the approved resource paths are read; no
whole resource chunks, credentials, account files, or executable code are run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import zipfile

try:
    from . import export_android_research as existing
    from . import inventory_android_resources as android
    from . import read_ssra_manifest as ssra
except ImportError:
    import export_android_research as existing
    import inventory_android_resources as android
    import read_ssra_manifest as ssra

PACKAGE = android.PACKAGE
RESOURCE_ROOT = android.RESOURCE_ROOTS[0]
PROFILE = "chaos-card-battle-ranges-45a009358972-v1"
MANIFEST_PATH = "gameres/manifest.ssra"
MANIFEST_BYTES = 7_506_387
MANIFEST_SHA256 = "45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15"
PACK_NAME = "chaos-card-battle-ranges.zip"
MAX_PLAN_BYTES = 64 * 1024
MAX_INDEX_BYTES = 256 * 1024
MAX_FILES = 20
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024
MAX_READBACK_BYTES = 8 * 1024 * 1024
MAX_BINARY_CALL_BYTES = 1024 * 1024
MAX_BINARY_STDERR_BYTES = 64 * 1024
MAX_DIAGNOSTIC_OUTPUT_BYTES = 64 * 1024
MAX_ZIP_BYTES = 30 * 1024 * 1024
BLOCK_BYTES = 65_536
FILE_FIELDS = {"path", "row", "group_id", "offset", "stored_length", "decoded_length",
               "compression", "encryption", "flags", "file_hash64"}
APPROVED_PATHS = (
    "db/card.db", "db/skill_eff.db", "db/cs.db", "db/cond_card.db",
    "db/battle_system_effect.db", "db/card(public)@card.db", "db/card(ikarus)@card.db",
    "db/card(public)@skill_eff.db", "db/card(ikarus)@skill_eff.db", "db/cs(card1)@cs.db",
    "db/cs(card1)@skill_eff.db", "db/condition@cond_card.db",
    "db/battle_system_effect@battle_system_effect.db", "wnd/scene_battle_field.csb",
    "wnd/game_hud_hand.csb", "ui/game_hud_handpiles.csb", "wnd/game_card_select_hand.csb",
    "wnd/card.csb",
)


@dataclass(frozen=True)
class RangeReader:
    identity: str
    prefix: str


READERS = (
    RangeReader("dd", "dd"),
    RangeReader("system-toybox-dd", "/system/bin/toybox dd"),
    RangeReader("system-xbin-busybox-dd", "/system/xbin/busybox dd"),
    RangeReader("system-bin-busybox-dd", "/system/bin/busybox dd"),
)


class RangeExportError(ValueError):
    """Invalid plan, changed local resources, or failed bounded export."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RangeExportError("Plan JSON contains a duplicate object key")
        result[key] = value
    return result


def _keys(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise RangeExportError(f"{label} has unexpected or missing fields")


def _integer(value, label: str, maximum: int = (1 << 64) - 1) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise RangeExportError(f"Invalid bounded integer: {label}")
    return value


def file_selection(item: dict) -> dict:
    """Canonical expected row metadata; the JSON contains no executable paths."""
    result = {key: item[key] for key in FILE_FIELDS if key != "file_hash64"}
    result["file_hash64"] = (f"{item['file_hash64']:016x}" if item["file_hash64"] is not None else None)
    return result


def read_plan(path: Path) -> tuple[dict, str]:
    metadata = Path(path).lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PLAN_BYTES:
        raise RangeExportError("Plan must be a regular nonsymlink file no larger than 64 KiB")
    with Path(path).open("rb") as stream:
        encoded = stream.read(MAX_PLAN_BYTES + 1)
    if len(encoded) != metadata.st_size or len(encoded) > MAX_PLAN_BYTES:
        raise RangeExportError("Plan size changed or exceeded its limit")
    try:
        plan = json.loads(encoded.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except RangeExportError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RangeExportError("Plan is not bounded UTF-8 JSON") from error
    _keys(plan, {"schema_version", "profile", "package", "manifest", "selected_files"}, "Plan")
    if (type(plan["schema_version"]) is not int or plan["schema_version"] != 1
            or plan["profile"] != PROFILE or plan["package"] != PACKAGE):
        raise RangeExportError("Plan schema, profile, or package differs from this fixed selection")
    _keys(plan["manifest"], {"relative_path", "bytes", "sha256"}, "Plan manifest")
    if (plan["manifest"]["relative_path"] != MANIFEST_PATH
            or type(plan["manifest"]["bytes"]) is not int
            or plan["manifest"]["bytes"] != MANIFEST_BYTES
            or plan["manifest"]["sha256"] != MANIFEST_SHA256):
        raise RangeExportError("Plan manifest path, size, or SHA-256 differs from the pinned profile")
    selected = plan["selected_files"]
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_FILES:
        raise RangeExportError("Select between one and 20 approved resource paths")
    seen = set()
    total = 0
    for item in selected:
        _keys(item, FILE_FIELDS, "Selected resource")
        name = item["path"]
        if not isinstance(name, str) or name not in APPROVED_PATHS or name in seen:
            raise RangeExportError("Selected resource path is unexpected, unsafe, or duplicated")
        seen.add(name)
        for key, maximum in (("row", ssra.MAX_FILES - 1), ("group_id", 65535),
                             ("offset", (1 << 64) - 1), ("stored_length", MAX_PAYLOAD_BYTES),
                             ("decoded_length", 64 * 1024 * 1024), ("compression", 1),
                             ("encryption", 0), ("flags", 0)):
            _integer(item[key], key, maximum)
        if not item["stored_length"] or not isinstance(item["file_hash64"], str) or not re.fullmatch(r"[0-9a-f]{16}", item["file_hash64"]):
            raise RangeExportError("Selected resource must have a nonempty stored span and an observed FHSH value")
        total += item["stored_length"]
    if total > MAX_PAYLOAD_BYTES:
        raise RangeExportError("Selected stored resources exceed the 5 MiB limit")
    return plan, hashlib.sha256(encoded).hexdigest()


def derive_selection(manifest: dict, selected: list[dict]) -> tuple[list[dict], list[dict]]:
    """Recompute every physical range and merged aligned read from actual rows."""
    by_path = {item["path"]: item for item in manifest["files"]}
    items, spans = [], {}
    for expected in selected:
        item = by_path.get(expected["path"])
        if item is None or file_selection(item) != expected:
            raise RangeExportError("Selected resource metadata disagrees with the verified manifest")
        if item["flags"] or item["encryption"] or not item["stored_length"]:
            raise RangeExportError("Only present, unencrypted resource ranges are supported")
        start, end = item["offset"], item["offset"] + item["stored_length"]
        cursor, segments = start, []
        for chunk in manifest["chunks"]:
            if chunk["group_id"] != item["group_id"]:
                continue
            chunk_start, chunk_end = chunk["logical_start"], chunk["logical_start"] + chunk["logical_length"]
            overlap_start, overlap_end = max(start, chunk_start), min(end, chunk_end)
            if overlap_start >= overlap_end:
                continue
            name = chunk["filename"]
            if (overlap_start != cursor or not isinstance(name, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ssrc", name)
                    or chunk["physical_length"] < 16
                    or chunk["logical_length"] > chunk["physical_length"] - 16):
                raise RangeExportError("Selected range has unknown or unsafe chunk metadata")
            offset, length = overlap_start - chunk_start, overlap_end - overlap_start
            segments.append({"chunk_row": chunk["row"], "chunk_index": chunk["index"],
                             "group_id": chunk["group_id"], "chunk_filename": name,
                             "physical_offset": offset, "bytes": length,
                             "chunk_logical_length": chunk["logical_length"],
                             "chunk_physical_length": chunk["physical_length"],
                             "expected_chunk_xxh64": f"{chunk['hash64']:016x}"})
            aligned_start = offset // BLOCK_BYTES * BLOCK_BYTES
            aligned_end = min((offset + length + BLOCK_BYTES - 1) // BLOCK_BYTES * BLOCK_BYTES,
                              chunk["physical_length"])
            spans.setdefault(chunk["row"], []).append((aligned_start, aligned_end, chunk))
            cursor = overlap_end
        if cursor != end:
            raise RangeExportError("Selected resource has incomplete chunk coverage")
        items.append({**expected, "segments": segments})
    reads = []
    for row, chunk_spans in sorted(spans.items()):
        merged = []
        for start, end, chunk in sorted(chunk_spans, key=lambda span: span[0]):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]), chunk)
            else:
                merged.append((start, end, chunk))
        for start, end, chunk in merged:
            while start < end:
                length = min(MAX_BINARY_CALL_BYTES, end - start)
                reads.append({"chunk_row": row, "chunk_filename": chunk["filename"],
                              "chunk_physical_length": chunk["physical_length"],
                              "physical_offset": start, "bytes": length,
                              "skip_blocks": start // BLOCK_BYTES,
                              "count_blocks": (length + BLOCK_BYTES - 1) // BLOCK_BYTES})
                start += length
    if sum(item["stored_length"] for item in items) > MAX_PAYLOAD_BYTES:
        raise RangeExportError("Selected stored resources exceed the 5 MiB limit")
    if sum(read["bytes"] for read in reads) > MAX_READBACK_BYTES:
        raise RangeExportError("Aligned chunk readback exceeds the 8 MiB limit")
    return items, reads


class RangeAdbRunner(existing.ExportAdbRunner):
    """Retain shared bounded local commands and separately bound binary stdout."""

    def __init__(self, executable: Path):
        super().__init__(executable)
        self.binary_remaining = MAX_READBACK_BYTES
        self.stderr_remaining = existing.MAX_ADB_OUTPUT_BYTES

    def run_diagnostic(self, arguments: list[str]) -> android.CommandResult:
        # Reuse the local-server/time-bounded runner with a smaller per-command
        # text budget while preserving its cumulative diagnostic budget.
        previous = self.remaining
        allowance = min(previous, MAX_DIAGNOSTIC_OUTPUT_BYTES)
        self.remaining = allowance
        try:
            return self.run(arguments)
        finally:
            self.remaining = previous - (allowance - self.remaining)

    def run_binary(self, arguments: list[str], expected_bytes: int) -> android.CommandResult:
        if not 0 < expected_bytes <= min(MAX_BINARY_CALL_BYTES, self.binary_remaining):
            raise RangeExportError("Binary ADB read exceeds its per-call or cumulative limit")
        env = os.environ.copy()
        for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
            env.pop(name, None)
        try:
            process = subprocess.Popen([str(self.executable), "-P", "5037", *arguments],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, shell=False, env=env)
        except OSError as error:
            raise RangeExportError(f"Could not start ADB: {android.diagnostic(str(error))}") from error
        limits = (expected_bytes, min(MAX_BINARY_STDERR_BYTES, self.stderr_remaining))
        buffers = [bytearray(), bytearray()]
        observed = [0, 0]
        overflow = threading.Event()

        def drain(stream, index):
            try:
                while True:
                    block = stream.read(BLOCK_BYTES)
                    if not block:
                        break
                    observed[index] += len(block)
                    allowed = min(len(block), limits[index] - len(buffers[index]))
                    buffers[index].extend(block[:allowed])
                    if allowed != len(block):
                        overflow.set()
                        try:
                            process.kill()
                        except OSError:
                            pass
                        break
            finally:
                stream.close()

        threads = [threading.Thread(target=drain, args=(stream, index), daemon=True)
                   for index, stream in enumerate((process.stdout, process.stderr))]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=existing.COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if timed_out or process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    timed_out = True
            for thread in threads:
                thread.join(timeout=2)
            self.binary_remaining -= len(buffers[0])
            self.stderr_remaining -= len(buffers[1])
        received = (f"at least {observed[0]}" if observed[0] > limits[0] else str(observed[0]))
        counts = (f"exit={process.returncode}; expected_stdout_bytes={expected_bytes}; "
                  f"received_stdout_bytes={received}; local_stderr_bytes={observed[1]}")
        detail = android.diagnostic(bytes(buffers[1]))[:512] or "no local ADB diagnostic returned"
        if any(thread.is_alive() for thread in threads):
            raise RangeExportError(f"Binary ADB pipes did not close within the command limit ({counts}); {detail}")
        if timed_out:
            raise RangeExportError(f"Binary ADB command timed out after 60 seconds ({counts}); {detail}")
        if overflow.is_set():
            raise RangeExportError(f"Binary ADB stdout or stderr exceeded its bounded limit ({counts}); {detail}")
        result = android.CommandResult(process.returncode, bytes(buffers[0]), bytes(buffers[1]))
        if result.returncode or len(result.stdout) != expected_bytes:
            raise RangeExportError(f"Binary ADB read failed or returned an unexpected byte count ({counts}); {detail}")
        return result


def chunk_stat_command(filename: str) -> str:
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ssrc", filename):
        raise RangeExportError("Chunk filename is not a fixed safe resource basename")
    root = RESOURCE_ROOT + "/gameres"
    directory = root + "/chunks"
    path = directory + "/" + filename
    return (f"if [ ! -L {shlex.quote(root)} ] && [ ! -L {shlex.quote(directory)} ] "
            f"&& [ -f {shlex.quote(path)} ] && [ ! -L {shlex.quote(path)} ]; "
            f"then stat -c '%s' {shlex.quote(path)}; else exit 7; fi")


def _check_chunk(runner, serial: str, read: dict) -> None:
    result = runner.run(["-s", serial, "shell", chunk_stat_command(read["chunk_filename"])])
    size = result.stdout.strip()
    if result.returncode or not re.fullmatch(rb"[0-9]{1,19}", size):
        raise RangeExportError("Selected resource chunk is not an accessible regular nonsymlink file")
    if int(size) != read["chunk_physical_length"]:
        raise RangeExportError("Selected resource chunk size changed or disagrees with the manifest")


def _reader(reader: RangeReader) -> RangeReader:
    if reader not in READERS:
        raise RangeExportError("Android range reader must be one of the fixed approved backends")
    return reader


def reader_probe_command(reader: RangeReader) -> str:
    prefix = _reader(reader).prefix
    return (f"{prefix} if=/dev/zero of=/dev/null bs={BLOCK_BYTES} skip=1 count=1 2>&1; "
            "ssra_reader_probe_status=$?; printf '__ssra_reader_probe_exit=%s\\n' \"$ssra_reader_probe_status\"")


def select_reader(runner, serial: str) -> tuple[RangeReader, list[dict]]:
    """Probe fixed Android binaries against inert data, never game resources."""
    probes = []
    for reader in READERS:
        try:
            result = runner.run_diagnostic(["-s", serial, "shell", reader_probe_command(reader)])
        except (RangeExportError, existing.ExportError, android.InventoryError, OSError) as error:
            raise RangeExportError(f"Android range-reader probe transport failed on {serial}: {android.diagnostic(str(error))[:512]}") from error
        if len(result.stdout) + len(result.stderr) > MAX_DIAGNOSTIC_OUTPUT_BYTES:
            raise RangeExportError("Android range-reader probe exceeded its 64 KiB text limit")
        text = result.stdout.decode("utf-8", "replace")
        markers = re.findall(r"(?:^|\n)__ssra_reader_probe_exit=([0-9]{1,3})\r?(?=\n|$)", text)
        status = int(markers[0]) if len(markers) == 1 and int(markers[0]) <= 255 else None
        detail = android.diagnostic(re.sub(r"(?:^|\n)__ssra_reader_probe_exit=[^\r\n]*", "", text))[:256]
        probes.append({"reader": reader.identity, "shell_exit": result.returncode,
                       "remote_exit": status, "usable": result.returncode == 0 and status == 0,
                       "remote_detail": detail, "local_ADB_detail": android.diagnostic(result.stderr)[:256]})
        if result.returncode:
            raise RangeExportError(f"Android range-reader probe transport failed on {serial}: shell_exit={result.returncode}; {android.diagnostic(result.stderr)[:512] or detail or 'no diagnostic returned'}")
        if status == 0:
            return reader, probes
    details = "; ".join(f"{item['reader']}: remote_exit={item['remote_exit']}; {item['remote_detail'] or 'no remote diagnostic'}" for item in probes)
    raise RangeExportError(
        f"No usable bounded Android dd reader found on {serial}. Checked only fixed dd/toybox/busybox backends; "
        f"no manifest or resource chunks were copied. Share this capability result for the next reader choice: {details}"
    )


def dd_command(read: dict, reader: RangeReader = READERS[0]) -> str:
    prefix = _reader(reader).prefix
    name = read["chunk_filename"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ssrc", name):
        raise RangeExportError("Unsafe chunk filename")
    skip = _integer(read["skip_blocks"], "skip blocks")
    count = _integer(read["count_blocks"], "count blocks", MAX_BINARY_CALL_BYTES // BLOCK_BYTES)
    offset, expected = skip * BLOCK_BYTES, _integer(read["bytes"], "read bytes", MAX_BINARY_CALL_BYTES)
    if (not count or not expected or offset != read["physical_offset"]
            or expected != min(read["chunk_physical_length"] - offset, count * BLOCK_BYTES)):
        raise RangeExportError("Invalid independently derived aligned read")
    remote = RESOURCE_ROOT + "/gameres/chunks/" + name
    # ADB's raw exec-out service merges the remote command's fd 1 and fd 2.
    # Suppress dd's remote statistics/errors so they cannot become payload bytes;
    # the exact returned length still rejects missing or failed range reads.
    # Popen.stderr contains local ADB diagnostics only, not remote dd stderr.
    return f"{prefix} if={shlex.quote(remote)} bs={BLOCK_BYTES} skip={skip} count={count} 2>/dev/null"


def diagnostic_dd_command(read: dict, reader: RangeReader = READERS[0]) -> str:
    """Read the same bounded span into /dev/null, returning remote status only."""
    command = dd_command(read, reader).removesuffix(" 2>/dev/null")
    return (command + " of=/dev/null 2>&1; ssra_range_dd_status=$?; "
            "printf '__ssra_range_dd_exit=%s\\n' \"$ssra_range_dd_status\"")


def _diagnose_remote_read(runner, serial: str, read: dict, reader: RangeReader) -> str:
    # This is one diagnostic after a failed export, never a transport fallback.
    # It reads only the failed <=1 MiB span, discards payload bytes remotely and
    # cannot rescue or publish the failed export.
    try:
        result = runner.run_diagnostic(["-s", serial, "shell", diagnostic_dd_command(read, reader)])
    except (RangeExportError, existing.ExportError, android.InventoryError, OSError) as error:
        return f"Same-range remote diagnostic transport failed: {android.diagnostic(str(error))[:512]}"
    if len(result.stdout) + len(result.stderr) > MAX_DIAGNOSTIC_OUTPUT_BYTES:
        return "Same-range remote diagnostic exceeded its 64 KiB text limit"
    remote_text = result.stdout.decode("utf-8", "replace")
    markers = re.findall(r"(?:^|\n)__ssra_range_dd_exit=([0-9]{1,3})\r?(?=\n|$)", remote_text)
    remote_exit = markers[0] if len(markers) == 1 and int(markers[0]) <= 255 else "unknown (missing or invalid marker)"
    remote_text = re.sub(r"(?:^|\n)__ssra_range_dd_exit=[^\r\n]*", "", remote_text)
    remote_detail = android.diagnostic(remote_text)[:512] or "no remote dd diagnostic returned"
    local_detail = android.diagnostic(result.stderr)[:256] or "none"
    return (f"Same-range diagnostic: shell_exit={result.returncode}; remote_dd_exit={remote_exit}; "
            f"remote_output_bytes={len(result.stdout)}; local_stderr_bytes={len(result.stderr)}; "
            f"remote_detail={remote_detail}; local_ADB_detail={local_detail}")


def export_ranges(plan_path: Path, output: Path, adb: Path | None, serial: str, runner=None) -> dict:
    output = Path(output)
    if os.path.lexists(output):
        raise RangeExportError("Output already exists; choose a new directory to preserve research")
    if android._control_text(str(output)) or not android.local_serial(serial):
        raise RangeExportError("Output must be a safe new path and serial must name a local emulator")
    plan, plan_hash = read_plan(plan_path)
    executable = android.locate_adb(adb)
    runner = runner or RangeAdbRunner(executable)
    devices = runner.run(["devices", "-l"])
    if devices.returncode:
        raise RangeExportError("Could not list local ADB devices")
    serial = android.select_device(android.parse_devices(devices.stdout), serial)
    android.validate_package_query(runner.run(["-s", serial, "shell", f"pm path {PACKAGE}"]), serial)
    reader, reader_probes = select_reader(runner, serial)
    manifest_target = existing.Target(MANIFEST_PATH, MANIFEST_BYTES, existing.PACK_NAMES[0])
    existing._check_remote(runner, serial, manifest_target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chaos-range-export-", dir=output.parent) as temporary:
        stage = Path(temporary)
        manifest_file = stage / "manifest-00.bin"
        result = runner.run(["-s", serial, "pull", RESOURCE_ROOT + "/" + MANIFEST_PATH, str(manifest_file)],
                            destination=manifest_file, maximum_bytes=MANIFEST_BYTES)
        if result.returncode or existing._file_hash(manifest_file, MANIFEST_BYTES) != MANIFEST_SHA256:
            raise RangeExportError("Manifest pull failed or its SHA-256 differs from the pinned source")
        existing._check_remote(runner, serial, manifest_target)
        manifest_file.chmod(0o600)
        manifest = ssra.parse_ssra(manifest_file.read_bytes())
        items, reads = derive_selection(manifest, plan["selected_files"])
        readback = {}
        for ordinal, read in enumerate(reads):
            _check_chunk(runner, serial, read)
            try:
                result = runner.run_binary(["-s", serial, "exec-out", dd_command(read, reader)], read["bytes"])
                if (result.returncode or len(result.stdout) != read["bytes"]
                        or len(result.stderr) > MAX_BINARY_STDERR_BYTES):
                    detail = android.diagnostic(result.stderr)[:512] or "no local ADB diagnostic returned"
                    raise RangeExportError(
                        "Binary ADB read failed or returned an unexpected bounded byte count "
                        f"(exit={result.returncode}; expected_stdout_bytes={read['bytes']}; "
                        f"received_stdout_bytes={len(result.stdout)}; local_stderr_bytes={len(result.stderr)}); {detail}"
                    )
            except RangeExportError as error:
                context = (f"Read {ordinal + 1}/{len(reads)} on {serial}: reader={reader.identity}; "
                           f"chunk={read['chunk_filename']}; physical_offset={read['physical_offset']}; "
                           f"skip_blocks={read['skip_blocks']}; count_blocks={read['count_blocks']}")
                diagnostic = _diagnose_remote_read(runner, serial, read, reader)
                raise RangeExportError(f"{context}. {error}. {diagnostic}") from error
            readback[ordinal] = result.stdout
            _check_chunk(runner, serial, read)
            read["actual_span_sha256"] = hashlib.sha256(result.stdout).hexdigest()
        payloads = {"manifest/00.bin": manifest_file}
        entries = []
        for ordinal, item in enumerate(items):
            pieces = []
            for segment in item["segments"]:
                start, end = segment["physical_offset"], segment["physical_offset"] + segment["bytes"]
                cursor = start
                for read_ordinal, read in enumerate(reads):
                    if read["chunk_row"] != segment["chunk_row"]:
                        continue
                    read_start, read_end = read["physical_offset"], read["physical_offset"] + read["bytes"]
                    left, right = max(start, read_start), min(end, read_end)
                    if left < right:
                        if left != cursor:
                            raise RangeExportError("Selected payload coverage changed during range assembly")
                        pieces.append(readback[read_ordinal][left - read_start:right - read_start])
                        cursor = right
                if cursor != end:
                    raise RangeExportError("Selected payload is not fully covered by the bounded reads")
            data = b"".join(pieces)
            if len(data) != item["stored_length"]:
                raise RangeExportError("Selected stored resource length disagrees after assembly")
            label = f"files/{ordinal:02d}.bin"
            destination = stage / f"payload-{ordinal:02d}.bin"
            destination.write_bytes(data)
            destination.chmod(0o600)
            payloads[label] = destination
            entries.append({**item, "archive_path": label, "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "expected_decoded_xxh64": item["file_hash64"]})
        aligned_bytes = sum(read["bytes"] for read in reads)
        index = {"schema_version": 1, "profile": PROFILE, "package": PACKAGE,
                 "range_reader": reader.identity, "reader_capability_probes": reader_probes,
                 "source_plan_sha256": plan_hash, "source_manifest_sha256": MANIFEST_SHA256,
                 "manifest": {"archive_path": "manifest/00.bin", "relative_path": MANIFEST_PATH,
                              "bytes": MANIFEST_BYTES, "sha256": MANIFEST_SHA256},
                 "files": entries, "aligned_reads": reads,
                 "transfer_bytes": {"manifest": MANIFEST_BYTES, "aligned_chunks": aligned_bytes,
                                    "total": MANIFEST_BYTES + aligned_bytes},
                 "scope": {"root_elevation_requested": False, "account_data_exported": False,
                           "stored_payloads_only": True, "surrounding_aligned_bytes_discarded": True,
                           "whole_chunk_hashes_verified": False, "decoded_FHSH_verified": False,
                           "source_authenticity": "unknown; manifest pin and actual partial-span SHA-256 identify received bytes"}}
        encoded = (json.dumps(index, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_INDEX_BYTES:
            raise RangeExportError("Research index exceeds 256 KiB")
        zip_path = stage / PACK_NAME
        identities = {item["archive_path"]: (item["bytes"], item["sha256"]) for item in entries}
        identities["manifest/00.bin"] = (MANIFEST_BYTES, MANIFEST_SHA256)
        with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("research-index.json", encoded)
            for label, path in payloads.items():
                info = zipfile.ZipInfo(label)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                expected_size, expected_hash = identities[label]
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise RangeExportError("Staged payload is no longer a regular file")
                digest, copied = hashlib.sha256(), 0
                with path.open("rb") as source, archive.open(info, "w") as member:
                    for block in iter(lambda: source.read(BLOCK_BYTES), b""):
                        copied += len(block)
                        if copied > expected_size:
                            raise RangeExportError("Staged payload grew while creating the pack")
                        digest.update(block)
                        member.write(block)
                if copied != expected_size or digest.hexdigest() != expected_hash:
                    raise RangeExportError("Staged payload changed while creating the pack")
        size = zip_path.stat().st_size
        if size > MAX_ZIP_BYTES:
            raise RangeExportError("Research ZIP exceeds the 30 MiB limit")
        digest = existing._file_hash(zip_path, size)
        # Publish only after all transfers, source checks and archive bounds pass.
        output.mkdir()
        try:
            shutil.move(str(zip_path), str(output / PACK_NAME))
        except OSError:
            (output / PACK_NAME).unlink(missing_ok=True)
            output.rmdir()
            raise
    return {"filename": PACK_NAME, "bytes": size, "sha256": digest,
            "range_reader": reader.identity,
            "resource_count": len(entries), "stored_payload_bytes": sum(item["bytes"] for item in entries),
            "aligned_chunk_readback_bytes": aligned_bytes,
            "manifest_bytes": MANIFEST_BYTES, "total_transfer_bytes": MANIFEST_BYTES + aligned_bytes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="Fixed reviewed card/battle selection JSON")
    parser.add_argument("--adb", type=Path, help="Trusted existing LDPlayer adb.exe")
    parser.add_argument("--serial", required=True, help="Local serial from adb devices, such as emulator-5554")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args(argv)
    try:
        result = export_ranges(args.plan, args.output, args.adb, args.serial)
    except (RangeExportError, existing.ExportError, android.InventoryError, ssra.SSRAError, OSError) as error:
        print(f"Range export failed: {android.diagnostic(str(error))}", file=sys.stderr)
        return 2
    print(f"Exported {result['resource_count']} stored resource ranges ({result['stored_payload_bytes']} bytes).")
    print(f"Android range reader: {result['range_reader']}")
    print(f"Transferred manifest {result['manifest_bytes']} bytes + aligned chunks {result['aligned_chunk_readback_bytes']} bytes.")
    print(f"ZIP: {args.output / result['filename']} ({result['bytes']} bytes; SHA-256 {result['sha256']})")
    print("Upload this inert ZIP for static decoding; whole-chunk checksums and source authenticity remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
