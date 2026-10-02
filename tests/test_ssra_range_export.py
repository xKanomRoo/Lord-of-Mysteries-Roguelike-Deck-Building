"""Synthetic SSRA metadata and fake ADB; no Android, game or network is used."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import export_ssra_ranges as export
from tools import inventory_android_resources as android
from tools import read_ssra_manifest as ssra


def fixture():
    paths = ("db/card.db", "wnd/card.csb")
    chunk_names = ("base_b00_0.ssrc", "base_b01_0.ssrc")
    offsets, blob = {}, bytearray()
    for name in (*chunk_names, *paths):
        offsets[name] = len(blob)
        blob.extend(name.encode() + b"\0")
    chunk_payloads = {name: bytes((index + row * 19) % 256 for index in range(70_000)) + b"SSRC" + bytes(12)
                      for row, name in enumerate(chunk_names)}
    chunks = b"".join(struct.pack("<IHHQQQ", row, 12, 0, 70_000, 70_016, 0xA0 + row)
                      for row in range(2))
    file_rows = ((69_990, 30), (1000, 200))
    files = b"".join(struct.pack("<QQ4IBBHB3s", ssra.xxh64(name.encode()), offset, length, length,
                                  0, offsets[name], 0, 0, 12, 0, bytes(3))
                      for name, (offset, length) in zip(paths, file_rows))
    path_offset = 64 + len(chunks) + len(files)
    header = struct.pack("<4s5I4Q2I", b"SSRA", 4, 0, 2, 2, 6,
                         path_offset, len(blob), 64, 64 + len(chunks), 0, 0)
    cnam = struct.pack("<4sIII", b"CNAM", 2, 0, 0)
    cnam += b"".join(struct.pack("<II", row, offsets[name]) for row, name in enumerate(chunk_names))
    fhsh = struct.pack("<4sIII", b"FHSH", 2, 1, 0) + struct.pack("<2Q", 0xD0, 0xD1)
    return header + chunks + files + blob + cnam + fhsh, chunk_payloads


class FakeRunner:
    def __init__(self, manifest, chunks, *, corrupt_manifest=False, stat_failure=False,
                 changed_after=False, binary_result=None, package_result=None,
                 diagnostic_result=None, diagnostic_error=None):
        self.manifest = manifest
        self.chunks = chunks
        self.corrupt_manifest = corrupt_manifest
        self.stat_failure = stat_failure
        self.changed_after = changed_after
        self.binary_result = binary_result
        self.package_result = package_result
        self.diagnostic_result = diagnostic_result
        self.diagnostic_error = diagnostic_error
        self.calls = []
        self.binary_calls = []
        self.diagnostic_calls = []

    def run(self, arguments, **limits):
        self.calls.append((arguments, limits))
        if arguments == ["devices", "-l"]:
            return android.CommandResult(0, b"List of devices attached\nemulator-5554 device\n")
        if arguments[-1] == f"pm path {export.PACKAGE}":
            return self.package_result or android.CommandResult(0, b"package:/data/app/synthetic/base.apk\n")
        if arguments[-1] == export.existing.target_stat_command(export.existing.TARGETS[0]):
            return android.CommandResult(0, str(len(self.manifest)).encode())
        if len(arguments) == 5 and arguments[2] == "pull":
            data = self.manifest
            if self.corrupt_manifest:
                data = b"X" + data[1:]
            Path(arguments[-1]).write_bytes(data)
            return android.CommandResult(0, b"synthetic manifest copied\n")
        for name, data in self.chunks.items():
            if arguments[-1] == export.chunk_stat_command(name):
                if self.stat_failure:
                    return android.CommandResult(7, b"", b"synthetic missing or symlink resource")
                changed = self.changed_after and any(name in call[-1] for call in self.binary_calls)
                return android.CommandResult(0, str(len(data) + int(changed)).encode())
        raise AssertionError(f"Unexpected ADB call: {arguments}")

    def run_binary(self, arguments, expected_bytes):
        self.binary_calls.append(arguments)
        if self.binary_result is not None:
            return self.binary_result
        match = re.fullmatch(r"dd if=(.+)/([A-Za-z0-9_.-]+\.ssrc) bs=65536 skip=([0-9]+) count=([0-9]+)( 2>/dev/null)?", arguments[-1])
        if not match or match.group(1) != export.RESOURCE_ROOT + "/gameres/chunks":
            raise AssertionError("Binary command did not use a single fixed resource dd argument")
        start, length = int(match.group(3)) * export.BLOCK_BYTES, int(match.group(4)) * export.BLOCK_BYTES
        data = self.chunks[match.group(2)][start:start + length]
        # ADB raw exec-out merges REMOTE stdout/stderr. Only LOCAL diagnostics
        # reach Popen.stderr; dd statistics enter stdout without redirection.
        if match.group(5) is None:
            data += b"synthetic records in/out\n"
        return android.CommandResult(0, data)

    def run_diagnostic(self, arguments):
        self.diagnostic_calls.append(arguments)
        if self.diagnostic_error is not None:
            raise self.diagnostic_error
        return self.diagnostic_result or android.CommandResult(0, b"synthetic records in/out\n__ssra_range_dd_exit=0\n")


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", returncode=0, timeout=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None
        self.final_returncode = returncode
        self.timeout = timeout
        self.killed = False

    def wait(self, timeout=None):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("synthetic adb", timeout)
        self.returncode = -9 if self.killed else self.final_returncode
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


class SSRARangeExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-range-export-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.plan_path = self.root / "plan.json"
        self.adb = self.root / "adb.exe"
        self.adb.write_bytes(b"synthetic not executed")
        self.adb.chmod(0o700)
        self.manifest, self.chunks = fixture()
        self.metadata = ssra.parse_ssra(self.manifest)
        self.digest = hashlib.sha256(self.manifest).hexdigest()
        self.addCleanup(patch.stopall)
        patch.object(export, "MANIFEST_BYTES", len(self.manifest)).start()
        patch.object(export, "MANIFEST_SHA256", self.digest).start()
        manifest_target = export.existing.Target(export.MANIFEST_PATH, len(self.manifest), export.existing.PACK_NAMES[0])
        patch.object(export.existing, "TARGETS", (manifest_target,)).start()
        self.plan = {"schema_version": 1, "profile": export.PROFILE, "package": export.PACKAGE,
                     "manifest": {"relative_path": export.MANIFEST_PATH, "bytes": len(self.manifest), "sha256": self.digest},
                     "selected_files": [export.file_selection(item) for item in self.metadata["files"]]}
        self.write_plan(self.plan)

    def write_plan(self, plan):
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def run_export(self, runner=None):
        return export.export_ranges(self.plan_path, self.output, self.adb, "emulator-5554",
                                    runner or FakeRunner(self.manifest, self.chunks))

    def assert_clean(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".chaos-range-export-*")), [])

    def test_cross_chunk_and_merged_aligned_reads_export_only_selected_payloads(self):
        runner = FakeRunner(self.manifest, self.chunks)
        result = self.run_export(runner)
        self.assertEqual(result["resource_count"], 2)
        self.assertEqual(result["stored_payload_bytes"], 230)
        self.assertEqual(result["aligned_chunk_readback_bytes"], 135_552)
        self.assertEqual(result["total_transfer_bytes"], len(self.manifest) + 135_552)
        self.assertEqual(len(runner.binary_calls), 2)
        self.assertEqual(runner.diagnostic_calls, [])
        path = self.output / export.PACK_NAME
        self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.namelist(), ["research-index.json", "manifest/00.bin", "files/00.bin", "files/01.bin"])
            self.assertEqual(archive.read("manifest/00.bin"), self.manifest)
            self.assertEqual(archive.read("files/00.bin"), self.chunks["base_b00_0.ssrc"][69_990:70_000] + self.chunks["base_b01_0.ssrc"][:20])
            self.assertEqual(archive.read("files/01.bin"), self.chunks["base_b00_0.ssrc"][1000:1200])
            index = json.loads(archive.read("research-index.json"))
            self.assertFalse(index["scope"]["whole_chunk_hashes_verified"])
            self.assertFalse(index["scope"]["decoded_FHSH_verified"])
            self.assertEqual(index["source_manifest_sha256"], self.digest)
            self.assertEqual(index["source_plan_sha256"], hashlib.sha256(self.plan_path.read_bytes()).hexdigest())
            for item in index["files"]:
                data = archive.read(item["archive_path"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                self.assertEqual(item["file_hash64"], item["expected_decoded_xxh64"])
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
        for call in runner.binary_calls:
            self.assertEqual(call[:3], ["-s", "emulator-5554", "exec-out"])
            self.assertEqual(len(call), 4)
            self.assertNotIn("sh -c", call[-1])
            self.assertTrue(call[-1].endswith(" 2>/dev/null"))
        self.assertEqual(list(self.root.glob(".chaos-range-export-*")), [])

    def test_duplicate_unknown_or_unsafe_plan_fields_fail_before_adb(self):
        cases = []
        bad = copy.deepcopy(self.plan); bad["adb"] = "/untrusted/launch.exe"; cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["manifest"]["sha256"] = "0" * 64; cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["selected_files"][0]["path"] = "../accounts.db"; cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["selected_files"][0]["path"] = "db/card.db\n"; cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["selected_files"].append(bad["selected_files"][0]); cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["selected_files"][0]["offset"] = True; cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["selected_files"][0]["encryption"] = 1; cases.append(bad)
        bad = copy.deepcopy(self.plan); bad["selected_files"][0]["file_hash64"] = "G" * 16; cases.append(bad)
        for plan in cases:
            self.write_plan(plan)
            runner = FakeRunner(self.manifest, self.chunks)
            with self.subTest(plan=plan), self.assertRaises(export.RangeExportError):
                self.run_export(runner)
            self.assertEqual(runner.calls, [])
        self.plan_path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(export.RangeExportError, "duplicate"):
            self.run_export()
        self.assert_clean()

    def test_bounded_json_size_surrogates_nested_and_large_integer_are_controlled(self):
        for content in (b" " * (export.MAX_PLAN_BYTES + 1), b'{"schema_version":' + b"[" * 2000,
                        b'{"schema_version":' + b"9" * 5000 + b"}"):
            self.plan_path.write_bytes(content)
            with self.subTest(size=len(content)), self.assertRaises(export.RangeExportError):
                self.run_export()
        bad = copy.deepcopy(self.plan)
        bad["selected_files"][0]["path"] = "db/\ud800.db"
        self.write_plan(bad)
        with self.assertRaises(export.RangeExportError):
            self.run_export()
        self.assert_clean()

    def test_expected_metadata_is_rederived_and_wrong_offset_never_reads_a_chunk(self):
        for field in ("row", "group_id", "offset", "stored_length", "decoded_length"):
            bad = copy.deepcopy(self.plan)
            bad["selected_files"][0][field] += 1
            self.write_plan(bad)
            runner = FakeRunner(self.manifest, self.chunks)
            with self.subTest(field=field), self.assertRaisesRegex(export.RangeExportError, "metadata disagrees"):
                self.run_export(runner)
            self.assertEqual(runner.binary_calls, [])
            self.assert_clean()

    def test_manifest_hash_mismatch_stops_before_any_chunk_read(self):
        runner = FakeRunner(self.manifest, self.chunks, corrupt_manifest=True)
        with self.assertRaisesRegex(export.RangeExportError, "Manifest pull failed"):
            self.run_export(runner)
        self.assertEqual(runner.binary_calls, [])
        self.assert_clean()

    def test_missing_or_changed_chunk_stops_and_cleans_unpublished_output(self):
        for options in ({"stat_failure": True}, {"changed_after": True}):
            runner = FakeRunner(self.manifest, self.chunks, **options)
            with self.subTest(options=options), self.assertRaises(export.RangeExportError):
                self.run_export(runner)
            self.assertLessEqual(len(runner.binary_calls), 1)
            self.assert_clean()

    def test_binary_nonzero_short_extra_or_oversized_stderr_fails(self):
        for result in (android.CommandResult(7, bytes(65_536), b"dd failed"),
                       android.CommandResult(0, bytes(65_535)),
                       android.CommandResult(0, bytes(65_537)),
                       android.CommandResult(0, bytes(65_536), bytes(export.MAX_BINARY_STDERR_BYTES + 1))):
            runner = FakeRunner(self.manifest, self.chunks, binary_result=result)
            with self.subTest(result=(result.returncode, len(result.stdout), len(result.stderr))), self.assertRaises(export.RangeExportError):
                self.run_export(runner)
            self.assert_clean()

    def test_empty_raw_read_shows_counts_context_and_same_range_remote_status(self):
        runner = FakeRunner(self.manifest, self.chunks, binary_result=android.CommandResult(0, b""))
        with self.assertRaises(export.RangeExportError) as raised:
            self.run_export(runner)
        message = str(raised.exception)
        self.assertIn("Read 1/2 on emulator-5554", message)
        self.assertIn("chunk=base_b00_0.ssrc; physical_offset=0; skip_blocks=0; count_blocks=2", message)
        self.assertIn("exit=0; expected_stdout_bytes=70016; received_stdout_bytes=0", message)
        self.assertIn("no local ADB diagnostic returned", message)
        self.assertIn("shell_exit=0; remote_dd_exit=0", message)
        self.assertEqual(len(runner.binary_calls), 1)
        self.assertEqual(len(runner.diagnostic_calls), 1)
        diagnostic = runner.diagnostic_calls[0]
        self.assertEqual(diagnostic[:3], ["-s", "emulator-5554", "shell"])
        self.assertEqual(len(diagnostic), 4)
        self.assertIn("bs=65536 skip=0 count=2 of=/dev/null 2>&1", diagnostic[-1])
        self.assertNotIn("2>/dev/null", diagnostic[-1])
        self.assert_clean()

    def test_remote_dd_failure_is_reported_without_exposing_binary_or_retrying(self):
        runner = FakeRunner(self.manifest, self.chunks, binary_result=android.CommandResult(0, b""),
                            diagnostic_result=android.CommandResult(0, b"dd: Permission denied\n__ssra_range_dd_exit=1\n"))
        with self.assertRaises(export.RangeExportError) as raised:
            self.run_export(runner)
        self.assertIn("remote_dd_exit=1", str(raised.exception))
        self.assertIn("remote_detail=dd: Permission denied", str(raised.exception))
        self.assertEqual(len(runner.binary_calls), 1)
        self.assertEqual(len(runner.diagnostic_calls), 1)
        self.assert_clean()

    def test_secondary_transport_failure_never_hides_original_raw_failure(self):
        for options in ({"diagnostic_result": android.CommandResult(1, b"", b"error: closed")},
                        {"diagnostic_error": export.existing.ExportError("ADB command timed out after 60 seconds")}):
            runner = FakeRunner(self.manifest, self.chunks,
                                binary_result=android.CommandResult(9, b"", b"local raw service failed"), **options)
            with self.subTest(options=options), self.assertRaises(export.RangeExportError) as raised:
                self.run_export(runner)
            message = str(raised.exception)
            self.assertIn("exit=9; expected_stdout_bytes=70016; received_stdout_bytes=0", message)
            self.assertIn("local raw service failed", message)
            if "diagnostic_result" in options:
                self.assertIn("shell_exit=1; remote_dd_exit=unknown", message)
                self.assertIn("local_ADB_detail=error: closed", message)
            else:
                self.assertIn("Same-range remote diagnostic transport failed", message)
                self.assertIn("timed out", message)
            self.assertEqual(len(runner.binary_calls), 1)
            self.assertEqual(len(runner.diagnostic_calls), 1)
            self.assert_clean()

    def test_existing_output_and_launcher_are_preserved_without_adb_commands(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_bytes(b"keep")
        runner = FakeRunner(self.manifest, self.chunks)
        with self.assertRaisesRegex(export.RangeExportError, "already exists"):
            self.run_export(runner)
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertEqual(runner.calls, [])
        self.output.rename(self.root / "previous-output")
        launcher = self.root / "dnplayer.exe"
        launcher.write_bytes(b"synthetic not executed")
        launcher.chmod(0o700)
        with self.assertRaisesRegex(android.InventoryError, "dnplayer.exe"):
            export.export_ranges(self.plan_path, self.output, launcher, "emulator-5554", runner)
        self.assertEqual(runner.calls, [])
        self.assert_clean()

    def test_package_transport_and_nonlocal_serial_fail_before_manifest_pull(self):
        runner = FakeRunner(self.manifest, self.chunks, package_result=android.CommandResult(1, b"", b"error: closed"))
        with self.assertRaisesRegex(android.InventoryError, "transport failed"):
            self.run_export(runner)
        self.assertEqual(len(runner.calls), 2)
        with self.assertRaisesRegex(export.RangeExportError, "local emulator"):
            export.export_ranges(self.plan_path, self.output, self.adb, "192.168.1.3:5555", runner)
        self.assert_clean()

    def test_readback_caps_and_unknown_chunk_names_reject_before_binary_read(self):
        with patch.object(export, "MAX_READBACK_BYTES", 100):
            with self.assertRaisesRegex(export.RangeExportError, "8 MiB"):
                self.run_export()
        metadata = copy.deepcopy(self.metadata)
        metadata["chunks"][0]["filename"] = None
        with self.assertRaisesRegex(export.RangeExportError, "chunk metadata"):
            export.derive_selection(metadata, self.plan["selected_files"])
        metadata["chunks"][0]["filename"] = "bad;command.ssrc"
        with self.assertRaisesRegex(export.RangeExportError, "chunk metadata"):
            export.derive_selection(metadata, self.plan["selected_files"])
        self.assert_clean()

    def test_large_aligned_spans_are_split_into_one_mib_binary_calls(self):
        metadata = copy.deepcopy(self.metadata)
        item = metadata["files"][0]
        item.update(offset=100, stored_length=3 * 1024 * 1024, decoded_length=3 * 1024 * 1024)
        metadata["chunks"] = [metadata["chunks"][0]]
        metadata["chunks"][0].update(logical_length=4 * 1024 * 1024, physical_length=4 * 1024 * 1024 + 16)
        _, reads = export.derive_selection(metadata, [export.file_selection(item)])
        self.assertEqual([read["bytes"] for read in reads], [1024 * 1024] * 3 + [65_536])
        self.assertEqual([read["skip_blocks"] for read in reads], [0, 16, 32, 48])
        for read in reads:
            self.assertLessEqual(read["bytes"], export.MAX_BINARY_CALL_BYTES)
            export.dd_command(read)

    @unittest.skipUnless(os.name == "posix" and shutil.which("sh") and shutil.which("dd"),
                         "Trusted local POSIX sh/dd probe is unavailable")
    def test_dd_redirect_removes_remote_statistics_from_raw_merged_output(self):
        # Exercise trusted host sh/dd against our inert temporary fixture. ADB's
        # raw remote service has the same merged stdout/stderr behavior; this is
        # not a live Android or Windows connection test.
        resource_root = self.root / "resource-root"
        chunks_dir = resource_root / "gameres" / "chunks"
        chunks_dir.mkdir(parents=True)
        data = bytes(range(256)) * 256
        (chunks_dir / "base_b00_0.ssrc").write_bytes(data)
        read = {"chunk_filename": "base_b00_0.ssrc", "physical_offset": 0,
                "chunk_physical_length": len(data), "bytes": len(data),
                "skip_blocks": 0, "count_blocks": 1}
        with patch.object(export, "RESOURCE_ROOT", str(resource_root)):
            command = export.dd_command(read)
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                  "stderr": subprocess.STDOUT, "check": False, "timeout": 10}
        unredirected = subprocess.run([shutil.which("sh"), "-c", command.removesuffix(" 2>/dev/null")], **kwargs)
        redirected = subprocess.run([shutil.which("sh"), "-c", command], **kwargs)
        self.assertEqual(unredirected.returncode, 0)
        self.assertEqual(redirected.returncode, 0)
        self.assertTrue(unredirected.stdout.startswith(data))
        self.assertGreater(len(unredirected.stdout), len(data))
        self.assertEqual(redirected.stdout, data)
        with patch.object(export, "RESOURCE_ROOT", str(resource_root)):
            diagnostic_command = export.diagnostic_dd_command(read)
        diagnostic = subprocess.run([shutil.which("sh"), "-c", diagnostic_command], **kwargs)
        self.assertEqual(diagnostic.returncode, 0)
        self.assertIn(b"__ssra_range_dd_exit=0\n", diagnostic.stdout)
        self.assertNotIn(data, diagnostic.stdout)

    def test_binary_runner_uses_local_server_and_retains_exact_binary_stdout(self):
        data = b"\x00\xff\r\n" + bytes(range(256))
        process = FakeProcess(data, b"records in/out\n")
        overrides = {"ADB_SERVER_SOCKET": "tcp:remote:5037", "ANDROID_ADB_SERVER_ADDRESS": "remote", "ANDROID_ADB_SERVER_PORT": "1234"}
        args = ["-s", "emulator-5554", "exec-out", "dd if=/fixed bs=65536 skip=0 count=1"]
        with patch.dict(os.environ, overrides), patch.object(export.subprocess, "Popen", return_value=process) as popen:
            result = export.RangeAdbRunner(self.adb).run_binary(args, len(data))
        self.assertEqual(result.stdout, data)
        self.assertEqual(popen.call_args.args[0], [str(self.adb), "-P", "5037", *args])
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertTrue(all(name not in popen.call_args.kwargs["env"] for name in overrides))

    def test_binary_runner_rejects_output_overflow_wrong_length_nonzero_and_timeout(self):
        for process in (FakeProcess(bytes(11)), FakeProcess(bytes(9)),
                        FakeProcess(bytes(10), returncode=7), FakeProcess(bytes(10), bytes(export.MAX_BINARY_STDERR_BYTES + 1)),
                        FakeProcess(bytes(10), timeout=True)):
            with self.subTest(process=process), patch.object(export.subprocess, "Popen", return_value=process):
                with self.assertRaises(export.RangeExportError):
                    export.RangeAdbRunner(self.adb).run_binary(["-s", "emulator-5554", "exec-out", "dd fixed"], 10)
        runner = export.RangeAdbRunner(self.adb)
        with self.assertRaisesRegex(export.RangeExportError, "per-call"):
            runner.run_binary([], export.MAX_BINARY_CALL_BYTES + 1)

    def test_binary_runner_reports_empty_or_short_counts_without_binary_preview(self):
        for body in (b"", b"private payload"):
            process = FakeProcess(body)
            with self.subTest(length=len(body)), patch.object(export.subprocess, "Popen", return_value=process):
                with self.assertRaises(export.RangeExportError) as raised:
                    export.RangeAdbRunner(self.adb).run_binary(["-s", "emulator-5554", "exec-out", "dd fixed"], 100)
            message = str(raised.exception)
            self.assertIn(f"exit=0; expected_stdout_bytes=100; received_stdout_bytes={len(body)}", message)
            self.assertIn("no local ADB diagnostic returned", message)
            self.assertNotIn("private payload", message)

    def test_diagnostic_command_budget_is_bounded_and_preserves_cumulative_limit(self):
        runner = export.RangeAdbRunner(self.adb)
        previous = runner.remaining
        process = FakeProcess(b"__ssra_range_dd_exit=0\n")
        with patch.object(export.subprocess, "Popen", return_value=process):
            result = runner.run_diagnostic(["-s", "emulator-5554", "shell", "diagnostic fixture"])
        self.assertEqual(runner.remaining, previous - len(result.stdout))
        overflow = FakeProcess(bytes(export.MAX_DIAGNOSTIC_OUTPUT_BYTES + 1))
        with patch.object(export.subprocess, "Popen", return_value=overflow):
            with self.assertRaises(export.existing.ExportError):
                runner.run_diagnostic(["-s", "emulator-5554", "shell", "diagnostic fixture"])
        self.assertEqual(runner.remaining, previous - len(result.stdout) - export.MAX_DIAGNOSTIC_OUTPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
