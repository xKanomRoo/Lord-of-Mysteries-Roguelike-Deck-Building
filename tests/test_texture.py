import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

from tools.decode_texture import (
    MAX_DECODED_BYTES, TextureDecodeError, decode_lz4_block, decode_sct1_rgba, decode_sct2_rgba,
    encode_png_rgba, inspect_file, inspect_scsp, inspect_sct, main,
)


def literal_block(data):
    """An independently constructed literal-only LZ4 raw block."""
    if len(data) < 15:
        return bytes([len(data) << 4]) + data
    remainder = len(data) - 15
    extension = bytearray()
    while remainder >= 255:
        extension.append(255)
        remainder -= 255
    extension.append(remainder)
    return b"\xf0" + extension + data


def sct1(width=2, height=2, words=(0xF800, 0x07E0, 0x001F, 0xFFFF),
         alpha=b"\xff\x80\x00\x40", format_number=4):
    raw = struct.pack("<" + "H" * len(words), *words) + alpha
    compressed = literal_block(raw)
    return (b"SCT\x01" + bytes([format_number])
            + struct.pack("<HHII", width, height, len(raw), len(compressed)) + compressed)


def sct2(payload=None, width=4, height=4, format_number=40, compressed=False):
    if payload is None:
        payload = bytes(range(16))
    flags = 0x80000011 if compressed else 0x11
    if compressed:
        encoded = literal_block(payload)
        payload = struct.pack("<II", len(payload), len(encoded)) + encoded
    # The header length is a field; 36 is the minimum structural header.
    header = (b"SCT2" + struct.pack("<IIIII", 36 + len(payload), zlib.crc32(payload),
                                    36, 4, format_number)
              + struct.pack("<HHHHI", width, height, width, height, flags))
    return header + payload


def scsp(binary=b"scsp1u\0\0", strings=b"opaque\x00" + b"3.8.79.scsp\x00root\x00intro\x00secret-value\x00"):
    raw = struct.pack("<II", len(binary), len(strings)) + binary + strings
    compressed = literal_block(raw)
    return struct.pack("<II", len(raw), len(compressed)) + compressed


