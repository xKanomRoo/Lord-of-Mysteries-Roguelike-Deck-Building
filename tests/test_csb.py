"""Synthetic CSParseBinary fixtures; no extracted game content is checked in."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.decode_csb import (DecodeError, Limits, Reader, VENDOR_SCHEMA_ID,
                              VENDOR_SCHEMA_REFERENCE, decode_pack, decode_scene, main)


class FixtureBuilder:
    """Tiny independent forward builder for only the FlatBuffer fixture fields."""
    def __init__(self):
        self.data = bytearray(4)

    def align(self, alignment):
        self.data.extend(b"\0" * (-len(self.data) % alignment))

    def table(self, fields, count=None):
        count = count if count is not None else max(fields, default=-1) + 1
        offsets = [0] * count
        body = bytearray(4)
        for index, payload in sorted(fields.items()):
            body.extend(b"\0" * (-len(body) % min(len(payload), 4)))
            offsets[index] = len(body)
            body.extend(payload)
        self.align(2)
        vtable = len(self.data)
        self.data.extend(struct.pack("<HH", 4 + count * 2, len(body)))
        self.data.extend(struct.pack("<" + "H" * count, *offsets))
        self.align(4)
        start = len(self.data)
        struct.pack_into("<i", body, 0, start - vtable)
        self.data.extend(body)
        return start, {index: start + offset for index, offset in enumerate(offsets) if offset}

    def string(self, text):
        self.align(4)
        start = len(self.data)
        raw = text.encode("utf-8")
        self.data.extend(struct.pack("<I", len(raw)) + raw + b"\0")
        return start

    def vector(self, count):
        self.align(4)
        start = len(self.data)
        self.data.extend(struct.pack("<I", count) + b"\0" * (count * 4))
        return start

    def reference(self, source, target):
        struct.pack_into("<I", self.data, source, target - source)


def make_scene(classname="Node", child_count=0, *, vendor_values=None, vendor_resource=False):
    builder = FixtureBuilder()
    root, root_fields = builder.table({0: b"\0" * 4, 3: b"\0" * 4}, 6)
    builder.reference(0, root)
    builder.reference(root_fields[0], builder.string("synthetic-1.0"))
    tree, tree_fields = builder.table({0: b"\0" * 4, 1: b"\0" * 4, 2: b"\0" * 4}, 4)
    builder.reference(root_fields[3], tree)
    builder.reference(tree_fields[0], builder.string(classname))
    children = builder.vector(child_count)
    builder.reference(tree_fields[1], children)
    wrapper, wrapper_fields = builder.table({0: b"\0" * 4})
    builder.reference(tree_fields[2], wrapper)
    option_fields = None
    if classname != "Node":
        payloads = {0: b"\0" * 4}
        if vendor_values is not None:
            payloads.update({index: struct.pack("<f", value) for index, value in vendor_values.items()})
        if vendor_resource:
            payloads[5] = b"\0" * 4
        options, option_fields = builder.table(payloads)
        builder.reference(wrapper_fields[0], options)
    widget, fields = builder.table({0: b"\0" * 4, 7: struct.pack("<ff", 150, 250),
                                    8: struct.pack("<ff", 1, 1), 9: struct.pack("<ff", .5, .5),
                                    11: struct.pack("<ff", 1280, 720), 15: b"\x01"}, 21)
    builder.reference(option_fields[0] if option_fields else wrapper_fields[0], widget)
    builder.reference(fields[0], builder.string("synthetic-root"))
    resource = None
    if vendor_resource:
        resource, resource_fields = builder.table({0: b"\0" * 4, 1: b"\0" * 4, 2: struct.pack("<i", 1)})
        builder.reference(option_fields[5], resource)
        builder.reference(resource_fields[0], builder.string("synthetic/pattern.png"))
        builder.reference(resource_fields[1], builder.string("synthetic/atlas.plist"))
    for number in range(child_count):
        child, child_fields = builder.table({0: b"\0" * 4}, 4)
        builder.reference(children + 4 + number * 4, child)
        builder.reference(child_fields[0], builder.string("SingleNode"))
    return builder, {"root": root, "root_fields": root_fields, "tree": tree,
                     "tree_fields": tree_fields, "widget": widget, "fields": fields,
                     "children": children, "options": options if option_fields else None,
                     "option_fields": option_fields, "resource": resource}


class CsbTests(unittest.TestCase):
    def test_known_fixture_hierarchy_layout_offsets_and_defaults(self):
        builder, locations = make_scene(child_count=2)
        report = decode_scene(bytes(builder.data))
        self.assertEqual(report["node_count"], 3)
        self.assertEqual(report["serialized_version"], "synthetic-1.0")
        self.assertEqual(report["nodes"][0]["child_ids"], [1, 2])
        self.assertEqual(report["nodes"][2]["parent_id"], 0)
        widget = report["nodes"][0]["options"]["widget"]
        self.assertEqual(widget["name"], "synthetic-root")
        self.assertEqual(widget["position"], {"x": 150, "y": 250})
        self.assertEqual(widget["size"], {"width": 1280, "height": 720})
        self.assertEqual(widget["anchorPoint"], {"x": .5, "y": .5})
        self.assertEqual(widget["alpha"], 255)
        self.assertEqual(widget["touchEnabled"], 1)
        self.assertEqual(widget["evidence"]["table_offset"], locations["widget"])
        self.assertEqual(report["source"]["sha256"], hashlib.sha256(builder.data).hexdigest())

    def test_standard_wrapper_and_custom_unknown(self):
        builder, _ = make_scene("SingleNode")
        self.assertEqual(decode_scene(bytes(builder.data))["nodes"][0]["options"]["widget"]["name"],
                         "synthetic-root")
        builder, _ = make_scene("SyntheticCustomSprite")
        scene = decode_scene(bytes(builder.data))
        self.assertEqual(scene["unsupported_class_counts"], {"SyntheticCustomSprite": 1})
        options = scene["nodes"][0]["options"]
        self.assertIsNone(options["widget"])
        self.assertEqual(options["status"], "unsupported_custom_class")

    def test_vendor_tile_schema_defaults_and_unverified_files_stay_unknown(self):
        builder, _ = make_scene("TileSprite")
        plain = decode_scene(bytes(builder.data))
        self.assertEqual(plain["unsupported_class_counts"], {"TileSprite": 1})
        self.assertIsNone(plain["nodes"][0]["options"]["widget"])
        # Claimed metadata cannot enable the version-specific native schema.
        spoofed = decode_scene(bytes(builder.data), source={"stored_sha256":
            "5edcfb6f78042745e6f65e88f2461493c88f203d3d45f9bb79855a79cb63a0d7"})
        self.assertEqual(spoofed["unsupported_class_counts"], {"TileSprite": 1})
        scene = decode_scene(bytes(builder.data), vendor_schema=VENDOR_SCHEMA_ID)
        options = scene["nodes"][0]["options"]
        self.assertEqual(options["schema"], "TileSpriteOptions")
        self.assertEqual(options["status"], "decoded_vendor_schema")
        self.assertEqual(options["widget"]["name"], "synthetic-root")
        self.assertEqual(options["widget"]["position"], {"x": 150, "y": 250})
        self.assertEqual([options[name] for name in ("tilingX", "tilingY", "offsetX", "offsetY")], [0.0] * 4)
        self.assertEqual(options["resources"], {})
        self.assertEqual(scene["vendor_schema_node_count"], 1)
        self.assertEqual(scene["unsupported_class_counts"], {})
        self.assertEqual(scene["vendor_schema_reference"], VENDOR_SCHEMA_REFERENCE)
        self.assertIn("explicit_interpretation", scene["vendor_schema_selection"])

    def test_vendor_tile_float_fields_and_resource_reference_are_distinct(self):
        builder, locations = make_scene("TileSprite", vendor_values={1: 2.5, 2: 3.25, 3: -10, 4: 17},
                                        vendor_resource=True)
        options = decode_scene(bytes(builder.data), vendor_schema=VENDOR_SCHEMA_ID)["nodes"][0]["options"]
        self.assertEqual([options[name] for name in ("tilingX", "tilingY", "offsetX", "offsetY")], [2.5, 3.25, -10, 17])
        self.assertEqual(options["evidence"]["table_offset"], locations["options"])
        self.assertEqual(options["resources"]["fileData"]["path"], "synthetic/pattern.png")
        self.assertEqual(options["resources"]["fileData"]["plistFile"], "synthetic/atlas.plist")
        self.assertEqual(options["resources"]["fileData"]["resourceType"], 1)
        self.assertEqual(options["resources"]["fileData"]["evidence"]["table_offset"], locations["resource"])

    def test_vendor_tile_float_field_width_and_nonfinite_values_rejected(self):
        builder, locations = make_scene("TileSprite", vendor_values={1: 1.0})
        invalid = bytearray(builder.data)
        struct.pack_into("<f", invalid, locations["option_fields"][1], float("inf"))
        with self.assertRaisesRegex(DecodeError, "Non-finite"):
            decode_scene(bytes(invalid), vendor_schema=VENDOR_SCHEMA_ID)
        invalid = bytearray(builder.data)
        start = locations["options"]
        vtable = start - struct.unpack_from("<i", invalid, start)[0]
        size = struct.unpack_from("<H", invalid, vtable + 2)[0]
        struct.pack_into("<H", invalid, vtable + 4 + 1 * 2, size - 1)
        with self.assertRaisesRegex(DecodeError, "extends beyond"):
            decode_scene(bytes(invalid), vendor_schema=VENDOR_SCHEMA_ID)
        builder, locations = make_scene("TileSprite", vendor_resource=True)
        struct.pack_into("<I", builder.data, locations["option_fields"][5], 0xffffffff)
        with self.assertRaisesRegex(DecodeError, "bounds"):
            decode_scene(bytes(builder.data), vendor_schema=VENDOR_SCHEMA_ID)

    def test_all_truncations_rejected(self):
        builder, _ = make_scene()
        for length in range(len(builder.data)):
            with self.subTest(length=length), self.assertRaises(DecodeError):
                decode_scene(bytes(builder.data[:length]))

    def test_invalid_root_reference(self):
        builder, _ = make_scene()
        struct.pack_into("<I", builder.data, 0, 0xffffffff)
        with self.assertRaisesRegex(DecodeError, "bounds"):
            decode_scene(bytes(builder.data))

    def test_bad_table_field_range(self):
        builder, locations = make_scene()
        start = locations["widget"]
        vtable = start - struct.unpack_from("<i", builder.data, start)[0]
        size = struct.unpack_from("<H", builder.data, vtable + 2)[0]
        struct.pack_into("<H", builder.data, vtable + 4, size)
        with self.assertRaisesRegex(DecodeError, "field offset"):
            decode_scene(bytes(builder.data))

    def test_inline_field_width_cannot_cross_table_boundary(self):
        builder, locations = make_scene()
        start = locations["widget"]
        vtable = start - struct.unpack_from("<i", builder.data, start)[0]
        size = struct.unpack_from("<H", builder.data, vtable + 2)[0]
        struct.pack_into("<H", builder.data, vtable + 4 + 7 * 2, size - 4)
        with self.assertRaisesRegex(DecodeError, "extends beyond"):
            decode_scene(bytes(builder.data))

    def test_limits_nodes_depth_vectors_and_file_bytes(self):
        builder, _ = make_scene(child_count=2)
        for limits, message in ((replace(Limits(), max_nodes=2), "maximum nodes"),
                                (replace(Limits(), max_depth=0), "maximum depth"),
                                (replace(Limits(), max_vector_items=1), "maximum items"),
                                (replace(Limits(), max_table_fields=1), "maximum schema fields"),
                                (replace(Limits(), max_file_bytes=4), "maximum file bytes")):
            with self.subTest(message=message), self.assertRaisesRegex(DecodeError, message):
                decode_scene(bytes(builder.data), limits=limits)

    def test_repeated_hierarchy_node_rejected(self):
        builder, locations = make_scene(child_count=2)
        vector = locations["children"]
        first = vector + 4 + struct.unpack_from("<I", builder.data, vector + 4)[0]
        builder.reference(vector + 8, first)
        with self.assertRaisesRegex(DecodeError, "Repeated"):
            decode_scene(bytes(builder.data))

    def test_nonfinite_coordinate_rejected(self):
        builder, locations = make_scene()
        struct.pack_into("<f", builder.data, locations["fields"][7], float("nan"))
        with self.assertRaisesRegex(DecodeError, "Non-finite"):
            decode_scene(bytes(builder.data))

    def test_aggregate_string_budget(self):
        builder, _ = make_scene()
        with self.assertRaisesRegex(DecodeError, "aggregate byte limit"):
            decode_scene(bytes(builder.data), limits=replace(Limits(), max_decoded_string_bytes=2))

    def test_invalid_utf8_terminator_and_string_limit(self):
        builder, _ = make_scene()
        report = decode_scene(bytes(builder.data))
        root = Reader(bytes(builder.data)).table(report["root_evidence"]["table_offset"])
        string = root.reference(0)
        invalid = bytearray(builder.data)
        invalid[string + 4] = 255
        with self.assertRaisesRegex(DecodeError, "UTF-8"):
            decode_scene(bytes(invalid))
        invalid = bytearray(builder.data)
        invalid[string + 4 + len("synthetic-1.0")] = 1
        with self.assertRaisesRegex(DecodeError, "terminator"):
            decode_scene(bytes(invalid))
        with self.assertRaisesRegex(DecodeError, "String exceeds"):
            decode_scene(bytes(builder.data), limits=replace(Limits(), max_string_bytes=2))

    def test_forward_shared_vtable_is_permitted(self):
        data = bytearray(struct.pack("<iIHHH", -8, 123, 6, 8, 4))
        table = Reader(bytes(data)).table(0)
        self.assertEqual(table.scalar(0, "I", 0), 123)
        self.assertEqual(table.vtable, 8)

    def test_pack_provenance_hash_refusal_path_refusal_and_no_overwrite(self):
        builder, _ = make_scene()
        with tempfile.TemporaryDirectory(prefix="csb-synthetic-") as temporary:
            root = Path(temporary)
            data = bytes(builder.data)
            (root / "scene.csb").write_bytes(data)
            entry = {"stored_path": "scene.csb", "original_path": "assets/ui/scene.csb",
                     "stored_sha256": hashlib.sha256(data).hexdigest(),
                     "original_sha256": hashlib.sha256(data).hexdigest(),
                     "evidence_path": "synthetic.xapk!synthetic.apk!assets/ui/scene.csb",
                     "transformation": "unchanged_static_binary"}
            index = root / "pack-index.json"
            def write():
                index.write_text(json.dumps({"files": [entry]}), encoding="utf-8")
            write()
            report = decode_pack(index)
            self.assertEqual(report["decoded_scene_count"], 1)
            self.assertEqual(report["scenes"][0]["source"]["evidence_path"], entry["evidence_path"])
            with self.assertRaisesRegex(DecodeError, "aggregate input byte limit"):
                decode_pack(index, replace(Limits(), max_pack_csb_bytes=1))
            with self.assertRaisesRegex(DecodeError, "aggregate node limit"):
                decode_pack(index, replace(Limits(), max_pack_nodes=0))
            with self.assertRaisesRegex(DecodeError, "aggregate decoded string byte limit"):
                decode_pack(index, replace(Limits(), max_pack_decoded_string_bytes=0))
            output = root / "result"
            self.assertEqual(main(["--pack-index", str(index), "--output", str(output)]), 0)
            before = (output / "layouts.json").read_bytes()
            self.assertEqual(main(["--pack-index", str(index), "--output", str(output)]), 1)
            self.assertEqual((output / "layouts.json").read_bytes(), before)
            entry["stored_sha256"] = "0" * 64
            write()
            with self.assertRaisesRegex(DecodeError, "hash"):
                decode_pack(index)
            entry["stored_path"] = "../scene.csb"
            write()
            with self.assertRaisesRegex(DecodeError, "Unsafe"):
                decode_pack(index)

    def test_failed_scene_is_reported_without_losing_other_results(self):
        with tempfile.TemporaryDirectory(prefix="csb-synthetic-") as temporary:
            root = Path(temporary)
            data = b"bad"
            (root / "scene.csb").write_bytes(data)
            index = root / "pack-index.json"
            index.write_text(json.dumps({"files": [{"stored_path": "scene.csb", "original_path": "scene.csb",
                                                   "stored_sha256": hashlib.sha256(data).hexdigest()}]}))
            report = decode_pack(index)
            self.assertEqual(report["decoded_scene_count"], 0)
            self.assertEqual(report["scenes"][0]["status"], "decode_failed")

    def test_aggregate_budgets_stop_decoding_remaining_scenes(self):
        builder, _ = make_scene()
        with tempfile.TemporaryDirectory(prefix="csb-synthetic-") as temporary:
            root = Path(temporary)
            data = bytes(builder.data)
            (root / "scene.csb").write_bytes(data)
            index = root / "pack-index.json"
            index.write_text(json.dumps({"files": [
                {"stored_path": "scene.csb", "original_path": f"scene-{number}.csb",
                 "stored_sha256": hashlib.sha256(data).hexdigest()}
                for number in range(5)]}))
            for limits, message, expected_calls in (
                (replace(Limits(), max_pack_nodes=0), "aggregate node limit", 0),
                (replace(Limits(), max_pack_nodes=1), "aggregate node limit", 1),
                (replace(Limits(), max_pack_decoded_string_bytes=0), "aggregate decoded string byte limit", 0),
                (replace(Limits(), max_pack_decoded_string_bytes=1), "aggregate decoded string byte limit", 1),
            ):
                with self.subTest(limits=limits), patch("tools.decode_csb.decode_scene", wraps=decode_scene) as decode:
                    with self.assertRaisesRegex(DecodeError, message):
                        decode_pack(index, limits)
                    self.assertEqual(decode.call_count, expected_calls)


if __name__ == "__main__":
    unittest.main()
