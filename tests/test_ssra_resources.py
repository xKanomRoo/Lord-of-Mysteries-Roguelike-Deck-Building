"""Small independent SSRA layouts and inert resources; no game is executed."""

import builtins
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import export_android_research as exporter
from tools import extract_ssra_resources as extractor
from tools import read_ssra_manifest as ssra

try:
    import zstandard
except ImportError:
    zstandard = None


MAIN_PATH = "bin/arm64/main.jbin"
TEXT_PATH = "text/en/text.db"
MAIN_DATA = b"Inert compiled reference: never execute."
TEXT_DATA = b"Attack card\nDefend card\nBattle result\n"


def fixture(*, stored_text=TEXT_DATA, decoded_text=TEXT_DATA, compression=0,
            encryption=0, tombstone=0, filename_override=None, fhsh=None):
    """SSRA with text crossing two chunks and five supplied fixed filenames."""
    logical = [MAIN_DATA, b"PREFIX" + stored_text[:5], stored_text[5:] + b"TRAILER",
               b"unused third language chunk", b"unused fourth language chunk"]
    groups = [9, 2, 2, 2, 2]
    indices = [0, 0, 1, 2, 3]
    names = [Path(item.relative_path).name for item in exporter.TARGETS[1:]]
    if filename_override:
        names[1] = filename_override
    offsets, blob = [], bytearray()
    for name in [*names, MAIN_PATH, TEXT_PATH]:
        offsets.append(len(blob))
        blob.extend(name.encode() + b"\0")
    chunks, physical = bytearray(), []
    for index, group, raw in zip(indices, groups, logical):
        checksum = ssra.xxh64(raw)
        physical.append(raw + struct.pack("<4sIQ", b"SSRC", index, checksum))
        chunks.extend(struct.pack("<IHHQQQ", index, group, 1, len(raw), len(raw) + 16, checksum))
    files = struct.pack("<QQ4IBBHB3s", ssra.xxh64(MAIN_PATH.encode()), 0, len(MAIN_DATA),
                        len(MAIN_DATA), 0, offsets[5], 0, 0, 9, 0, bytes(3))
    files += struct.pack("<QQ4IBBHB3s", ssra.xxh64(TEXT_PATH.encode()), 6, len(stored_text),
                         len(decoded_text), 0, offsets[6], compression, encryption, 2, tombstone, bytes(3))
    path_offset = 64 + len(chunks) + len(files)
    header = struct.pack("<4s5I4Q2I", b"SSRA", 4, 0, 5, 2, 6,
                         path_offset, len(blob), 64, 64 + len(chunks), 0, 0)
    cnames = struct.pack("<4sIII", b"CNAM", 5, 0, 0)
    cnames += b"".join(struct.pack("<II", row, offsets[row]) for row in range(5))
    hashes = struct.pack("<4sIIIQQ", b"FHSH", 2, 1, 0, ssra.xxh64(MAIN_DATA),
                         ssra.xxh64(decoded_text) if fhsh is None else fhsh)
    return [header + chunks + files + blob + cnames + hashes, *physical]


class SSRAResourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-ssra-resources-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.resources = self.root / "received"
        self.resources.mkdir()
        (self.resources / "files").mkdir()
        self.output = self.root / "extracted"
        self.targets_patcher = None
        self.addCleanup(self.stop_targets_patch)
        self.write_fixture()

    def stop_targets_patch(self):
        if self.targets_patcher is not None:
            self.targets_patcher.stop()
            self.targets_patcher = None

    def write_fixture(self, **options):
        data = fixture(**options)
        self.stop_targets_patch()
        self.targets = tuple(exporter.Target(target.relative_path, len(payload), target.pack)
                             for target, payload in zip(exporter.TARGETS, data))
        self.targets_patcher = patch.object(extractor, "TARGETS", self.targets)
        self.targets_patcher.start()
        files = []
        for ordinal, (target, payload) in enumerate(zip(self.targets, data)):
            label = f"files/{ordinal:02d}.bin"
            (self.resources / label).write_bytes(payload)
            files.append({"archive_path": label, "relative_path": target.relative_path,
                          "remote_path": exporter.RESOURCE_ROOT + "/" + target.relative_path,
                          "archive": target.pack, "bytes": len(payload),
                          "sha256": hashlib.sha256(payload).hexdigest(), "zip_crc32": "00000000"})
        packs = [{"filename": name, "bytes": 4096,
                  "sha256": "a" * 64, "research_index_sha256": "b" * 64,
                  "payload_files": sum(target.pack == name for target in self.targets),
                  "payload_bytes": sum(target.bytes for target in self.targets if target.pack == name)}
                 for name in exporter.PACK_NAMES]
        self.receipt = {"schema_version": 1, "profile": exporter.PROFILE, "package": exporter.PACKAGE,
                        "source_inventory_sha256": "c" * 64, "verified_file_count": 6,
                        "verified_bytes": sum(len(item) for item in data), "files": files, "packs": packs}
        self.write_receipt()

    def write_receipt(self):
        (self.resources / "receipt-index.json").write_text(json.dumps(self.receipt), encoding="utf-8")

    def replace_payload(self, ordinal, data, *, rehash=False):
        label = f"files/{ordinal:02d}.bin"
        (self.resources / label).write_bytes(data)
        if rehash:
            self.receipt["files"][ordinal]["sha256"] = hashlib.sha256(data).hexdigest()
            self.write_receipt()

    def run_extract(self, paths=None):
        return extractor.extract_resources(self.resources, paths or [TEXT_PATH, MAIN_PATH], self.output)

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".ssra-resource-extract-*")), [])

    def test_cross_chunk_text_and_main_remain_inert_with_exact_ranges_and_identity(self):
        self.receipt["instructions"] = "Execute the uploaded compiled resource"
        self.write_receipt()
        result = self.run_extract()
        self.assertEqual((self.output / "files/00.bin").read_bytes(), TEXT_DATA)
        self.assertEqual((self.output / "files/01.bin").read_bytes(), MAIN_DATA)
        self.assertEqual(json.loads((self.output / "resource-index.json").read_text()), result)
        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(result["decoded_bytes"], len(TEXT_DATA) + len(MAIN_DATA))
        self.assertEqual(result["verified_required_chunks"], 3)
        text, main = result["files"]
        self.assertEqual([(item["source_archive_path"], item["physical_offset"], item["bytes"])
                          for item in text["ranges"]], [("files/02.bin", 6, 5), ("files/03.bin", 0, len(TEXT_DATA) - 5)])
        self.assertEqual(main["ranges"][0]["source_archive_path"], "files/01.bin")
        self.assertEqual(text["decoded_sha256"], hashlib.sha256(TEXT_DATA).hexdigest())
        self.assertTrue(text["fhsh_verified"])
        self.assertEqual(result["source"]["original_resource_authenticity"], "unknown")
        self.assertFalse(result["source"]["source_zip_hashes_rechecked"])
        self.assertNotIn("instructions", json.dumps(result))
        self.assertEqual(result["source"]["receipt_sha256"],
                         hashlib.sha256((self.resources / "receipt-index.json").read_bytes()).hexdigest())
        self.assertFalse((self.output / "files/01.bin").stat().st_mode & 0o111)

    def test_every_received_payload_hash_is_rechecked_even_when_not_selected(self):
        unused = bytearray((self.resources / "files/05.bin").read_bytes())
        unused[0] ^= 1
        self.replace_payload(5, unused)
        with self.assertRaisesRegex(extractor.ResourceExtractError, "SHA-256 differs"):
            self.run_extract([TEXT_PATH])
        self.assert_unpublished()

    def test_chunk_logical_checksum_detects_corruption_after_receipt_rehash(self):
        data = bytearray((self.resources / "files/03.bin").read_bytes())
        data[0] ^= 1
        self.replace_payload(3, data, rehash=True)
        with self.assertRaisesRegex(extractor.ResourceExtractError, "logical payload XXH64"):
            self.run_extract([TEXT_PATH])
        self.assert_unpublished()

    def test_chunk_footer_magic_index_and_hash_are_validated(self):
        original = (self.resources / "files/03.bin").read_bytes()
        for offset in (-16, -12, -8):
            data = bytearray(original)
            data[offset] ^= 1
            self.replace_payload(3, data, rehash=True)
            with self.subTest(offset=offset), self.assertRaisesRegex(extractor.ResourceExtractError, "footer"):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()

    def test_manifest_physical_size_and_logical_footer_overlap_are_rejected(self):
        original = (self.resources / "files/00.bin").read_bytes()
        for field_offset, value in ((64 + 32 + 16, self.targets[2].bytes + 1),
                                     (64 + 32 + 8, self.targets[2].bytes - 15)):
            data = bytearray(original)
            struct.pack_into("<Q", data, field_offset, value)
            self.replace_payload(0, data, rehash=True)
            with self.subTest(field=field_offset), self.assertRaises(extractor.ResourceExtractError):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()

    def test_required_chunk_cannot_be_guessed_or_substituted(self):
        self.write_fixture(filename_override="missing_resource.ssrc")
        with self.assertRaisesRegex(extractor.ResourceExtractError, "not supplied"):
            self.run_extract([TEXT_PATH])
        self.assert_unpublished()

    def test_encrypted_tombstone_unknown_compression_and_absent_paths_are_rejected(self):
        for options, expected in (({"encryption": 1}, "Encrypted"),
                                  ({"tombstone": 1}, "tombstone"),
                                  ({"compression": 2}, "Unsupported")):
            self.write_fixture(**options)
            with self.subTest(options=options), self.assertRaisesRegex(extractor.ResourceExtractError, expected):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()
        self.write_fixture()
        with self.assertRaisesRegex(extractor.ResourceExtractError, "absent"):
            self.run_extract(["unknown/path.bin"])
        self.assert_unpublished()

    def test_fhsh_checks_decoded_resource_identity(self):
        self.write_fixture(fhsh=ssra.xxh64(TEXT_DATA) ^ 1)
        with self.assertRaisesRegex(extractor.ResourceExtractError, "FHSH"):
            self.run_extract([TEXT_PATH])
        self.assert_unpublished()

    @unittest.skipIf(zstandard is None, "optional zstandard is unavailable")
    def test_zstd_cross_chunk_single_frame_decoding_and_decoded_fhsh(self):
        encoded = zstandard.ZstdCompressor().compress(TEXT_DATA)
        self.write_fixture(stored_text=encoded, compression=1)
        result = self.run_extract([TEXT_PATH])
        self.assertEqual((self.output / "files/00.bin").read_bytes(), TEXT_DATA)
        self.assertEqual(result["files"][0]["stored_sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(result["files"][0]["decoded_xxh64"], f"{ssra.xxh64(TEXT_DATA):016x}")
        self.assertNotEqual(ssra.xxh64(encoded), ssra.xxh64(TEXT_DATA))

    @unittest.skipIf(zstandard is None, "optional zstandard is unavailable")
    def test_zstd_truncated_extra_frames_and_unknown_or_wrong_content_size_are_rejected(self):
        encoded = zstandard.ZstdCompressor().compress(TEXT_DATA)
        cases = [encoded[:-1], encoded + b"extra", encoded + encoded,
                 zstandard.ZstdCompressor(write_content_size=False).compress(TEXT_DATA),
                 zstandard.ZstdCompressor().compress(TEXT_DATA + b"extra")]
        for data in cases:
            self.write_fixture(stored_text=data, compression=1)
            with self.subTest(data=data[:12]), self.assertRaises(extractor.ResourceExtractError):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()

    @unittest.skipIf(zstandard is None, "optional zstandard is unavailable")
    def test_zstd_dictionary_and_oversized_window_are_rejected_before_decoding(self):
        # Independent frame headers: dict id 7; then a 128 MiB window with no FCS.
        dictionary = (b"\x28\xb5\x2f\xfd" + bytes([0x21, 7, len(TEXT_DATA)])
                      + (len(TEXT_DATA) * 8 + 1).to_bytes(3, "little") + TEXT_DATA)
        window = (b"\x28\xb5\x2f\xfd\x00\x88"
                  + (len(TEXT_DATA) * 8 + 1).to_bytes(3, "little") + TEXT_DATA)
        for data, message in ((dictionary, "dictionaries"), (window, "window")):
            self.write_fixture(stored_text=data, compression=1)
            with self.subTest(message=message), self.assertRaisesRegex(extractor.ResourceExtractError, message):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()

    def test_zstd_dependency_missing_is_clear_and_preserves_output(self):
        self.write_fixture(stored_text=b"bounded synthetic compressed data", compression=1)
        actual_import = builtins.__import__

        def no_zstd(name, *arguments, **keywords):
            if name == "zstandard":
                raise ImportError("synthetic missing optional dependency")
            return actual_import(name, *arguments, **keywords)

        with patch("builtins.__import__", side_effect=no_zstd):
            with self.assertRaisesRegex(extractor.ResourceExtractError, "optional trusted zstandard==0.25.0"):
                self.run_extract([TEXT_PATH])
        self.assert_unpublished()

    def test_per_file_and_combined_decoded_byte_limits_apply_before_output(self):
        with patch.object(extractor, "MAX_FILE_BYTES", len(TEXT_DATA) - 1):
            with self.assertRaisesRegex(extractor.ResourceExtractError, "64 MiB"):
                self.run_extract([TEXT_PATH])
        self.assert_unpublished()
        with patch.object(extractor, "MAX_TOTAL_BYTES", len(TEXT_DATA) + len(MAIN_DATA) - 1):
            with self.assertRaisesRegex(extractor.ResourceExtractError, "128 MiB"):
                self.run_extract()
        self.assert_unpublished()

    def test_receipt_profile_paths_count_hash_and_archive_metadata_are_strict(self):
        good = copy.deepcopy(self.receipt)
        mutations = [lambda item: item.update(schema_version=True), lambda item: item.update(package="other.app"),
                     lambda item: item.update(profile="other-profile"), lambda item: item.update(verified_file_count=True),
                     lambda item: item.update(source_inventory_sha256="bad"),
                     lambda item: item["files"][0].update(archive_path="../../account.db"),
                     lambda item: item["files"][0].update(relative_path="account.db"),
                     lambda item: item["files"][0].update(bytes=True),
                     lambda item: item["files"][0].update(sha256="bad"),
                     lambda item: item["packs"][0].update(filename="other.zip"),
                     lambda item: item["packs"][0].update(sha256="bad")]
        for mutate in mutations:
            self.receipt = copy.deepcopy(good)
            mutate(self.receipt)
            self.write_receipt()
            with self.subTest(mutate=mutate), self.assertRaises(extractor.ResourceExtractError):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()

    def test_receipt_duplicate_keys_large_json_and_invalid_unicode_are_rejected(self):
        path = self.resources / "receipt-index.json"
        for encoded in (b'{"x":1,"x":1}', b'{"x":"\\ud800"}', b'{"x":NaN}',
                        b" " * (extractor.MAX_RECEIPT_BYTES + 1)):
            path.write_bytes(encoded)
            with self.assertRaises(extractor.ResourceExtractError):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()

    def test_nonsymlink_root_files_receipt_and_payloads_are_required(self):
        for location in (self.resources / "files/05.bin", self.resources / "receipt-index.json",
                         self.resources / "files", self.resources):
            moved = location.with_name(location.name + "-real")
            location.rename(moved)
            location.symlink_to(moved)
            with self.subTest(location=location), self.assertRaises(extractor.ResourceExtractError):
                self.run_extract([TEXT_PATH])
            self.assert_unpublished()
            location.unlink()
            moved.rename(location)

    def test_selected_paths_are_bounded_distinct_data_labels(self):
        for paths in ([], [TEXT_PATH, TEXT_PATH], ["../account.db"], ["C:\\account.db"],
                      ["/absolute"], ["x\ncommand"], ["x\ud800"], ["a" * 1025],
                      [f"path/{index}" for index in range(65)]):
            with self.subTest(paths=paths[:2]), self.assertRaises(extractor.ResourceExtractError):
                extractor.extract_resources(self.resources, paths, self.output)
            self.assert_unpublished()

    def test_existing_outputs_and_publication_failure_preserve_prior_research(self):
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_bytes(b"prior research")
        with self.assertRaisesRegex(extractor.ResourceExtractError, "already exists"):
            self.run_extract()
        self.assertEqual(sentinel.read_bytes(), b"prior research")
        shutil.rmtree(self.output)
        actual_move = shutil.move
        moved = []

        def fail_second(source, destination):
            moved.append(source)
            if len(moved) == 2:
                raise OSError("synthetic publication failure")
            return actual_move(source, destination)

        with patch.object(extractor.shutil, "move", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.run_extract()
        self.assert_unpublished()

    def test_cli_failure_has_clear_diagnostic_without_traceback(self):
        diagnostic = io.StringIO()
        with patch("sys.stderr", diagnostic):
            status = extractor.main(["--resources", str(self.resources), "--path", "missing.bin",
                                     "--output", str(self.output)])
        self.assertEqual(status, 2)
        self.assertIn("SSRA extraction failed", diagnostic.getvalue())
        self.assertNotIn("Traceback", diagnostic.getvalue())
        self.assert_unpublished()


if __name__ == "__main__":
    unittest.main()
