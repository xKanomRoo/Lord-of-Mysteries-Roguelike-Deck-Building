"""Static all-content upload validation, split assets, resume and hostile inputs."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tools import read_all_game_resources as reader
from tools import read_ssra_manifest as ssra
from tools import export_all_game_resources as exporter

try:
    import zstandard
except ImportError:
    zstandard = None


def fixture(*, compression=0, wrong_fhsh=False, encoded_transform=None):
    paths = ["card_illustration/test.sct", "sound/test.bank", "bin/arm64/inert.jbin"]
    decoded = [b"Thirty-nine bytes of inert image payload!", b"FMOD bank sample data", b"Never execute uploaded code"]
    stored = [zstandard.ZstdCompressor().compress(value) if compression else value for value in decoded]
    if encoded_transform:
        stored[0] = encoded_transform(stored[0])
    data, offsets = bytearray(), []
    for value in stored:
        data.extend(b"PAD")
        offsets.append(len(data))
        data.extend(value)
    split = offsets[0] + 7
    payloads = [bytes(data[:split]), bytes(data[split:])]
    blob, names = bytearray(), []
    for name in ["base_b00_0.ssrc", "base_b01_0.ssrc", *paths]:
        names.append(len(blob))
        blob.extend(name.encode() + b"\0")
    chunks = b"".join(struct.pack("<IHHQQQ", index, 12, 0, len(value), len(value) + 16, ssra.xxh64(value))
                      for index, value in enumerate(payloads))
    files = b"".join(struct.pack("<QQ4IBBHB3s", ssra.xxh64(path.encode()), offset, len(encoded),
                                len(clear), 0, name, compression, 0, 12, 0, bytes(3))
                     for path, offset, encoded, clear, name in zip(paths, offsets, stored, decoded, names[2:]))
    path_offset = 64 + len(chunks) + len(files)
    header = struct.pack("<4s5I4Q2I", b"SSRA", 4, 0, 2, len(paths), 6,
                         path_offset, len(blob), 64, 64 + len(chunks), 0, 0)
    cnam = struct.pack("<4sIII4I", b"CNAM", 2, 0, 0, 0, names[0], 1, names[1])
    fhsh = [ssra.xxh64(value) for value in decoded]
    if wrong_fhsh:
        fhsh[0] ^= 1
    hashes = struct.pack("<4sIII3Q", b"FHSH", len(paths), 1, 0, *fhsh)
    manifest = header + chunks + files + blob + cnam + hashes
    return manifest, stored, decoded


class AllResourceReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="all-inert-read-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = self.root / ".local"
        self.output = self.private / "research"
        self.source = self.root / "chaos-all-source.zip"
        self.patches = []
        self.addCleanup(self._stop)
        self._fixture()

    def _stop(self):
        for value in reversed(self.patches):
            value.stop()
        self.patches = []

    def _fixture(self, **options):
        self._stop()
        self.manifest_data, self.stored, self.decoded = fixture(**options)
        self.manifest = ssra.parse_ssra(self.manifest_data)
        self.manifest_hash = hashlib.sha256(self.manifest_data).hexdigest()
        for owner, name, value in [(reader, "MANIFEST_SHA256", self.manifest_hash),
                                   (reader, "MANIFEST_BYTES", len(self.manifest_data)),
                                   (reader, "MAX_PART_BYTES", 16),
                                   (reader, "PRIVATE_ROOT", self.private)]:
            patcher = patch.object(owner, name, value)
            patcher.start()
            self.patches.append(patcher)
        self.source_index = {"schema_version": 1, "profile": reader.PROFILE, "package": reader.PACKAGE,
                             "kind": "source", "source_manifest_sha256": self.manifest_hash,
                             "manifest": {"archive_path": reader.MANIFEST_MEMBER, "bytes": len(self.manifest_data), "sha256": self.manifest_hash}}
        self._write_source()

    def _write_zip(self, path, members, *, compression=zipfile.ZIP_STORED, modes=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w", compression=compression) as archive:
                for name, data in members:
                    if modes and name in modes:
                        info = zipfile.ZipInfo(name)
                        info.create_system = 3
                        info.external_attr = modes[name] << 16
                        info.compress_type = compression
                        archive.writestr(info, data)
                    else:
                        archive.writestr(name, data)

    def _write_source(self, *, manifest=None, raw_index=None, extra=()):
        self._write_zip(self.source, [(reader.INDEX_NAME, raw_index if raw_index is not None else json.dumps(self.source_index).encode()),
                                     (reader.MANIFEST_MEMBER, manifest if manifest is not None else self.manifest_data), *extra])

    def _records(self, rows=None):
        result = []
        for row, item in enumerate(self.manifest["files"]):
            if rows is not None and row not in rows:
                continue
            for offset in range(0, item["stored_length"], reader.MAX_PART_BYTES):
                value = self.stored[row][offset:offset + reader.MAX_PART_BYTES]
                record = {"resource": reader.resource_identity(item), "part_offset": offset,
                          "archive_path": f"parts/{row:06d}-{offset:012d}.bin", "bytes": len(value),
                          "sha256": hashlib.sha256(value).hexdigest(),
                          "segments": reader.fragment_segments(self.manifest, item, offset, len(value))}
                result.append((record, value))
        return result

    def _batch(self, number=1, *, records=None, raw_index=None, extra=(), omit=(), modes=None, compression=zipfile.ZIP_STORED):
        records = self._records() if records is None else records
        index = {"schema_version": 1, "profile": reader.PROFILE, "package": reader.PACKAGE,
                 "kind": "resources", "source_manifest_sha256": self.manifest_hash,
                 "batch_number": number, "files": [record for record, payload in records]}
        path = self.root / f"chaos-all-{number:06d}.zip"
        members = [(reader.INDEX_NAME, raw_index if raw_index is not None else json.dumps(index).encode()),
                   *((record["archive_path"], payload) for record, payload in records), *extra]
        members = [(name, data) for name, data in members if name not in omit]
        self._write_zip(path, members, modes=modes, compression=compression)
        return path

    def _read(self, packs):
        return reader.read_resources(self.source, packs, self.output)

    def test_all_types_and_cross_chunk_split_verified_without_execution(self):
        records = self._records()
        self.assertEqual(len(records[0][0]["segments"]), 2)
        pack = self._batch(records=list(reversed(records)))
        receipt = self._read([pack])
        self.assertEqual(receipt["resource_status_counts"], {"verified": 3})
        self.assertTrue(receipt["all_manifest_resources_verified"])
        self.assertFalse(receipt["scope"]["scripts_executed"])
        for row, value in enumerate(self.decoded):
            self.assertEqual((self.output / "files" / f"{row:06d}.bin").read_bytes(), value)
        catalog = json.loads((self.output / "resource-index.json").read_text())
        self.assertTrue(all(not record["rendered"] and not record["format_parsed"] for record in catalog["files"]))

    def test_partial_then_resume_and_idempotent_duplicate(self):
        records = self._records()
        first = self._batch(1, records=records[:1])
        receipt = self._read([first])
        self.assertEqual(receipt["resource_status_counts"], {"partial": 1, "missing": 2})
        self.assertFalse(receipt["all_manifest_resources_verified"])
        second = self._batch(2, records=records[1:])
        receipt = self._read([second, first])
        self.assertEqual(receipt["verified_batch_count"], 2)
        self.assertEqual(receipt["received_unique_stored_bytes"], sum(map(len, self.stored)))
        again = self._read([first, second])
        self.assertEqual(again["received_unique_stored_bytes"], receipt["received_unique_stored_bytes"])
        self.assertEqual(again["verified_batch_count"], 2)

    def test_same_batch_number_changed_archive_is_rejected(self):
        first = self._batch(1, records=self._records()[:1])
        self._read([first])
        changed = self._batch(1, records=self._records()[1:])
        receipt = self._read([changed])
        self.assertEqual(len(receipt["rejected_input_batches"]), 1)
        self.assertEqual(receipt["resource_status_counts"], {"partial": 1, "missing": 2})

    def test_new_number_with_only_old_fragments_is_not_a_limit_reset(self):
        self._read([self._batch(1)])
        receipt = self._read([self._batch(2)])
        self.assertEqual(receipt["verified_batch_count"], 1)
        self.assertEqual(len(receipt["rejected_input_batches"]), 1)

    def test_hash_failure_rejects_entire_pack(self):
        records = self._records()
        records[-1][0]["sha256"] = "a" * 64
        receipt = self._read([self._batch(records=records)])
        self.assertEqual(receipt["received_unique_stored_bytes"], 0)
        self.assertEqual(receipt["resource_status_counts"], {"missing": 3})
        self.assertEqual(receipt["historical_rejected_zip_count"], 1)

    def test_manifest_metadata_path_and_segments_are_not_authorization(self):
        edits = [lambda r: r["resource"].update(path="private/accounts.db"),
                 lambda r: r["resource"].update(row=True),
                 lambda r: r["resource"].update(decoded_length=float(r["resource"]["decoded_length"])),
                 lambda r: r.update(archive_path="../../asset.bin"),
                 lambda r: r["segments"][0].update(physical_offset=100),
                 lambda r: r["segments"][0].update(chunk_filename="preferences.xml"),
                 lambda r: r.update(bytes=True),
                 lambda r: r.update(part_offset=1),
                 lambda r: r.update(extra="scope declaration")]
        for edit in edits:
            with self.subTest(edit=edit):
                records = self._records()
                edit(records[0][0])
                with self.assertRaises(reader.AllReadError):
                    reader.verify_batch(self._batch(records=records), self.manifest)

    def test_duplicate_and_non_grid_fragments_rejected(self):
        record = self._records()[0]
        with self.assertRaises(reader.AllReadError):
            reader.verify_batch(self._batch(records=[record, record]), self.manifest)
        short = copy.deepcopy(record)
        short[0]["bytes"] -= 1
        with self.assertRaises(reader.AllReadError):
            reader.verify_batch(self._batch(records=[short]), self.manifest)

    def test_unsafe_extra_missing_and_symlink_archive_members(self):
        records = self._records()
        label = records[0][0]["archive_path"]
        cases = [dict(extra=[("../../outside", b"bad")]), dict(extra=[("directory/", b"")]),
                 dict(extra=[(reader.INDEX_NAME, b"{}")]), dict(omit=[label]),
                 dict(modes={label: stat.S_IFLNK | 0o777}),
                 dict(compression=zipfile.ZIP_DEFLATED)]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(reader.AllReadError):
                reader.verify_batch(self._batch(**options), self.manifest)

    def test_bad_json_index(self):
        bad = [b'{"schema_version":1,"schema_version":1}', b'{"value":NaN}',
               b'{"value":"\\ud800"}', b'[]', b'\xff', b'{' + b' ' * reader.MAX_INDEX_BYTES + b'}']
        for data in bad:
            with self.subTest(data=data[:30]), self.assertRaises(reader.AllReadError):
                reader.verify_batch(self._batch(raw_index=data), self.manifest)

    def test_source_hash_and_extra_member_failure_do_not_create_store(self):
        for options in [dict(manifest=self.manifest_data[:-1] + b"X"), dict(extra=[("other.bin", b"bad")])]:
            self._write_source(**options)
            with self.assertRaises(reader.AllReadError):
                self._read([])
            self.assertFalse(self.output.exists())

    def test_source_unknown_scope_and_type_mismatch(self):
        for edit in [lambda: self.source_index.update(scope={"trusted": True}),
                     lambda: self.source_index.update(schema_version=1.0)]:
            original = copy.deepcopy(self.source_index)
            edit()
            self._write_source()
            with self.assertRaises(reader.AllReadError):
                self._read([])
            self.source_index = original

    def test_input_zip_must_be_nonsymlink_and_bounded(self):
        pack = self._batch()
        alias = self.root / "alias.zip"
        alias.symlink_to(pack)
        with self.assertRaises(reader.AllReadError):
            reader.verify_batch(alias, self.manifest)
        with patch.object(reader, "MAX_ZIP_BYTES", 20), self.assertRaises(reader.AllReadError):
            reader.verify_batch(pack, self.manifest)

    def test_tampered_stored_part_refuses_resume(self):
        self._read([self._batch()])
        path = next((self.output / "parts").iterdir())
        path.write_bytes(b"X" * path.stat().st_size)
        with self.assertRaisesRegex(reader.AllReadError, "changed"):
            self._read([])

    def test_malicious_saved_result_cannot_claim_partial_complete(self):
        self._read([self._batch(records=self._records()[:1])])
        with sqlite3.connect(self.output / "state.sqlite3") as database:
            database.execute("INSERT INTO results VALUES(0,'verified',?,?,NULL)", ("a" * 64, "b" * 64))
        with self.assertRaisesRegex(reader.AllReadError, "incomplete"):
            self._read([])

    def test_uncommitted_canonical_part_after_crash_is_recovered(self):
        self._read([])
        record, payload = self._records()[0]
        orphan = self.output / record["archive_path"]
        orphan.write_bytes(payload)
        receipt = self._read([self._batch()])
        self.assertEqual(receipt["discarded_uncommitted_fragment_count"], 1)
        self.assertTrue(receipt["all_manifest_resources_verified"])

    def test_zero_and_short_uncommitted_parts_after_crash_are_recovered(self):
        for amount in [0, 3]:
            with self.subTest(amount=amount):
                self.output = self.private / f"crash-{amount}"
                self._read([])
                record, payload = self._records()[0]
                (self.output / record["archive_path"]).write_bytes(payload[:amount])
                receipt = self._read([self._batch()])
                self.assertEqual(receipt["discarded_uncommitted_fragment_count"], 1)
                self.assertTrue(receipt["all_manifest_resources_verified"])

    def test_interrupted_owned_temporary_stages_are_bounded_and_removed(self):
        self._read([])
        stage = self.output / ".all-ingest-abc12345"
        stage.mkdir()
        (stage / "000000-000000000000.bin").write_bytes(b"short")
        decode = self.output / ".all-decode-abc12345"
        decode.mkdir()
        (decode / "decoded.bin").write_bytes(b"partial")
        (self.output / ".catalog-abc12345").write_bytes(b"partial")
        receipt = self._read([self._batch()])
        self.assertTrue(receipt["all_manifest_resources_verified"])
        self.assertFalse(stage.exists())
        self.assertFalse(decode.exists())
        self.assertFalse((self.output / ".catalog-abc12345").exists())

    def test_unknown_member_in_interrupted_stage_is_preserved_and_rejected(self):
        self._read([])
        stage = self.output / ".all-ingest-abc12345"
        stage.mkdir()
        (stage / "notes.txt").write_text("preserve")
        with self.assertRaisesRegex(reader.AllReadError, "staging member"):
            self._read([])
        self.assertEqual((stage / "notes.txt").read_text(), "preserve")

    def test_unknown_or_symlink_orphan_is_rejected(self):
        self._read([])
        path = self.output / "parts" / "notes.txt"
        path.write_text("unknown")
        with self.assertRaisesRegex(reader.AllReadError, "filename"):
            self._read([])
        path.unlink()
        record, payload = self._records()[0]
        path = self.output / record["archive_path"]
        target = self.root / "do-not-delete"
        target.write_bytes(payload)
        path.symlink_to(target)
        with self.assertRaises(reader.AllReadError):
            self._read([])
        self.assertEqual(target.read_bytes(), payload)

    def test_changed_decoded_output_restored_from_verified_fragments(self):
        self._read([self._batch()])
        target = self.output / "files" / "000000.bin"
        target.write_bytes(b"changed")
        receipt = self._read([])
        self.assertTrue(receipt["all_manifest_resources_verified"])
        self.assertEqual(target.read_bytes(), self.decoded[0])

    def test_output_private_and_nonsymlink(self):
        with self.assertRaises(reader.AllReadError):
            reader.read_resources(self.source, [], self.root / "public")
        self.private.mkdir()
        alias = self.private / "alias"
        actual = self.root / "outside"
        actual.mkdir()
        alias.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(reader.AllReadError):
            reader.read_resources(self.source, [], alias / "research")

    def test_decoded_destination_and_sqlite_sidecar_symlinks_rejected(self):
        self._read([])
        secret = self.root / "secret"
        secret.write_bytes(b"preserve")
        (self.output / "state.sqlite3-journal").symlink_to(secret)
        with self.assertRaises(reader.AllReadError):
            self._read([])
        self.assertEqual(secret.read_bytes(), b"preserve")

    def test_batch_publication_failure_rolls_back_files_and_database(self):
        pack = self._batch()
        with patch.object(reader.shutil, "copyfileobj", side_effect=OSError("synthetic disk failure")):
            receipt = self._read([pack])
        self.assertEqual(receipt["resource_status_counts"], {"missing": 3})
        self.assertEqual(list((self.output / "parts").iterdir()), [])
        self.assertEqual(receipt["verified_batch_count"], 0)

    def test_fhsh_failure_retains_stored_fragments_but_no_decoded_asset(self):
        self._fixture(wrong_fhsh=True)
        receipt = self._read([self._batch()])
        self.assertEqual(receipt["resource_status_counts"], {"invalid": 1, "verified": 2})
        self.assertFalse(receipt["all_manifest_resources_verified"])
        self.assertFalse((self.output / "files" / "000000.bin").exists())
        self.assertTrue(list((self.output / "parts").iterdir()))

    @unittest.skipIf(zstandard is None, "Optional pinned Zstd library unavailable")
    def test_zstd_content_verified_and_trailing_or_multiframe_rejected(self):
        self._fixture(compression=1)
        receipt = self._read([self._batch()])
        self.assertTrue(receipt["all_manifest_resources_verified"])
        for transform in [lambda value: value + b"TRAIL", lambda value: value + value]:
            with self.subTest(transform=transform):
                self.output = self.private / ("invalid-" + str(id(transform)))
                self._fixture(compression=1, encoded_transform=transform)
                receipt = self._read([self._batch()])
                self.assertEqual(receipt["resource_status_counts"], {"invalid": 1, "verified": 2})

    @unittest.skipIf(zstandard is None, "Optional pinned Zstd library unavailable")
    def test_optional_zstd_failure_is_reported_as_unsupported(self):
        self._fixture(compression=1)
        pack = self._batch()
        with patch.object(reader.resources, "_decode_resource", side_effect=reader.resources.ResourceExtractError("Zstd extraction requires optional trusted zstandard==0.25.0")):
            receipt = self._read([pack])
        self.assertEqual(receipt["resource_status_counts"], {"unsupported": 3})
        self.assertFalse(receipt["all_manifest_resources_verified"])

    def test_source_aggregate_resource_bound_is_not_per_batch_reset(self):
        with patch.object(reader, "MAX_RESOURCE_BYTES", 20), self.assertRaises(reader.AllReadError):
            self._read([])
        for key in ["MAX_STORED_TOTAL_BYTES", "MAX_DECODED_TOTAL_BYTES"]:
            with patch.object(reader, key, 50), self.assertRaises(reader.AllReadError):
                self._read([])
        self.assertFalse(self.output.exists())

    def test_independent_reader_exporter_physical_segments_match(self):
        for item in self.manifest["files"]:
            for offset in range(0, item["stored_length"], reader.MAX_PART_BYTES):
                length = min(reader.MAX_PART_BYTES, item["stored_length"] - offset)
                self.assertEqual(reader.fragment_segments(self.manifest, item, offset, length),
                                 exporter.derive_segments(self.manifest, item, offset, length))

    def test_batch_directory_flat_exact_names_source_and_unrelated_excluded(self):
        first = self._batch(1, records=self._records()[:1])
        second = self._batch(2, records=self._records()[1:])
        (self.root / "do-not-read.zip").write_bytes(b"unrelated")
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "chaos-all-000003.zip").write_bytes(b"nested")
        self.assertEqual(reader.batch_directory(self.root), [first, second])
        stdout = io.StringIO()
        with patch.object(reader.sys, "stdout", stdout):
            result = reader.main(["--source", str(self.source), "--output", str(self.output), "--batch-dir", str(self.root)])
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(stdout.getvalue())["all_manifest_resources_verified"])

    def test_batch_directory_empty_and_symlink_members_rejected(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(reader.AllReadError, "no chaos"):
            reader.batch_directory(empty)
        pack = self._batch()
        (empty / "chaos-all-000001.zip").symlink_to(pack)
        with self.assertRaises(reader.AllReadError):
            reader.batch_directory(empty)
        alias = self.root / "directory-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(reader.AllReadError):
            reader.batch_directory(alias)


class StreamingHashTests(unittest.TestCase):
    def test_matches_independent_standard_xxh64_across_boundaries(self):
        for size in [0, 1, 7, 8, 15, 16, 31, 32, 33, 63, 64, 65, 127, 1024, 4097]:
            data = bytes((index * 37 + 11) % 256 for index in range(size))
            for block in [1, 7, 31, 32, 33, 511, 1024]:
                with self.subTest(size=size, block=block):
                    digest = reader.StreamingXXH64()
                    for offset in range(0, len(data), block):
                        digest.update(data[offset:offset + block])
                        self.assertLess(len(digest.buffer), 32)
                    self.assertEqual(digest.intdigest(), ssra.xxh64(data))
                    self.assertEqual(digest.intdigest(), ssra.xxh64(data))

    def test_large_uncompressed_resource_is_streamed_past_compressed_limit(self):
        # A lowered compressed bound exercises the bank path without a huge
        # fixture. No compressed allocation or Zstd call may serve this path.
        case = AllResourceReadTests(methodName="test_all_types_and_cross_chunk_split_verified_without_execution")
        case.setUp()
        try:
            with patch.object(reader, "MAX_COMPRESSED_BYTES", 8), patch.object(reader.resources, "_decode_resource", side_effect=AssertionError("uncompressed data must stream")):
                receipt = case._read([case._batch()])
            self.assertTrue(receipt["all_manifest_resources_verified"])
        finally:
            case.doCleanups()


class ActualManifestTests(unittest.TestCase):
    def test_actual_pinned_manifest_all_asset_bounds_and_mapping(self):
        path = Path(__file__).resolve().parents[1] / ".local/research/runtime-received-45a009358972/files/00.bin"
        if not path.exists():
            self.skipTest("Actual private received manifest is not in this checkout")
        data = path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), reader.MANIFEST_SHA256)
        manifest = ssra.parse_ssra(data)
        self.assertEqual(len(manifest["files"]), 87529)
        self.assertEqual(sum(item["stored_length"] for item in manifest["files"]), 8_268_841_848)
        self.assertEqual(sum(item["decoded_length"] for item in manifest["files"]), 9_092_590_042)
        bank = next(item for item in manifest["files"] if item["path"] == "sound/master.bank")
        self.assertEqual(bank["stored_length"], 361_306_848)
        self.assertLess(bank["decoded_length"], reader.MAX_RESOURCE_BYTES)
        for item in manifest["files"][::997] + [bank]:
            for offset in {0, (item["stored_length"] - 1) // reader.MAX_PART_BYTES * reader.MAX_PART_BYTES}:
                length = min(reader.MAX_PART_BYTES, item["stored_length"] - offset)
                self.assertEqual(reader.fragment_segments(manifest, item, offset, length),
                                 exporter.derive_segments(manifest, item, offset, length))
        compressed = [item for item in manifest["files"] if item["compression"]]
        self.assertTrue(all(item["decoded_length"] <= reader.MAX_COMPRESSED_BYTES for item in compressed))


if __name__ == "__main__":
    unittest.main()
