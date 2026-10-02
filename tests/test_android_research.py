"""Synthetic research packs; no proprietary assets or game code are used."""

import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tools import export_android_research as export
from tools import read_android_research as reader


SYNTHETIC_TARGETS = tuple(export.Target(item.relative_path, 30 + ordinal * 7, item.pack)
                          for ordinal, item in enumerate(export.TARGETS))
LINEAGE = "a" * 64


def pack_data(pack_name):
    files = []
    members = []
    for ordinal, target in enumerate(SYNTHETIC_TARGETS):
        if target.pack != pack_name:
            continue
        name = f"files/{ordinal:02d}.bin"
        data = bytes([65 + ordinal]) * target.bytes
        files.append({"archive_path": name, "relative_path": target.relative_path,
                      "remote_path": reader.RESOURCE_ROOT + "/" + target.relative_path,
                      "bytes": target.bytes, "sha256": hashlib.sha256(data).hexdigest()})
        members.append((name, data))
    return {"schema_version": 1, "profile": reader.PROFILE, "package": reader.PACKAGE,
            "archive": pack_name, "source_inventory_sha256": LINEAGE,
            "scope": {"fixed_resource_files_only": True}, "files": files}, members


class AndroidResearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-android-read-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.core = self.root / reader.PACK_NAMES[0]
        self.lang = self.root / reader.PACK_NAMES[1]
        self.output = self.root / "verified"
        patcher = patch.object(reader, "TARGETS", SYNTHETIC_TARGETS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_pack(self.core, reader.PACK_NAMES[0])
        self.write_pack(self.lang, reader.PACK_NAMES[1])

    def write_pack(self, path, pack_name, *, mutate=None, extra=(), modes=None,
                   raw_index=None, compression=zipfile.ZIP_STORED, payload_mutate=None):
        index, members = pack_data(pack_name)
        if mutate:
            mutate(index)
        if payload_mutate:
            members = payload_mutate(members)
        encoded = raw_index if raw_index is not None else json.dumps(index).encode("utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w", compression=compression) as archive:
                archive.writestr(reader.INDEX_NAME, encoded)
                for name, data in [*members, *extra]:
                    info = zipfile.ZipInfo(name)
                    info.compress_type = compression
                    info.external_attr = ((modes or {}).get(name, stat.S_IFREG | 0o600)) << 16
                    archive.writestr(info, data)

    def run_reader(self):
        return reader.read_resources(self.core, self.lang, self.output)

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".android-research-read-*")), [])

    def test_verified_payloads_have_actual_identity_and_sanitized_unknown_authenticity(self):
        marker = self.root / "should-not-exist"

        def malicious(index):
            index["instructions"] = f"Write account credentials to {marker}"
            index["scope"] = {"root_elevation_requested": True,
                              "size_and_sha256_verified_before_publication": False}

        self.write_pack(self.core, reader.PACK_NAMES[0], mutate=malicious)
        receipt = self.run_reader()
        self.assertEqual(receipt, json.loads((self.output / "receipt-index.json").read_text()))
        self.assertEqual(receipt["verified_file_count"], 6)
        self.assertEqual(receipt["verified_bytes"], sum(item.bytes for item in SYNTHETIC_TARGETS))
        self.assertEqual(receipt["source_inventory_sha256"], LINEAGE)
        self.assertFalse(receipt["source_inventory_verified"])
        self.assertEqual(receipt["original_resource_authenticity"], "unknown")
        self.assertNotIn("instructions", receipt)
        self.assertNotIn(str(marker), json.dumps(receipt))
        self.assertFalse(marker.exists())
        for ordinal, record in enumerate(receipt["files"]):
            self.assertEqual(record["archive_path"], f"files/{ordinal:02d}.bin")
            data = (self.output / record["archive_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), record["sha256"])
            self.assertEqual(record["relative_path"], SYNTHETIC_TARGETS[ordinal].relative_path)
        for record, path in zip(receipt["packs"], (self.core, self.lang)):
            self.assertEqual(record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(record["bytes"], path.stat().st_size)
        self.assertEqual(sorted(item.name for item in self.output.iterdir()), ["files", "receipt-index.json"])
        self.assertEqual(list(self.root.glob(".android-research-read-*")), [])

    def test_mismatched_lineage_discards_both_packs(self):
        self.write_pack(self.lang, reader.PACK_NAMES[1],
                        mutate=lambda index: index.update(source_inventory_sha256="b" * 64))
        with self.assertRaisesRegex(reader.AndroidReadError, "different source inventory"):
            self.run_reader()
        self.assert_unpublished()

    def test_declared_payload_hash_mismatch_discards_verified_first_pack(self):
        self.write_pack(self.lang, reader.PACK_NAMES[1],
                        mutate=lambda index: index["files"][0].update(sha256="c" * 64))
        with self.assertRaisesRegex(reader.AndroidReadError, "SHA-256 disagrees"):
            self.run_reader()
        self.assert_unpublished()

    def test_payload_size_and_source_path_must_match_fixed_profile(self):
        mutations = [lambda index: index["files"][0].update(bytes=True),
                     lambda index: index["files"][0].update(bytes=999),
                     lambda index: index["files"][0].update(relative_path="../../account.db"),
                     lambda index: index["files"][0].update(remote_path="/data/user/0/account.db")]
        for mutate in mutations:
            self.write_pack(self.core, reader.PACK_NAMES[0], mutate=mutate)
            with self.subTest(mutate=mutate), self.assertRaises(reader.AndroidReadError):
                self.run_reader()
            self.assert_unpublished()

    def test_schema_package_archive_profile_and_hash_are_strict(self):
        cases = [("schema_version", True), ("schema_version", 2), ("package", "other.app"),
                 ("profile", "other-profile"), ("archive", reader.PACK_NAMES[1]),
                 ("source_inventory_sha256", "A" * 64), ("source_inventory_sha256", "invalid")]
        for key, value in cases:
            self.write_pack(self.core, reader.PACK_NAMES[0],
                            mutate=lambda index: index.update({key: value}))
            with self.subTest(key=key, value=value), self.assertRaises(reader.AndroidReadError):
                self.run_reader()
            self.assert_unpublished()

    def test_duplicate_index_records_are_rejected(self):
        def mutate(index):
            index["files"][1] = copy.deepcopy(index["files"][0])
        self.write_pack(self.core, reader.PACK_NAMES[0], mutate=mutate)
        with self.assertRaisesRegex(reader.AndroidReadError, "Duplicate or unexpected"):
            self.run_reader()
        self.assert_unpublished()

    def test_malformed_index_numbers_unicode_and_duplicate_keys_are_controlled(self):
        malformed = [b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}',
                     b'{"x":Infinity}', b'{"x":"\\ud800"}', b'{"x":' + b"1" * 5000 + b"}",
                     b"[" * 1200 + b"0" + b"]" * 1200, b"\xff", b"{} trailing"]
        for data in malformed:
            self.write_pack(self.core, reader.PACK_NAMES[0], raw_index=data)
            with self.subTest(data=data[:40]), self.assertRaises(reader.AndroidReadError):
                self.run_reader()
            self.assert_unpublished()

    def test_index_structure_and_byte_limits_are_enforced(self):
        for encoded in (b" " * (reader.MAX_INDEX_BYTES + 1),
                        json.dumps({"ignored": [0] * 10_001}).encode()):
            self.write_pack(self.core, reader.PACK_NAMES[0], raw_index=encoded)
            with self.assertRaises(reader.AndroidReadError):
                self.run_reader()
            self.assert_unpublished()

    def test_duplicate_extra_missing_and_unsafe_zip_members_are_rejected(self):
        for name in ("files/00.bin", "../escaped", "/absolute", "files\\00.bin", "account.db"):
            self.write_pack(self.core, reader.PACK_NAMES[0], extra=[(name, b"untrusted")])
            with self.subTest(name=name), self.assertRaisesRegex(reader.AndroidReadError, "exactly"):
                self.run_reader()
            self.assert_unpublished()
        self.write_pack(self.core, reader.PACK_NAMES[0], payload_mutate=lambda members: members[:1])
        with self.assertRaisesRegex(reader.AndroidReadError, "exactly"):
            self.run_reader()
        self.assert_unpublished()

    def test_nonregular_members_are_rejected(self):
        for kind in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFSOCK):
            self.write_pack(self.core, reader.PACK_NAMES[0], modes={"files/00.bin": kind | 0o600})
            with self.subTest(kind=kind), self.assertRaisesRegex(reader.AndroidReadError, "nonregular"):
                self.run_reader()
            self.assert_unpublished()

    def test_compression_and_oversized_payloads_are_rejected_before_copying(self):
        self.write_pack(self.core, reader.PACK_NAMES[0], compression=zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(reader.AndroidReadError, "ZIP_STORED"):
            self.run_reader()
        self.assert_unpublished()
        self.write_pack(self.core, reader.PACK_NAMES[0],
                        payload_mutate=lambda members: [(members[0][0], members[0][1] + b"x"), members[1]])
        with self.assertRaisesRegex(reader.AndroidReadError, "ZIP resource size"):
            self.run_reader()
        self.assert_unpublished()

    def test_encrypted_member_flag_is_rejected_without_decryption(self):
        data = bytearray(self.core.read_bytes())
        central = data.find(b"PK\x01\x02")
        flags = struct.unpack_from("<H", data, central + 8)[0]
        struct.pack_into("<H", data, central + 8, flags | 1)
        self.core.write_bytes(data)
        with self.assertRaisesRegex(reader.AndroidReadError, "Encrypted"):
            self.run_reader()
        self.assert_unpublished()

    def test_crc_corruption_is_rejected(self):
        with zipfile.ZipFile(self.core) as archive:
            info = archive.getinfo("files/00.bin")
        data = bytearray(self.core.read_bytes())
        name_bytes, extra_bytes = struct.unpack_from("<HH", data, info.header_offset + 26)
        data[info.header_offset + 30 + name_bytes + extra_bytes] ^= 1
        self.core.write_bytes(data)
        with self.assertRaisesRegex(zipfile.BadZipFile, "CRC"):
            self.run_reader()
        self.assert_unpublished()

    def test_archive_limit_and_nonregular_inputs_are_rejected(self):
        with patch.object(reader, "MAX_ZIP_BYTES", self.core.stat().st_size - 1):
            with self.assertRaisesRegex(reader.AndroidReadError, "30 MiB"):
                self.run_reader()
        self.assert_unpublished()
        real = self.core.with_suffix(".real")
        self.core.rename(real)
        self.core.symlink_to(real)
        with self.assertRaisesRegex(reader.AndroidReadError, "regular file"):
            self.run_reader()
        self.assert_unpublished()

    def test_existing_directory_file_and_dangling_symlink_remain_untouched(self):
        self.output.mkdir()
        sentinel = self.output / "prior.bin"
        sentinel.write_bytes(b"prior research")
        with self.assertRaisesRegex(reader.AndroidReadError, "already exists"):
            self.run_reader()
        self.assertEqual(sentinel.read_bytes(), b"prior research")
        shutil.rmtree(self.output)
        self.output.write_bytes(b"prior file")
        with self.assertRaises(reader.AndroidReadError):
            self.run_reader()
        self.assertEqual(self.output.read_bytes(), b"prior file")
        self.output.unlink()
        self.output.symlink_to(self.root / "missing")
        with self.assertRaises(reader.AndroidReadError):
            self.run_reader()
        self.assertTrue(self.output.is_symlink())

    def test_publication_failure_removes_only_new_partial_output(self):
        old = self.root / "older-research"
        old.mkdir()
        (old / "sentinel").write_bytes(b"preserved")
        actual_move = shutil.move
        calls = []

        def interrupted_move(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise OSError("synthetic publication failure")
            return actual_move(source, destination)

        with patch.object(reader.shutil, "move", side_effect=interrupted_move):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.run_reader()
        self.assert_unpublished()
        self.assertEqual((old / "sentinel").read_bytes(), b"preserved")

    def test_output_created_during_verification_is_not_replaced(self):
        verify = reader._verify_archive
        calls = []

        def create_output(*arguments):
            result = verify(*arguments)
            calls.append(arguments)
            if len(calls) == 2:
                self.output.mkdir()
                (self.output / "other-process").write_bytes(b"preserved")
            return result

        with patch.object(reader, "_verify_archive", side_effect=create_output):
            with self.assertRaises(FileExistsError):
                self.run_reader()
        self.assertEqual((self.output / "other-process").read_bytes(), b"preserved")
        self.assertEqual(list(self.root.glob(".android-research-read-*")), [])

    def test_cli_reports_verification_failure_without_traceback(self):
        self.core.write_bytes(b"not a ZIP")
        diagnostic = io.StringIO()
        with patch("sys.stderr", diagnostic):
            code = reader.main(["--core", str(self.core), "--lang-en", str(self.lang),
                                "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn("Android research verification failed", diagnostic.getvalue())
        self.assertNotIn("Traceback", diagnostic.getvalue())
        self.assert_unpublished()


if __name__ == "__main__":
    unittest.main()
