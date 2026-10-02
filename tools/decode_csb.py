#!/usr/bin/env python3
"""Bounded, partial static decoder for Cocos Studio CSParseBinary scene files.

The reader implements a documented subset of the official generated schema;
it never loads a game runtime or executes archive content. Offsets and source
hashes are retained so observations can be checked against the original bytes.
Output may contain third-party text: keep it in ignored .local/ research folders.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import struct
import sys


SCHEMA_REFERENCE = {
    "format": "Cocos Studio CSParseBinary (partial documented schema)",
    "commit": "e4b6a5ef8fcdc99a7ebea606312b67fe4c534b9f",
    "url": "https://raw.githubusercontent.com/cocos2d/cocos2d-x/"
           "e4b6a5ef8fcdc99a7ebea606312b67fe4c534b9f/"
           "cocos/editor-support/cocostudio/CSParseBinary_generated.h",
    "sha256": "9512c62f41f701cd32a530765c34c76c63d67f2263d07fe553958fd2522fd80f",
    "node_reader_url": "https://raw.githubusercontent.com/cocos2d/cocos2d-x/"
                       "e4b6a5ef8fcdc99a7ebea606312b67fe4c534b9f/"
                       "cocos/editor-support/cocostudio/WidgetReader/NodeReader/NodeReader.cpp",
    "node_reader_sha256": "ea69376ef72ca96e5e5a99fdaf1036b8dfcf902da720d7a8db47488fdf4f6e45",
}


class DecodeError(ValueError):
    """Malformed, unsupported or oversized static research input."""


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 16 * 1024 * 1024
    max_index_bytes: int = 4 * 1024 * 1024
    max_string_bytes: int = 64 * 1024
    max_decoded_string_bytes: int = 16 * 1024 * 1024
    max_vector_items: int = 10_000
    max_table_fields: int = 128
    max_nodes: int = 10_000
    max_depth: int = 128
    max_scenes: int = 256
    max_pack_csb_bytes: int = 32 * 1024 * 1024
    max_pack_nodes: int = 50_000
    max_pack_decoded_string_bytes: int = 32 * 1024 * 1024


class Reader:
    def __init__(self, data, limits=None):
        self.data = data
        self.limits = limits or Limits()
        self.decoded_string_bytes = 0
        if len(data) > self.limits.max_file_bytes:
            raise DecodeError("CSB exceeds maximum file bytes")

    def span(self, start, size):
        if start < 0 or size < 0 or start > len(self.data) - size:
            raise DecodeError(f"Out-of-bounds span at byte {start} ({size} bytes)")

    def unpack(self, fmt, start):
        size = struct.calcsize("<" + fmt)
        self.span(start, size)
        values = struct.unpack_from("<" + fmt, self.data, start)
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            raise DecodeError(f"Non-finite numeric value at byte {start}")
        return values

    def u32(self, start):
        return self.unpack("I", start)[0]

    def table(self, start):
        return Table(self, start)

    def reference(self, location):
        relative = self.u32(location)
        if relative < 4:
            raise DecodeError(f"Invalid forward reference at byte {location}")
        target = location + relative
        self.span(target, 4)
        return target

    def string(self, start):
        size = self.u32(start)
        if size > self.limits.max_string_bytes:
            raise DecodeError("String exceeds maximum bytes")
        self.decoded_string_bytes += size
        if self.decoded_string_bytes > self.limits.max_decoded_string_bytes:
            raise DecodeError("Decoded strings exceed aggregate byte limit")
        self.span(start + 4, size + 1)
        if self.data[start + 4 + size] != 0:
            raise DecodeError(f"String missing terminator at byte {start}")
        try:
            return self.data[start + 4:start + 4 + size].decode("utf-8")
        except UnicodeDecodeError as error:
            raise DecodeError(f"Invalid UTF-8 string at byte {start}") from error

    def vector_refs(self, start):
        size = self.u32(start)
        if size > self.limits.max_vector_items:
            raise DecodeError("Vector exceeds maximum items")
        self.span(start + 4, size * 4)
        return [self.reference(start + 4 + index * 4) for index in range(size)]


class Table:
    def __init__(self, reader, start):
        self.reader = reader
        self.start = start
        self.vtable = start - reader.unpack("i", start)[0]
        vsize, self.size = reader.unpack("HH", self.vtable)
        if vsize < 4 or vsize % 2 or self.size < 4:
            raise DecodeError(f"Invalid table header at byte {start}")
        if (vsize - 4) // 2 > reader.limits.max_table_fields:
            raise DecodeError("Table exceeds maximum schema fields")
        reader.span(self.vtable, vsize)
        reader.span(start, self.size)
        self.field_offsets = reader.unpack("H" * ((vsize - 4) // 2), self.vtable + 4)
        if any(offset and (offset < 4 or offset >= self.size) for offset in self.field_offsets):
            raise DecodeError(f"Invalid field offset at byte {start}")

    def location(self, index, width=1):
        if index >= len(self.field_offsets) or not self.field_offsets[index]:
            return None
        offset = self.field_offsets[index]
        if offset + width > self.size:
            raise DecodeError(f"Field {index} extends beyond table at byte {self.start}")
        return self.start + offset

    def reference(self, index):
        location = self.location(index, 4)
        return self.reader.reference(location) if location is not None else None

    def child_table(self, index):
        start = self.reference(index)
        return self.reader.table(start) if start is not None else None

    def string(self, index):
        start = self.reference(index)
        return self.reader.string(start) if start is not None else None

    def scalar(self, index, fmt, default):
        location = self.location(index, struct.calcsize("<" + fmt))
        return self.reader.unpack(fmt, location)[0] if location is not None else default

    def inline(self, index, fmt, names):
        location = self.location(index, struct.calcsize("<" + fmt))
        if location is None:
            return None
        return dict(zip(names, self.reader.unpack(fmt, location)))

    def evidence(self):
        return {"table_offset": self.start, "vtable_offset": self.vtable,
                "table_bytes": self.size, "field_offsets": list(self.field_offsets)}


# Zero-based indices below correspond to (generated vtable selector - 4) / 2.
# Only these named standard classes are interpreted; custom classes stay unknown.
KNOWN_WRAPPERS = {"SingleNode", "Sprite", "Particle", "GameMap", "Button",
                  "CheckBox", "ImageView", "TextAtlas", "TextBMFont", "Text",
                  "TextField", "LoadingBar", "Slider", "Panel", "ScrollView",
                  "PageView", "ListView", "ProjectNode"}
RESOURCE_FIELDS = {
    "Sprite": {1: "fileNameData"}, "Particle": {1: "fileNameData"},
    "GameMap": {1: "fileNameData"}, "ImageView": {1: "fileNameData"},
    "TextBMFont": {1: "fileNameData"}, "TextAtlas": {1: "charMapFileData"},
    "Button": {1: "normalData", 2: "pressedData", 3: "disabledData", 4: "fontResource"},
    "CheckBox": {1: "backGroundBoxData", 2: "backGroundBoxSelectedData",
                 3: "frontCrossData", 4: "backGroundBoxDisabledData", 5: "frontCrossDisabledData"},
    "Text": {1: "fontResource"}, "TextField": {1: "fontResource"},
    "LoadingBar": {1: "textureData"},
    "Slider": {1: "barFileNameData", 2: "ballNormalData", 3: "ballPressedData",
               4: "ballDisabledData", 5: "progressBarData"},
    **{name: {1: "backGroundImageData"}
       for name in ("Panel", "ScrollView", "PageView", "ListView")},
}
TEXT_FIELDS = {
    "Button": {5: "text", 6: "fontName"}, "Text": {2: "fontName", 4: "text"},
    "TextField": {2: "fontName", 4: "text", 5: "placeHolder", 7: "passwordStyleText"},
    "TextBMFont": {2: "text"}, "TextAtlas": {2: "stringValue", 3: "startCharMap"},
    "ProjectNode": {1: "fileName"},
}


def decode_widget(table):
    result = {"evidence": table.evidence(), "name": table.string(0)}
    for name, index, fmt, default in (
        ("actionTag", 1, "i", 0), ("zOrder", 3, "i", 0), ("visible", 4, "B", 1),
        ("alpha", 5, "B", 255), ("tag", 6, "i", 0), ("flipX", 12, "B", 0),
        ("flipY", 13, "B", 0), ("ignoreSize", 14, "B", 0), ("touchEnabled", 15, "B", 0),
    ):
        result[name] = table.scalar(index, fmt, default)
    for name, index, fmt, names in (
        ("rotationSkew", 2, "ff", ("x", "y")), ("position", 7, "ff", ("x", "y")),
        ("scale", 8, "ff", ("x", "y")), ("anchorPoint", 9, "ff", ("x", "y")),
        ("color", 10, "BBBB", ("a", "r", "g", "b")),
        ("size", 11, "ff", ("width", "height")),
    ):
        result[name] = table.inline(index, fmt, names)
    # These are strings only. They are never executed or treated as instructions.
    for name, index in (("frameEvent", 16), ("customProperty", 17),
                        ("callBackType", 18), ("callBackName", 19)):
        result[name] = table.string(index)
    component = table.child_table(20)
    if component:
        result["layoutComponent"] = {"status": "not_decoded", "evidence": component.evidence()}
    if len(table.field_offsets) > 21:
        result["unknown_additional_field_indices"] = list(range(21, len(table.field_offsets)))
    return result


def decode_resource(table):
    return {"path": table.string(0), "plistFile": table.string(1),
            "resourceType": table.scalar(2, "i", 0), "evidence": table.evidence()}


def decode_options(data, classname):
    result = {"evidence": data.evidence()}
    if classname == "Node":
        result.update({"schema": "WidgetOptions", "widget": decode_widget(data)})
        return result
    if classname not in KNOWN_WRAPPERS:
        result.update({"status": "unsupported_custom_class", "widget": None,
                       "unknown_field_indices": list(range(len(data.field_offsets)))})
        return result
    result["schema"] = {"Particle": "ParticleSystemOptions"}.get(classname, classname + "Options")
    widget = data.child_table(0)
    result["widget"] = decode_widget(widget) if widget else None
    result["resources"] = {}
    for index, name in RESOURCE_FIELDS.get(classname, {}).items():
        resource = data.child_table(index)
        if resource:
            result["resources"][name] = decode_resource(resource)
    result["strings"] = {name: data.string(index) for index, name in TEXT_FIELDS.get(classname, {}).items()}
    if classname in {"Text", "TextField", "Button"}:
        result["fontSize"] = data.scalar(7 if classname == "Button" else 3, "i", 0)
    if classname == "ImageView":
        result["capInsets"] = data.inline(2, "ffff", ("x", "y", "width", "height"))
        result["scale9Size"] = data.inline(3, "ff", ("width", "height"))
        result["scale9Enabled"] = data.scalar(4, "B", 0)
    result["scope"] = "partial: standard widget, selected text/resources; other options not interpreted"
    return result


def decode_scene(data, *, source=None, limits=None):
    reader = Reader(data, limits)
    root = reader.table(reader.reference(0))
    if len(root.field_offsets) < 4:
        raise DecodeError("Missing CSParseBinary root fields")
    version = root.string(0)
    if not version:
        raise DecodeError("Missing CSParseBinary version")
    tree = root.child_table(3)
    if tree is None:
        raise DecodeError("Missing CSParseBinary nodeTree")
    nodes = []
    encountered = set()

    def visit(table, parent, depth):
        if depth > reader.limits.max_depth:
            raise DecodeError("Node hierarchy exceeds maximum depth")
        if len(nodes) >= reader.limits.max_nodes:
            raise DecodeError("Node hierarchy exceeds maximum nodes")
        if table.start in encountered:
            raise DecodeError("Repeated or cyclic node table in hierarchy")
        encountered.add(table.start)
        classname = table.string(0)
        if not classname:
            raise DecodeError("Node missing classname")
        wrapper = table.child_table(2)
        options = wrapper.child_table(0) if wrapper else None
        index = len(nodes)
        node = {"id": index, "parent_id": parent, "depth": depth,
                "classname": classname, "customClassName": table.string(3),
                "evidence": table.evidence(), "options_wrapper": wrapper.evidence() if wrapper else None,
                "options": decode_options(options, classname) if options else None,
                "child_ids": []}
        nodes.append(node)
        children = table.reference(1)
        if children is not None:
            for child in reader.vector_refs(children):
                node["child_ids"].append(visit(reader.table(child), index, depth + 1))
        return index

    visit(tree, None, 0)
    textures = {}
    for name, index in (("textures", 1), ("texturePngs", 2)):
        vector = root.reference(index)
        textures[name] = [reader.string(ref) for ref in reader.vector_refs(vector)] if vector is not None else []
    action = root.child_table(4)
    animations = root.reference(5)
    animation_tables = [reader.table(ref).evidence() for ref in reader.vector_refs(animations)] if animations else []
    return {
        "source": source or {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "status": "decoded_documented_subset", "serialized_version": version,
        "decoded_string_bytes": reader.decoded_string_bytes,
        "root_evidence": root.evidence(), **textures, "node_count": len(nodes),
        "class_counts": dict(sorted(Counter(node["classname"] for node in nodes).items())),
        "unsupported_class_counts": dict(sorted(Counter(node["classname"] for node in nodes
                                                        if node["classname"] != "Node"
                                                        and node["classname"] not in KNOWN_WRAPPERS).items())),
        "action": {"status": "not_decoded", "evidence": action.evidence() if action else None},
        "animationList": {"status": "not_decoded", "table_evidence": animation_tables},
        "nodes": nodes,
        "limitations": ["Partial schema decoding does not fully verify every field or identify the complete game engine.",
                        "Coordinates are serialized local values; runtime scripts, anchors, constraints and animation can change display.",
                        "Custom classes, detailed layout constraints, animations, clipping and unspecified options are not interpreted.",
                        "Text and texture references do not prove final localization, asset availability or gameplay rules."],
    }


def read_bounded(path, limit):
    if path.stat().st_size > limit:
        raise DecodeError(f"Input exceeds limit: {path.name}")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise DecodeError(f"Input exceeds limit: {path.name}")
    return data


def decode_pack(index_path, limits=None):
    limits = limits or Limits()
    index_path = Path(index_path)
    raw = read_bounded(index_path, limits.max_index_bytes)
    try:
        pack = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DecodeError("Invalid pack index JSON") from error
    if not isinstance(pack, dict) or not isinstance(pack.get("files"), list):
        raise DecodeError("Missing pack index files")
    if len(pack["files"]) > 100_000:
        raise DecodeError("Too many pack index entries")
    candidates = []
    for entry in pack["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("original_path"), str):
            raise DecodeError("Invalid pack index entry")
        if entry["original_path"].lower().endswith(".csb"):
            candidates.append(entry)
    if len(candidates) > limits.max_scenes:
        raise DecodeError("Too many CSB scenes")
    scenes = []
    total_csb_bytes = 0
    total_nodes = 0
    total_decoded_string_bytes = 0
    root = index_path.parent.resolve()
    for entry in candidates:
        # Aggregate limits are pack-level failures, never recoverable scene errors.
        # Check exhaustion before reading or decoding another scene.
        if total_nodes >= limits.max_pack_nodes:
            raise DecodeError("CSB pack exhausts aggregate node limit")
        if total_decoded_string_bytes >= limits.max_pack_decoded_string_bytes:
            raise DecodeError("CSB pack exhausts aggregate decoded string byte limit")
        stored = entry.get("stored_path")
        if not isinstance(stored, str) or "\\" in stored:
            raise DecodeError("Invalid stored path")
        relative = PurePosixPath(stored)
        if relative.is_absolute() or ".." in relative.parts:
            raise DecodeError("Unsafe stored path")
        path = (root / stored).resolve()
        if not path.is_relative_to(root):
            raise DecodeError("Stored path escapes research pack")
        data = read_bounded(path, limits.max_file_bytes)
        total_csb_bytes += len(data)
        if total_csb_bytes > limits.max_pack_csb_bytes:
            raise DecodeError("CSB pack exceeds aggregate input byte limit")
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.get("stored_sha256"):
            raise DecodeError("Stored CSB hash does not match pack index")
        source = {key: entry.get(key) for key in ("evidence_path", "original_path", "original_sha256",
                                                 "stored_path", "stored_sha256", "transformation")}
        source["bytes"] = len(data)
        try:
            scene = decode_scene(data, source=source, limits=limits)
        except DecodeError as error:
            scenes.append({"source": source, "status": "decode_failed", "error": str(error)})
            continue
        total_nodes += scene["node_count"]
        if total_nodes > limits.max_pack_nodes:
            raise DecodeError("CSB pack exceeds aggregate node limit")
        total_decoded_string_bytes += scene["decoded_string_bytes"]
        if total_decoded_string_bytes > limits.max_pack_decoded_string_bytes:
            raise DecodeError("CSB pack exceeds aggregate decoded string byte limit")
        scenes.append(scene)
    return {"schema_version": 1, "schema_reference": SCHEMA_REFERENCE,
            "pack_index_sha256": hashlib.sha256(raw).hexdigest(),
            "pack_input": pack.get("input"), "scene_count": len(scenes),
            "decoded_scene_count": sum(scene["status"] == "decoded_documented_subset" for scene in scenes),
            "total_node_count": sum(scene.get("node_count", 0) for scene in scenes), "scenes": scenes}


def summary(report):
    lines = ["# Static CSB decoding", "", f"Decoded {report['decoded_scene_count']} / {report['scene_count']} scenes; "
             f"{report['total_node_count']} hierarchy nodes.", "",
             "These are serialized layout observations, not a reconstruction of game behavior or final screenshots.", "",
             "| Original scene | Version | Nodes | Unsupported classes |", "| --- | --- | ---: | --- |"]
    for scene in report["scenes"]:
        name = scene["source"]["original_path"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {scene.get('serialized_version', 'failed')} | {scene.get('node_count', 0)} | "
                     f"{json.dumps(scene.get('unsupported_class_counts', {}), ensure_ascii=True)} |")
    lines.extend(["", "Schema reference: " + SCHEMA_REFERENCE["url"],
                  "", "Raw text, references and hierarchy JSON should remain in ignored local research storage."])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New ignored research output directory")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise DecodeError("Output directory already exists; choose a new output path")
        report = decode_pack(args.pack_index)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "layouts.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output / "summary.md").write_text(summary(report), encoding="utf-8")
        print(f"Decoded {report['decoded_scene_count']} / {report['scene_count']} scenes; "
              f"{report['total_node_count']} nodes. Output: {args.output}")
        return 0 if report["decoded_scene_count"] == report["scene_count"] and report["scene_count"] else 1
    except (DecodeError, OSError) as error:
        print(f"CSB decoding failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
