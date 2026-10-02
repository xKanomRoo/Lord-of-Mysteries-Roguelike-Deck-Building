import hashlib
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.read_ssra_manifest import SSRAError, parse_ssra, read_ssra, write_index, xxh64


def fixture():
    """Independent small v4 layout; checksums fixed from standard XXH64 vectors."""
    names = [b"lang_en_b00_0.ssrc", b"lang_en_b01_0.ssrc", b"base_b00_0.ssrc",
             b"text/en/text.db", b"cards/one.json", "cards/ไทย.json".encode()]
    offsets, blob = [], bytearray()
    for name in names:
        offsets.append(len(blob))
        blob.extend(name + b"\0")
    chunks = b"".join(struct.pack("<IHHQQQ", index, group, 1, logical, logical + 16, 123 + row)
                       for row, (index, group, logical) in enumerate(((0, 2, 8), (1, 2, 8), (0, 12, 32))))
    entries = []
    for row, (pathhash, offset, stored, decoded, compression, group) in enumerate((
            (0x5055F45E1B303D0F, 6, 6, 12, 1, 2),
            (0x835AD41A8CAFC87A, 0, 8, 8, 0, 12),
            (0xF933FE7A04D90D60, 16, 8, 8, 0, 12))):
        entries.append(struct.pack("<QQ4IBBHB3s", pathhash, offset, stored, decoded,
                                   0, offsets[3 + row], compression, 0, group, 0, bytes(3)))
    files = b"".join(entries)
    path_offset = 64 + len(chunks) + len(files)
    header = struct.pack("<4s5I4Q2I", b"SSRA", 4, 88, 3, 3, 7,
                         path_offset, len(blob), 64, 64 + len(chunks), 28, 0)
    group_blob = b"lang_en\0lang.en\0base\0*\0"
    groups = struct.pack("<4sIII", b"GRPS", 2, len(group_blob), 0)
    groups += struct.pack("<HH5I", 2, 0, 0, 8, 0, 2, 1)
    groups += struct.pack("<HH5I", 12, 0, 16, 21, 2, 1, 2) + group_blob
    cnames = struct.pack("<4sIII", b"CNAM", 3, 0, 0)
    cnames += b"".join(struct.pack("<II", row, offsets[row]) for row in range(3))
    labels = b"target/base/260930\0" + b"a" * 40 + b"\0"
    meta = struct.pack("<4sIII", b"META", len(labels), 0, 19) + labels
    hashes = struct.pack("<4sIII", b"FHSH", 3, 1, 0) + struct.pack("<3Q", 1, 2, 3)
    return bytearray(header + chunks + files + blob + groups + cnames + meta + hashes)


class SSRAManifestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_standard_xxh64_vectors_all_input_widths(self):
        for data, expected in ((b"", 0xEF46DB3751D8E999), (b"a", 0xD24EC4F1A98C6E5B),
                               (b"abc", 0x44BC2CF5AD770999),
                               (b"abcdefghijklmno", 0x2E1218A2B1375068),
                               (bytes(range(96)), 0x450BAA11F6739216),
                               (b"123456789012345678901234567890123456789", 0x490AFD8C09F2040B)):
            self.assertEqual(xxh64(data), expected)
        self.assertEqual(xxh64(bytes(range(96)), seed=42), 0x07D87B45EF55D042)

    def test_schema_optional_sections_utf8_and_cross_chunk_ranges(self):
        data = fixture()
        result = parse_ssra(data)
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(result["coverage"]["covered_bytes"], len(data))
        self.assertEqual(result["chunks"][1]["logical_start"], 8)
        self.assertEqual(result["chunks"][2]["logical_start"], 0)
        self.assertEqual(result["chunks"][2]["filename"], "base_b00_0.ssrc")
        self.assertEqual(result["files"][2]["path"], "cards/ไทย.json")
        self.assertEqual(result["files"][0]["offset"], 6)
        self.assertEqual(result["files"][0]["file_hash64"], 1)
        self.assertEqual([s["tag"] for s in result["sections"]], ["GRPS", "CNAM", "META", "FHSH"])
        self.assertEqual(result["groups"][1]["file_count"], 2)
        self.assertEqual(result["build_metadata"]["target_label"], "target/base/260930")
        self.assertEqual(result["header"]["unknown8"], 88)
        self.assertEqual(result["header"]["unknown56"], 28)

    def test_minimal_v4_and_no_guessed_filenames_without_cnam(self):
        data = fixture()
        path_end = sum(struct.unpack_from("<QQ", data, 24))
        struct.pack_into("<I", data, 20, 0)
        result = parse_ssra(data[:path_end])
        self.assertEqual(result["sections"], [])
        self.assertTrue(all(item["filename"] is None for item in result["chunks"]))
        empty = struct.pack("<4s5I4Q2I", b"SSRA", 4, 0, 0, 0, 0, 64, 0, 64, 64, 0, 0)
        self.assertEqual(parse_ssra(empty)["files"], [])

    def test_source_hash_before_writing_new_output_only_and_no_assets(self):
        source = self.root / "manifest.ssra"
        data = fixture()
        source.write_bytes(data)
        output = self.root / "index"
        with self.assertRaisesRegex(SSRAError, "SHA-256 mismatch"):
            write_index(source, output, "0" * 64)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(SSRAError, "Expected SHA-256"):
            read_ssra(source, "bad")
        result = write_index(source, output, hashlib.sha256(data).hexdigest())
        self.assertEqual(set(p.name for p in output.iterdir()), {"manifest-index.json", "paths.tsv"})
        self.assertEqual(json.loads((output / "manifest-index.json").read_text()), result)
        for item in output.iterdir():
            self.assertFalse(item.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        with self.assertRaisesRegex(SSRAError, "preserved"):
            write_index(source, output)
        self.assertEqual(len(list(output.iterdir())), 2)

    def test_observed_zero_width_space_preserves_path_hash_and_is_visible_in_inventory(self):
        data = fixture()
        original = b"cards/one.json"
        replacement = "card/\u200bone.db".encode("utf-8")
        self.assertEqual(len(original), len(replacement))
        start = data.index(original)
        data[start:start + len(original)] = replacement
        file_offset = struct.unpack_from("<Q", data, 48)[0]
        struct.pack_into("<Q", data, file_offset + 40, xxh64(replacement))
        source = self.root / "manifest.ssra"
        source.write_bytes(data)
        result = write_index(source, self.root / "index")
        self.assertEqual(result["files"][1]["path"], replacement.decode("utf-8"))
        self.assertEqual(result["files"][1]["path_hash64"], xxh64(replacement))
        self.assertEqual(result["files"][1]["path_format_characters"], ["U+200B ZERO WIDTH SPACE"])
        for name in ("paths.tsv", "manifest-index.json"):
            visible = (self.root / "index" / name).read_text()
            self.assertIn("\\u200b", visible)
            self.assertNotIn("\u200b", visible)

    def test_truncated_magic_version_count_limits_and_unknown_flags(self):
        data = fixture()
        for offset, value in ((0, 0), (4, 5), (12, 10001), (16, 200001), (20, 8), (60, 1)):
            malformed = bytearray(data)
            struct.pack_into("<I", malformed, offset, value)
            with self.subTest(offset=offset), self.assertRaises(SSRAError):
                parse_ssra(malformed)
        for end in (0, 63, len(data) - 1):
            with self.assertRaises(SSRAError):
                parse_ssra(data[:end])
        with patch("tools.read_ssra_manifest.MAX_FILE_BYTES", len(data) - 1):
            with self.assertRaisesRegex(SSRAError, "32 MiB"):
                parse_ssra(data)

    def test_large_unsigned_offsets_bounds_overlap_gaps_and_trailers(self):
        data = fixture()
        for offset, value in ((24, (1 << 64) - 1), (32, (1 << 64) - 1), (40, 32), (48, 65)):
            malformed = bytearray(data)
            struct.pack_into("<Q", malformed, offset, value)
            with self.subTest(offset=offset), self.assertRaises(SSRAError):
                parse_ssra(malformed)
        with self.assertRaisesRegex(SSRAError, "trailing"):
            parse_ssra(data + b"unindexed")

    def test_bad_strings_unsafe_paths_start_offsets_and_checksum(self):
        data = fixture()
        path_offset = struct.unpack_from("<Q", data, 24)[0]
        file_offset = struct.unpack_from("<Q", data, 48)[0]
        name_offset = struct.unpack_from("<I", data, file_offset + 28)[0]
        for payload in (b"../bad/name.bin", b"/etc/passwdxxx", b"bad\\slash/file", b"bad:drive/file",
                        b"bad\tcontrolxxx", "bad\u202ereverse".encode(),
                        "bad\u0085control".encode(), b"\xff" + b"x" * 13):
            malformed = bytearray(data)
            malformed[path_offset + name_offset:path_offset + name_offset + 14] = payload[:14].ljust(14, b"x")
            with self.subTest(payload=payload), self.assertRaises(SSRAError):
                parse_ssra(malformed)
        shifted = bytearray(data)
        struct.pack_into("<I", shifted, file_offset + 28, name_offset + 1)
        with self.assertRaisesRegex(SSRAError, "string start"):
            parse_ssra(shifted)
        changed = bytearray(data)
        changed[path_offset + name_offset] = ord("z")
        with self.assertRaisesRegex(SSRAError, "checksum"):
            parse_ssra(changed)
        with patch("tools.read_ssra_manifest.MAX_STRING_BYTES", 4):
            with self.assertRaisesRegex(SSRAError, "unterminated"):
                parse_ssra(data)

    def test_duplicate_records_out_of_group_ranges_and_selectors(self):
        data = fixture()
        file_offset = struct.unpack_from("<Q", data, 48)[0]
        duplicate_chunk = bytearray(data)
        duplicate_chunk[96:104] = duplicate_chunk[64:72]
        with self.assertRaisesRegex(SSRAError, "Duplicate chunk"):
            parse_ssra(duplicate_chunk)
        duplicate_path = bytearray(data)
        duplicate_path[file_offset + 40:file_offset + 48] = duplicate_path[file_offset:file_offset + 8]
        duplicate_path[file_offset + 68:file_offset + 72] = duplicate_path[file_offset + 28:file_offset + 32]
        with self.assertRaisesRegex(SSRAError, "Duplicate resource"):
            parse_ssra(duplicate_path)
        for relative_offset, fmt, value in ((8, "<Q", 20), (20, "<I", 100),
                                             (32, "<B", 2), (33, "<B", 2), (36, "<B", 2)):
            malformed = bytearray(data)
            target_row = 1 if relative_offset == 20 else 0
            struct.pack_into(fmt, malformed, file_offset + target_row * 40 + relative_offset, value)
            with self.subTest(offset=relative_offset), self.assertRaises(SSRAError):
                parse_ssra(malformed)

    def test_extension_group_cnam_and_hash_count_mapping_validation(self):
        data = fixture()
        positions = {tag: data.index(tag) for tag in (b"GRPS", b"CNAM", b"META", b"FHSH")}
        for offset, value in ((positions[b"GRPS"] + 16 + 12, 1),
                              (positions[b"GRPS"] + 16 + 20, 2),
                              (positions[b"CNAM"] + 16 + 8, 0),
                              (positions[b"CNAM"] + 16, 3),
                              (positions[b"META"] + 8, 1),
                              (positions[b"FHSH"] + 4, 4),
                              (positions[b"FHSH"] + 8, 2)):
            malformed = bytearray(data)
            struct.pack_into("<I", malformed, offset, value)
            with self.subTest(offset=offset), self.assertRaises(SSRAError):
                parse_ssra(malformed)
        malformed = bytearray(data)
        malformed[positions[b"GRPS"]] = ord("X")
        with self.assertRaisesRegex(SSRAError, "GRPS"):
            parse_ssra(malformed)

    def test_output_budget_before_directory_creation(self):
        source = self.root / "manifest.ssra"
        source.write_bytes(fixture())
        output = self.root / "large-index"
        with patch("tools.read_ssra_manifest.MAX_INDEX_BYTES", 10):
            with self.assertRaisesRegex(SSRAError, "bounded output"):
                write_index(source, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
