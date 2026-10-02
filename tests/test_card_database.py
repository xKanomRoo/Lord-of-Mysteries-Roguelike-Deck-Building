"""Synthetic DB storage fixtures; no reference game rows or native table literals."""
from pathlib import Path
import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import read_card_database as db
import read_game_text as resource


def u40(value):
    return bytes([value >> 32]) + struct.pack("<I", value & 0xffffffff)


def pack_records(records, buckets=1, footer=True):
    table_bytes = 5 + 5 * buckets
    offset = 38 + table_bytes
    locations = []
    for key, payload in records:
        locations.append(offset)
        offset += 15 + len(key) + len(payload)
    chains = [[] for _ in range(buckets)]
    for i, (key, _) in enumerate(records):
        value = 0
        for char in key.lower():
            value = (43 * value + char) & 0xffffffff
        chains[value % buckets].append(i)
    nexts = {}
    for chain in chains:
        for position, index in enumerate(chain):
            nexts[index] = locations[chain[position + 1]] if position + 1 < len(chain) else 0
    table = struct.pack("<IB", table_bytes, 1) + b"".join(u40(locations[chain[0]] if chain else 0) for chain in chains)
    chunks = []
    for i, (key, payload) in enumerate(records):
        size = 15 + len(key) + len(payload)
        chunks.append(struct.pack("<IBBI", size, 2, len(key), len(payload)) + u40(nexts[i]) + key + payload)
    header = bytearray(38)
    header[:8] = b"PLPcK\x01\x26\x00"
    struct.pack_into("<II", header, 17, 0, buckets)
    header[25:30] = u40(38)
    if footer:
        tail = bytearray(header)
        struct.pack_into("<I", tail, 17, len(records))
    else:
        tail = b""
    return bytes(header) + table + b"".join(chunks) + bytes(tail)


def records():
    return [(b"\trows", struct.pack("<I", 2)), (b"\tcols", struct.pack("<I", 3)),
            (b"\t0", b"id"), (b"\t1", b"cost"), (b"\t2", b"eff"),
            (b"\t\t0", b"original_a"), (b"original_a", b"original_a\x001\x00EFFECT_DRAW\x00"),
            (b"\t\t1", b"original_b"), (b"original_b", b"original_b\x002\x00EFFECT_GUARD\x00")]


def synthetic_elf():
    data = bytearray(512)
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", data, 16, 3, 183, 1)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HHH", data, 52, 64, 56, 1)
    struct.pack_into("<II6Q", data, 64, 1, 4, 256, resource.TABLE_VA, resource.TABLE_VA, 256, 256, 256)
    data[256:] = bytes((i * 7 + 3) % 256 for i in range(256))
    return bytes(data)


