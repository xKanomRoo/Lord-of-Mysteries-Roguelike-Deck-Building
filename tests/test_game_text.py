"""Synthetic containers test static decoding; no reference text or table is stored."""
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
import read_game_text as game_text


def u40(value):
    return bytes([value >> 32]) + struct.pack("<I", value & 0xffffffff)


def container(rows):
    bucket_count = 1
    table = struct.pack("<IB", 10, 1) + u40(48)
    chunks = []
    offset = 48
    for ordinal, (key, payload) in enumerate(rows):
        size = 15 + len(key) + len(payload)
        nxt = offset + size if ordinal + 1 < len(rows) else 0
        chunks.append(struct.pack("<IBBI", size, 2, len(key), len(payload)) + u40(nxt) + key + payload)
        offset += size
    header = bytearray(38)
    header[:8] = b"PLPcK\x01\x26\x00"
    struct.pack_into("<II", header, 17, len(rows), bucket_count)
    header[25:30] = u40(38)
    return bytes(header) + table + b"".join(chunks)


def text_container(value=b"Draw two cards"):
    key = b"card@desc@original_test"
    return container([(key, key + b"\0" + value + b"\0"), (b"\t\t0", key), (b"\xffmetadata", b"\x01\x00")])


def synthetic_elf():
    data = bytearray(512)
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", data, 16, 3, 183, 1)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HHH", data, 52, 64, 56, 1)
    struct.pack_into("<II6Q", data, 64, 1, 4, 256, game_text.TABLE_VA, game_text.TABLE_VA, 256, 256, 256)
    data[256:] = bytes((i * 7 + 3) % 256 for i in range(256))
    return bytes(data)


