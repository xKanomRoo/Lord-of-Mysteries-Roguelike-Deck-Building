#!/usr/bin/env python3
"""Copy six fixed resource files from the user's existing local Android emulator.

The inventory report supplies metadata, never executable locations or commands.
Only the selected manifest, ARM64 resource chunk, and four English chunks are
copied. No root, settings changes, account files, or game execution are involved.
Transfers have pre/post size checks and a best-effort disk-growth monitor; a pull
can temporarily exceed the selected size between checks, then be rejected and
removed. Only completely verified packs are published to the output directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
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
import time
import zipfile

try:
    from . import inventory_android_resources as android
except ImportError:  # Direct Windows invocation: py tools/export_android_research.py.
    import inventory_android_resources as android


PACKAGE = android.PACKAGE
RESOURCE_ROOT = android.RESOURCE_ROOTS[0]
PROFILE = "chaos-zero-ldplayer-2026-10-02-v1"
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_REPORT_FILES = 20_000
MAX_ZIP_BYTES = 30 * 1024 * 1024
MAX_TOTAL_PAYLOAD_BYTES = 50 * 1024 * 1024
MAX_INDEX_BYTES = 64 * 1024
MAX_ADB_OUTPUT_BYTES = 2 * 1024 * 1024
COMMAND_TIMEOUT = 60
PACK_NAMES = ("chaos-runtime-core.zip", "chaos-runtime-lang-en.zip")


@dataclass(frozen=True)
class Target:
    relative_path: str
    bytes: int
    pack: str


TARGETS = (
    Target("gameres/manifest.ssra", 7_506_387, PACK_NAMES[0]),
    Target("gameres/chunks/bin_arm64_b01_0.ssrc", 18_277_264, PACK_NAMES[0]),
    Target("gameres/chunks/lang_en_b00_0.ssrc", 259_776, PACK_NAMES[1]),
    Target("gameres/chunks/lang_en_b01_0.ssrc", 181_040, PACK_NAMES[1]),
    Target("gameres/chunks/lang_en_b02_0.ssrc", 76_208, PACK_NAMES[1]),
    Target("gameres/chunks/lang_en_b03_0.ssrc", 15_459_312, PACK_NAMES[1]),
)


class ExportError(ValueError):
    """Invalid metadata or a failed bounded local export."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExportError("Inventory JSON contains a duplicate object key")
        result[key] = value
    return result


