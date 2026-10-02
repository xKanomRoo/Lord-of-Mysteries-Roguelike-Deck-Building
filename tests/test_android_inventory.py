"""Synthetic local-emulator responses; no real ADB or game data is contacted."""

import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import inventory_android_resources as android


def records(root, files=()):
    return b"CZNI_DIRECTORY\0" + b"".join(
        str(size).encode() + b"\0" + (root + "/" + name).encode() + b"\0"
        for name, size in files
    )


class FakeRunner:
    def __init__(self, devices=b"List of devices attached\n127.0.0.1:5555 device product:synthetic\n",
                 roots=None, installed=True):
        self.devices = devices
        self.roots = roots or {}
        self.installed = installed
        self.calls = []

    def run(self, args):
        self.calls.append(args)
        if args == ["version"]:
            return android.CommandResult(0, b"Android Debug Bridge version 1.0.41\nVersion 35.0.synthetic\nInstalled as /private/location/adb\n")
        if args == ["devices", "-l"]:
            return android.CommandResult(0, self.devices)
        if args[-1] == f"pm path {android.PACKAGE}":
            return android.CommandResult(0, b"package:/data/app/synthetic/base.apk\n" if self.installed else b"")
        if args[-1] == "getprop ro.build.version.sdk":
            return android.CommandResult(0, b"28\n")
        for root in android.RESOURCE_ROOTS:
            if args[-1] == android.inventory_command(root):
                result = self.roots.get(root, android.CommandResult(1, b"CZNI_ABSENT\0", b"No such file or directory"))
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"Unexpected ADB operation: {args}")


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", timeout=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = 0
        self.killed = False
        self.timeout = timeout
        self.wait_calls = 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.timeout and self.wait_calls == 1:
            raise subprocess.TimeoutExpired("synthetic adb", timeout)
        return self.returncode

    def kill(self):
        self.killed = True


class AndroidInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-android-inventory-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.adb = self.root / "adb.exe"
        self.adb.write_bytes(b"not executed: synthetic trusted ADB location")
        self.adb.chmod(0o700)
        self.output = self.root / "inventory"

    def inventory(self, runner=None, serial=None):
        return android.inventory_resources(self.output, self.adb, serial, runner or FakeRunner())

    def test_success_records_only_scoped_names_sizes_and_access_status(self):
        public, obb, private, alias = android.RESOURCE_ROOTS
        runner = FakeRunner(roots={
            public: android.CommandResult(0, records(public, [("sourcepack/main.jbin", 321), ("images/card two.png", 45)])),
            obb: android.CommandResult(0, records(obb, [("main.synthetic.obb", 700)])),
            private: android.CommandResult(1, b"CZNI_ABSENT\0", b"ls: Permission denied\n"),
            alias: android.CommandResult(1, b"CZNI_ABSENT\0", b"ls: Permission denied\n"),
        })
        result = self.inventory(runner)
        self.assertEqual(result["listed_file_count"], 3)
        self.assertEqual(result["android_sdk"], 28)
        self.assertEqual([location["status"] for location in result["locations"]],
                         ["accessible", "accessible", "permission_denied", "permission_denied"])
        self.assertEqual(result["locations"][0]["listed_bytes"], 366)
        self.assertFalse(result["scope"]["contents_read"])
        self.assertFalse(result["scope"]["root_elevation_requested"])
        self.assertEqual(json.loads((self.output / "report.json").read_text()), result)
        self.assertTrue((self.output / "summary.md").exists())
        self.assertNotIn("/private/location", result["adb"]["version"])
        self.assertFalse(any(any(arg in ("root", "su", "pull", "install", "connect", "tcpip") for arg in call)
                             for call in runner.calls))

    def test_selection_refuses_no_multiple_offline_unauthorized_and_nonlocal_devices(self):
        cases = (
            (b"List of devices attached\n", None, "No local"),
            (b"List of devices attached\n192.168.1.3:5555 device\n", None, "No local"),
            (b"List of devices attached\nemulator-5554 device\n127.0.0.1:5555 offline\n", None, "Multiple"),
            (b"List of devices attached\nemulator-5554 offline\n", None, "offline"),
            (b"List of devices attached\n127.0.0.1:5555 unauthorized\n", None, "unauthorized"),
            (b"List of devices attached\nUSB123 device\n", "USB123", "local"),
        )
        for device_list, serial, message in cases:
            with self.subTest(device_list=device_list), self.assertRaisesRegex(android.InventoryError, message):
                self.inventory(FakeRunner(devices=device_list), serial)
            self.assertFalse(self.output.exists())

    def test_explicit_local_selection_does_not_probe_or_connect_other_devices(self):
        runner = FakeRunner(devices=b"List of devices attached\nemulator-5554 device\n127.0.0.1:5555 device\nUSB123 device\n")
        result = self.inventory(runner, "emulator-5554")
        self.assertEqual(result["serial"], "emulator-5554")
        self.assertTrue(all(call[1] == "emulator-5554" for call in runner.calls if call[0] == "-s"))
        for serial in ("127.0.0.1:65536", "127.0.0.1:0", "localhost:5555;su", "emulator-5554\n"):
            self.assertFalse(android.local_serial(serial))

    def test_malformed_and_duplicate_device_lists_are_rejected(self):
        for body in (b"unrecognized", b"List of devices attached\nemulator-5554\n",
                     b"List of devices attached\nemulator-5554 device\nemulator-5554 device\n",
                     b"List of devices attached\n\xff device\n"):
            with self.subTest(body=body), self.assertRaises(android.InventoryError):
                android.parse_devices(body)

    def test_uninstalled_fixed_package_fails_before_resource_listing(self):
        runner = FakeRunner(installed=False)
        with self.assertRaisesRegex(android.InventoryError, "not installed"):
            self.inventory(runner)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(runner.calls), 3)

    def test_spaces_shell_characters_and_unicode_in_filenames_are_data(self):
        root = android.RESOURCE_ROOTS[0]
        filename = "folder/card $(touch marker)' ไทย.png"
        files, omitted = android.parse_file_records(records(root, [(filename, 0)]), root)
        self.assertEqual(files[0]["relative_path"], filename)
        self.assertEqual(files[0]["bytes"], 0)
        self.assertEqual(omitted, 0)
        command = android.inventory_command(root)
        self.assertNotIn(filename, command)
        self.assertIn('"$f"', command)
        with self.assertRaisesRegex(android.InventoryError, "fixed"):
            android.inventory_command("/sdcard/anything; su")

    def test_unsafe_out_of_scope_noncanonical_duplicate_and_invalid_utf8_paths_fail(self):
        root = android.RESOURCE_ROOTS[0]
        marker = b"CZNI_DIRECTORY\0"
        paths = (root + "/../other", root + "//file", root + "/a\nfile", root + "/a\tfile",
                 "/data/user/0/other/files/file", root + "/a/" + "/".join(["x"] * android.MAX_DEPTH))
        for path in paths:
            with self.subTest(path=path), self.assertRaises(android.InventoryError):
                android.parse_file_records(marker + b"5\0" + path.encode() + b"\0", root)
        with self.assertRaisesRegex(android.InventoryError, "UTF-8"):
            android.parse_file_records(marker + b"5\0" + root.encode() + b"/\xff\0", root)
        with self.assertRaisesRegex(android.InventoryError, "duplicate"):
            android.parse_file_records(records(root, [("same", 1), ("same", 1)]), root)

    def test_sensitive_names_are_omitted_without_reading_their_contents(self):
        root = android.RESOURCE_ROOTS[0]
        data = records(root, [("cards.db", 100), ("account.db", 99), ("preferences/settings.json", 23),
                              ("session-token.json", 30), ("sourcepack/main.jbin", 321)])
        files, omitted = android.parse_file_records(data, root)
        self.assertEqual(omitted, 3)
        self.assertEqual([file["relative_path"] for file in files], ["cards.db", "sourcepack/main.jbin"])
        command = android.inventory_command(root)
        self.assertIn("-prune", command)
        self.assertNotIn("cat ", command)

    def test_truncation_invalid_sizes_count_and_byte_bounds_are_rejected(self):
        root = android.RESOURCE_ROOTS[0]
        marker = b"CZNI_DIRECTORY\0"
        for body in (marker + b"1\0path", marker + b"1\0", marker + b"-1\0" + root.encode() + b"/file\0",
                     records(root, [("file", 2**63)])):
            with self.subTest(body=body), self.assertRaises(android.InventoryError):
                android.parse_file_records(body, root)
        with patch.object(android, "MAX_FILES", 1), self.assertRaises(android.CommandLimitError):
            android.parse_file_records(records(root, [("a", 1), ("b", 2)]), root)
        with patch.object(android, "MAX_OUTPUT_BYTES", 10), self.assertRaises(android.CommandLimitError):
            android.parse_file_records(records(root, [("a", 1)]), root)

    def test_permission_error_keeps_partial_metadata_and_never_claims_complete(self):
        root = android.RESOURCE_ROOTS[0]
        runner = FakeRunner(roots={root: android.CommandResult(1, records(root, [("main.jbin", 5)]),
                                                            b"find: secret: Permission denied\n")})
        result = self.inventory(runner)
        location = result["locations"][0]
        self.assertEqual(location["status"], "permission_denied")
        self.assertFalse(location["complete_within_declared_scope"])
        self.assertEqual(location["listed_file_count"], 1)
        self.assertNotIn("\n", location["diagnostic"])

    def test_unsupported_toybox_is_reported_as_command_failed(self):
        root = android.RESOURCE_ROOTS[0]
        runner = FakeRunner(roots={root: android.CommandResult(1, b"CZNI_DIRECTORY\0", b"find: unknown option -maxdepth\n")})
        result = self.inventory(runner)
        self.assertEqual(result["locations"][0]["status"], "command_failed")
        self.assertIn("unknown option", result["locations"][0]["diagnostic"])

    def test_combined_count_limit_stops_further_directory_commands(self):
        first, second, third, fourth = android.RESOURCE_ROOTS
        runner = FakeRunner(roots={
            first: android.CommandResult(0, records(first, [("main.jbin", 5)])),
            second: android.CommandResult(0, records(second, [("second.obb", 6)])),
        })
        with patch.object(android, "MAX_FILES", 1):
            result = self.inventory(runner)
        self.assertTrue(result["limit_reached"])
        self.assertEqual(result["listed_file_count"], 1)
        self.assertEqual(result["locations"][2]["status"], "not_inspected_limit")
        self.assertFalse(any(call[-1] == android.inventory_command(third) for call in runner.calls))

    def test_output_and_explicit_adb_validation_preserve_user_files_before_commands(self):
        self.output.mkdir()
        existing = self.output / "user-file"
        existing.write_text("preserve")
        runner = FakeRunner()
        with self.assertRaisesRegex(android.InventoryError, "already exists"):
            self.inventory(runner)
        self.assertEqual(existing.read_text(), "preserve")
        self.assertEqual(runner.calls, [])
        with self.assertRaisesRegex(android.InventoryError, "executable"):
            android.locate_adb(self.root / "missing.exe")
        with self.assertRaisesRegex(android.InventoryError, "executable"):
            android.locate_adb(self.root)

    def test_path_discovery_checks_regular_executable_and_reports_missing(self):
        with patch.object(android.shutil, "which", return_value=str(self.adb)):
            self.assertEqual(android.locate_adb(), self.adb.resolve())
        if os.name != "nt":
            with patch.object(android.shutil, "which", return_value=None), self.assertRaisesRegex(android.InventoryError, "ADB not found"):
                android.locate_adb()
            self.adb.chmod(0o600)
            with self.assertRaisesRegex(android.InventoryError, "executable"):
                android.locate_adb(self.adb)

    def test_ldplayer_launcher_is_rejected_before_inventory_commands(self):
        launcher = self.root / "dnplayer.exe"
        launcher.write_bytes(b"not executed: synthetic LDPlayer launcher")
        launcher.chmod(0o700)
        runner = FakeRunner()
        with (patch.object(android.subprocess, "Popen") as popen,
              self.assertRaisesRegex(android.InventoryError, "dnplayer.exe")):
            android.inventory_resources(self.output, launcher, runner=runner)
        popen.assert_not_called()
        self.assertEqual(runner.calls, [])
        self.assertFalse(self.output.exists())

    def test_adb_filenames_follow_platform_case_rules(self):
        uppercase = self.root / "ADB.EXE"
        uppercase.write_bytes(b"not executed: synthetic ADB location")
        uppercase.chmod(0o700)
        suffixless = self.root / "adb"
        suffixless.write_bytes(b"not executed: synthetic ADB location")
        suffixless.chmod(0o700)
        uppercase_resolved = uppercase.resolve()
        suffixless_resolved = suffixless.resolve()
        with patch.object(android.os, "name", "nt"):
            self.assertEqual(android._executable(uppercase), uppercase_resolved)
            self.assertIsNone(android._executable(suffixless))
        with patch.object(android.os, "name", "posix"):
            self.assertIsNone(android._executable(uppercase))
            self.assertEqual(android._executable(suffixless), suffixless_resolved)

    @unittest.skipIf(os.name == "nt", "Synthetic symlinks do not require Windows privileges")
    def test_adb_named_symlink_cannot_select_the_ldplayer_launcher(self):
        launcher = self.root / "dnplayer.exe"
        launcher.write_bytes(b"not executed: synthetic LDPlayer launcher")
        launcher.chmod(0o700)
        self.adb.unlink()
        self.adb.symlink_to(launcher)
        runner = FakeRunner()
        with self.assertRaisesRegex(android.InventoryError, "executable"):
            self.inventory(runner)
        self.assertEqual(runner.calls, [])
        self.assertFalse(self.output.exists())

    def test_subprocess_locks_local_server_and_bounds_combined_pipe_output(self):
        process = FakeProcess(stdout=b"out", stderr=b"err")
        with (patch.object(android.subprocess, "Popen", return_value=process) as popen,
              patch.dict(os.environ, {"ADB_SERVER_SOCKET": "tcp:remote:5037", "ANDROID_ADB_SERVER_ADDRESS": "remote"})):
            runner = android.AdbRunner(self.adb)
            result = runner.run(["devices", "-l"])
        self.assertEqual(result.stdout, b"out")
        self.assertEqual(result.stderr, b"err")
        argv = popen.call_args.args[0]
        self.assertEqual(argv[1:5], ["-H", "127.0.0.1", "-P", "5037"])
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertNotIn("ADB_SERVER_SOCKET", popen.call_args.kwargs["env"])
        with patch.object(android, "MAX_OUTPUT_BYTES", 8), patch.object(android.subprocess, "Popen", return_value=FakeProcess(stdout=b"x" * 9)):
            runner = android.AdbRunner(self.adb)
            with self.assertRaisesRegex(android.CommandLimitError, "2 MiB"):
                runner.run(["version"])
            with self.assertRaises(android.CommandLimitError):
                runner.run(["devices", "-l"])

    def test_subprocess_timeout_kills_only_the_started_adb_client(self):
        process = FakeProcess(timeout=True)
        with patch.object(android.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(android.InventoryError, "timed out"):
                android.AdbRunner(self.adb).run(["version"])
        self.assertTrue(process.killed)


if __name__ == "__main__":
    unittest.main()
