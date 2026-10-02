"""Synthetic APKs only; no reference game payload is stored in these tests."""

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.analyze_apk import Analyzer
from tools.create_research_pack import Limits, PackError
from tools.extract_nested_apk import DEFAULT_ENTRY, extract_nested_apk


def archive_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


class NestedAPKExtractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="synthetic-nested-apk-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.input = self.root / "synthetic.xapk"
        self.report_path = self.root / "report.json"
        self.output = self.root / "research" / DEFAULT_ENTRY
        self.native_bytes = archive_bytes([
            ("AndroidManifest.xml", b"synthetic split manifest"),
            ("lib/arm64-v8a/libsynthetic.so", b"synthetic native bytes"),
        ])
        self.input.write_bytes(archive_bytes([
            (DEFAULT_ENTRY, self.native_bytes),
            ("config.en.apk", archive_bytes([("AndroidManifest.xml", b"synthetic locale manifest")])),
            ("manifest.json", b'{"package_name":"synthetic"}'),
        ]))
        self.report = Analyzer().analyze(self.input)
        self.write_report()

    def write_report(self):
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")

    def selected_report_entry(self):
        return next(entry for entry in self.report["entries"]
                    if entry["container"] == "synthetic.xapk" and entry["path"] == DEFAULT_ENTRY)

    def assert_no_published_or_partial_file(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob("nested-apk-*.partial")), [])

    def test_exact_bytes_hash_and_report_lineage(self):
        result = extract_nested_apk(self.input, self.report_path, self.output)
        self.assertEqual(self.output.read_bytes(), self.native_bytes)
        self.assertEqual(result["sha256"], hashlib.sha256(self.native_bytes).hexdigest())
        self.assertEqual(result["input"], self.report["input"])
        self.assertEqual(result["report_sha256"], hashlib.sha256(self.report_path.read_bytes()).hexdigest())
        self.assertEqual(result["evidence_path"], "synthetic.xapk!" + DEFAULT_ENTRY)
        self.assertEqual(result["bytes"], len(self.native_bytes))
        self.assertEqual(result["nested_file_count"], 2)
        self.assertTrue(result["static_only"])
        self.assertEqual(list(self.output.parent.glob("nested-apk-*.partial")), [])

    def test_cli_runs_as_script_with_sibling_import(self):
        result = subprocess.run([
            sys.executable, str(Path(__file__).resolve().parents[1] / "tools/extract_nested_apk.py"),
            str(self.input), "--report", str(self.report_path), "--output", str(self.output),
        ], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), self.native_bytes)
        self.assertIn("Static research only", result.stdout)
        self.assertIn("2 nested files", result.stdout)
        self.assertIn(hashlib.sha256(self.native_bytes).hexdigest(), result.stdout)

    def test_tampered_input_and_nested_hashes_fail_before_publication(self):
        self.report["input"]["sha256"] = "0" * 64
        self.write_report()
        with self.assertRaisesRegex(PackError, "Input SHA-256"):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assert_no_published_or_partial_file()
        self.report["input"]["sha256"] = hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.selected_report_entry()["sha256"] = "0" * 64
        self.write_report()
        with self.assertRaisesRegex(PackError, "Nested APK SHA-256"):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assert_no_published_or_partial_file()

    def test_tampered_metadata_and_streaming_crc_fail_before_publication(self):
        selected = self.selected_report_entry()
        original_crc = selected["crc32"]
        selected["crc32"] = "00000000"
        self.write_report()
        with self.assertRaisesRegex(PackError, "metadata disagrees"):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assert_no_published_or_partial_file()
        selected["crc32"] = original_crc
        altered = self.input.read_bytes().replace(b"synthetic native bytes", b"synthetic damage bytes", 1)
        self.assertEqual(len(altered), self.input.stat().st_size)
        self.input.write_bytes(altered)
        self.report["input"]["sha256"] = hashlib.sha256(altered).hexdigest()
        self.write_report()
        with self.assertRaises(zipfile.BadZipFile):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assert_no_published_or_partial_file()

    def test_root_apk_selection_and_completed_report_are_required(self):
        for entry in ("../config.arm64_v8a.apk", "dir/config.arm64_v8a.apk", "manifest.json",
                      "missing.apk", "C:config.apk", "bad\\config.apk", "bad!config.apk"):
            with self.subTest(entry=entry), self.assertRaises(PackError):
                extract_nested_apk(self.input, self.report_path, self.output, entry)
            self.assert_no_published_or_partial_file()
        selected = self.selected_report_entry()
        selected["status"] = "nested_archive_read_failed"
        self.write_report()
        with self.assertRaisesRegex(PackError, "nested_archive"):
            extract_nested_apk(self.input, self.report_path, self.output)
        selected["status"] = "nested_archive"
        del selected["sha256"]
        self.write_report()
        with self.assertRaisesRegex(PackError, "needs a SHA-256"):
            extract_nested_apk(self.input, self.report_path, self.output)
        selected["sha256"] = hashlib.sha256(self.native_bytes).hexdigest()
        self.report["analysis_status"] = "incomplete"
        self.write_report()
        with self.assertRaisesRegex(PackError, "completed"):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assert_no_published_or_partial_file()

    def test_byte_limit_and_fixed_30_mib_upload_cap(self):
        with self.assertRaisesRegex(PackError, "byte limit"):
            extract_nested_apk(self.input, self.report_path, self.output,
                               limits=replace(Limits(), max_nested_bytes=1))
        self.selected_report_entry()["bytes"] = 30 * 1024 * 1024 + 1
        self.write_report()
        with self.assertRaisesRegex(PackError, "30 MiB"):
            extract_nested_apk(self.input, self.report_path, self.output,
                               limits=replace(Limits(), max_nested_bytes=100 * 1024 * 1024,
                                              max_pack_bytes=100 * 1024 * 1024))
        self.assert_no_published_or_partial_file()

    def test_existing_output_symlink_and_user_partial_are_preserved(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b"existing user output")
        partial = self.output.parent / "nested-apk-user.partial"
        partial.write_bytes(b"existing user partial")
        with self.assertRaisesRegex(PackError, "already exists"):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing user output")
        self.assertEqual(partial.read_bytes(), b"existing user partial")
        self.output.unlink()
        try:
            self.output.symlink_to(self.output.parent / "missing-target")
        except (OSError, NotImplementedError):
            return  # Windows without symlink privilege still tests existing-file preservation.
        with self.assertRaisesRegex(PackError, "already exists"):
            extract_nested_apk(self.input, self.report_path, self.output)
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(partial.read_bytes(), b"existing user partial")

    def test_atomic_publish_race_preserves_concurrent_output(self):
        def racing_link(source, destination):
            Path(destination).write_bytes(b"concurrent user output")
            raise FileExistsError("synthetic race")

        with patch("tools.extract_nested_apk.os.link", side_effect=racing_link):
            with self.assertRaisesRegex(PackError, "appeared during extraction"):
                extract_nested_apk(self.input, self.report_path, self.output)
        self.assertEqual(self.output.read_bytes(), b"concurrent user output")
        self.assertEqual(list(self.output.parent.glob("nested-apk-*.partial")), [])

    def test_unsupported_drive_fails_without_output_and_closes_temp_before_link(self):
        real_temporary_file = tempfile.NamedTemporaryFile
        opened_temporaries = []

        def local_temporary_file(*args, **kwargs):
            self.assertEqual(Path(kwargs["dir"]), self.output.parent)
            temporary = real_temporary_file(*args, **kwargs)
            opened_temporaries.append(temporary)
            return temporary

        def unsupported_link(source, destination):
            self.assertTrue(opened_temporaries[0].closed)
            self.assertEqual(Path(source).parent, Path(destination).parent)
            raise OSError("synthetic filesystem without hard links")

        with patch("tools.extract_nested_apk.tempfile.NamedTemporaryFile", side_effect=local_temporary_file), patch(
                "tools.extract_nested_apk.os.link", side_effect=unsupported_link):
            with self.assertRaisesRegex(PackError, "drive supporting hard links"):
                extract_nested_apk(self.input, self.report_path, self.output)
        self.assert_no_published_or_partial_file()


if __name__ == "__main__":
    unittest.main()