def parse_png(data):
    """Independent PNG chunk/CRC validator for checking our generated output."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("bad PNG signature")
    chunks = []
    offset = 8
    while offset < len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + size]
        checksum = struct.unpack_from(">I", data, offset + 8 + size)[0]
        if checksum != zlib.crc32(kind + body):
            raise AssertionError("bad PNG CRC")
        chunks.append((kind, body))
        offset += size + 12
    return chunks


class Lz4Tests(unittest.TestCase):
    def test_literal_extension_and_exact_length(self):
        data = bytes(range(256)) * 3
        self.assertEqual(decode_lz4_block(literal_block(data), len(data)), data)
        self.assertEqual(decode_lz4_block(b"", 0), b"")
        with self.assertRaisesRegex(TextureDecodeError, "output length"):
            decode_lz4_block(literal_block(data), len(data) + 1)

    def test_overlapping_match_can_read_its_own_new_bytes(self):
        # Two literal bytes AB, a six-byte match at distance two, then Z.
        compressed = b"\x22AB\x02\x00\x10Z"
        self.assertEqual(decode_lz4_block(compressed, 9), b"ABABABABZ")
        self.assertEqual(decode_lz4_block(b"\x10a\x01\0", 5), b"aaaaa")

    def test_truncation_invalid_offsets_and_overruns(self):
        cases = [
            (b"\xf0", 20), (b"\x30ab", 3), (b"\x10a\x01", 5),
            (b"\x10a\0\0", 5), (b"\x10a\x02\0", 5),
            (b"\x10a\x01\0", 4), (b"\x20ab", 1),
        ]
        for data, size in cases:
            with self.subTest(data=data, size=size):
                with self.assertRaises(TextureDecodeError):
                    decode_lz4_block(data, size)

    def test_limit_is_checked_before_decompression(self):
        for expected, limit in [(-1, 100), (101, 100), (MAX_DECODED_BYTES + 1, MAX_DECODED_BYTES)]:
            with self.subTest(expected=expected, limit=limit):
                with self.assertRaisesRegex(TextureDecodeError, "limit"):
                    decode_lz4_block(b"", expected, limit=limit)


class TextureTests(unittest.TestCase):
    def test_rgb565_and_alpha_decode_then_png_roundtrip(self):
        width, height, rgba = decode_sct1_rgba(sct1())
        expected = bytes([
            255, 0, 0, 255, 0, 255, 0, 128,
            0, 0, 255, 0, 255, 255, 255, 64,
        ])
        self.assertEqual((width, height, rgba), (2, 2, expected))
        chunks = parse_png(encode_png_rgba(width, height, rgba))
        self.assertEqual([kind for kind, _ in chunks], [b"IHDR", b"IDAT", b"IEND"])
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[0][1]), (2, 2, 8, 6, 0, 0, 0))
        self.assertEqual(zlib.decompress(chunks[1][1]), b"\0" + expected[:8] + b"\0" + expected[8:])

    def test_sct1_sizes_dimensions_and_truncation_are_checked(self):
        data = sct1()
        cases = [data[:10], data[:-1], sct1(width=0), sct1(width=3)]
        excessive = bytearray(data)
        struct.pack_into("<I", excessive, 9, MAX_DECODED_BYTES + 1)
        cases.append(bytes(excessive))
        for broken in cases:
            with self.subTest(broken=broken[:17]):
                with self.assertRaises(TextureDecodeError): inspect_sct(broken)

    def test_sct2_uncompressed_and_lz4_container_checks(self):
        raw = bytes(range(16))
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                info, payload = inspect_sct(sct2(raw, compressed=compressed), return_payload=True)
                self.assertEqual(payload, raw)
                self.assertTrue(info["crc32_matches"])
                self.assertEqual(info["decoded_payload_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(info["pixel_decoder_status"], "unavailable")
                self.assertEqual(info["codec_candidate"], "ASTC 4x4")
        astc = inspect_sct(sct2(bytes(16), width=8, height=8, format_number=47))
        self.assertEqual(astc["codec_candidate"], "ASTC 8x8")

    def test_sct2_crc_total_header_and_block_bounds_reject_corruption(self):
        valid = sct2()
        corrupt = bytearray(valid)
        corrupt[-1] ^= 1
        with self.assertRaisesRegex(TextureDecodeError, "CRC-32"):
            inspect_sct(bytes(corrupt))
        for position, value in [(4, len(valid) + 1), (12, 12), (12, len(valid) + 1)]:
            broken = bytearray(valid)
            struct.pack_into("<I", broken, position, value)
            with self.subTest(position=position, value=value):
                with self.assertRaises(TextureDecodeError): inspect_sct(bytes(broken))
        with self.assertRaisesRegex(TextureDecodeError, "block byte count"):
            inspect_sct(sct2(b"too short"))
        with self.assertRaisesRegex(TextureDecodeError, "Truncated"):
            inspect_sct(valid[:20])

    def test_compression_length_is_checked_even_with_valid_crc(self):
        broken = bytearray(sct2(compressed=True))
        struct.pack_into("<I", broken, 40, 999)
        struct.pack_into("<I", broken, 8, zlib.crc32(broken[36:]))
        with self.assertRaisesRegex(TextureDecodeError, "compressed size"):
            inspect_sct(bytes(broken))

    def test_unknown_format_is_reported_without_invented_pixels(self):
        info = inspect_sct(sct2(b"unknown encoded pixels", format_number=999))
        self.assertEqual(info["format"], 999)
        self.assertEqual(info["pixel_decoder_status"], "unsupported")
        self.assertNotIn("codec_candidate", info)
        self.assertEqual(inspect_sct(sct1(format_number=99))["pixel_decoder_status"], "unsupported")
        with self.assertRaisesRegex(TextureDecodeError, "Only SCT1"):
            decode_sct1_rgba(sct2())
        with self.assertRaisesRegex(TextureDecodeError, "Only SCT1"):
            decode_sct1_rgba(sct1(format_number=99))

    def test_png_rejects_bad_byte_count_and_oversized_dimensions(self):
        for width, height, raw in [(1, 1, b"abc"), (0, 1, b""), (9000, 1, b"")]:
            with self.subTest(width=width):
                with self.assertRaises(TextureDecodeError): encode_png_rgba(width, height, raw)


class OptionalAstcTests(unittest.TestCase):
    def test_verified_block_routing_and_bgra_channel_conversion(self):
        for number, dimension, block_width in [(40, 4, 4), (47, 8, 8)]:
            with self.subTest(number=number):
                payload = bytes(range(16))
                native = mock.Mock(return_value=b"\x10\x20\x30\x40" * dimension ** 2)
                decoder = SimpleNamespace(__version__="1.0.6", decode_astc=native)
                width, height, rgba = decode_sct2_rgba(
                    sct2(payload, width=dimension, height=dimension, format_number=number), decoder=decoder)
                self.assertEqual((width, height), (dimension, dimension))
                self.assertEqual(rgba, b"\x30\x20\x10\x40" * dimension ** 2)
                native.assert_called_once_with(payload, dimension, dimension, block_width, block_width)

    def test_unknown_format_and_oversized_rgba_fail_before_native_call(self):
        native = mock.Mock()
        decoder = SimpleNamespace(__version__="1.0.6", decode_astc=native)
        with self.assertRaisesRegex(TextureDecodeError, "formats 40 and 47"):
            decode_sct2_rgba(sct2(b"unknown", format_number=999), decoder=decoder)
        # Valid bounded ASTC payload, but its RGBA expansion exceeds 16 MiB.
        width, height = 4096, 1028
        payload = bytes((width // 4) * (height // 4) * 16)
        with self.assertRaisesRegex(TextureDecodeError, "RGBA output exceeds"):
            decode_sct2_rgba(sct2(payload, width=width, height=height), decoder=decoder)
        native.assert_not_called()

    def test_wrong_decoder_version_and_output_shape_fail_clearly(self):
        for version, result, message in [
            ("1.0.5", bytes(64), "1.0.6"),
            ("1.0.6", bytes(63), "byte count"),
            ("1.0.6", [0] * 64, "byte count"),
        ]:
            with self.subTest(version=version, result_type=type(result)):
                decoder = SimpleNamespace(__version__=version, decode_astc=mock.Mock(return_value=result))
                with self.assertRaisesRegex(TextureDecodeError, message):
                    decode_sct2_rgba(sct2(), decoder=decoder)

    def test_optional_import_is_lazy_and_clear_when_unavailable(self):
        with mock.patch("tools.decode_texture._optional_astc_decoder",
                        side_effect=TextureDecodeError("requires texture2ddecoder==1.0.6")) as loader:
            inspect_sct(sct2())
            loader.assert_not_called()
            with self.assertRaisesRegex(TextureDecodeError, "requires texture2ddecoder"):
                decode_sct2_rgba(sct2())
            loader.assert_called_once()


class ScspTests(unittest.TestCase):
    def test_section_structure_reports_only_selected_safe_names(self):
        info = inspect_scsp(scsp())
        self.assertEqual(info["version_string"], "3.8.79.scsp")
        self.assertEqual(info["marker"], "scsp1u")
        self.assertEqual(info["structural_names_present"], ["intro", "root"])
        self.assertNotIn("opaque", json.dumps(info))
        self.assertNotIn("secret-value", json.dumps(info))
        self.assertEqual(info["string_section_offset_in_decoded"], 16)
        old = inspect_scsp(scsp(binary=b"\x50\0\0\0", strings=b"opaque\0" + b"2.1.27.scsp\0root\0"))
        self.assertEqual(old["version_string"], "2.1.27.scsp")
        self.assertIsNone(old["marker"])

    def test_malformed_outer_and_inner_sections(self):
        raw = struct.pack("<II", 500, 20) + b"short"
        block = literal_block(raw)
        broken = struct.pack("<II", len(raw), len(block)) + block
        for data in [scsp()[:5], scsp()[:-1], broken]:
            with self.subTest(data=data[:8]):
                with self.assertRaises(TextureDecodeError): inspect_scsp(data)

    def test_malformed_or_unbounded_strings_are_rejected(self):
        for strings in [b"opaque\0wrong\0root\0", b"opaque\0" + b"3.8.79.scsp\0unterminated",
                        b"opaque\0" + b"3.8.79.scsp\0" + b"\0" * 20001]:
            with self.subTest(length=len(strings)):
                with self.assertRaises(TextureDecodeError): inspect_scsp(scsp(strings=strings))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_actual_output_contract_and_preservation(self):
        path = self.root / "synthetic.sct"
        path.write_bytes(sct1())
        output = self.root / "decoded"
        info = inspect_file(path, output)
        self.assertEqual(json.loads((output / "header-report.json").read_text()), info)
        self.assertEqual(set(item.name for item in output.iterdir()), {"header-report.json", "texture.png"})
        previous = (output / "texture.png").read_bytes()
        with self.assertRaisesRegex(TextureDecodeError, "preserved"):
            inspect_file(path, output)
        self.assertEqual((output / "texture.png").read_bytes(), previous)

    def test_unsupported_pixel_format_writes_report_only(self):
        path = self.root / "unknown.sct"
        path.write_bytes(sct2(b"encoded data", format_number=999))
        output = self.root / "unknown-output"
        info = inspect_file(path, output)
        self.assertEqual(info["format"], 999)
        self.assertEqual(set(item.name for item in output.iterdir()), {"header-report.json"})

    def test_optional_cli_writes_provenance_and_png_with_mocked_native_decoder(self):
        path = self.root / "astc.sct"
        path.write_bytes(sct2())
        output = self.root / "astc-output"
        decoder = SimpleNamespace(__version__="1.0.6", decode_astc=mock.Mock(return_value=b"\x01\x02\x03\xff" * 16))
        with mock.patch("tools.decode_texture._optional_astc_decoder", return_value=decoder):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path), "--output", str(output), "--decode-astc"]), 0)
        info = json.loads((output / "header-report.json").read_text())
        self.assertEqual(info["pixel_decoder"]["version"], "1.0.6")
        self.assertEqual(info["pixel_decoder"]["channel_conversion"], "BGRA to RGBA")
        self.assertEqual(info["source_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        chunks = parse_png((output / "texture.png").read_bytes())
        self.assertEqual(zlib.decompress(chunks[1][1]), (b"\0" + b"\x03\x02\x01\xff" * 4) * 4)

    def test_requested_astc_on_scsp_fails_before_writing(self):
        path = self.root / "animation.scsp"
        path.write_bytes(scsp())
        output = self.root / "astc-scsp-output"
        with self.assertRaisesRegex(TextureDecodeError, "not an SCSP"):
            inspect_file(path, output, decode_astc=True)
        self.assertFalse(output.exists())

    def test_invalid_input_fails_before_writing_and_cli_returns_error(self):
        path = self.root / "broken.sct"
        path.write_bytes(b"SCT2bad")
        output = self.root / "output"
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(path), "--output", str(output)]), 1)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
