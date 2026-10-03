"""Fake local ADB exercises stream batching/resume; no game or network runs."""

import copy
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import export_all_game_resources as export
from tools import inventory_android_resources as android
from tools import read_ssra_manifest as ssra


def fixture():
    block = export.MAX_PART_BYTES
    names = ("base_b00_0.ssrc", "base_b01_0.ssrc")
    files = (("face/hero.sct", 0, 90), ("img/cost.sct", 90, 64),
             ("bin/arm64/main.jbin", 154, 31), ("wnd/card.csb", 185, 128),
             ("sound/master.bank", block + 17, 2 * block + 37), ("img/empty.sct", 313, 0))
    logical = 2 * block
    offsets, blob = {}, bytearray()
    for name in (*names, *(row[0] for row in files)):
        offsets[name] = len(blob)
        blob.extend(name.encode() + b"\0")
    chunks = {name: bytes((i + row * 13) % 256 for i in range(logical)) + b"SSRC" + bytes(12)
              for row, name in enumerate(names)}
    chunk_rows = b"".join(struct.pack("<IHHQQQ", row, 12, 0, logical, logical + 16, 0xA0 + row)
                          for row in range(2))
    file_rows = b"".join(struct.pack("<QQ4IBBHB3s", ssra.xxh64(name.encode()), offset, length,
                                    length, 0, offsets[name], 0, 0, 12, 0, bytes(3))
                         for name, offset, length in files)
    path_offset = 64 + len(chunk_rows) + len(file_rows)
    header = struct.pack("<4s5I4Q2I", b"SSRA", 4, 0, 2, len(files), 6,
                         path_offset, len(blob), 64, 64 + len(chunk_rows), 0, 0)
    cnam = struct.pack("<4sIII", b"CNAM", 2, 0, 0)
    cnam += b"".join(struct.pack("<II", row, offsets[name]) for row, name in enumerate(names))
    fhsh = struct.pack("<4sIII", b"FHSH", len(files), 1, 0)
    fhsh += b"".join(struct.pack("<Q", 0xD0 + row) for row in range(len(files)))
    return header + chunk_rows + file_rows + blob + cnam + fhsh, chunks


class FakeRunner:
    def __init__(self, manifest, chunks, *, absent=None, fail_read=None, wrong_size=False):
        self.manifest, self.chunks = manifest, chunks
        self.absent, self.fail_read = set(absent or ()), fail_read
        self.wrong_size = wrong_size
        self.calls, self.binary_calls = [], []

    def run(self, args, **limits):
        self.calls.append(args)
        if args == ["devices", "-l"]:
            return android.CommandResult(0, b"List of devices attached\nemulator-5554 device\n")
        if args[-1] == f"pm path {export.PACKAGE}":
            return android.CommandResult(0, b"package:/data/app/synthetic/base.apk\n")
        if args[-1] == export.existing.target_stat_command(export.existing.TARGETS[0]):
            return android.CommandResult(0, str(len(self.manifest)).encode())
        if len(args) == 5 and args[2] == "pull":
            Path(args[-1]).write_bytes(self.manifest)
            return android.CommandResult(0, b"manifest copied\n")
        for name, data in self.chunks.items():
            if args[-1] == export.ranges.chunk_stat_command(name):
                if name in self.absent:
                    return android.CommandResult(7, b"")
                return android.CommandResult(0, str(len(data) + int(self.wrong_size)).encode())
        raise AssertionError(f"Unexpected ADB call: {args}")

    def run_diagnostic(self, args):
        self.calls.append(args)
        return android.CommandResult(0, b"__ssra_reader_probe_exit=0\n")

    def run_binary(self, args, expected):
        self.binary_calls.append(args)
        if len(self.binary_calls) == self.fail_read:
            raise export.ranges.RangeExportError("synthetic ADB disconnection")
        command = args[-1]
        match = re.fullmatch(r"dd if=(.+)/([A-Za-z0-9_.-]+\.ssrc) bs=65536 skip=([0-9]+) count=([0-9]+) 2>/dev/null", command)
        if not match or match.group(1) != export.RESOURCE_ROOT + "/gameres/chunks":
            raise AssertionError("Read escaped the fixed external resource chunk path")
        name = match.group(2)
        start, size = int(match.group(3)) * 65536, int(match.group(4)) * 65536
        data = self.chunks[name][start:start + size]
        if len(data) != expected:
            raise AssertionError("Incorrect independently bounded read size")
        return android.CommandResult(0, data)


class AllResourceExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="all-resource-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.adb = self.root / "adb.exe"
        self.adb.write_bytes(b"synthetic never executed")
        self.adb.chmod(0o700)
        self.manifest, self.chunks = fixture()
        self.metadata = ssra.parse_ssra(self.manifest)
        self.digest = hashlib.sha256(self.manifest).hexdigest()
        self.addCleanup(patch.stopall)
        patch.object(export, "MANIFEST_BYTES", len(self.manifest)).start()
        patch.object(export, "MANIFEST_SHA256", self.digest).start()
        target = export.existing.Target(export.MANIFEST_PATH, len(self.manifest), export.existing.PACK_NAMES[0])
        patch.object(export.existing, "TARGETS", (target,)).start()

    def run_export(self, runner=None, **kwargs):
        with patch("sys.stdout", new=io.StringIO()):
            return export.export_all(self.output, self.adb, runner=runner or FakeRunner(self.manifest, self.chunks), **kwargs)

    def collect(self):
        parts = {}
        for path in sorted(self.output.glob("chaos-all-*.zip")):
            if not export.BATCH_PATTERN.fullmatch(path.name):
                continue
            index, _ = export.verify_batch(path, self.metadata)
            with zipfile.ZipFile(path) as archive:
                for entry in index["files"]:
                    row = entry["resource"]["row"]
                    parts.setdefault(row, []).append((entry["part_offset"], archive.read(entry["archive_path"])))
        return {row: b"".join(data for _, data in sorted(entries)) for row, entries in parts.items()}

    def test_all_rows_including_inert_code_stream_and_split(self):
        runner = FakeRunner(self.manifest, self.chunks)
        report = self.run_export(runner, batch_bytes=export.MAX_PART_BYTES)
        self.assertTrue(report["all_manifest_resources_exported"])
        self.assertEqual(report["exported_resource_count"], 6)
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["scope"]["game_code_executed"])
        self.assertFalse(report["scope"]["decoded_FHSH_verified"])
        self.assertLessEqual(len(runner.binary_calls), 4)
        combined = b"".join(data[:-16] for data in self.chunks.values())
        received = self.collect()
        for row in self.metadata["files"]:
            if row["stored_length"]:
                self.assertEqual(received[row["row"]], combined[row["offset"]:row["offset"] + row["stored_length"]])
        self.assertIn(2, received)  # Main cache is copied as inert bytes.
        self.assertGreater(len(report["batches"]), 1)
        for batch in report["batches"]:
            self.assertLessEqual(batch["bytes"], export.MAX_ZIP_BYTES)
        with zipfile.ZipFile(self.output / export.SOURCE_PACK) as archive:
            self.assertEqual(archive.read(export.SOURCE_MEMBER), self.manifest)

    def test_resume_after_disconnect_preserves_batches_and_finishes(self):
        with self.assertRaisesRegex(export.AllExportError, "Use --resume"):
            self.run_export(FakeRunner(self.manifest, self.chunks, fail_read=3), batch_bytes=export.MAX_PART_BYTES)
        complete_before = {p.name: p.read_bytes() for p in self.output.glob("chaos-all-*.zip")}
        self.assertTrue(complete_before)
        self.assertFalse(list(self.output.glob("*.part")))
        report = self.run_export(resume=True, batch_bytes=export.MAX_PART_BYTES)
        self.assertTrue(report["all_manifest_resources_exported"])
        for name, data in complete_before.items():
            self.assertEqual((self.output / name).read_bytes(), data)
        self.assertEqual(len(self.collect()), 5)

    def test_full_resume_performs_no_binary_resource_reads(self):
        self.run_export()
        runner = FakeRunner(self.manifest, self.chunks)
        report = self.run_export(runner, resume=True)
        self.assertTrue(report["all_manifest_resources_exported"])
        self.assertEqual(runner.binary_calls, [])

    def test_missing_chunk_is_reported_and_then_resume_completes(self):
        missing = {"base_b01_0.ssrc"}
        report = self.run_export(FakeRunner(self.manifest, self.chunks, absent=missing))
        self.assertFalse(report["all_manifest_resources_exported"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["resource_status_counts"]["missing"], 1)
        self.assertEqual(report["missing_chunks"][0]["filename"], "base_b01_0.ssrc")
        self.assertTrue(self.run_export(resume=True)["all_manifest_resources_exported"])

    def test_manifest_pin_mismatch_stops_before_binary_reads(self):
        changed = bytearray(self.manifest)
        changed[-1] ^= 1
        runner = FakeRunner(bytes(changed), self.chunks)
        with self.assertRaisesRegex(export.AllExportError, "manifest differs"):
            self.run_export(runner)
        self.assertEqual(runner.binary_calls, [])
        self.assertFalse(self.output.exists())

    def test_output_preservation_and_nonlocal_serial(self):
        self.output.mkdir()
        with self.assertRaisesRegex(export.AllExportError, "Output exists"):
            self.run_export()
        self.output.rmdir()
        with self.assertRaisesRegex(export.AllExportError, "local emulator serial"):
            self.run_export(serial="192.168.0.10:5555")

    def test_bad_manifest_flags_and_unsafe_chunk_fail_validation(self):
        for key, value in (("flags", 1), ("encryption", 1), ("compression", 7),
                           ("stored_length", export.MAX_RESOURCE_BYTES + 1)):
            manifest = copy.deepcopy(self.metadata)
            manifest["files"][0][key] = value
            with self.subTest(key=key), self.assertRaises(export.AllExportError):
                export.validate_manifest(manifest, export.DEFAULT_TOTAL_BYTES)
        manifest = copy.deepcopy(self.metadata)
        manifest["chunks"][0]["filename"] = "../../account.ssrc"
        with self.assertRaises(export.AllExportError):
            export.validate_manifest(manifest, export.DEFAULT_TOTAL_BYTES)

    def test_resume_corrupt_fragment_is_rejected(self):
        self.run_export()
        path = next(p for p in self.output.glob("chaos-all-*.zip") if export.BATCH_PATTERN.fullmatch(p.name))
        with zipfile.ZipFile(path) as archive:
            items = [(info.filename, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in items:
                archive.writestr(name, (bytes([data[0] ^ 1]) + data[1:]) if name.startswith("parts/") else data)
        with self.assertRaisesRegex(export.AllExportError, "hash/CRC"):
            self.run_export(resume=True)

    def test_batch_wrong_manifest_mapping_is_rejected(self):
        self.run_export()
        path = next(p for p in self.output.glob("chaos-all-*.zip") if export.BATCH_PATTERN.fullmatch(p.name))
        with zipfile.ZipFile(path) as archive:
            items = [(info.filename, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in items:
                if name == export.INDEX_MEMBER:
                    index = json.loads(data)
                    index["files"][0]["segments"][0]["physical_offset"] += 1
                    data = export.encode_json(index)
                archive.writestr(name, data)
        with self.assertRaisesRegex(export.AllExportError, "mapping"):
            export.verify_batch(path, self.metadata)

    def rewrite_index(self, path, mutate):
        with zipfile.ZipFile(path) as archive:
            items = [(info.filename, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in items:
                if name == export.INDEX_MEMBER:
                    index = json.loads(data)
                    mutate(index)
                    data = json.dumps(index).encode()
                archive.writestr(name, data)

    def test_resource_json_key_order_does_not_break_resume(self):
        self.run_export()
        path = next(p for p in self.output.glob("chaos-all-*.zip") if export.BATCH_PATTERN.fullmatch(p.name))
        def reorder(index):
            for entry in index["files"]:
                entry["resource"] = dict(reversed(list(entry["resource"].items())))
        self.rewrite_index(path, reorder)
        self.assertTrue(self.run_export(resume=True)["all_manifest_resources_exported"])

    def test_bool_float_resource_fields_rejected(self):
        self.run_export()
        path = next(p for p in self.output.glob("chaos-all-*.zip") if export.BATCH_PATTERN.fullmatch(p.name))
        original = path.read_bytes()
        for field, value in (("row", False), ("row", 0.0), ("compression", False)):
            path.write_bytes(original)
            self.rewrite_index(path, lambda index: index["files"][0]["resource"].__setitem__(field, value))
            with self.subTest(field=field, value=value), self.assertRaisesRegex(export.AllExportError, "differs"):
                export.verify_batch(path, self.metadata)

    def test_off_grid_or_short_fragments_rejected(self):
        self.run_export()
        path = next(p for p in self.output.glob("chaos-all-*.zip") if export.BATCH_PATTERN.fullmatch(p.name))
        original = path.read_bytes()
        for field, value in (("part_offset", 1), ("bytes", 89)):
            path.write_bytes(original)
            self.rewrite_index(path, lambda index: index["files"][0].__setitem__(field, value))
            with self.subTest(field=field), self.assertRaisesRegex(export.AllExportError, "byte count"):
                export.verify_batch(path, self.metadata)

    def test_missing_index_member_is_clean_error(self):
        self.run_export()
        path = next(p for p in self.output.glob("chaos-all-*.zip") if export.BATCH_PATTERN.fullmatch(p.name))
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("parts/000000-000000000000.bin", b"inert")
        with self.assertRaisesRegex(export.AllExportError, "missing a declared"):
            export.verify_batch(path, self.metadata)

    def test_chunk_cache_coalesces_adjacent_small_assets(self):
        runner = FakeRunner(self.manifest, self.chunks)
        cache = export.ChunkCache(runner, "emulator-5554", export.ranges.READERS[0], self.metadata["chunks"], export.DEFAULT_TOTAL_BYTES)
        for item in self.metadata["files"][:4]:
            segments = export.derive_segments(self.metadata, item, 0, item["stored_length"])
            data = b"".join(block for segment in segments for block in cache.read_segment(segment))
            self.assertEqual(len(data), item["stored_length"])
        self.assertEqual(len(runner.binary_calls), 1)

    def test_transfer_budget_rejects_overflow_before_read(self):
        runner = FakeRunner(self.manifest, self.chunks)
        cache = export.ChunkCache(runner, "emulator-5554", export.ranges.READERS[0], self.metadata["chunks"], 1)
        segment = export.derive_segments(self.metadata, self.metadata["files"][0], 0, 90)[0]
        with self.assertRaisesRegex(export.AllExportError, "transfer budget"):
            list(cache.read_segment(segment))
        self.assertEqual(runner.binary_calls, [])

    def test_metadata_only_reads_pinned_manifest_without_adb(self):
        manifest = self.root / "manifest.bin"
        manifest.write_bytes(self.manifest)
        with patch.object(android, "locate_adb", side_effect=AssertionError("ADB must not be used")), patch("sys.stdout", new=io.StringIO()) as stream:
            self.assertEqual(export.main(["--list-only", "--manifest", str(manifest)]), 0)
            report = json.loads(stream.getvalue())
        self.assertEqual(report["resources"], 6)
        self.assertFalse(report["payloads_received_by_this_command"])


if __name__ == "__main__":
    unittest.main()
