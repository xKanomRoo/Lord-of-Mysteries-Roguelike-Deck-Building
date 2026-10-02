"""Synthetic fixtures only; these tests contain no reference game content."""

import hashlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.analyze_apk import Analyzer
from tools.create_research_pack import Limits, PackError, create_pack


def make_zip(entries, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


class ResearchPackTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="synthetic-research-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.input = self.root / "synthetic.xapk"
        self.report = self.root / "report.json"
        self.output = self.root / "research.zip"

    def fixture(self, extra=(), *, outer_extra=(), nested_compression=zipfile.ZIP_STORED):
        inner = make_zip([
            ("AndroidManifest.xml", b"\x03\x00\x08\x00"),
            ("resources.arsc", b"\x02\x00\x0c\x00"),
            ("assets/pre/bin/arm64/init.jbin", b"\x00synthetic compiled bytes"),
            ("assets/pre/bin/arm/init.jbin", b"excluded duplicate architecture"),
            ("assets/pre/bin/gitsha.txt", b"abcdef"),
            ("assets/info.txt", b"synthetic fixture metadata"),
            ("assets/progress.json", b'{"layers": [], "api_key": "synthetic-secret"}'),
            ("assets/pre/ui/start.csb", b"\x00synthetic layout"),
            ("assets/pre/ui/start.png", b"\x89PNG\r\n\x1a\nsynthetic image"),
            ("assets/pre/Default/Button_Normal.png", b"\x89PNGsynthetic"),
            ("assets/pre/effect/start.atlas", b"synthetic.png\nsize: 1,1"),
            ("assets/sdata/small.bin", b"\x00unknown binary"),
            *[(f"assets/sdata/sample-{number}.bin", b"\x00synthetic sample" + bytes([number]))
              for number in range(6)],
            ("assets/sdata/large.bin", b"x" * 100_001),
            ("assets/pre/ui/secret.png", b"excluded credential-like name"),
            ("assets/pre/ui/font.ttf", b"excluded font"),
            ("assets/sounds/track.bnk", b"excluded audio"),
            ("classes.dex", b"excluded dex"),
            ("lib/arm64-v8a/libengine.so", b"excluded native"),
            *extra,
        ], nested_compression)
        self.input.write_bytes(make_zip([
            ("base.apk", inner), ("manifest.json", b'{"package_name": "synthetic"}'),
            ("icon.png", b"excluded icon"),
            ("config.en.apk", make_zip([("AndroidManifest.xml", b"synthetic split manifest")])),
            *outer_extra,
        ]))
        report = Analyzer().analyze(self.input)
        self.write_report(report)
        return report

    def write_report(self, report):
        self.report.write_text(json.dumps(report), encoding="utf-8")

    def test_pack_selection_lineage_transformed_hashes_and_redaction(self):
        report = self.fixture()
        index = create_pack(self.input, self.report, self.output)
        self.assertEqual(index["input"]["sha256"], report["input"]["sha256"])
        self.assertEqual(index["selected_count"], 18)
        names = {entry["original_path"] for entry in index["files"]}
        self.assertIn("assets/sdata/small.bin", names)
        self.assertEqual(sum(name.startswith("assets/sdata/") for name in names), 7)
        self.assertNotIn("assets/sdata/large.bin", names)
        self.assertNotIn("classes.dex", names)
        self.assertFalse(any(name.startswith("lib/") for name in names))
        self.assertNotIn("assets/pre/bin/arm/init.jbin", names)
        self.assertNotIn("assets/pre/ui/secret.png", names)
        self.assertNotIn("assets/pre/ui/font.ttf", names)
        self.assertNotIn("assets/sounds/track.bnk", names)
        self.assertTrue(any(entry["reason"] == "credential_like_path" for entry in index["skipped"]))
        with zipfile.ZipFile(self.output) as archive:
            stored_index = json.loads(archive.read("pack-index.json"))
            self.assertEqual(stored_index, index)
            self.assertEqual(len(archive.namelist()), index["selected_count"] + 1)
            for entry in index["files"]:
                self.assertRegex(entry["stored_path"], r"^files/[0-9a-f]{64}\.[a-z0-9]+$")
                content = archive.read(entry["stored_path"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry["stored_sha256"])
                self.assertEqual(len(content), entry["stored_bytes"])
                self.assertEqual(entry["sharing_status"], "manual_review_required")
            progress = next(entry for entry in index["files"] if entry["original_path"] == "assets/progress.json")
            self.assertNotEqual(progress["original_sha256"], progress["stored_sha256"])
            safe_json = archive.read(progress["stored_path"])
            self.assertNotIn(b"synthetic-secret", safe_json)
            self.assertEqual(json.loads(safe_json)["api_key"], "[REDACTED]")
            self.assertEqual(next(entry for entry in index["files"] if entry["original_path"].endswith(".jbin"))[
                "content_analysis"]["status"], "binary_static_only")

    def test_cli_runs_as_script_with_sibling_import(self):
        self.fixture()
        result = subprocess.run([
            sys.executable, str(Path(__file__).resolve().parents[1] / "tools/create_research_pack.py"),
            str(self.input), "--report", str(self.report), "--output", str(self.output),
        ], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("18 files", result.stdout)

    def test_missing_report_and_incomplete_report_fail_without_output(self):
        report = self.fixture()
        with self.assertRaises(FileNotFoundError):
            create_pack(self.input, self.root / "missing.json", self.output)
        report["analysis_status"] = "incomplete"
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "completed"):
            create_pack(self.input, self.report, self.output)
        self.assertFalse(self.output.exists())

    def test_tampered_input_hash_is_rejected(self):
        report = self.fixture()
        report["input"]["sha256"] = "0" * 64
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "Input SHA-256"):
            create_pack(self.input, self.report, self.output)
        self.assertFalse(self.output.exists())

    def test_tampered_nested_hash_is_rejected_and_temp_is_cleaned(self):
        report = self.fixture()
        next(entry for entry in report["entries"] if entry["path"] == "base.apk")["sha256"] = "0" * 64
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "Nested APK SHA-256"):
            create_pack(self.input, self.report, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("research-pack-*.partial")), [])

    def test_tampered_selected_hash_or_metadata_is_rejected(self):
        for field, value in (("sha256", "0" * 64), ("bytes", 12345)):
            with self.subTest(field=field):
                report = self.fixture()
                target = next(entry for entry in report["entries"] if entry["path"] == "assets/info.txt")
                target[field] = value
                self.write_report(report)
                with self.assertRaises(PackError):
                    create_pack(self.input, self.report, self.output)
                self.assertFalse(self.output.exists())

    def test_selected_entry_missing_from_report_is_rejected(self):
        report = self.fixture()
        report["entries"] = [entry for entry in report["entries"] if entry["path"] != "assets/info.txt"]
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "missing from report"):
            create_pack(self.input, self.report, self.output)
        self.assertFalse(self.output.exists())

    def test_report_bounds_and_structure_are_checked(self):
        report = self.fixture()
        with self.assertRaisesRegex(PackError, "metadata size"):
            create_pack(self.input, self.report, self.output, replace(Limits(), max_report_bytes=100))
        with self.assertRaisesRegex(PackError, "entry count"):
            create_pack(self.input, self.report, self.output, replace(Limits(), max_entries=1))
        report["entries"][0]["bytes"] = True
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "Invalid byte count"):
            create_pack(self.input, self.report, self.output)
        self.report.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(PackError, "Duplicate report JSON key"):
            create_pack(self.input, self.report, self.output)

    def test_report_paths_cannot_select_local_files(self):
        report = self.fixture()
        entry = report["entries"][0]
        entry["container"] = "../private"
        entry["evidence_path"] = "../private!" + entry["path"]
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "not descended"):
            create_pack(self.input, self.report, self.output)
        self.assertFalse(self.output.exists())

    def test_unsafe_names_and_duplicates_are_rejected(self):
        for name in ("../escape.png", "/absolute.png", "C:/drive.png", "bad\\name.png",
                     "assets//empty.png", "assets/./relative.png", "bad!container.png"):
            with self.subTest(name=name):
                self.fixture(extra=[(name, b"synthetic")])
                with self.assertRaises(PackError):
                    create_pack(self.input, self.report, self.output)
                self.assertFalse(self.output.exists())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.fixture(extra=[("assets/pre/ui/start.png", b"duplicate")])
        with self.assertRaisesRegex(PackError, "Duplicate"):
            create_pack(self.input, self.report, self.output)

    def test_symlink_is_rejected_even_if_outside_allowlist(self):
        link = zipfile.ZipInfo("assets/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.fixture(extra=[(link, b"../../secret")])
        with self.assertRaisesRegex(PackError, "symlink"):
            create_pack(self.input, self.report, self.output)

    def test_oversized_files_and_total_budget_are_skipped_with_reasons(self):
        self.fixture(extra=[("assets/pre/ui/oversized.png", b"x" * 512)])
        index = create_pack(self.input, self.report, self.output,
                            replace(Limits(), max_file_bytes=128, max_selected_bytes=150))
        self.assertLessEqual(index["selected_bytes"], 150)
        reasons = {entry["reason"] for entry in index["skipped"]}
        self.assertIn("per_file_byte_limit", reasons)
        self.assertIn("cumulative_byte_limit", reasons)
        self.assertTrue(all(entry["stored_bytes"] <= 128 for entry in index["files"]))

    def test_oversized_nested_apk_and_final_pack_leave_no_output(self):
        self.fixture()
        with self.assertRaisesRegex(PackError, "Entry exceeds byte limit"):
            create_pack(self.input, self.report, self.output, replace(Limits(), max_nested_bytes=100))
        with self.assertRaisesRegex(PackError, "Final ZIP"):
            create_pack(self.input, self.report, self.output, replace(Limits(), max_pack_bytes=100))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("research-pack-*.partial")), [])

    def test_high_compression_ratio_is_rejected(self):
        report = self.fixture(extra=[("assets/pre/ui/compression.png", b"x" * 100_000)],
                              nested_compression=zipfile.ZIP_DEFLATED)
        report["analysis_status"] = "completed"
        self.write_report(report)
        with self.assertRaisesRegex(PackError, "compression ratio"):
            create_pack(self.input, self.report, self.output)

    def test_crc_damage_is_detected_while_streaming_nested_apk(self):
        report = self.fixture()
        data = self.input.read_bytes().replace(b"synthetic compiled bytes", b"synthetic tampered bytes", 1)
        self.input.write_bytes(data)
        report["input"]["sha256"] = hashlib.sha256(data).hexdigest()
        self.write_report(report)
        with self.assertRaises(zipfile.BadZipFile):
            create_pack(self.input, self.report, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_and_partial_file_are_preserved(self):
        self.fixture()
        self.output.write_bytes(b"user output")
        partial = self.root / "research-pack-user.partial"
        partial.write_bytes(b"user partial")
        with self.assertRaisesRegex(PackError, "already exists"):
            create_pack(self.input, self.report, self.output)
        self.assertEqual(self.output.read_bytes(), b"user output")
        self.assertEqual(partial.read_bytes(), b"user partial")

    def test_atomic_publish_race_preserves_existing_file(self):
        self.fixture()

        def racing_link(source, destination):
            Path(destination).write_bytes(b"concurrent user output")
            raise FileExistsError("synthetic race")

        with patch("tools.create_research_pack.os.link", side_effect=racing_link):
            with self.assertRaisesRegex(PackError, "appeared during creation"):
                create_pack(self.input, self.report, self.output)
        self.assertEqual(self.output.read_bytes(), b"concurrent user output")
        self.assertEqual(list(self.root.glob("research-pack-*.partial")), [])

    def test_platform_temporary_directory_is_used_on_windows(self):
        self.fixture()
        platform_temp = self.root / "platform-temp"
        platform_temp.mkdir()
        real_temporary_file = tempfile.TemporaryFile

        def windows_like_tempfile(*args, **kwargs):
            self.assertNotEqual(kwargs.get("dir"), "/tmp")
            return real_temporary_file(*args, **kwargs)

        with patch("tempfile.tempdir", str(platform_temp)), patch(
                "tools.create_research_pack.tempfile.TemporaryFile", side_effect=windows_like_tempfile):
            create_pack(self.input, self.report, self.output)
        self.assertTrue(self.output.is_file())
        self.assertEqual(list(platform_temp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