class GameTextTests(unittest.TestCase):
    def test_size_seed_transform_and_binary_internal_labels(self):
        plain = text_container()
        table = game_text.native_default_table(synthetic_elf())
        encoded = game_text.transform_resource(plain, table)
        self.assertNotEqual(encoded[:5], plain[:5])
        parsed = game_text.parse_game_text(game_text.transform_resource(encoded, table))
        self.assertEqual(parsed["coverage"], {"status": "complete_nonoverlapping", "covered_bytes": len(plain)})
        self.assertEqual(parsed["text_entry_count"], 1)
        self.assertEqual(parsed["record_forms"]["internal_row_index"], 1)
        self.assertEqual(parsed["uninterpreted_metadata"][0]["key_hex"], b"\xffmetadata".hex())
        self.assertEqual(parsed["entries"][0]["text"], "Draw two cards")

    def test_native_mapping_rejects_wrong_architecture_and_truncated_segment(self):
        wrong = bytearray(synthetic_elf())
        struct.pack_into("<H", wrong, 18, 62)
        with self.assertRaisesRegex(game_text.GameTextError, "AArch64"):
            game_text.native_default_table(bytes(wrong))
        with self.assertRaisesRegex(game_text.GameTextError, "bounds"):
            game_text.native_default_table(synthetic_elf()[:-1])

    def test_native_mapping_rejects_overlapping_table_mappings(self):
        data = bytearray(synthetic_elf())
        struct.pack_into("<H", data, 56, 2)
        data[120:176] = data[64:120]
        with self.assertRaisesRegex(game_text.GameTextError, "unique"):
            game_text.native_default_table(bytes(data))

    def test_cycle_and_header_count_disagreement(self):
        data = bytearray(text_container())
        data[58:63] = u40(48)
        with self.assertRaisesRegex(game_text.GameTextError, "cyclic"):
            game_text.parse_game_text(bytes(data))
        data = bytearray(text_container())
        struct.pack_into("<I", data, 17, 4)
        with self.assertRaisesRegex(game_text.GameTextError, "disagrees"):
            game_text.parse_game_text(bytes(data))

    def test_record_spans_lengths_duplicate_keys_and_trailing_bytes(self):
        data = bytearray(text_container())
        struct.pack_into("<I", data, 54, 100000)
        with self.assertRaisesRegex(game_text.GameTextError, "lengths"):
            game_text.parse_game_text(bytes(data))
        with self.assertRaisesRegex(game_text.GameTextError, "duplicate record key"):
            game_text.parse_game_text(container([(b"a", b"a\0one\0"), (b"a", b"a\0two\0")]))
        with self.assertRaisesRegex(game_text.GameTextError, "trailing"):
            game_text.parse_game_text(text_container() + b"unused")
        with self.assertRaises(game_text.GameTextError):
            game_text.parse_game_text(text_container()[:-1])

    def test_recognized_text_requires_utf8_and_no_extra_field_delimiters(self):
        with self.assertRaisesRegex(game_text.GameTextError, "UTF-8"):
            game_text.parse_game_text(text_container(b"\xff"))
        with self.assertRaisesRegex(game_text.GameTextError, "delimiter"):
            game_text.parse_game_text(text_container(b"first\0second"))
        parsed = game_text.parse_game_text(container([(b"good", b"good\0text\0"), (b"unknown", b"wrong\0text\0")]))
        self.assertEqual(parsed["text_entry_count"], 1)
        self.assertEqual(parsed["record_forms"]["metadata_or_uninterpreted"], 1)

    def test_resource_and_count_bounds(self):
        data = text_container()
        with patch.object(game_text, "MAX_FILE_BYTES", len(data) - 1):
            with self.assertRaisesRegex(game_text.GameTextError, "64 MiB"):
                game_text.parse_game_text(data)
        with patch.object(game_text, "MAX_RECORDS", 2):
            with self.assertRaisesRegex(game_text.GameTextError, "limits"):
                game_text.parse_game_text(data)
        with self.assertRaises(game_text.GameTextError):
            game_text.transform_resource(data, b"not a table")

    def test_search_bounded_excerpts_offsets_case_and_limits(self):
        parsed = game_text.parse_game_text(text_container(b"x" * 1500 + b" DRAW " + b"y" * 1500))
        result = game_text.search_entries(parsed["entries"], "draw", 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["text"]), game_text.MAX_EXCERPT_CHARS)
        self.assertIn("DRAW", result[0]["text"])
        self.assertTrue(result[0]["text_truncated"])
        self.assertEqual(result[0]["record_offset"], 48)
        self.assertEqual(game_text.search_entries(parsed["entries"], "CARD@DESC", 1)[0]["key"], "card@desc@original_test")
        for query, limit in [("", 1), ("x" * 201, 1), ("card", 0), ("card", 101), ("card", True)]:
            with self.subTest(query=query[:4], limit=limit), self.assertRaises(game_text.GameTextError):
                game_text.search_entries(parsed["entries"], query, limit)

    def test_search_expanding_case_fold_preserves_original_excerpt_offset(self):
        text = "ß" * 1600 + " DRAW " + "y" * 1600
        parsed = game_text.parse_game_text(text_container(text.encode("utf-8")))
        result = game_text.search_entries(parsed["entries"], "draw", 1)[0]
        self.assertIn("DRAW", result["text"])
        self.assertEqual(result["excerpt_start"], text.index("DRAW") - game_text.MAX_EXCERPT_CHARS // 3)
        self.assertEqual(result["text"], text[result["excerpt_start"]:result["excerpt_start"] + game_text.MAX_EXCERPT_CHARS])
        self.assertEqual(result["excerpt_start"] + result["text"].index("DRAW"), text.index("DRAW"))
        expanded_term = game_text.search_entries(parsed["entries"], "SS", 1)[0]
        self.assertIn("ss", expanded_term["text"].casefold())
        self.assertEqual(expanded_term["excerpt_start"], 0)

    def test_wrong_native_source_and_existing_output_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, native, output = root / "input.bin", root / "native.so", root / "out"
            source.write_bytes(text_container())
            native.write_bytes(synthetic_elf())
            with self.assertRaisesRegex(game_text.GameTextError, "SHA-256"):
                game_text.decode_game_text(source, native, output)
            self.assertFalse(output.exists())
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("existing research")
            with self.assertRaisesRegex(game_text.GameTextError, "preserved"):
                game_text.decode_game_text(source, native, output)
            self.assertEqual(sentinel.read_text(), "existing research")

    def test_successful_private_outputs_and_bounded_publication_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native_bytes = synthetic_elf()
            plain = text_container()
            encoded = game_text.transform_resource(plain, game_text.native_default_table(native_bytes))
            source, native = root / "input.bin", root / "native.so"
            source.write_bytes(encoded)
            native.write_bytes(native_bytes)
            # A synthetic source hash is injected only in this fixture; production
            # CLI accepts only the observed native source hash.
            with patch.object(game_text, "NATIVE_SHA256", game_text.digest(native_bytes)):
                summary = game_text.decode_game_text(source, native, root / "out", "draw", 1)
                self.assertEqual((root / "out/text-db.bin").read_bytes(), plain)
                self.assertEqual(json.loads((root / "out/query.json").read_text())["entries"][0]["text"], "Draw two cards")
                self.assertEqual(summary["source"]["sha256"], game_text.digest(plain))
                self.assertNotIn("entries", summary)
                with patch.object(game_text, "MAX_INDEX_BYTES", 1):
                    with self.assertRaisesRegex(game_text.GameTextError, "index exceeds"):
                        game_text.decode_game_text(source, native, root / "failed")
                self.assertFalse((root / "failed").exists())
                self.assertEqual(list(root.glob(".game-text-stage-*")), [])

    def test_cli_failures_do_not_print_text_or_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "input.bin").write_bytes(text_container())
            (root / "native.so").write_bytes(synthetic_elf())
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = game_text.main(["--input", str(root / "input.bin"), "--native-library", str(root / "native.so"), "--output", str(root / "out")])
            self.assertEqual(code, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertNotIn("Draw two cards", err.getvalue())


if __name__ == "__main__":
    unittest.main()
