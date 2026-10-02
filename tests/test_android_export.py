"""Synthetic inventory and ADB pulls; no game, network, or emulator is contacted."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import export_android_research as export
from tools import inventory_android_resources as android


SYNTHETIC_TARGETS = tuple(
    export.Target(target.relative_path, 10 + ordinal * 3, target.pack)
    for ordinal, target in enumerate(export.TARGETS)
)


def payload(target):
    ordinal = SYNTHETIC_TARGETS.index(target)
    return bytes([65 + ordinal]) * target.bytes


def inventory():
    files = [{"path": export.RESOURCE_ROOT + "/" + target.relative_path,
              "relative_path": target.relative_path, "bytes": target.bytes,
              "extension": Path(target.relative_path).suffix}
             for target in SYNTHETIC_TARGETS]
    # These observed names must never become export targets or exported contents.
    files.extend({"path": export.RESOURCE_ROOT + "/" + name,
                  "relative_path": name, "bytes": 8, "extension": Path(name).suffix}
                 for name in ("device_os.pw", "gameres/patch-meta.json"))
    locations = [{"root": export.RESOURCE_ROOT, "status": "accessible", "returncode": 0,
                  "complete_within_declared_scope": True, "files": files,
                  "listed_file_count": len(files), "listed_bytes": sum(item["bytes"] for item in files)}]
    for root in android.RESOURCE_ROOTS[1:]:
        locations.append({"root": root, "status": "permission_denied", "returncode": 1,
                          "complete_within_declared_scope": False, "files": [],
                          "listed_file_count": 0, "listed_bytes": 0})
    return {"schema_version": 1, "package": export.PACKAGE, "serial": "emulator-5554",
            "adb": {"executable": "/untrusted/report-selected/program.exe"},
            "scope": {"regular_files_only": True, "follows_directory_symlinks": False,
                      "root_elevation_requested": False, "contents_read": False},
            "limit_reached": False, "listed_file_count": len(files), "locations": locations}


class FakeRunner:
    def __init__(self, *, devices=None, installed=True, failed_pull=None,
                 bad_size=None, stat_changed=None, stat_failed=None, mutate_after_pull=None,
                 package_result=None):
        self.devices = devices or b"List of devices attached\nemulator-5554 device\n"
        self.installed = installed
        self.package_result = package_result
        self.failed_pull = failed_pull
        self.bad_size = bad_size
        self.stat_changed = stat_changed
        self.stat_failed = stat_failed
        self.mutate_after_pull = mutate_after_pull
        self.pulled = []
        self.calls = []

    def run(self, args, **limits):
        self.calls.append((args, limits))
        if args == ["devices", "-l"]:
            return android.CommandResult(0, self.devices)
        if args[-1] == f"pm path {export.PACKAGE}":
            if self.package_result is not None:
                return self.package_result
            return android.CommandResult(0, b"package:/data/app/synthetic/base.apk\n" if self.installed else b"")
        for target in SYNTHETIC_TARGETS:
            if args[-1] == export.target_stat_command(target):
                if target == self.stat_failed:
                    return android.CommandResult(7, b"", b"synthetic symlink or inaccessible resource")
                changed = target == self.stat_changed or target == self.mutate_after_pull and target in self.pulled
                return android.CommandResult(0, str(target.bytes + int(changed)).encode() + b"\n")
            if len(args) == 5 and args[2] == "pull" and args[3] == export.RESOURCE_ROOT + "/" + target.relative_path:
                self.pulled.append(target)
                destination = Path(args[4])
                destination.write_bytes(payload(target) + (b"extra" if self.bad_size == target else b""))
                if target == self.failed_pull:
                    return android.CommandResult(1, b"", b"synthetic pull interrupted")
                return android.CommandResult(0, b"synthetic resource pulled\n")
        raise AssertionError(f"Unexpected operation: {args}")


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", wait_hook=None):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None
        self.killed = False
        self.wait_hook = wait_hook

    def wait(self, timeout=None):
        if self.wait_hook is not None and not self.killed:
            self.wait_hook()
            raise subprocess.TimeoutExpired("synthetic adb", timeout)
        self.returncode = -9 if self.killed else 0
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


class AndroidExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-android-export-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.adb = self.root / "adb.exe"
        self.adb.write_bytes(b"not executed")
        self.adb.chmod(0o700)
        self.report = self.root / "report.json"
        self.output = self.root / "export"
        self.addCleanup(patch.stopall)
        patch.object(export, "TARGETS", SYNTHETIC_TARGETS).start()
        self.write_report(inventory())

    def write_report(self, report):
        self.report.write_text(json.dumps(report, ensure_ascii=True), encoding="utf-8")

    def run_export(self, runner=None):
        return export.export_resources(self.report, self.output, self.adb, runner or FakeRunner())

    def assert_clean(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".chaos-runtime-export-*")), [])

    def test_fixed_selection_produces_two_inert_hash_verified_packs(self):
        runner = FakeRunner()
        result = self.run_export(runner)
        report_hash = hashlib.sha256(self.report.read_bytes()).hexdigest()
        self.assertEqual(result["source_inventory_sha256"], report_hash)
        self.assertEqual(result["payload_file_count"], 6)
        self.assertEqual(result["payload_bytes"], sum(target.bytes for target in SYNTHETIC_TARGETS))
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), sorted((*export.PACK_NAMES, "summary.md")))
        observed = []
        for pack in result["packs"]:
            path = self.output / pack["filename"]
            self.assertLess(path.stat().st_size, export.MAX_ZIP_BYTES)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), pack["sha256"])
            with zipfile.ZipFile(path) as archive:
                index = json.loads(archive.read("research-index.json"))
                self.assertEqual(index["source_inventory_sha256"], report_hash)
                self.assertNotIn("adb", index)
                self.assertEqual(len(index["files"]), pack["payload_files"])
                self.assertEqual(len(archive.namelist()), pack["payload_files"] + 1)
                for item in index["files"]:
                    data = archive.read(item["archive_path"])
                    self.assertEqual(len(data), item["bytes"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                    self.assertEqual(archive.getinfo(item["archive_path"]).compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(item["remote_path"], export.RESOURCE_ROOT + "/" + item["relative_path"])
                    observed.append(item["relative_path"])
        self.assertEqual(observed, [target.relative_path for target in SYNTHETIC_TARGETS])
        pulls = [call for call, limits in runner.calls if "pull" in call]
        self.assertEqual(len(pulls), 6)
        self.assertFalse(any("device_os.pw" in arg or "patch-meta" in arg for call in pulls for arg in call))
        self.assertFalse(any(any(arg in ("root", "su", "connect", "install", "tcpip") for arg in call)
                             for call, limits in runner.calls))
        for call, limits in runner.calls:
            if "pull" in call:
                self.assertRegex(Path(call[-1]).name, r"^payload-\d{2}\.bin$")
                self.assertEqual(limits["destination"], Path(call[-1]))
                self.assertGreater(limits["maximum_bytes"], 0)
        self.assertEqual(list(self.root.glob(".chaos-runtime-export-*")), [])

    def test_report_cannot_select_the_executed_adb(self):
        with patch.object(export.android, "locate_adb", return_value=self.adb) as locate:
            self.run_export()
        locate.assert_called_once_with(self.adb)

    def test_ldplayer_launcher_is_rejected_before_export_commands(self):
        launcher = self.root / "dnplayer.exe"
        launcher.write_bytes(b"not executed: synthetic LDPlayer launcher")
        launcher.chmod(0o700)
        runner = FakeRunner()
        with (patch.object(export.subprocess, "Popen") as popen,
              self.assertRaisesRegex(android.InventoryError, "dnplayer.exe")):
            export.export_resources(self.report, self.output, launcher, runner)
        popen.assert_not_called()
        self.assertEqual(runner.calls, [])
        self.assert_clean()

    def test_package_serial_scope_and_incomplete_inventory_fail_before_adb(self):
        cases = [
            ("package", "other.app"), ("serial", "192.168.1.5:5555"),
            ("schema_version", True), ("schema_version", 2), ("limit_reached", True),
        ]
        for key, value in cases:
            report = inventory()
            report[key] = value
            self.write_report(report)
            runner = FakeRunner()
            with self.subTest(key=key), self.assertRaises(export.ExportError):
                self.run_export(runner)
            self.assertEqual(runner.calls, [])
        for key, value in (("regular_files_only", False), ("follows_directory_symlinks", True),
                           ("root_elevation_requested", True), ("contents_read", True)):
            report = inventory()
            report["scope"][key] = value
            self.write_report(report)
            with self.subTest(key=key), self.assertRaises(export.ExportError):
                self.run_export()
        self.assert_clean()

    def test_nonlocal_absent_offline_or_unauthorized_report_device_never_pulls(self):
        for devices in (b"List of devices attached\n", b"List of devices attached\nemulator-5556 device\n",
                        b"List of devices attached\nemulator-5554 offline\n",
                        b"List of devices attached\nemulator-5554 unauthorized\n"):
            runner = FakeRunner(devices=devices)
            with self.subTest(devices=devices), self.assertRaises(android.InventoryError):
                self.run_export(runner)
            self.assertEqual(runner.pulled, [])
            self.assert_clean()

    def test_multiple_devices_uses_only_the_report_local_serial(self):
        runner = FakeRunner(devices=b"List of devices attached\nemulator-5554 device\nemulator-5556 device\nUSB123 device\n")
        self.run_export(runner)
        self.assertTrue(all(call[1] == "emulator-5554" for call, limits in runner.calls if call[0] == "-s"))

    def test_uninstalled_package_stops_before_remote_file_checks(self):
        runner = FakeRunner(installed=False)
        with self.assertRaisesRegex(export.ExportError, "not installed"):
            self.run_export(runner)
        self.assertEqual(len(runner.calls), 2)
        self.assert_clean()

    def test_closed_adb_shell_fails_as_export_error_before_stat_or_pull(self):
        runner = FakeRunner(package_result=android.CommandResult(1, b"", b"error: closed\n"))
        with self.assertRaises(export.ExportError) as raised:
            self.run_export(runner)
        message = str(raised.exception)
        self.assertIn("ADB shell transport failed", message)
        self.assertIn("emulator-5554", message)
        self.assertIn("error: closed", message)
        self.assertIn("shell echo adb-ok", message)
        self.assertNotIn("not installed", message)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.pulled, [])
        self.assert_clean()

    def test_nonzero_package_query_with_valid_stdout_stops_before_export(self):
        runner = FakeRunner(package_result=android.CommandResult(
            7, b"package:/data/app/synthetic/base.apk\n", b"package manager unavailable\n"))
        with self.assertRaises(export.ExportError) as raised:
            self.run_export(runner)
        self.assertIn("ADB shell package query failed", str(raised.exception))
        self.assertIn("exit 7", str(raised.exception))
        self.assertNotIn("not installed", str(raised.exception))
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.pulled, [])
        self.assert_clean()

    def test_successful_malformed_package_query_stops_before_remote_checks(self):
        for body in (b"Error: service unavailable\n", b"package:/\n", b"\xff\n",
                     b"package:/data/app/base.apk\nunknown line\n", b"package:/data/app/\x00base.apk\n"):
            runner = FakeRunner(package_result=android.CommandResult(0, body))
            with self.subTest(body=body), self.assertRaises(export.ExportError) as raised:
                self.run_export(runner)
            self.assertIn("Unexpected package-query response", str(raised.exception))
            self.assertNotIn("not installed", str(raised.exception))
            self.assertEqual(len(runner.calls), 2)
            self.assertEqual(runner.pulled, [])
            self.assert_clean()

    def test_inventory_missing_changed_and_duplicate_targets_are_rejected(self):
        report = inventory()
        report["locations"][0]["files"].pop(0)
        report["locations"][0]["listed_file_count"] -= 1
        report["listed_file_count"] -= 1
        report["locations"][0]["listed_bytes"] -= SYNTHETIC_TARGETS[0].bytes
        self.write_report(report)
        with self.assertRaisesRegex(export.ExportError, "absent"):
            self.run_export()
        report = inventory()
        report["locations"][0]["files"][0]["bytes"] += 1
        report["locations"][0]["listed_bytes"] += 1
        self.write_report(report)
        with self.assertRaisesRegex(export.ExportError, "size differs"):
            self.run_export()
        report = inventory()
        report["locations"][0]["files"].append(copy.deepcopy(report["locations"][0]["files"][0]))
        self.write_report(report)
        with self.assertRaisesRegex(export.ExportError, "duplicate"):
            self.run_export()
        self.assert_clean()

    def test_unsafe_paths_cannot_replace_selected_or_other_inventory_records(self):
        for relative in ("../shared_prefs/login.xml", "gameres/../manifest.ssra", "gameres//manifest.ssra",
                         "gameres\\manifest.ssra", "gameres/manifest.ssra\n", "gameres/\ud800.ssra"):
            report = inventory()
            item = report["locations"][0]["files"][0]
            item["relative_path"] = relative
            item["path"] = export.RESOURCE_ROOT + "/" + relative
            self.write_report(report)
            with self.subTest(relative=repr(relative)), self.assertRaises(export.ExportError):
                self.run_export()
        report = inventory()
        report["locations"][0]["files"][0]["path"] = "/data/user/0/other.app/shared_prefs/login.xml"
        self.write_report(report)
        with self.assertRaises(export.ExportError):
            self.run_export()
        self.assert_clean()

    def test_invalid_counts_roots_sizes_or_access_status_are_rejected(self):
        modifications = (
            lambda report: report.update(listed_file_count=True),
            lambda report: report["locations"][0].update(listed_bytes=0),
            lambda report: report["locations"][0].update(listed_file_count=0),
            lambda report: report["locations"][0].update(status="permission_denied"),
            lambda report: report["locations"][0].update(complete_within_declared_scope=False),
            lambda report: report["locations"][0].update(returncode=True),
            lambda report: report["locations"][1].update(root=export.RESOURCE_ROOT),
            lambda report: report["locations"][1].update(root="/sdcard/arbitrary"),
            lambda report: report["locations"][0]["files"][0].update(bytes=-1),
            lambda report: report["locations"][0]["files"][0].update(bytes=2**63),
        )
        for modify in modifications:
            report = inventory()
            modify(report)
            self.write_report(report)
            with self.subTest(modify=modify), self.assertRaises(export.ExportError):
                self.run_export()
        self.assert_clean()

    def test_oversized_malformed_and_duplicate_key_reports_are_rejected(self):
        for raw in (b"\xff", b"not JSON", b'{"schema_version":1,"schema_version":1}',
                    b'{"large_integer":' + b"9" * 5000 + b"}"):
            self.report.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(export.ExportError):
                self.run_export()
        self.report.write_bytes(b" " * 100)
        with patch.object(export, "MAX_REPORT_BYTES", 50), self.assertRaisesRegex(export.ExportError, "2 MiB"):
            self.run_export()
        self.assert_clean()

    def test_profile_total_and_individual_pack_bounds_fail_before_adb(self):
        with patch.object(export, "MAX_TOTAL_PAYLOAD_BYTES", 1), self.assertRaisesRegex(export.ExportError, "total"):
            self.run_export()
        with patch.object(export, "MAX_ZIP_BYTES", 1), self.assertRaisesRegex(export.ExportError, "individual"):
            self.run_export()
        self.assert_clean()

    def test_changed_remote_size_or_inaccessible_symlink_fails_without_pull(self):
        for runner in (FakeRunner(stat_changed=SYNTHETIC_TARGETS[2]), FakeRunner(stat_failed=SYNTHETIC_TARGETS[1])):
            with self.assertRaises(export.ExportError):
                self.run_export(runner)
            self.assertEqual(runner.pulled, [])
            self.assert_clean()
        command = export.target_stat_command(SYNTHETIC_TARGETS[1])
        self.assertIn("[ ! -L " + export.RESOURCE_ROOT + "/gameres ]", command)
        self.assertIn("[ ! -L " + export.RESOURCE_ROOT + "/gameres/chunks ]", command)
        self.assertIn("[ -f " + export.RESOURCE_ROOT + "/" + SYNTHETIC_TARGETS[1].relative_path + " ]", command)
        with self.assertRaisesRegex(export.ExportError, "fixed"):
            export.target_stat_command(export.Target("device_os.pw", 8, export.PACK_NAMES[0]))

    def test_pull_failure_wrong_size_or_post_pull_change_cleans_all_staging(self):
        for runner in (FakeRunner(failed_pull=SYNTHETIC_TARGETS[3]),
                       FakeRunner(bad_size=SYNTHETIC_TARGETS[1]),
                       FakeRunner(mutate_after_pull=SYNTHETIC_TARGETS[2])):
            with self.assertRaises(export.ExportError):
                self.run_export(runner)
            self.assert_clean()

    def test_existing_output_and_symlink_are_preserved_before_any_commands(self):
        self.output.mkdir()
        marker = self.output / "user-file.txt"
        marker.write_text("preserve")
        runner = FakeRunner()
        with self.assertRaisesRegex(export.ExportError, "already exists"):
            self.run_export(runner)
        self.assertEqual(marker.read_text(), "preserve")
        self.assertEqual(runner.calls, [])
        if os.name != "nt":
            alias = self.root / "alias"
            alias.symlink_to(self.output, target_is_directory=True)
            with self.assertRaisesRegex(export.ExportError, "already exists"):
                export.export_resources(self.report, alias, self.adb, runner)
            self.assertTrue(alias.is_symlink())

    def test_pack_creation_size_failure_never_promotes_partial_output(self):
        # Validation passes with the normal bounds; reduce only when packing starts.
        original = export._write_pack

        def too_small(*args):
            with patch.object(export, "MAX_ZIP_BYTES", 10):
                return original(*args)

        with patch.object(export, "_write_pack", side_effect=too_small), self.assertRaisesRegex(export.ExportError, "30 MiB"):
            self.run_export()
        self.assert_clean()

    def test_runner_pins_local_server_ignores_remote_env_and_bounds_pipe_output(self):
        process = FakeProcess(stdout=b"ok", stderr=b"note")
        with (patch.object(export.subprocess, "Popen", return_value=process) as popen,
              patch.dict(os.environ, {"ADB_SERVER_SOCKET": "tcp:remote:5037", "ANDROID_ADB_SERVER_ADDRESS": "remote"})):
            result = export.ExportAdbRunner(self.adb).run(["devices", "-l"])
        self.assertEqual(result.stdout, b"ok")
        self.assertEqual(popen.call_args.args[0][1:5], ["-H", "127.0.0.1", "-P", "5037"])
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertNotIn("ADB_SERVER_SOCKET", popen.call_args.kwargs["env"])
        process = FakeProcess(stdout=b"x" * 20)
        with patch.object(export, "MAX_ADB_OUTPUT_BYTES", 8), patch.object(export.subprocess, "Popen", return_value=process):
            runner = export.ExportAdbRunner(self.adb)
            with self.assertRaisesRegex(export.ExportError, "2 MiB"):
                runner.run(["devices", "-l"])
            with self.assertRaisesRegex(export.ExportError, "2 MiB"):
                runner.run(["devices", "-l"])

    def test_runner_monitors_transfer_size_and_kills_only_started_client(self):
        destination = self.root / "synthetic-pull.bin"
        process = FakeProcess(wait_hook=lambda: destination.write_bytes(b"x" * 21))
        with patch.object(export.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(export.ExportError, "selected size"):
                export.ExportAdbRunner(self.adb).run(["pull", "fixed", str(destination)],
                                                     destination=destination, maximum_bytes=20)
        self.assertTrue(process.killed)

    def test_runner_timeout_is_bounded_and_reported(self):
        process = FakeProcess(wait_hook=lambda: None)
        with (patch.object(export.subprocess, "Popen", return_value=process),
              patch.object(export.time, "monotonic", side_effect=(0, 61))):
            with self.assertRaisesRegex(export.ExportError, "60 seconds"):
                export.ExportAdbRunner(self.adb).run(["devices", "-l"])
        self.assertTrue(process.killed)

    def test_main_reports_failure_without_claiming_created_archives(self):
        with patch.object(export.sys, "stderr", new_callable=io.StringIO) as stderr:
            self.report.write_text("malformed")
            result = export.main(["--report", str(self.report), "--output", str(self.output), "--adb", str(self.adb)])
        self.assertEqual(result, 2)
        self.assertIn("Export failed", stderr.getvalue())
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
