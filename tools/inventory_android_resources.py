#!/usr/bin/env python3
"""List the fixed game's resource files through an existing local Android emulator.

This helper reads filenames and sizes only. It never pulls file contents, runs the
game, enables root, changes emulator settings, or requests account credentials.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import threading
import unicodedata


PACKAGE = "com.smilegate.chaoszero.stove.google"
RESOURCE_ROOTS = (
    f"/sdcard/Android/data/{PACKAGE}/files",
    f"/sdcard/Android/obb/{PACKAGE}",
    f"/data/user/0/{PACKAGE}/files",
    f"/data/data/{PACKAGE}/files",
)
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_FILES = 20_000
MAX_DEPTH = 12
COMMAND_TIMEOUT = 25
MAX_PATH_BYTES = 4096
SENSITIVE_DIRS = ("shared_prefs", "accounts", "account", "preferences", "prefs", "auth", "credentials", "sessions")
SENSITIVE_FILES = re.compile(
    r"(?:^|[._-])(?:accounts?|auth|cookies?|credentials?|login|prefs?|session|tokens?)(?:[._-]|$)",
    re.IGNORECASE,
)


class InventoryError(ValueError):
    """An unsafe input, ambiguous device, or failed bounded operation."""


class CommandLimitError(InventoryError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


def _control_text(value: str) -> bool:
    return any(unicodedata.category(char) == "Cc" for char in value)


def diagnostic(data: bytes | str) -> str:
    value = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return "".join(" " if unicodedata.category(char) == "Cc" else char
                   for char in value)[:2048].strip()


def local_serial(serial: str) -> bool:
    if re.fullmatch(r"emulator-[0-9]{1,6}", serial):
        return True
    match = re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})", serial)
    return bool(match and 0 < int(match.group(1)) <= 65535)


def parse_devices(data: bytes) -> list[dict[str, str]]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise InventoryError("ADB device list is not UTF-8") from error
    started = False
    devices: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        if line.strip() == "List of devices attached":
            started = True
            continue
        if not started or not line.strip() or line.startswith("* "):
            continue
        parts = line.split()
        if len(parts) < 2 or _control_text(parts[0]) or parts[0] in seen:
            raise InventoryError("Malformed or duplicate ADB device entry")
        serial, state = parts[:2]
        if len(serial) > 128 or len(devices) >= 256:
            raise InventoryError("ADB device list exceeds the inspection limit")
        seen.add(serial)
        devices.append({"serial": serial, "state": state})
    if not started:
        raise InventoryError("ADB did not return its device-list header")
    return devices


def select_device(devices: list[dict[str, str]], serial: str | None = None) -> str:
    local = [device for device in devices if local_serial(device["serial"])]
    if serial is not None:
        if not local_serial(serial):
            raise InventoryError("--serial must be a local emulator or loopback address")
        matches = [device for device in local if device["serial"] == serial]
        if not matches:
            raise InventoryError("Selected local emulator is absent from adb devices")
        chosen = matches[0]
    else:
        if not local:
            raise InventoryError("No local emulator found. Enable LDPlayer's local ADB connection, then try again")
        if len(local) != 1:
            names = ", ".join(device["serial"] for device in local)
            raise InventoryError(f"Multiple local emulators found; select one with --serial ({names})")
        chosen = local[0]
    if chosen["state"] != "device":
        raise InventoryError(f"Local emulator is {diagnostic(chosen['state'])}; make it available in adb devices first")
    return chosen["serial"]


def _adb_filename(name: str) -> bool:
    if os.name == "nt":
        return name.lower() == "adb.exe"
    return name in ("adb", "adb.exe")


def _executable(path: Path) -> Path | None:
    # Test-Path alone also accepts LDPlayer's dnplayer.exe launcher. Reject that
    # common selection mistake before resolving or ever starting the program.
    if not _adb_filename(path.name):
        return None
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not _adb_filename(resolved.name) or not resolved.is_file() or _control_text(str(resolved)):
        return None
    if os.name == "nt":
        # Avoid Windows batch files, whose invocation can introduce shell parsing.
        return resolved if resolved.suffix.lower() == ".exe" else None
    return resolved if os.access(resolved, os.X_OK) else None


def locate_adb(explicit: Path | None = None) -> Path:
    if explicit is not None:
        found = _executable(Path(explicit))
        if found is None:
            raise InventoryError("--adb must name an existing regular ADB executable named adb.exe on Windows or adb/adb.exe elsewhere; dnplayer.exe is the LDPlayer launcher")
        return found
    candidates: list[Path] = []
    on_path = shutil.which("adb")
    if on_path:
        candidates.append(Path(on_path))
    if os.name == "nt":
        folders = ("LDPlayer/LDPlayer9", "LDPlayer/LDPlayer4", "LDPlayer9", "LDPlayer4",
                   "XuanZhi/LDPlayer9", "XuanZhi/LDPlayer", "Program Files/LDPlayer/LDPlayer9",
                   "Program Files/LDPlayer", "Program Files (x86)/LDPlayer/LDPlayer9")
        for drive in ("C", "D", "E"):
            candidates.extend(Path(f"{drive}:/{folder}/adb.exe") for folder in folders)
    for candidate in candidates:
        found = _executable(candidate)
        if found is not None:
            return found
    raise InventoryError("ADB not found. Locate adb.exe in your LDPlayer installation and pass --adb PATH")


class AdbRunner:
    """Use a local ADB server, bounded pipes, and a cumulative output budget."""

    def __init__(self, executable: Path):
        self.executable = executable
        self.remaining = MAX_OUTPUT_BYTES

    def run(self, arguments: list[str]) -> CommandResult:
        if self.remaining <= 0:
            raise CommandLimitError("ADB output exceeded the 2 MiB inventory limit")
        env = os.environ.copy()
        for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
            env.pop(name, None)
        argv = [str(self.executable), "-H", "127.0.0.1", "-P", "5037", *arguments]
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, shell=False, env=env)
        except OSError as error:
            raise InventoryError(f"Could not start ADB: {diagnostic(str(error))}") from error
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
        timed_out = False
        try:
            process.wait(timeout=COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise InventoryError("ADB did not stop after the command timeout") from error
        finally:
            for thread in threads:
                thread.join(timeout=2)
            self.remaining -= consumed
        if any(thread.is_alive() for thread in threads):
            raise InventoryError("ADB pipe did not close after the bounded command")
        if overflow.is_set():
            raise CommandLimitError("ADB output exceeded the 2 MiB inventory limit")
        if timed_out:
            raise InventoryError("ADB command timed out after 25 seconds")
        return CommandResult(process.returncode, bytes(buffers[0]), bytes(buffers[1]))


def inventory_command(root: str) -> str:
    if root not in RESOURCE_ROOTS:
        raise InventoryError("Only the fixed game's resource directories may be inspected")
    quoted = shlex.quote(root)
    excluded = " -o ".join(f"-name {shlex.quote(name)}" for name in SENSITIVE_DIRS)
    # The remote helper receives filenames as positional arguments, never as code.
    stat_script = 'for f do n=$(stat -c %s "$f") || exit 9; printf "%s\\0%s\\0" "$n" "$f"; done'
    return (
        f"if [ -d {quoted} ]; then printf 'CZNI_DIRECTORY\\0'; "
        f"find {quoted} -maxdepth {MAX_DEPTH} "
        f"\\( -type d \\( {excluded} \\) -prune \\) -o "
        f"\\( -type f -exec sh -c {shlex.quote(stat_script)} sh {{}} + \\); "
        f"else printf 'CZNI_ABSENT\\0'; ls -d {quoted} >/dev/null; fi"
    )


def parse_file_records(data: bytes, root: str) -> tuple[list[dict], int]:
    marker = b"CZNI_DIRECTORY\0"
    if not data.startswith(marker):
        raise InventoryError("Unexpected Android inventory output")
    if len(data) > MAX_OUTPUT_BYTES:
        raise CommandLimitError("Android inventory exceeds the 2 MiB output limit")
    body = data[len(marker):]
    if not body:
        return [], 0
    if not body.endswith(b"\0"):
        raise InventoryError("Android inventory contains a truncated record")
    values = body[:-1].split(b"\0")
    if len(values) % 2:
        raise InventoryError("Android inventory has malformed records")
    if len(values) // 2 > MAX_FILES:
        raise CommandLimitError("Android inventory exceeds the file-count limit")
    files: list[dict] = []
    excluded = 0
    seen: set[str] = set()
    for position in range(0, len(values), 2):
        size_bytes, path_bytes = values[position:position + 2]
        if not re.fullmatch(rb"[0-9]{1,19}", size_bytes) or int(size_bytes) > 2**63 - 1:
            raise InventoryError("Android inventory has an invalid file size")
        if len(path_bytes) > MAX_PATH_BYTES:
            raise InventoryError("Android inventory has an oversized filename")
        try:
            path = path_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InventoryError("Android inventory filename is not UTF-8") from error
        if _control_text(path) or not path.startswith(root + "/"):
            raise InventoryError("Android inventory filename is unsafe or outside its selected root")
        relative = path[len(root) + 1:]
        components = relative.split("/")
        if len(components) > MAX_DEPTH or any(component in ("", ".", "..") for component in components) or path in seen:
            raise InventoryError("Android inventory has a duplicate or noncanonical filename")
        seen.add(path)
        if any(component.lower() in SENSITIVE_DIRS for component in components[:-1]) or SENSITIVE_FILES.search(components[-1]):
            excluded += 1
            continue
        files.append({"path": path, "relative_path": relative, "bytes": int(size_bytes),
                      "extension": PurePosixPath(relative).suffix.lower()})
    return sorted(files, key=lambda item: item["path"]), excluded


def inspect_root(runner, serial: str, root: str) -> dict:
    result = runner.run(["-s", serial, "shell", inventory_command(root)])
    detail = diagnostic(result.stderr)
    if b"permission denied" in result.stderr.lower() or b"operation not permitted" in result.stderr.lower():
        status = "permission_denied"
    elif result.stdout == b"CZNI_ABSENT\0":
        status = "missing" if result.returncode else "not_directory"
    elif result.returncode:
        status = "command_failed"
    else:
        status = "accessible"
    files: list[dict] = []
    excluded = 0
    if result.stdout.startswith(b"CZNI_DIRECTORY\0"):
        files, excluded = parse_file_records(result.stdout, root)
    elif result.stdout != b"CZNI_ABSENT\0":
        raise InventoryError("Android shell returned unexpected resource-directory output")
    return {"root": root, "status": status, "returncode": result.returncode,
            "diagnostic": detail or None, "files": files,
            "listed_file_count": len(files), "listed_bytes": sum(file["bytes"] for file in files),
            "omitted_sensitive_filename_count": excluded,
            "observed_record_count": len(files) + excluded,
            "complete_within_declared_scope": status == "accessible"}


def _check_new_output(output: Path) -> None:
    if os.path.lexists(output):
        raise InventoryError("Output already exists; choose a new directory to preserve previous research")
    if _control_text(str(output)):
        raise InventoryError("Output path contains control characters")


def inventory_resources(output: Path, adb: Path | None = None, serial: str | None = None,
                        runner=None) -> dict:
    output = Path(output)
    _check_new_output(output)
    if serial is not None and not local_serial(serial):
        raise InventoryError("--serial must be a local emulator or loopback address")
    executable = locate_adb(adb)
    runner = runner or AdbRunner(executable)
    version = runner.run(["version"])
    if version.returncode:
        raise InventoryError(f"ADB version failed: {diagnostic(version.stderr)}")
    devices_result = runner.run(["devices", "-l"])
    if devices_result.returncode:
        raise InventoryError(f"ADB devices failed: {diagnostic(devices_result.stderr)}")
    selected = select_device(parse_devices(devices_result.stdout), serial)
    package = runner.run(["-s", selected, "shell", f"pm path {PACKAGE}"])
    apk_lines = package.stdout.decode("utf-8", "replace").splitlines()
    if package.returncode or not apk_lines or any(not line.startswith("package:/") or _control_text(line) for line in apk_lines):
        raise InventoryError(f"The fixed game package is not installed or pm path failed: {diagnostic(package.stderr)}")
    sdk = runner.run(["-s", selected, "shell", "getprop ro.build.version.sdk"])
    sdk_value = sdk.stdout.strip()
    sdk_number = int(sdk_value) if not sdk.returncode and re.fullmatch(rb"[0-9]{1,3}", sdk_value) else None
    locations: list[dict] = []
    count = 0
    observed = 0
    limit_reached = False
    for root in RESOURCE_ROOTS:
        if limit_reached:
            locations.append({"root": root, "status": "not_inspected_limit", "files": [],
                              "listed_file_count": 0, "complete_within_declared_scope": False})
            continue
        try:
            location = inspect_root(runner, selected, root)
            if observed + location["observed_record_count"] > MAX_FILES:
                raise CommandLimitError("Combined inventory exceeds the 20,000-file limit")
            count += len(location["files"])
            observed += location["observed_record_count"]
            locations.append(location)
        except InventoryError as error:
            locations.append({"root": root, "status": "inspection_failed", "files": [],
                              "listed_file_count": 0, "diagnostic": diagnostic(str(error)),
                              "complete_within_declared_scope": False})
            if isinstance(error, CommandLimitError):
                limit_reached = True
    report = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "package": PACKAGE, "serial": selected, "android_sdk": sdk_number,
        "installed_apk_count": len(apk_lines),
        "adb": {"executable": str(executable), "version": diagnostic(b"\n".join(version.stdout.splitlines()[:2])),
                "server": "127.0.0.1:5037"},
        "scope": {"contents_read": False, "root_elevation_requested": False,
                  "regular_files_only": True, "follows_directory_symlinks": False,
                  "max_depth": MAX_DEPTH, "max_files": MAX_FILES,
                  "max_adb_output_bytes": MAX_OUTPUT_BYTES,
                  "excluded_directory_names": list(SENSITIVE_DIRS),
                  "known_account_preference_filenames_omitted": True,
                  "private_roots_can_be_aliases": True},
        "listed_file_count": count, "limit_reached": limit_reached, "locations": locations,
    }
    summary = ["# Local emulator resource inventory", "", f"Package: `{PACKAGE}`",
               f"Local emulator: `{selected}`", "",
               "Filenames and sizes only; no file contents, root elevation, or game execution.",
               "Results cover regular files up to depth 12. Known account and preference names are omitted.",
               "Generic resource database filenames can be listed; no database contents are opened.",
               "The two private paths may show the same files through Android aliases; totals are listing counts.",
               "Permission failures indicate what the existing ADB shell can access.", "",
               "| Directory | Status | Listed files |", "| --- | --- | --- |"]
    summary.extend(f"| `{item['root']}` | {item['status']} | {item['listed_file_count']} |" for item in locations)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Refuse any destination created since the initial check.
    try:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        (output / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    except OSError:
        for name in ("report.json", "summary.md"):
            (output / name).unlink(missing_ok=True)
        output.rmdir()
        raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for report.json and summary.md")
    parser.add_argument("--adb", type=Path, help="Existing trusted adb.exe, for example in the LDPlayer installation")
    parser.add_argument("--serial", help="Local serial from adb devices, required if multiple emulators are present")
    args = parser.parse_args(argv)
    try:
        report = inventory_resources(args.output, args.adb, args.serial)
    except (InventoryError, OSError) as error:
        print(f"Inventory failed: {diagnostic(str(error))}", file=sys.stderr)
        return 2
    print(f"Listed {report['listed_file_count']} files on {report['serial']}; contents were not copied.")
    print(f"Report: {args.output / 'report.json'}")
    print(f"Summary: {args.output / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
