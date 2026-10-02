import hashlib
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.read_plpck import PLPcKError, parse_plpck, read_plpck, write_index


def u40(value):
    return bytes([value >> 32]) + struct.pack("<I", value & 0xFFFFFFFF)


def container(items=None, buckets=2):
    """Independent minimal fixture, including a linked bucket chain."""
    items = items if items is not None else [(b"init.js", b"\xb7\x05\xde\xc0opaque cache"),
                                            ("types/ไทย.js".encode(), b"second payload")]
    header = bytearray(38)
    header[:5] = b"PLPcK"
    header[5] = 1
    struct.pack_into("<H", header, 6, 38)
    struct.pack_into("<II", header, 17, len(items), buckets)
    header[25:30] = u40(38)
    table = bytearray(struct.pack("<I", 5 + 5 * buckets) + b"\x01" + bytes(5 * buckets))
    offsets = []
    records = []
    cursor = len(header) + len(table)
    for key, payload in items:
        offsets.append(cursor)
        total = 15 + len(key) + len(payload)
        records.append(bytearray(struct.pack("<IBBI", total, 2, len(key), len(payload))
                                 + bytes(5) + key + payload))
        cursor += total
    for index, record in enumerate(records[:-1]):
        record[10:15] = u40(offsets[index + 1])
    if offsets:
        table[5:10] = u40(offsets[0])
    return bytearray(header + table + b"".join(records)), offsets


class PLPcKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "synthetic.jbin"

    def test_linked_records_utf8_payload_hashes_and_complete_coverage(self):
        data, offsets = container()
        result = parse_plpck(data)
        self.assertEqual(result["header"]["record_count"], 2)
        self.assertEqual(result["records"][0]["next_offset"], offsets[1])
        self.assertEqual(result["records"][1]["key"], "types/ไทย.js")
        self.assertEqual(result["records"][1]["payload_sha256"],
                         hashlib.sha256(b"second payload").hexdigest())
        self.assertEqual(result["records"][0]["payload_kind"], "v8_cached_data_magic_observed")
        self.assertEqual(result["coverage"]["covered_bytes"], len(data))
        self.assertTrue(result["static_only"])

    def test_default_indexes_only_and_extracts_to_inert_hashed_paths(self):
        data, _ = container([(b"../../outside.py", b"opaque bytes"),
                             (b"alias.js", b"opaque bytes")])
        self.source.write_bytes(data)
        indexed = self.root / "index-only"
        write_index(self.source, indexed)
        self.assertEqual([p.name for p in indexed.iterdir()], ["index.json"])
        extracted = self.root / "extracted"
        report = write_index(self.source, extracted, extract_payloads=True)
        output_files = list((extracted / "payloads").iterdir())
        self.assertEqual(len(output_files), 1)
        self.assertEqual(output_files[0].name, hashlib.sha256(b"opaque bytes").hexdigest() + ".bin")
        self.assertEqual(output_files[0].read_bytes(), b"opaque bytes")
        self.assertFalse(output_files[0].stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        self.assertFalse((self.root / "outside.py").exists())
        self.assertEqual(json.loads((extracted / "index.json").read_text()), report)

    def test_wrong_hash_and_invalid_container_fail_before_output(self):
        data, _ = container()
        self.source.write_bytes(data)
        output = self.root / "output"
        with self.assertRaisesRegex(PLPcKError, "SHA-256 mismatch"):
            write_index(self.source, output, "0" * 64)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(PLPcKError, "Expected SHA-256"):
            read_plpck(self.source, "not a hash")
        self.source.write_bytes(data[:-1])
        with self.assertRaises(PLPcKError):
            write_index(self.source, output, extract_payloads=True)
        self.assertFalse(output.exists())

    def test_existing_research_is_preserved(self):
        data, _ = container()
        self.source.write_bytes(data)
        output = self.root / "research"
        output.mkdir()
        keep = output / "user-notes.txt"
        keep.write_text("keep this")
        with self.assertRaisesRegex(PLPcKError, "preserved"):
            write_index(self.source, output)
        self.assertEqual(keep.read_text(), "keep this")
        self.assertEqual(len(list(output.iterdir())), 1)

    def test_truncated_signature_version_table_size_and_flags(self):
        data, offsets = container()
        variants = [data[:20], data[:45]]
        for offset, value in [(0, ord("X")), (5, 2), (6, 39),
                              (38, 255), (42, 2), (offsets[0] + 4, 1)]:
            malformed = bytearray(data)
            malformed[offset] = value
            variants.append(malformed)
        for malformed in variants:
            with self.subTest(data=bytes(malformed[:8])):
                with self.assertRaises(PLPcKError):
                    parse_plpck(malformed)

    def test_u40_high_byte_and_out_of_bounds_table_and_record_pointers(self):
        data, _ = container()
        for pointer_offset in (25, 43):
            for pointer in (len(data) + 1, 1 << 32):
                with self.subTest(offset=pointer_offset, pointer=pointer):
                    malformed = bytearray(data)
                    malformed[pointer_offset:pointer_offset + 5] = u40(pointer)
                    with self.assertRaisesRegex(PLPcKError, "out-of-bounds"):
                        parse_plpck(malformed)

    def test_cycles_duplicate_bucket_pointers_and_duplicate_keys(self):
        data, offsets = container()
        cycle = bytearray(data)
        cycle[offsets[1] + 10:offsets[1] + 15] = u40(offsets[0])
        duplicate_pointer = bytearray(data)
        duplicate_pointer[48:53] = u40(offsets[0])
        for malformed in (cycle, duplicate_pointer):
            with self.assertRaisesRegex(PLPcKError, "Duplicate or cyclic"):
                parse_plpck(malformed)
        duplicate_key, _ = container([(b"same.js", b"one"), (b"same.js", b"two")])
        with self.assertRaisesRegex(PLPcKError, "Duplicate record key"):
            parse_plpck(duplicate_key)

    def test_count_limits_and_header_count_disagreement(self):
        data, _ = container()
        for offset, value in ((17, 3), (17, 20_001), (21, 0), (21, 65_537)):
            malformed = bytearray(data)
            struct.pack_into("<I", malformed, offset, value)
            with self.subTest(offset=offset, value=value):
                with self.assertRaisesRegex(PLPcKError, "count"):
                    parse_plpck(malformed)
        with patch("tools.read_plpck.MAX_FILE_BYTES", len(data) - 1):
            with self.assertRaisesRegex(PLPcKError, "32 MiB"):
                parse_plpck(data)

    def test_bad_record_lengths_and_invalid_text(self):
        data, offsets = container()
        struct.pack_into("<I", data, offsets[0] + 6, 1)
        with self.assertRaisesRegex(PLPcKError, "lengths disagree"):
            parse_plpck(data)
        for key in (b"\xff", b"bad\x00name", b""):
            malformed, _ = container([(key, b"payload")])
            with self.subTest(key=key):
                with self.assertRaisesRegex(PLPcKError, "key"):
                    parse_plpck(malformed)

    def test_metadata_overlap_record_overlap_and_unindexed_trailer(self):
        data, offsets = container()
        metadata = bytearray(data)
        metadata[43:48] = u40(38)
        with self.assertRaisesRegex(PLPcKError, "metadata"):
            parse_plpck(metadata)
        overlap = bytearray(data)
        first_total = struct.unpack_from("<I", overlap, offsets[0])[0]
        first_payload = struct.unpack_from("<I", overlap, offsets[0] + 6)[0]
        struct.pack_into("<I", overlap, offsets[0], first_total + 2)
        struct.pack_into("<I", overlap, offsets[0] + 6, first_payload + 2)
        with self.assertRaisesRegex(PLPcKError, "Overlapping"):
            parse_plpck(overlap)
        with self.assertRaisesRegex(PLPcKError, "trailing bytes"):
            parse_plpck(data + b"unindexed")

    def test_missing_coverage_and_empty_container(self):
        data, offsets = container([(b"one.js", b"payload")])
        gap = bytearray(data[:offsets[0]] + b"\x00" + data[offsets[0]:])
        gap[43:48] = u40(offsets[0] + 1)
        with self.assertRaisesRegex(PLPcKError, "unindexed bytes"):
            parse_plpck(gap)
        empty, _ = container([])
        self.assertEqual(parse_plpck(empty)["records"], [])


if __name__ == "__main__":
    unittest.main()
