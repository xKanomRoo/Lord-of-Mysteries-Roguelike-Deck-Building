import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
import zipfile

from tools.create_research_pack import PackError
from tools.inspect_native_apk import inspect_elf64, inspect_native_apk


def elf(*, machine=183, elf_class=2):
    ident = b"\x7fELF" + bytes([elf_class, 1, 1]) + bytes(9)
    # One bounded .text-like section follows the fixed ELF64 header.
    header = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, machine, 1,
                         0, 0, 64, 0, 64, 0, 0, 64, 2, 0)
    null_section = bytes(64)
    section = struct.pack("<IIQQQQIIQQ", 0, 1, 6, 0, 192, 4, 0, 0, 4, 0)
    return header + null_section + section + b"TEST"


class NativeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.apk = self.root / "native.apk"
        self.output = self.root / "research"
        self.library = elf()
        self.library_path = "lib/arm64-v8a/libtest.so"

    def write(self, extra=None, library=None):
        with zipfile.ZipFile(self.apk, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.library_path, self.library if library is None else library)
            archive.writestr("assets/ignored.txt", b"not selected")
            if extra:
                archive.writestr(*extra)
        return hashlib.sha256(self.apk.read_bytes()).hexdigest()

    def report(self):
        sha = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        with zipfile.ZipFile(self.apk) as archive:
            library = archive.getinfo(self.library_path)
        outer = "reference.xapk"
        container = outer + "!config.arm64_v8a.apk"
        report = {
            "schema_version": 1, "analysis_type": "static_archive_inventory",
            "analysis_status": "completed",
            "input": {"filename": outer, "sha256": "a" * 64, "bytes": 1024},
            "entries": [
                {"container": outer, "path": "config.arm64_v8a.apk",
                 "evidence_path": container, "status": "nested_archive",
                 "sha256": sha, "bytes": self.apk.stat().st_size,
                 "compressed_bytes": self.apk.stat().st_size, "crc32": "00000000"},
                {"container": container, "path": self.library_path,
                 "evidence_path": container + "!" + self.library_path,
                 "bytes": library.file_size, "compressed_bytes": library.compress_size,
                 "crc32": f"{library.CRC:08x}",
                 "sha256": hashlib.sha256(self.library).hexdigest()},
            ],
        }
        path = self.root / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path, report

    def test_verified_report_provenance_and_nonexecuting_hashed_files(self):
        expected = self.write()
        report_path, report = self.report()
        result = inspect_native_apk(self.apk, self.output, expected, report_path)
        self.assertEqual(result["library_count"], 1)
        self.assertEqual(result["library_bytes"], len(self.library))
        entry = result["files"][0]
        self.assertEqual(entry["evidence_path"], report["entries"][1]["evidence_path"])
        self.assertTrue(entry["report_sha256_verified"])
        stored = self.output / entry["stored_path"]
        self.assertEqual(stored.read_bytes(), self.library)
        self.assertEqual(stored.name, hashlib.sha256(self.library).hexdigest() + ".so")
        self.assertFalse(stored.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        self.assertEqual(entry["elf"]["architecture"], "AArch64")
        self.assertEqual(json.loads((self.output / "native-index.json").read_text()), result)
        self.assertFalse((self.output / "assets").exists())

    def test_wrong_sha_and_report_hash_fail_before_output(self):
        self.write()
        with self.assertRaisesRegex(PackError, "expected identity"):
            inspect_native_apk(self.apk, self.output, "f" * 64)
        self.assertFalse(self.output.exists())
        path, report = self.report()
        report["entries"][0]["sha256"] = "f" * 64
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(PackError, "APK identity"):
            inspect_native_apk(self.apk, self.output, report_path=path)
        self.assertFalse(self.output.exists())

    def test_report_library_metadata_and_hash_are_checked(self):
        self.write()
        path, original = self.report()
        for key, value, message in [("bytes", 999, "metadata disagrees"),
                                    ("sha256", "f" * 64, "SHA-256 disagrees")]:
            with self.subTest(key=key):
                report = json.loads(json.dumps(original))
                report["entries"][1][key] = value
                path.write_text(json.dumps(report))
                with self.assertRaisesRegex(PackError, message):
                    inspect_native_apk(self.apk, self.output, report_path=path)
                self.assertFalse(self.output.exists())
                self.assertFalse(list(self.root.glob("native-inventory-*")))

    def test_elf_machine_class_and_truncation_are_rejected(self):
        for data in [elf(machine=62), elf(elf_class=1), self.library[:30]]:
            with self.subTest(prefix=data[:8]):
                self.write(library=data)
                with self.assertRaises(PackError):
                    inspect_native_apk(self.apk, self.output)
                self.assertFalse(self.output.exists())
                self.assertFalse(list(self.root.glob("native-inventory-*")))

    def test_elf_section_and_program_bounds_are_checked(self):
        bad_section = bytearray(self.library)
        struct.pack_into("<Q", bad_section, 128 + 24, len(self.library) + 1)
        with self.assertRaisesRegex(PackError, "section 1"):
            inspect_elf64(bytes(bad_section))
        bad_program = bytearray(self.library)
        struct.pack_into("<Q", bad_program, 32, 64)  # e_phoff
        struct.pack_into("<HH", bad_program, 54, 56, 1)
        struct.pack_into("<IIQQQQQQ", bad_program, 64, 1, 5, 192, 0, 0, 5, 5, 1)
        with self.assertRaisesRegex(PackError, "program 0"):
            inspect_elf64(bytes(bad_program))
        self.assertEqual(inspect_elf64(io.BytesIO(self.library))["section_header_count"], 2)

    def test_zip_traversal_and_symlink_are_rejected(self):
        link = zipfile.ZipInfo("lib/arm64-v8a/link.so")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in [("../outside.txt", b"never extracted"), (link, b"target.so")]:
            with self.subTest(extra=extra[0]):
                self.write(extra)
                with self.assertRaises(PackError):
                    inspect_native_apk(self.apk, self.output)
                self.assertFalse(self.output.exists())

    def test_existing_research_is_preserved_and_empty_directory_is_allowed(self):
        self.write()
        self.output.mkdir()
        keep = self.output / "user.txt"
        keep.write_text("keep")
        with self.assertRaisesRegex(PackError, "preserved"):
            inspect_native_apk(self.apk, self.output)
        self.assertEqual(keep.read_text(), "keep")
        keep.unlink()
        result = inspect_native_apk(self.apk, self.output)
        self.assertEqual(result["library_count"], 1)


if __name__ == "__main__":
    unittest.main()
