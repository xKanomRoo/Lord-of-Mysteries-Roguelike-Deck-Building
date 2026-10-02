import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.read_research_pack import PackReadError, read_pack, unpack_pack


class PackReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "pack.zip"
        self.data = b"synthetic scene bytes"
        self.stored = "files/" + "a" * 64 + ".csb"
        self.index = {
            "schema_version": 1, "pack_type": "bounded_static_bootstrap_research",
            "input": {"sha256": "b" * 64}, "report_sha256": "c" * 64,
            "nested_apk": {"sha256": "d" * 64}, "selected_count": 1,
            "selected_bytes": len(self.data),
            "files": [{"stored_path": self.stored, "original_path": "assets/pre/ui/scene.csb",
                       "evidence_path": "synthetic.xapk!base.apk!assets/pre/ui/scene.csb",
                       "stored_bytes": len(self.data), "original_bytes": len(self.data),
                       "stored_sha256": hashlib.sha256(self.data).hexdigest(),
                       "original_sha256": hashlib.sha256(self.data).hexdigest(),
                       "transformation": "unchanged_static_binary"}],
        }

    def write(self, extra=None):
        with zipfile.ZipFile(self.path, "w") as z:
            z.writestr("pack-index.json", json.dumps(self.index))
            z.writestr(self.stored, self.data)
            if extra: z.writestr(*extra)

    def test_verified_pack_writes_only_hashed_members_and_provenance(self):
        self.write()
        output = self.root / "output"
        result = unpack_pack(self.path, output, "b" * 64)
        self.assertEqual(result["verified_file_count"], 1)
        self.assertEqual((output / self.stored).read_bytes(), self.data)
        self.assertEqual(json.loads((output / "verification.json").read_text()), result)

    def test_corrupt_content_fails_before_any_output(self):
        self.index["files"][0]["stored_sha256"] = "f" * 64
        self.write()
        output = self.root / "output"
        with self.assertRaisesRegex(PackReadError, "SHA-256 mismatch"):
            unpack_pack(self.path, output)
        self.assertFalse(output.exists())

    def test_traversal_or_unindexed_member_is_rejected(self):
        for name in ["../outside.py", "files/" + "e" * 64 + ".txt"]:
            with self.subTest(name=name):
                self.write((name, b"do not execute"))
                with self.assertRaises(PackReadError): read_pack(self.path)

    def test_source_and_unchanged_hash_must_match(self):
        self.write()
        with self.assertRaisesRegex(PackReadError, "Source identity"):
            read_pack(self.path, "e" * 64)
        self.index["files"][0]["original_sha256"] = "e" * 64
        self.write()
        with self.assertRaisesRegex(PackReadError, "Unchanged"):
            read_pack(self.path)

    def test_duplicate_indexed_files_and_byte_counts_are_rejected(self):
        self.index["files"].append(dict(self.index["files"][0]))
        self.index["selected_count"] = 2
        self.write()
        with self.assertRaisesRegex(PackReadError, "Duplicate"):
            read_pack(self.path)
        self.index["files"].pop()
        self.index["selected_count"] = 1
        self.index["selected_bytes"] += 1
        self.write()
        with self.assertRaisesRegex(PackReadError, "Selected byte"):
            read_pack(self.path)

    def test_existing_research_is_preserved(self):
        self.write()
        output = self.root / "output"
        output.mkdir()
        keep = output / "keep.txt"
        keep.write_text("user work")
        with self.assertRaisesRegex(PackReadError, "preserved"):
            unpack_pack(self.path, output)
        self.assertEqual(keep.read_text(), "user work")

    def test_invalid_original_path_is_rejected_before_output(self):
        for value in (None, 42, [], "", "invalid\x00name"):
            with self.subTest(value=value):
                self.index["files"][0]["original_path"] = value
                self.write()
                output = self.root / "output"
                with self.assertRaisesRegex(PackReadError, "original path"):
                    unpack_pack(self.path, output)
                self.assertFalse(output.exists())


if __name__ == "__main__": unittest.main()
