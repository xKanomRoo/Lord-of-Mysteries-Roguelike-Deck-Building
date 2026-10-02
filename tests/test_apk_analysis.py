"""All archives below are synthetic fixtures, not Chaos Zero Nightmare evidence."""

import hashlib
import io
import json
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools.analyze_apk import Analyzer, Limits, main, markdown_summary
from tools.join_chunks import join_chunks


def make_zip(entries, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


class StaticAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="synthetic-apk-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def analyze(self, entries, *, limits=None, extract=False, compression=zipfile.ZIP_STORED):
        path = self.root / "synthetic.xapk"
        path.write_bytes(make_zip(entries, compression))
        output = self.root / "output"
        output.mkdir(exist_ok=True)
        analyzer = Analyzer(limits=limits, output=output, extract_text=extract)
        return analyzer.analyze(path), output

    def test_nested_apk_manifest_hash_and_engine_evidence(self):
        nested = make_zip([
            ("lib/arm64-v8a/libunity.so", b"synthetic library placeholder"),
            ("assets/config/cards.json", b'{"cards":[{"id":"synthetic_card"}]}'),
        ])
        manifest = b'{"package_name":"synthetic.example", "version_name":"test"}'
        report, _ = self.analyze([("manifest.json", manifest), ("base.apk", nested)])
        self.assertEqual(len(report["archives"]), 2)
        self.assertEqual(report["archives"][1]["sha256"], hashlib.sha256(nested).hexdigest())
        self.assertEqual(report["engine_hints"], [{
            "engine": "Unity", "basis": "file_path_hint",
            "evidence_path": "synthetic.xapk!base.apk!lib/arm64-v8a/libunity.so",
        }])
        cards = next(entry for entry in report["entries"] if entry["path"].endswith("cards.json"))
        self.assertEqual(cards["text_analysis"]["top_level_keys"], ["cards"])
        self.assertEqual(cards["sha256"], hashlib.sha256(b'{"cards":[{"id":"synthetic_card"}]}').hexdigest())
        self.assertEqual(report["errors"], [])

    def test_nested_apks_use_platform_temp_directory_when_posix_tmp_is_absent(self):
        nested = make_zip([("lib/arm64-v8a/libunity.so", b"synthetic library")])
        platform_temp = self.root / "platform-temp"
        platform_temp.mkdir()
        real_temporary_file = tempfile.TemporaryFile

        def windows_like_tempfile(*args, **kwargs):
            if kwargs.get("dir") == "/tmp":
                raise FileNotFoundError("Synthetic Windows: POSIX /tmp does not exist")
            return real_temporary_file(*args, **kwargs)

        with patch("tempfile.tempdir", str(platform_temp)), patch(
                "tools.analyze_apk.tempfile.TemporaryFile", side_effect=windows_like_tempfile):
            report, _ = self.analyze([("base.apk", nested), ("config.arm64_v8a.apk", nested)])
        self.assertEqual(len(report["archives"]), 3)
        self.assertEqual(len(report["engine_hints"]), 2)
        self.assertEqual(report["errors"], [])

    def test_cli_reports_nested_io_failure_and_continues_outer_inventory(self):
        archive = self.root / "synthetic.xapk"
        nested = make_zip([("config.json", b"{}")])
        archive.write_bytes(make_zip([
            ("base.apk", nested),
            ("manifest.json", b'{"package_name":"synthetic.example"}'),
        ]))
        output = self.root / "failed-nested-report"
        with patch("tools.analyze_apk.tempfile.TemporaryFile", side_effect=FileNotFoundError(
                "synthetic private temp path")), redirect_stdout(io.StringIO()):
            result = main([str(archive), "--output", str(output)])
        self.assertEqual(result, 1)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["analysis_status"], "incomplete")
        self.assertEqual(report["entries"][0]["reason"], "nested_read_failed")
        self.assertEqual(report["entries"][1]["status"], "inspected_text")
        self.assertEqual(report["errors"][0]["error_type"], "FileNotFoundError")
        self.assertIn("incomplete", (output / "summary.md").read_text())
        self.assertNotIn("synthetic private temp path", json.dumps(report))

    def test_cli_limit_skips_are_explicit_without_becoming_io_failures(self):
        archive = self.root / "synthetic.xapk"
        archive.write_bytes(make_zip([("base.apk", b"x" * (1024 * 1024 + 1))]))
        output = self.root / "limited-report"
        with redirect_stdout(io.StringIO()):
            result = main([str(archive), "--output", str(output), "--max-nested-mib", "1"])
        self.assertEqual(result, 0)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["analysis_status"], "completed_with_skips")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["entries"][0]["reason"], "member_size_limit")

    def test_windows_default_output_stays_under_working_directory(self):
        archive = self.root / "synthetic.apk"
        archive.write_bytes(make_zip([("config.json", b"{}")]))
        with patch("tools.analyze_apk.sys.platform", "win32"), patch(
                "tools.analyze_apk.Path.cwd", return_value=self.root), redirect_stdout(io.StringIO()):
            result = main([str(archive)])
        self.assertEqual(result, 0)
        reports = list((self.root / ".local" / "game-research").glob("*/report.json"))
        self.assertEqual(len(reports), 1)
        self.assertEqual(json.loads(reports[0].read_text())["analysis_status"], "completed")

    def test_cli_text_read_failure_is_incomplete_and_sanitized(self):
        archive = self.root / "synthetic.apk"
        archive.write_bytes(make_zip([("config.json", b"{}")]))
        output = self.root / "failed-text-report"
        with patch.object(Analyzer, "_read", side_effect=OSError("synthetic private path")), \
                redirect_stdout(io.StringIO()):
            result = main([str(archive), "--output", str(output)])
        self.assertEqual(result, 1)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["analysis_status"], "incomplete")
        self.assertEqual(report["errors"][0]["reason"], "text_read_failed")
        self.assertNotIn("synthetic private path", json.dumps(report))

    def test_godot_unreal_hints_and_no_filename_screen_inference(self):
        report, output = self.analyze([
            ("lib/arm64-v8a/libgodot_android.so", b"fixture"),
            ("lib/arm64-v8a/libUnreal.so", b"fixture"),
            ("assets/shop_screen.png", b"not a real image"),
        ])
        self.assertEqual({hint["engine"] for hint in report["engine_hints"]}, {"Godot", "Unreal"})
        art = report["entries"][-1]
        self.assertEqual(art["status"], "inventory_only")
        self.assertNotIn("sha256", art)
        self.assertEqual(list(output.iterdir()), [])
        self.assertIn("Filenames do not establish a screen layout", markdown_summary(report))

    def test_traversal_absolute_windows_control_and_symlink_paths_not_read(self):
        link = zipfile.ZipInfo("assets/link.txt")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        report, output = self.analyze([
            ("../escape.json", b"{}"), ("/absolute.txt", b"fixture"),
            ("C:/drive.txt", b"fixture"), ("assets\\escape.txt", b"fixture"),
            ("line\nbreak.txt", b"fixture"), (link, b"../outside"),
        ], extract=True)
        reasons = {entry["reason"] for entry in report["entries"]}
        self.assertEqual(reasons, {"unsafe_parent_traversal", "unsafe_absolute_path",
                                   "unsafe_backslash_path", "unsafe_control_character", "unsafe_symlink"})
        self.assertEqual(report["read_bytes"], 0)
        self.assertEqual(list(output.iterdir()), [])
        self.assertFalse((self.root / "escape.json").exists())

    def test_member_and_cumulative_read_limits_are_explicit(self):
        report, _ = self.analyze([
            ("oversize.txt", b"a" * 12), ("first.txt", b"a" * 8),
            ("second.txt", b"b" * 8),
        ], limits=Limits(max_text_bytes=10, max_total_read_bytes=12))
        self.assertEqual(report["entries"][0]["reason"], "member_size_limit")
        self.assertEqual(report["entries"][1]["status"], "inspected_text")
        self.assertEqual(report["entries"][2]["reason"], "cumulative_read_limit")
        self.assertEqual(report["read_bytes"], 8)

    def test_compression_bomb_skipped_before_decompression(self):
        report, _ = self.analyze([("bomb.txt", b"0" * 100_000)],
                                 compression=zipfile.ZIP_DEFLATED,
                                 limits=Limits(max_compression_ratio=10))
        self.assertEqual(report["entries"][0]["reason"], "compression_ratio_limit")
        self.assertEqual(report["read_bytes"], 0)

    def test_nested_size_depth_and_total_entry_limits(self):
        nested = make_zip([("project.godot", b"fixture"), ("second.txt", b"fixture")])
        report, _ = self.analyze([("base.apk", nested)], limits=Limits(max_nested_bytes=1))
        self.assertEqual(report["entries"][0]["reason"], "member_size_limit")
        report, _ = self.analyze([("base.apk", nested)], limits=Limits(max_depth=0))
        self.assertEqual(report["entries"][0]["reason"], "nesting_depth_limit")
        report, _ = self.analyze([("base.apk", nested), ("outer.txt", b"x")],
                                 limits=Limits(max_entries=3))
        self.assertEqual(report["archives"][1]["reason"], "entry_count_limit")
        self.assertEqual(len(report["entries"]), 2)

    def test_binary_android_manifest_is_not_reported_as_decoded_layout(self):
        report, _ = self.analyze([
            ("AndroidManifest.xml", b"\x03\x00\x08\x00binary fixture"),
            ("resources.arsc", b"binary fixture"),
        ], extract=True)
        self.assertEqual(report["entries"][0]["text_analysis"]["status"], "binary_or_encoded")
        self.assertNotIn("extracted_text", report["entries"][0])
        self.assertEqual(report["entries"][1]["reason"], "decoder_required")

    def test_default_inventory_does_not_extract_text_or_values(self):
        report, output = self.analyze([("config.json", b'{"story":"synthetic private content"}')])
        self.assertEqual(list(output.iterdir()), [])
        self.assertNotIn("synthetic private content", json.dumps(report))

    def test_opt_in_extraction_redacts_json_xml_csv_and_skips_key_files(self):
        report, output = self.analyze([
            (".env", b"TOKEN=fixture-do-not-extract"),
            ("assets/signing.key", b"fixture-do-not-extract"),
            ("config.json", b'{"api_key":"fixture-secret-A", "nested":{"password":"fixture-secret-B"}, "cards":3}'),
            ("strings.xml", b'<resources><string name="api_key">fixture-secret-C</string></resources>'),
            ("accounts.csv", b"name,access_token\nfixture,fixture-secret-D\n"),
            ("public.txt", b"Authorization: Bearer fixture-secret-E"),
        ], extract=True)
        for entry in report["entries"][:2]:
            self.assertEqual(entry["reason"], "credential_or_key_filename")
        for entry in report["entries"][2:]:
            extracted = (output / entry["extracted_text"]).read_text()
            self.assertNotIn("fixture-secret-", extracted)
            self.assertIn("[REDACTED]", extracted)
        self.assertNotIn("fixture-secret-", json.dumps(report))

    def test_xml_entities_are_not_parsed_or_extracted(self):
        report, output = self.analyze([("entities.xml", b'<!DOCTYPE x [<!ENTITY x "fixture">]><x>&x;</x>')], extract=True)
        self.assertEqual(report["entries"][0]["text_analysis"]["parse_status"], "dtd_or_entity_declaration_not_parsed")
        self.assertEqual(list(output.iterdir()), [])

    def test_invalid_nested_archive_does_not_drop_other_entries(self):
        report, _ = self.analyze([("invalid.apk", b"not ZIP"), ("valid.json", b"{}")])
        self.assertTrue(report["errors"])
        self.assertEqual(report["entries"][0]["reason"], "nested_archive_invalid_or_limited")
        self.assertEqual(report["entries"][1]["status"], "inspected_text")

    def test_cli_creates_reports_and_preserves_existing_output(self):
        archive = self.root / "synthetic.apk"
        archive.write_bytes(make_zip([("config.json", b"{}")]))
        output = self.root / "cli-report"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(archive), "--output", str(output)]), 0)
        self.assertTrue((output / "report.json").is_file())
        self.assertTrue((output / "summary.md").is_file())
        before = (output / "report.json").read_bytes()
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            main([str(archive), "--output", str(output)])
        self.assertEqual((output / "report.json").read_bytes(), before)


class ChunkReassemblyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="synthetic-chunk-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.parts = [self.root / "game.part0000", self.root / "game.part0001"]
        self.parts[0].write_bytes(b"synthetic-archive-")
        self.parts[1].write_bytes(b"second-half")
        self.expected = hashlib.sha256(b"synthetic-archive-second-half").hexdigest()
        self.output = self.root / "game.xapk"

    def test_reassembly_requires_and_verifies_original_hash(self):
        self.assertEqual(join_chunks(self.parts, self.output, self.expected), self.expected)
        self.assertEqual(self.output.read_bytes(), b"synthetic-archive-second-half")
        self.assertFalse(self.output.with_suffix(".xapk.partial").exists())

    def test_reordered_chunks_fail_without_publishing_an_archive(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            join_chunks(list(reversed(self.parts)), self.output, self.expected)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".xapk.partial").exists())

    def test_existing_output_or_partial_and_duplicate_parts_preserved(self):
        self.output.write_bytes(b"user-original")
        with self.assertRaises(FileExistsError):
            join_chunks(self.parts, self.output, self.expected)
        self.assertEqual(self.output.read_bytes(), b"user-original")
        self.output.unlink()
        partial = self.output.with_suffix(".xapk.partial")
        partial.write_bytes(b"user-partial")
        with self.assertRaises(FileExistsError):
            join_chunks(self.parts, self.output, self.expected)
        self.assertEqual(partial.read_bytes(), b"user-partial")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            join_chunks([self.parts[0], self.parts[0]], self.output, self.expected)


if __name__ == "__main__":
    unittest.main()
