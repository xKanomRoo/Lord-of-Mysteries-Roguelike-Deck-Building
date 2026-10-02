#!/usr/bin/env python3
"""Bounded static inspection of SCT textures and SCSP animation containers.

These formats were observed in a user-supplied bootstrap research pack. Only
SCT1 format 4 has a stdlib pixel decoder: an LZ4 block containing RGB565
little-endian pixels followed by an A8 alpha plane. In the inspected reference
pack, SCT2 format 40/47 pixels were validated as ASTC 4x4/8x8; these numeric
mappings are not asserted for every game build. Optional SCT2 pixel decoding
requires texture2ddecoder==1.0.6 and the explicit --decode-astc flag.
SCSP inspection reads section lengths and selected structural string names,
not complete skeletons or executable code. No game code is ever executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import struct
import sys
import zlib

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_DECODED_BYTES = 16 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_STRING_BYTES = 1024 * 1024
MAX_STRINGS = 20000
ASTC_DECODER_VERSION = "1.0.6"
STRUCTURAL_NAMES = frozenset({
    b"root", b"default", b"pivot", b"intro", b"loop", b"title", b"zht_intro",
    b"zht_loop", b"bg", b"bridge", b"monitors", b"chairs", b"color_mask",
    b"robot_wait", b"trail", b"weapon",
})


class TextureDecodeError(ValueError):
    pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_data(data: bytes) -> None:
    if len(data) > MAX_INPUT_BYTES:
        raise TextureDecodeError("Input exceeds the 16 MiB limit")


def _dimensions(width: int, height: int) -> None:
    if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
        raise TextureDecodeError("Texture dimensions are invalid or exceed the limit")


def decode_lz4_block(data: bytes, expected_size: int, *,
                     limit: int = MAX_DECODED_BYTES) -> bytes:
    """Decode an LZ4 raw block, checking every read, offset and output length.

    This accepts a raw block, not an LZ4 frame. Overlapping matches are valid.
    The expected size must come from a bounded, checked container field.
    """
    if (type(expected_size) is not int or type(limit) is not int
            or not 0 <= expected_size <= limit or not 0 <= limit <= MAX_DECODED_BYTES):
        raise TextureDecodeError("LZ4 decoded size exceeds the limit")
    if len(data) > MAX_INPUT_BYTES:
        raise TextureDecodeError("LZ4 input exceeds the limit")
    cursor = 0
    output = bytearray()

    def extended_length(value: int) -> int:
        nonlocal cursor
        if value == 15:
            while True:
                if cursor >= len(data):
                    raise TextureDecodeError("Truncated LZ4 length extension")
                extension = data[cursor]
                cursor += 1
                value += extension
                if value > expected_size:
                    raise TextureDecodeError("LZ4 sequence exceeds the expected size")
                if extension != 255:
                    break
        return value

    while cursor < len(data):
        token = data[cursor]
        cursor += 1
        literal_size = extended_length(token >> 4)
        if cursor + literal_size > len(data):
            raise TextureDecodeError("Truncated LZ4 literals")
        if len(output) + literal_size > expected_size:
            raise TextureDecodeError("LZ4 literals exceed the expected size")
        output.extend(data[cursor:cursor + literal_size])
        cursor += literal_size
        if cursor == len(data):
            break
        if cursor + 2 > len(data):
            raise TextureDecodeError("Truncated LZ4 match offset")
        offset = data[cursor] | data[cursor + 1] << 8
        cursor += 2
        if not 1 <= offset <= len(output):
            raise TextureDecodeError("Invalid LZ4 match offset")
        match_size = extended_length(token & 15) + 4
        if len(output) + match_size > expected_size:
            raise TextureDecodeError("LZ4 match exceeds the expected size")
        # Each iteration sees bytes produced by previous iterations, allowing
        # offset-1 and other overlapping matches without copying unknown data.
        for _ in range(match_size):
            output.append(output[-offset])
    if len(output) != expected_size:
        raise TextureDecodeError("LZ4 output length disagrees with its container")
    return bytes(output)


def inspect_sct(data: bytes, *, return_payload: bool = False):
    """Return verified SCT metadata; optionally return ``(metadata, payload)``.

    Payload means the decompressed texture data, which is not necessarily RGBA.
    Unsupported format numbers are preserved in metadata; only their container
    structure is decoded. CRC checks are mandatory for SCT2.
    """
    _bounded_data(data)
    metadata = {"source_bytes": len(data), "source_sha256": _digest(data)}
    if data[:4] == b"SCT\x01":
        if len(data) < 17:
            raise TextureDecodeError("Truncated SCT1 header")
        format_number = data[4]
        width, height, raw_size, compressed_size = struct.unpack_from("<HHII", data, 5)
        _dimensions(width, height)
        if compressed_size != len(data) - 17:
            raise TextureDecodeError("SCT1 compressed size disagrees with the file")
        if format_number == 4 and raw_size != width * height * 3:
            raise TextureDecodeError("SCT1 RGB565/A8 byte count disagrees with dimensions")
        payload = decode_lz4_block(data[17:], raw_size)
        metadata.update({
            "container": "SCT1", "format": format_number,
            "width": width, "height": height, "payload_offset": 17,
            "compression": "LZ4 raw block", "compressed_bytes": compressed_size,
            "pixel_decoder_status": "supported" if format_number == 4 else "unsupported",
        })
        if format_number == 4:
            metadata["pixel_encoding"] = "RGB565 little-endian plane followed by A8 plane"
    elif data[:4] == b"SCT2":
        if len(data) < 36:
            raise TextureDecodeError("Truncated SCT2 header")
        total, expected_crc, header_size, container_field, format_number = struct.unpack_from(
            "<IIIII", data, 4)
        width, height, secondary_width, secondary_height = struct.unpack_from("<HHHH", data, 24)
        flags = struct.unpack_from("<I", data, 32)[0]
        _dimensions(width, height)
        if total != len(data):
            raise TextureDecodeError("SCT2 total size disagrees with the file")
        if not 36 <= header_size <= len(data):
            raise TextureDecodeError("Invalid SCT2 header size")
        if zlib.crc32(data[header_size:]) != expected_crc:
            raise TextureDecodeError("SCT2 payload CRC-32 mismatch")
        if flags & 0x80000000:
            if len(data) - header_size < 8:
                raise TextureDecodeError("Truncated SCT2 compression header")
            raw_size, compressed_size = struct.unpack_from("<II", data, header_size)
            offset = header_size + 8
            if compressed_size != len(data) - offset:
                raise TextureDecodeError("SCT2 compressed size disagrees with the file")
            payload = decode_lz4_block(data[offset:], raw_size)
            compression = "LZ4 raw block"
        else:
            offset = header_size
            compressed_size = None
            payload = data[offset:]
            if len(payload) > MAX_DECODED_BYTES:
                raise TextureDecodeError("SCT2 payload exceeds the decoded limit")
            compression = "none"
        metadata.update({
            "container": "SCT2", "header_bytes": header_size,
            "container_field": container_field, "format": format_number,
            "width": width, "height": height,
            "secondary_width_field": secondary_width, "secondary_height_field": secondary_height,
            "flags": f"0x{flags:08x}", "crc32_matches": True,
            "payload_offset": offset, "compression": compression,
            "compressed_bytes": compressed_size, "pixel_decoder_status": "unavailable",
        })
        if format_number in (40, 47):
            block_width = 4 if format_number == 40 else 8
            expected_size = ((width + block_width - 1) // block_width
                             * ((height + block_width - 1) // block_width) * 16)
            if len(payload) != expected_size:
                raise TextureDecodeError("SCT2 block byte count disagrees with dimensions")
            metadata["codec_candidate"] = "ASTC 4x4" if format_number == 40 else "ASTC 8x8"
            metadata["codec_evidence"] = (
                "Pixel decoding validated this mapping for the inspected reference pack; "
                "numeric format identifiers may differ in other builds")
        else:
            metadata["pixel_decoder_status"] = "unsupported"
    else:
        raise TextureDecodeError("Unsupported SCT container header")
    metadata["decoded_payload_bytes"] = len(payload)
    metadata["decoded_payload_sha256"] = _digest(payload)
    if return_payload:
        return metadata, payload
    return metadata


def decode_sct1_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Return width, height and RGBA bytes for verified SCT1 format 4 only."""
    metadata, payload = inspect_sct(data, return_payload=True)
    if metadata["container"] != "SCT1" or metadata["format"] != 4:
        raise TextureDecodeError("Only SCT1 format 4 has a validated pixel decoder")
    width, height = metadata["width"], metadata["height"]
    pixels = width * height
    if pixels * 4 > MAX_DECODED_BYTES:
        raise TextureDecodeError("RGBA output exceeds the decoded limit")
    rgba = bytearray(pixels * 4)
    for index in range(pixels):
        value = payload[index * 2] | payload[index * 2 + 1] << 8
        at = index * 4
        rgba[at] = (value >> 11) * 255 // 31
        rgba[at + 1] = ((value >> 5) & 63) * 255 // 63
        rgba[at + 2] = (value & 31) * 255 // 31
        rgba[at + 3] = payload[pixels * 2 + index]
    return width, height, bytes(rgba)


def encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encode bounded RGBA pixels as a standard PNG, using the stdlib only."""
    _dimensions(width, height)
    if len(rgba) != width * height * 4 or len(rgba) > MAX_DECODED_BYTES:
        raise TextureDecodeError("Invalid or excessive RGBA byte count")

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    stride = width * 4
    scanlines = b"".join(b"\0" + rgba[at:at + stride] for at in range(0, len(rgba), stride))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def _optional_astc_decoder():
    """Import an optional pinned decoder only after an explicit decode request."""
    try:
        import texture2ddecoder
    except ImportError as error:
        raise TextureDecodeError(
            "Optional ASTC decoding requires texture2ddecoder==1.0.6; "
            "install it in a separate local environment or omit --decode-astc") from error
    if getattr(texture2ddecoder, "__version__", None) != ASTC_DECODER_VERSION:
        raise TextureDecodeError("Optional ASTC decoding requires texture2ddecoder==1.0.6")
    return texture2ddecoder


def decode_sct2_rgba(data: bytes, *, decoder=None) -> tuple[int, int, bytes]:
    """Decode the observed SCT2 ASTC mapping to bounded RGBA pixels.

    The optional decoder is imported lazily. An injected decoder must expose
    ``__version__ == '1.0.6'`` and ``decode_astc(payload,w,h,bw,bh)`` returning
    BGRA bytes; injection is useful for deterministic tests. Numeric mappings
    40->4x4 and 47->8x8 were validated for this reference pack only.
    """
    metadata, payload = inspect_sct(data, return_payload=True)
    if metadata["container"] != "SCT2" or metadata["format"] not in (40, 47):
        raise TextureDecodeError("Optional ASTC decoding supports only SCT2 formats 40 and 47")
    width, height = metadata["width"], metadata["height"]
    expected = width * height * 4
    if expected > MAX_DECODED_BYTES:
        raise TextureDecodeError("RGBA output exceeds the decoded limit")
    block_width = 4 if metadata["format"] == 40 else 8
    if decoder is None:
        decoder = _optional_astc_decoder()
    if getattr(decoder, "__version__", None) != ASTC_DECODER_VERSION:
        raise TextureDecodeError("Optional ASTC decoding requires texture2ddecoder==1.0.6")
    try:
        bgra = decoder.decode_astc(payload, width, height, block_width, block_width)
    except (ValueError, RuntimeError, TypeError, AttributeError) as error:
        raise TextureDecodeError("Optional ASTC decoder rejected the verified payload") from error
    if not isinstance(bgra, (bytes, bytearray)) or len(bgra) != expected:
        raise TextureDecodeError("Optional ASTC decoder returned an invalid pixel byte count")
    # texture2ddecoder 1.0.6 returns BGRA, so swap R/B without changing the
    # source dimensions, alpha, orientation or spatial layout.
    rgba = bytearray(expected)
    rgba[0::4] = bgra[2::4]
    rgba[1::4] = bgra[1::4]
    rgba[2::4] = bgra[0::4]
    rgba[3::4] = bgra[3::4]
    return width, height, bytes(rgba)


def inspect_scsp(data: bytes) -> dict:
    """Inspect the verified custom SCSP section structure without dumping strings.

    Only a version-shaped string and fixed structural names are returned. The
    first opaque string is deliberately omitted; arbitrary embedded strings
    are untrusted data and may contain values unsuitable for a public report.
    """
    _bounded_data(data)
    if len(data) < 8:
        raise TextureDecodeError("Truncated SCSP compression header")
    raw_size, compressed_size = struct.unpack_from("<II", data)
    if compressed_size != len(data) - 8:
        raise TextureDecodeError("SCSP compressed size disagrees with the file")
    payload = decode_lz4_block(data[8:], raw_size)
    if len(payload) < 8:
        raise TextureDecodeError("Truncated SCSP section header")
    binary_size, string_size = struct.unpack_from("<II", payload)
    if 8 + binary_size + string_size != len(payload):
        raise TextureDecodeError("SCSP section sizes disagree with decoded bytes")
    if string_size > MAX_STRING_BYTES:
        raise TextureDecodeError("SCSP string section exceeds the limit")
    strings = payload[8 + binary_size:]
    if not strings.endswith(b"\0") or strings.count(b"\0") > MAX_STRINGS:
        raise TextureDecodeError("Invalid or excessive SCSP string table")
    entries = strings.split(b"\0")
    if len(entries) < 3 or not re.fullmatch(rb"\d{1,4}\.\d{1,4}\.\d{1,4}\.scsp", entries[1]):
        raise TextureDecodeError("SCSP version string is missing or malformed")
    names = sorted({entry.decode("ascii") for entry in entries[2:] if entry in STRUCTURAL_NAMES})
    return {
        "container": "SCSP", "source_bytes": len(data), "source_sha256": _digest(data),
        "payload_offset": 8, "compression": "LZ4 raw block",
        "compressed_bytes": compressed_size, "decoded_payload_bytes": len(payload),
        "decoded_payload_sha256": _digest(payload), "binary_section_bytes": binary_size,
        "string_section_offset_in_decoded": 8 + binary_size,
        "string_section_bytes": string_size, "version_string": entries[1].decode("ascii"),
        "marker": "scsp1u" if payload[8:14] == b"scsp1u" else None,
        "structural_names_present": names,
        "skeleton_decoder_status": "unavailable; complete binary schema has not been reconstructed",
    }


def inspect_file(path: Path, output: Path, *, decode_astc: bool = False) -> dict:
    """Validate first, then create a header report and supported texture preview."""
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise TextureDecodeError("Output must be new or empty; existing research is preserved")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise TextureDecodeError("Input exceeds the 16 MiB limit")
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    _bounded_data(data)
    preview = None
    if data[:3] == b"SCT":
        metadata = inspect_sct(data)
        if metadata["container"] == "SCT1" and metadata["format"] == 4:
            preview = encode_png_rgba(*decode_sct1_rgba(data))
        elif decode_astc:
            preview = encode_png_rgba(*decode_sct2_rgba(data))
            metadata["pixel_decoder_status"] = "decoded using optional ASTC decoder"
            metadata["pixel_decoder"] = {
                "package": "texture2ddecoder", "version": ASTC_DECODER_VERSION,
                "platform": sys.platform, "python_version": platform.python_version(),
                "channel_conversion": "BGRA to RGBA", "orientation_changed": False,
                "mapping_scope": "Numeric format mapping observed in inspected reference pack",
            }
        if preview is not None:
            metadata["preview"] = {
                "path": "texture.png", "sha256": _digest(preview),
                "meaning": "Decoded source texture atlas; not a composed game screenshot",
            }
    elif path.suffix.lower() == ".scsp":
        if decode_astc:
            raise TextureDecodeError("--decode-astc requires an SCT2 texture, not an SCSP container")
        metadata = inspect_scsp(data)
    else:
        raise TextureDecodeError("Input must be an SCT texture or SCSP container")
    metadata["source_file"] = path.name
    output.mkdir(parents=True, exist_ok=True)
    if preview is not None:
        with (output / "texture.png").open("xb") as stream:
            stream.write(preview)
    with (output / "header-report.json").open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    return metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decode-astc", action="store_true",
                        help="Decode observed SCT2 ASTC formats with optional texture2ddecoder==1.0.6")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_file(args.input, args.output, decode_astc=args.decode_astc),
                         ensure_ascii=False, indent=2))
    except (TextureDecodeError, OSError) as error:
        print(f"Static texture inspection failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
