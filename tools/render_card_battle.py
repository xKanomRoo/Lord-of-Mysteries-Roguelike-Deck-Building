#!/usr/bin/env python3
"""Replay private card/battle wireframes from the verified fixed range ZIP.

Only saved scene geometry is interpreted. Resource code, textures and fonts are
never executed or loaded. Keep the generated evidence in ignored .local/ paths.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

try:
    from . import decode_csb as csb, read_ssra_ranges as ranges, render_csb_wireframe as wireframe
except ImportError:
    import decode_csb as csb
    import read_ssra_ranges as ranges
    import render_csb_wireframe as wireframe


CSB_PATHS = ("wnd/scene_battle_field.csb", "wnd/game_hud_hand.csb",
             "ui/game_hud_handpiles.csb", "wnd/game_card_select_hand.csb", "wnd/card.csb")
MAX_CSB_TOTAL_BYTES = 2 * 1024 * 1024
MAX_TOTAL_NODES = 5000
MAX_DIAGRAM_SIZE = 16384
PADDING = 32
LIMITS = csb.Limits(max_file_bytes=1024 * 1024, max_nodes=2000, max_depth=64,
                    max_decoded_string_bytes=2 * 1024 * 1024)
COMPONENT_NOTE = ("card.csb has a saved 0 × 0 root. Its diagram viewport is inferred from nonzero "
                  "child bounds, including hidden saved states and ignoring rotation; it is not a recovered runtime viewport.")


class CardBattleRenderError(ValueError):
    """Invalid fixed selection, bounded scene or output destination."""


def project_component(scene):
    """Infer a diagram viewport for the fixed zero-root card component only."""
    roots = [n for n in scene["nodes"] if n.get("parent_id") is None]
    if len(roots) != 1 or scene.get("source", {}).get("original_path") != CSB_PATHS[-1]:
        raise CardBattleRenderError("Inferred viewport is restricted to the fixed card component")
    root = roots[0]
    size = (root.get("options", {}).get("widget") or {}).get("size", {})
    if size.get("width") != 0 or size.get("height") != 0:
        raise CardBattleRenderError("Component inference requires the saved root to be exactly 0 × 0")
    scratch = copy.deepcopy(scene)
    scratch_root = next(n for n in scratch["nodes"] if n["id"] == root["id"])
    widget = scratch_root["options"]["widget"]
    # A zero-size root's anchor contributes no translation. This scratch frame
    # must not introduce a one-unit anchor displacement in descendant geometry.
    widget["size"] = {"width": 1, "height": 1}
    widget["anchorPoint"] = {"x": 0, "y": 0}
    projected = wireframe.project_scene(scratch)
    rectangles = [n["rect"] for n in projected["nodes"] if n["id"] != root["id"]
                  and n["rect"][2] > 0 and n["rect"][3] > 0]
    if not rectangles:
        raise CardBattleRenderError("Card component has no nonzero child bounds for an inferred viewport")
    left, top = min(r[0] for r in rectangles), min(r[1] for r in rectangles)
    right, bottom = max(r[0] + r[2] for r in rectangles), max(r[1] + r[3] for r in rectangles)
    width, height = right - left + 2 * PADDING, bottom - top + 2 * PADDING
    if max(abs(left), abs(top), abs(right), abs(bottom), width, height) > MAX_DIAGRAM_SIZE:
        raise CardBattleRenderError("Inferred component viewport exceeds diagram bounds")
    dx, dy = PADDING - left, PADDING - top
    original = {n["id"]: n for n in scene["nodes"]}
    for n in projected["nodes"]:
        n["node"] = original[n["id"]]
        n["rect"][0] += dx
        n["rect"][1] += dy
        n["origin"][0] += dx
        n["origin"][1] += dy
        if n["id"] == root["id"]:
            n["rect"][2:] = [0, 0]
    projected.update(width=width, height=height)
    projected["diagram_viewport"] = {
        "kind": "inferred_component_bounds", "serialized_root_size": size,
        "method": "Nonzero child rectangles, hidden states included, rotation ignored, 32 units padding.",
        "svg_translation": {"x": dx, "y": dy}, "serialized_local_values_preserved": True,
        "is_recovered_runtime_viewport": False}
    return projected


def _project(scene):
    root = next(n for n in scene["nodes"] if n.get("parent_id") is None)
    size = (root.get("options", {}).get("widget") or {}).get("size", {})
    result = project_component(scene) if size.get("width") == size.get("height") == 0 else wireframe.project_scene(scene)
    if max(result["width"], result["height"]) > MAX_DIAGRAM_SIZE:
        raise CardBattleRenderError("Saved logical frame exceeds diagram bounds")
    return result


def _page(data):
    page = wireframe.PAGE
    replacements = {
        "Logical frame ${s.width} × ${s.height}":
            "${s.diagram_viewport?'Inferred component viewport (saved root 0 × 0)':'Saved logical frame'} ${s.width} × ${s.height}",
        "estimated_svg_rectangle:n.rect": "diagram_viewport:s.diagram_viewport||null,estimated_svg_rectangle:n.rect",
    }
    for old, new in replacements.items():
        if page.count(old) != 1:
            raise CardBattleRenderError("Wireframe viewer template changed; component labels require review")
        page = page.replace(old, new)
    return page.replace("__DATA__", wireframe.safe_json(data))


def _decode(receipt, directory):
    scenes, total_bytes, total_nodes = [], 0, 0
    for path in CSB_PATHS:
        matches = [r for r in receipt["files"] if r["resource_path"] == path]
        if len(matches) != 1:
            raise CardBattleRenderError("Verified receipt is missing a unique fixed CSB resource")
        record = matches[0]
        label = f"files/{ranges.export.APPROVED_PATHS.index(path):02d}.bin"
        if record["archive_path"] != label:
            raise CardBattleRenderError("Verified CSB ordinal differs from the fixed selection")
        data = csb.read_bounded(directory / label, LIMITS.max_file_bytes)
        total_bytes += len(data)
        if total_bytes > MAX_CSB_TOTAL_BYTES:
            raise CardBattleRenderError("Selected CSBs exceed the combined byte bound")
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != record["decoded_bytes"] or digest != record["decoded_sha256"]:
            raise CardBattleRenderError("Verified CSB changed before layout decoding")
        source = {"original_path": path, "original_sha256": digest, "bytes": len(data),
                  "stored_sha256": record["stored_sha256"], "archive_path": label,
                  "source_zip_sha256": receipt["source_zip"]["sha256"],
                  "source_manifest_sha256": receipt["source_manifest"]["sha256"],
                  "source_index_sha256": receipt["source_index_sha256"],
                  "manifest_row": record["manifest_file_row"], "resource_group": record["group_id"],
                  "resource_offset": record["logical_offset"], "stored_bytes": record["stored_bytes"],
                  "decoded_FHSH_verified": record["fhsh_verified"], "file_hash64": record["fhsh_xxh64"],
                  "evidence_path": f"{receipt['source_zip']['filename']}!{label} -> {path}"}
        scene = csb.decode_scene(data, source=source, limits=LIMITS)
        total_nodes += len(scene["nodes"])
        if total_nodes > MAX_TOTAL_NODES:
            raise CardBattleRenderError("Selected scenes exceed the combined node bound")
        scenes.append(scene)
    return scenes


def render_pack(pack, output):
    """Verify in a temporary stage and publish only diagram/evidence files."""
    output = Path(output)
    if os.path.lexists(output):
        raise CardBattleRenderError("Output already exists; choose a new directory to preserve research")
    if any(ord(c) < 32 or ord(c) == 127 for c in str(output)):
        raise CardBattleRenderError("Output path contains control characters")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".card-battle-render-", dir=output.parent) as temporary:
        stage = Path(temporary)
        try:
            receipt = ranges.read_ranges(Path(pack), stage / "verified")
            scenes = _decode(receipt, stage / "verified")
            projected = [_project(s) for s in scenes]
        except (ranges.RangeReadError, csb.DecodeError, wireframe.WireframeError) as error:
            raise CardBattleRenderError(str(error)) from error
        layouts = {"schema_version": 1, "static_only": True, "schema_reference": csb.SCHEMA_REFERENCE,
                   "source_zip_sha256": receipt["source_zip"]["sha256"],
                   "source_manifest_sha256": receipt["source_manifest"]["sha256"], "scenes": scenes}
        layouts_bytes = (json.dumps(layouts, ensure_ascii=True, indent=2) + "\n").encode()
        if len(layouts_bytes) > wireframe.MAX_INPUT_BYTES:
            raise CardBattleRenderError("Decoded layout evidence exceeds its byte bound")
        limits = list(wireframe.LIMITATIONS)
        limits[1] = "Positive-size scenes use their saved root frame; the zero-root card component uses an explicitly inferred diagram viewport."
        limits.extend([COMPONENT_NOTE, "ProjectNode references are not expanded. Saved numeric labels and text do not establish gameplay rules."])
        data = {"layouts_sha256": hashlib.sha256(layouts_bytes).hexdigest(), "colors": wireframe.COLORS,
                "limitations": limits, "scenes": projected}
        rendered = stage / "rendered"
        rendered.mkdir()
        (rendered / "layouts.json").write_bytes(layouts_bytes)
        (rendered / "source-receipt.json").write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n")
        (rendered / "index.html").write_text(_page(data), encoding="utf-8")
        files = []
        for i, scene in enumerate(projected):
            filename = f"scene-{i:02d}.svg"
            (rendered / filename).write_text(wireframe.scene_svg(scene), encoding="utf-8")
            files.append({"svg": filename, "original_path": scene["name"], "diagram_viewport": scene.get("diagram_viewport")})
        summary = {"scene_count": len(scenes), "node_count": sum(len(s["nodes"]) for s in scenes),
                   "layouts_sha256": data["layouts_sha256"], "source_zip_sha256": receipt["source_zip"]["sha256"],
                   "files": files, "limitations": limits}
        (rendered / "wireframe-index.json").write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n")
        output.mkdir()  # Reserve the new destination; never replace an existing directory.
        created = []
        try:
            for source in sorted(rendered.iterdir()):
                target = output / source.name
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    created.append(target)
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(0o600)
        except OSError:
            for target in created:
                target.unlink(missing_ok=True)
            try:
                output.rmdir()
            except OSError:
                pass
            raise
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="Fixed card/battle range ZIP")
    parser.add_argument("--output", required=True, type=Path, help="New ignored directory for HTML/SVG and evidence")
    args = parser.parse_args(argv)
    try:
        result = render_pack(args.pack, args.output)
    except (CardBattleRenderError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(f"Card/battle wireframe replay failed: {error}", file=sys.stderr)
        return 2
    print(f"Rendered {result['scene_count']} scenes / {result['node_count']} nodes: {args.output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