class CardDatabaseTests(unittest.TestCase):
    def test_schema_rows_indexes_footer_and_exact_field_offsets(self):
        data = pack_records(records())
        parsed = db.parse_database(data)
        self.assertEqual(parsed["row_count"], 2)
        self.assertEqual(parsed["column_count"], 3)
        self.assertEqual(parsed["linked_record_count"], 9)
        self.assertEqual(parsed["header"]["observed_counter"], 0)
        self.assertEqual(parsed["appended_header"]["updated_counter"], 9)
        self.assertEqual(parsed["coverage"]["covered_bytes"], len(data))
        count = parsed["count_metadata"]["rows"]
        self.assertEqual(resource.digest(data[count["payload_offset"]:count["payload_offset"] + 4]), count["payload_sha256"])
        row = parsed["rows"][0]
        self.assertEqual(resource.digest(data[row["index_payload_offset"]:row["index_payload_offset"] + len(row["id"])]), row["index_payload_sha256"])
        self.assertEqual(row["values"], {"id": "original_a", "cost": "1", "eff": "EFFECT_DRAW"})
        self.assertEqual(data[row["field_offsets"]["cost"]:row["field_offsets"]["cost"] + 2], b"1\0")
        self.assertEqual(resource.digest(data[row["payload_offset"]:row["payload_offset"] + row["payload_bytes"]]), row["payload_sha256"])

    def test_native_hash_bucket_membership_and_wrong_bucket(self):
        data = pack_records(records(), buckets=2)
        self.assertEqual(db.parse_database(data)["row_count"], 2)
        changed = bytearray(data)
        changed[43:48], changed[48:53] = changed[48:53], changed[43:48]
        with self.assertRaisesRegex(db.CardDatabaseError, "wrong hash bucket"):
            db.parse_database(bytes(changed))

    def test_footer_corruption_and_unknown_trailing_bytes_fail(self):
        data = bytearray(pack_records(records()))
        data[-21] ^= 1
        with self.assertRaisesRegex(db.CardDatabaseError, "trailing"):
            db.parse_database(bytes(data))
        with self.assertRaisesRegex(db.CardDatabaseError, "trailing"):
            db.parse_database(pack_records(records(), footer=False) + b"unexplained")

    def test_cycle_truncation_and_header_counter_disagreement(self):
        data = bytearray(pack_records(records()))
        data[58:63] = u40(48)
        with self.assertRaisesRegex(db.CardDatabaseError, "cyclic"):
            db.parse_database(bytes(data))
        with self.assertRaises(db.CardDatabaseError):
            db.parse_database(pack_records(records())[:-1])
        data = bytearray(pack_records(records(), footer=False))
        struct.pack_into("<I", data, 17, 8)
        with self.assertRaisesRegex(db.CardDatabaseError, "nonzero database header counter"):
            db.parse_database(bytes(data))

    def test_missing_malformed_or_bounded_count_metadata(self):
        values = records()
        for modified in [values[1:], [(b"\trows", b"\x02")]+values[1:],
                         [(b"\trows", struct.pack("<I", db.MAX_ROWS + 1))]+values[1:]]:
            with self.subTest(first=modified[0][0]), self.assertRaises(db.CardDatabaseError):
                db.parse_database(pack_records(modified))

    def test_declared_cell_budget_is_checked_before_building_row_metadata(self):
        declared = [(b"\trows", struct.pack("<I", db.MAX_ROWS)),
                    (b"\tcols", struct.pack("<I", db.MAX_COLUMNS))]
        with self.assertRaisesRegex(db.CardDatabaseError, "cell budget"):
            db.parse_database(pack_records(declared))

    def test_schema_labels_indexes_and_row_ids_must_agree(self):
        mutations = []
        values = records(); values[4] = (b"\t2", b"cost"); mutations.append(values)
        values = records(); values[7] = (b"\t\t1", b"original_a"); mutations.append(values)
        values = records(); values[5] = (b"\t\t0", b"missing"); mutations.append(values)
        values = records(); values[6] = (b"original_a", b"wrong\x001\x00EFFECT_DRAW\x00"); mutations.append(values)
        values = records(); values[6] = (b"original_a", b"original_a\x001\x00"); mutations.append(values)
        values = records(); values[6] = (b"original_a", b"original_a\x001\x00EFFECT_DRAW"); mutations.append(values)
        for mutation in mutations:
            with self.subTest(mutation=mutation[5][0]), self.assertRaises(db.CardDatabaseError):
                db.parse_database(pack_records(mutation))

    def test_unicode_fields_are_preserved_and_offsets_are_byte_offsets(self):
        values = records()
        values[6] = (b"original_a", "original_a\0é\0EFFECT_DRAW\0".encode("utf-8"))
        data = pack_records(values)
        row = db.parse_database(data)["rows"][0]
        self.assertEqual(row["values"]["cost"], "é")
        self.assertEqual(row["field_offsets"]["eff"] - row["field_offsets"]["cost"], 3)
        values[6] = (b"original_a", b"original_a\0\xff\0EFFECT_DRAW\0")
        with self.assertRaisesRegex(db.CardDatabaseError, "UTF-8"):
            db.parse_database(pack_records(values))

    def test_encrypted_and_unknown_records_are_rejected(self):
        with self.assertRaisesRegex(db.CardDatabaseError, "Encrypted"):
            db.parse_database(pack_records(records() + [(b"\x1b\x01", b"\x01\0\0\0")]))
        with self.assertRaisesRegex(db.CardDatabaseError, "unsupported or unindexed"):
            db.parse_database(pack_records(records() + [(b"unknown", b"uninterpreted")]))
        with self.assertRaisesRegex(db.CardDatabaseError, "duplicate database record key"):
            db.parse_database(pack_records(records() + [records()[0]]))

    def test_wrong_native_hash_input_hash_and_existing_output_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, native, output = root / "input.bin", root / "native.so", root / "out"
            source.write_bytes(pack_records(records())); native.write_bytes(synthetic_elf())
            with self.assertRaisesRegex(db.CardDatabaseError, "Native source SHA"):
                db.read_database(source, native, output)
            with self.assertRaisesRegex(db.CardDatabaseError, "input SHA"):
                db.read_database(source, native, output, "0" * 64)
            output.mkdir(); (output / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(db.CardDatabaseError, "preserved"):
                db.read_database(source, native, output)
            self.assertEqual((output / "keep.txt").read_text(), "keep")

    def test_private_outputs_and_bounded_publication_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plain = pack_records(records()); native_bytes = synthetic_elf()
            encoded = resource.transform_resource(plain, resource.native_default_table(native_bytes))
            source, native = root / "input.bin", root / "native.so"
            source.write_bytes(encoded); native.write_bytes(native_bytes)
            with patch.object(resource, "NATIVE_SHA256", resource.digest(native_bytes)):
                summary = db.read_database(source, native, root / "out", resource.digest(encoded))
                self.assertEqual((root / "out/database.bin").read_bytes(), plain)
                rows = json.loads((root / "out/rows.json").read_text())["rows"]
                self.assertEqual(rows[1]["values"]["cost"], "2")
                self.assertNotIn("rows", summary)
                with patch.object(db, "MAX_OUTPUT_BYTES", 1):
                    with self.assertRaisesRegex(db.CardDatabaseError, "index exceeds"):
                        db.read_database(source, native, root / "failed")
                self.assertFalse((root / "failed").exists())
                self.assertEqual(list(root.glob(".card-db-stage-*")), [])

    def test_cli_wrong_source_reports_only_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, native = root / "input.bin", root / "native.so"
            source.write_bytes(pack_records(records())); native.write_bytes(synthetic_elf())
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = db.main(["--input", str(source), "--native-library", str(native), "--output", str(root / "out")])
            self.assertEqual(status, 1); self.assertEqual(out.getvalue(), "")
            self.assertNotIn("original_a", err.getvalue())


if __name__ == "__main__":
    unittest.main()