def _integer(value, field: str, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ExportError(f"Inventory has an invalid {field}")
    return value


def _valid_path_text(value: str) -> bool:
    try:
        return len(value.encode("utf-8")) <= android.MAX_PATH_BYTES and not android._control_text(value)
    except UnicodeEncodeError:
        return False


def read_inventory(path: Path) -> tuple[dict, str]:
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ExportError("Inventory report exceeds the 2 MiB limit")
    try:
        report = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except ExportError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ExportError("Inventory report is not bounded UTF-8 JSON") from error
    validate_inventory(report)
    return report, hashlib.sha256(data).hexdigest()


def validate_inventory(report: dict) -> None:
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ExportError("Expected resource inventory schema_version 1")
    if report.get("package") != PACKAGE:
        raise ExportError("Inventory package does not match the fixed game package")
    serial = report.get("serial")
    if not isinstance(serial, str) or not android.local_serial(serial):
        raise ExportError("Inventory serial must name a local emulator")
    scope = report.get("scope")
    if (not isinstance(scope, dict) or scope.get("regular_files_only") is not True
            or scope.get("follows_directory_symlinks") is not False
            or scope.get("root_elevation_requested") is not False
            or scope.get("contents_read") is not False):
        raise ExportError("Inventory must describe regular files without symlink following or root elevation")
    if report.get("limit_reached") is not False:
        raise ExportError("Inventory was incomplete because its inspection limit was reached")
    locations = report.get("locations")
    if not isinstance(locations, list) or not 1 <= len(locations) <= len(android.RESOURCE_ROOTS):
        raise ExportError("Inventory has invalid resource locations")
    seen_roots = set()
    total_files = 0
    resource_location = None
    for location in locations:
        if not isinstance(location, dict):
            raise ExportError("Inventory location must be an object")
        root = location.get("root")
        if not isinstance(root, str) or root not in android.RESOURCE_ROOTS or root in seen_roots:
            raise ExportError("Inventory has an unexpected or duplicate resource root")
        seen_roots.add(root)
        files = location.get("files")
        if not isinstance(files, list) or len(files) > MAX_REPORT_FILES:
            raise ExportError("Inventory has an invalid file list")
        seen_paths = set()
        listed_bytes = 0
        for item in files:
            if not isinstance(item, dict):
                raise ExportError("Inventory file must be an object")
            relative = item.get("relative_path")
            path = item.get("path")
            if (not isinstance(relative, str) or not isinstance(path, str)
                    or not _valid_path_text(path) or "\\" in relative
                    or any(part in ("", ".", "..") for part in relative.split("/"))
                    or len(relative.split("/")) > android.MAX_DEPTH
                    or path != root + "/" + relative or path in seen_paths):
                raise ExportError("Inventory has an unsafe, noncanonical, or duplicate resource path")
            seen_paths.add(path)
            listed_bytes += _integer(item.get("bytes"), "file size")
        if _integer(location.get("listed_file_count"), "location file count", MAX_REPORT_FILES) != len(files):
            raise ExportError("Inventory location file count does not match its records")
        if _integer(location.get("listed_bytes"), "location byte total") != listed_bytes:
            raise ExportError("Inventory location byte total does not match its records")
        total_files += len(files)
        if total_files > MAX_REPORT_FILES:
            raise ExportError("Inventory exceeds the combined file-count limit")
        if root == RESOURCE_ROOT:
            resource_location = location
    if _integer(report.get("listed_file_count"), "combined file count", MAX_REPORT_FILES) != total_files:
        raise ExportError("Inventory combined file count does not match its records")
    if (resource_location is None or resource_location.get("status") != "accessible"
            or type(resource_location.get("returncode")) is not int or resource_location["returncode"] != 0
            or resource_location.get("complete_within_declared_scope") is not True):
        raise ExportError("The external game resource directory must have an accessible, complete inventory")
    by_relative = {item["relative_path"]: item for item in resource_location["files"]}
    selected_total = 0
    for target in TARGETS:
        item = by_relative.get(target.relative_path)
        if item is None:
            raise ExportError(f"Selected resource is absent from the inventory: {target.relative_path}")
        if item["bytes"] != target.bytes:
            raise ExportError(f"Selected resource size differs from this verified profile: {target.relative_path}; collect a fresh inventory for review")
        selected_total += target.bytes
    if selected_total > MAX_TOTAL_PAYLOAD_BYTES:
        raise ExportError("Selected resources exceed the total export limit")
    for pack in PACK_NAMES:
        if sum(target.bytes for target in TARGETS if target.pack == pack) + MAX_INDEX_BYTES > MAX_ZIP_BYTES:
            raise ExportError("Selected resources exceed an individual ZIP limit")


class ExportAdbRunner:
    """Local ADB, bounded diagnostics/time, and best-effort disk-growth checks."""

    def __init__(self, executable: Path):
        self.executable = executable
        self.remaining = MAX_ADB_OUTPUT_BYTES

    def run(self, arguments: list[str], *, destination: Path | None = None,
            maximum_bytes: int | None = None) -> android.CommandResult:
        if self.remaining <= 0:
            raise ExportError("ADB output exceeded the 2 MiB export limit")
        env = os.environ.copy()
        for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
            env.pop(name, None)
        # -H disables local automatic startup even with a loopback value.
        # Cleared host overrides preserve ADB's default local server.
        argv = [str(self.executable), "-P", "5037", *arguments]
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, shell=False, env=env)
        except OSError as error:
            raise ExportError(f"Could not start ADB: {android.diagnostic(str(error))}") from error
        buffers = [bytearray(), bytearray()]
        lock = threading.Lock()
        overflow = threading.Event()
        available = self.remaining
        consumed = 0

        def drain(stream, index):
            nonlocal consumed
            try:
                while True:
                    block = stream.read(65536)
                    if not block:
                        break
                    with lock:
                        allowed = min(len(block), available - consumed)
                        buffers[index].extend(block[:allowed])
                        consumed += allowed
                        if allowed != len(block):
                            overflow.set()
                    if overflow.is_set():
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
        failure = None
        deadline = time.monotonic() + COMMAND_TIMEOUT
        try:
            while True:
                if destination is not None and os.path.lexists(destination):
                    metadata = destination.lstat()
                    if (not stat.S_ISREG(metadata.st_mode) or maximum_bytes is None
                            or metadata.st_size > maximum_bytes):
                        failure = "ADB pull exceeded the selected size or created a nonregular file"
                        break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = "ADB command timed out after 60 seconds"
                    break
                try:
                    process.wait(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if failure is not None or process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    failure = failure or "ADB did not stop after its command limit"
            for thread in threads:
                thread.join(timeout=2)
            self.remaining -= consumed
        if any(thread.is_alive() for thread in threads):
            raise ExportError("ADB pipe did not close after the bounded command")
        if overflow.is_set():
            raise ExportError("ADB output exceeded the 2 MiB export limit")
        if failure is not None:
            raise ExportError(failure)
        return android.CommandResult(process.returncode, bytes(buffers[0]), bytes(buffers[1]))


def target_stat_command(target: Target) -> str:
    if target not in TARGETS:
        raise ExportError("Only the fixed resource profile may be exported")
    path = RESOURCE_ROOT + "/" + target.relative_path
    components = target.relative_path.split("/")
    ancestors = [RESOURCE_ROOT + "/" + "/".join(components[:index])
                 for index in range(1, len(components))]
    checks = " && ".join(f"[ ! -L {shlex.quote(parent)} ]" for parent in ancestors)
    return (f"if {checks} && [ -f {shlex.quote(path)} ] && [ ! -L {shlex.quote(path)} ]; "
            f"then stat -c '%s' {shlex.quote(path)}; else exit 7; fi")


def _check_remote(runner, serial: str, target: Target) -> None:
    result = runner.run(["-s", serial, "shell", target_stat_command(target)])
    value = result.stdout.strip()
    if result.returncode or not re.fullmatch(rb"[0-9]{1,19}", value):
        raise ExportError(f"Selected resource is not an accessible regular file: {target.relative_path}")
    if int(value) != target.bytes:
        raise ExportError(f"Selected resource size changed since inventory: {target.relative_path}; collect a fresh inventory")


def _file_hash(path: Path, expected_size: int) -> str:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != expected_size:
        raise ExportError("Pulled resource has an unexpected file type or size")
    digest = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            read_bytes += len(block)
            if read_bytes > expected_size:
                raise ExportError("Pulled resource grew beyond its selected size")
            digest.update(block)
    if read_bytes != expected_size:
        raise ExportError("Pulled resource size changed during hashing")
    return digest.hexdigest()


def _write_pack(path: Path, pack_name: str, entries: list[dict], report_hash: str,
                payloads: dict[str, Path]) -> dict:
    index = {
        "schema_version": 1, "profile": PROFILE, "package": PACKAGE,
        "source_inventory_sha256": report_hash, "archive": pack_name,
        "scope": {"fixed_resource_files_only": True, "root_elevation_requested": False,
                  "source_content_hashes_in_inventory": False,
                  "pulled_sizes_match_inventory": True,
                  "transfer_size_monitor": "best_effort; temporary overshoot is possible",
                  "size_and_sha256_verified_before_publication": True},
        "files": entries,
    }
    encoded = (json.dumps(index, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_INDEX_BYTES:
        raise ExportError("Research index exceeds its size limit")
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("research-index.json", encoded)
        for item in entries:
            info = zipfile.ZipInfo(item["archive_path"])
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            digest = hashlib.sha256()
            copied = 0
            with payloads[item["archive_path"]].open("rb") as source, archive.open(info, "w") as member:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    copied += len(block)
                    if copied > item["bytes"]:
                        raise ExportError("Pulled resource changed while creating its research pack")
                    digest.update(block)
                    member.write(block)
            if copied != item["bytes"] or digest.hexdigest() != item["sha256"]:
                raise ExportError("Pulled resource changed while creating its research pack")
    size = path.stat().st_size
    if size > MAX_ZIP_BYTES:
        raise ExportError("Research ZIP exceeds the 30 MiB upload limit")
    return {"filename": pack_name, "bytes": size, "sha256": _file_hash(path, size),
            "payload_files": len(entries), "payload_bytes": sum(item["bytes"] for item in entries)}


def export_resources(report_path: Path, output: Path, adb: Path | None = None, runner=None) -> dict:
    output = Path(output)
    if os.path.lexists(output):
        raise ExportError("Output already exists; choose a new directory to preserve previous research")
    if android._control_text(str(output)):
        raise ExportError("Output path contains control characters")
    report, report_hash = read_inventory(report_path)
    # The report's adb.executable is deliberately ignored. Only CLI/PATH discovery
    # selects a trusted local installation, using the existing inventory helper.
    executable = android.locate_adb(adb)
    runner = runner or ExportAdbRunner(executable)
    devices = runner.run(["devices", "-l"])
    if devices.returncode:
        raise ExportError("Could not list local ADB devices")
    serial = android.select_device(android.parse_devices(devices.stdout), report["serial"])
    installed = runner.run(["-s", serial, "shell", f"pm path {PACKAGE}"])
    try:
        android.validate_package_query(installed, serial)
    except android.InventoryError as error:
        raise ExportError(str(error)) from error
    for target in TARGETS:
        _check_remote(runner, serial, target)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = None
    with tempfile.TemporaryDirectory(prefix=".chaos-runtime-export-", dir=output.parent) as temporary:
        stage = Path(temporary)
        payloads = {}
        entries = []
        for ordinal, target in enumerate(TARGETS):
            # Constant ordinal names keep remote filenames out of local paths.
            local = stage / f"payload-{ordinal:02d}.bin"
            remote = RESOURCE_ROOT + "/" + target.relative_path
            pulled = runner.run(["-s", serial, "pull", remote, str(local)],
                                destination=local, maximum_bytes=target.bytes)
            if pulled.returncode:
                raise ExportError(f"ADB could not pull selected resource: {target.relative_path}; {android.diagnostic(pulled.stderr)}")
            digest = _file_hash(local, target.bytes)
            local.chmod(0o600)
            _check_remote(runner, serial, target)
            archive_path = f"files/{ordinal:02d}.bin"
            payloads[archive_path] = local
            entries.append({"archive_path": archive_path, "remote_path": remote,
                            "relative_path": target.relative_path, "bytes": target.bytes,
                            "sha256": digest, "pack": target.pack})
        packs = []
        for pack_name in PACK_NAMES:
            subset = [{key: value for key, value in item.items() if key != "pack"}
                      for item in entries if item["pack"] == pack_name]
            packs.append(_write_pack(stage / pack_name, pack_name, subset, report_hash, payloads))
        result = {"profile": PROFILE, "package": PACKAGE,
                  "source_inventory_sha256": report_hash,
                  "payload_file_count": len(TARGETS),
                  "payload_bytes": sum(target.bytes for target in TARGETS), "packs": packs}
        lines = ["# Selected local Android resource export", "",
                 f"Created at UTC: {datetime.now(timezone.utc).isoformat()}",
                 f"Package: `{PACKAGE}`", f"Profile: `{PROFILE}`",
                 f"Source inventory SHA-256: `{report_hash}`", "",
                 "Six fixed resource files were copied through the existing local ADB connection.",
                 "No root elevation, settings changes, account exports, or game execution were performed.",
                 "Each ZIP includes research-index.json with original resource paths, sizes, and pulled SHA-256 hashes.",
                 "The inventory contains no source content hashes; size matches and actual pulled hashes are recorded.",
                 "These are inert reference files for private static research, not assets imported into the prototype.",
                 "", "Upload both ZIPs for the next resource-format inspection.", "",
                 "| ZIP | Bytes | SHA-256 |", "| --- | ---: | --- |"]
        lines.extend(f"| {pack['filename']} | {pack['bytes']} | `{pack['sha256']}` |" for pack in packs)
        (stage / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Reserve a new final directory only after every transfer and pack passes.
        output.mkdir()
        promoted = []
        try:
            for name in (*PACK_NAMES, "summary.md"):
                shutil.move(str(stage / name), str(output / name))
                promoted.append(name)
        except OSError:
            for name in promoted:
                (output / name).unlink(missing_ok=True)
            try:
                output.rmdir()
            except OSError:
                pass
            raise
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="report.json from the local resource inventory")
    parser.add_argument("--output", type=Path, required=True, help="New output directory for the two selected ZIPs")
    parser.add_argument("--adb", type=Path, help="Existing trusted adb.exe in the LDPlayer installation")
    args = parser.parse_args(argv)
    try:
        result = export_resources(args.report, args.output, args.adb)
    except (ExportError, android.InventoryError, OSError) as error:
        print(f"Export failed: {android.diagnostic(str(error))}", file=sys.stderr)
        return 2
    print(f"Exported {result['payload_file_count']} selected resource files ({result['payload_bytes']} bytes).")
    for pack in result["packs"]:
        print(f"ZIP: {args.output / pack['filename']} ({pack['bytes']} bytes; SHA-256 {pack['sha256']})")
    print("Upload both ZIPs for static inspection; keep these reference files out of Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
