"""Synthetic diagram tests; the pinned ZIP reader has its own verification suite."""
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tools import render_card_battle as render


def node(identifier, parent=None, *, size=(0, 0), position=(0, 0), anchor=(0, 0), scale=(1, 1), visible=1):
    return {"id": identifier, "parent_id": parent, "classname": "Button", "evidence": {"table_offset": 64},
            "options": {"widget": {"name": f"synthetic{identifier}", "visible": visible,
                        "size": dict(zip(("width", "height"), size)),
                        "position": dict(zip(("x", "y"), position)),
                        "scale": dict(zip(("x", "y"), scale)),
                        "anchorPoint": dict(zip(("x", "y"), anchor))}}}


def scene(path=render.CSB_PATHS[-1]):
    return {"source": {"original_path": path, "original_sha256": "a" * 64},
            "nodes": [node(0, size=(0, 0) if path == render.CSB_PATHS[-1] else (1280, 720)),
                      node(1, 0, size=(20, 10), position=(-5, 5), anchor=(.5, .5))]}


class CardBattleReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-diagram-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "diagrams"

    def fake_reader(self, pack, destination):
        destination.mkdir()
        (destination / "files").mkdir()
        records = []
        for path in render.CSB_PATHS:
            ordinal = render.ranges.export.APPROVED_PATHS.index(path)
            label = f"files/{ordinal:02d}.bin"
            data = f"Synthetic CSB input {ordinal}".encode()
            (destination / label).write_bytes(data)
            records.append({"resource_path": path, "archive_path": label, "decoded_bytes": len(data),
                            "decoded_sha256": hashlib.sha256(data).hexdigest(), "stored_sha256": "b" * 64,
                            "manifest_file_row": ordinal, "group_id": 12, "logical_offset": ordinal * 1024,
                            "stored_bytes": len(data), "fhsh_verified": True, "fhsh_xxh64": "0" * 16})
        return {"files": records, "source_zip": {"filename": "synthetic.zip", "sha256": "c" * 64},
                "source_manifest": {"sha256": "d" * 64}, "source_index_sha256": "e" * 64,
                "whole_chunk_hashes_verified": False, "original_resource_authenticity": "unknown"}

    @staticmethod
    def fake_decoder(data, *, source, limits):
        result = scene(source["original_path"])
        result["source"] = source
        return result

    def run_wrapper(self):
        with patch.object(render.ranges, "read_ranges", side_effect=self.fake_reader) as reader, \
                patch.object(render.csb, "decode_scene", side_effect=self.fake_decoder) as decoder:
            result = render.render_pack(self.root / "synthetic.zip", self.output)
        return result, reader, decoder

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".card-battle-render-*")), [])

    def test_component_preserves_zero_root_anchor_and_original_local_values(self):
        original = scene()
        original["nodes"][0]["options"]["widget"].update(
            position={"x": 10, "y": 20}, anchorPoint={"x": .5, "y": .5}, scale={"x": 2, "y": 2})
        before = copy.deepcopy(original)
        projected = render.project_component(original)
        self.assertEqual(original, before)
        self.assertEqual(projected["nodes"][0]["node"], before["nodes"][0])
        self.assertEqual(projected["nodes"][0]["rect"][2:], [0, 0])
        self.assertEqual(projected["nodes"][1]["transform"], [2, 2, -20, 20])
        self.assertEqual(projected["nodes"][1]["rect"], [32, 32, 40, 20])
        self.assertEqual((projected["width"], projected["height"]), (104, 84))
        self.assertFalse(projected["diagram_viewport"]["is_recovered_runtime_viewport"])

    def test_hidden_saved_states_included_without_claiming_visibility_or_rotation(self):
        original = scene()
        original["nodes"].append(node(2, 0, size=(10, 10), position=(100, 0), visible=0))
        original["nodes"][2]["options"]["widget"]["rotationSkew"] = {"x": 30, "y": 30}
        projected = render.project_component(original)
        self.assertEqual(projected["width"], 189)
        self.assertFalse(projected["nodes"][2]["effective_visible"])
        self.assertIn("rotationSkew ignored", projected["nodes"][2]["estimate_reasons"])

    def test_only_fixed_exact_zero_root_component_can_get_inferred_viewport(self):
        for path, size in (("synthetic/other.csb", (0, 0)), (render.CSB_PATHS[-1], (0, 1)),
                           (render.CSB_PATHS[-1], (-1, 0))):
            value = scene(path)
            value["nodes"][0]["options"]["widget"]["size"] = dict(zip(("width", "height"), size))
            with self.subTest(path=path, size=size), self.assertRaises(ValueError):
                render._project(value)
        empty = scene()
        empty["nodes"] = empty["nodes"][:1]
        with self.assertRaisesRegex(render.CardBattleRenderError, "no nonzero child bounds"):
            render.project_component(empty)

    def test_component_and_positive_frames_are_capped(self):
        component = scene()
        component["nodes"][1]["options"]["widget"]["position"]["x"] = render.MAX_DIAGRAM_SIZE + 1
        with self.assertRaisesRegex(render.CardBattleRenderError, "diagram bounds"):
            render._project(component)
        positive = scene(render.CSB_PATHS[0])
        positive["nodes"][0]["options"]["widget"]["size"]["width"] = render.MAX_DIAGRAM_SIZE + 1
        with self.assertRaisesRegex(render.CardBattleRenderError, "diagram bounds"):
            render._project(positive)

    def test_hostile_strings_stay_data_in_html_and_svg(self):
        value = scene()
        attack = '</script><script>unexpected()</script><img src=x onerror=unexpected()>&\u2028'
        value["nodes"][1]["options"]["widget"]["name"] = attack
        projected = render.project_component(value)
        page = render._page({"scenes": [projected], "colors": {}, "limitations": []})
        embedded = re.search(r'<script id="layout-data" type="application/json">(.*?)</script>', page, re.S).group(1)
        self.assertNotIn("<", embedded)
        self.assertEqual(json.loads(embedded)["scenes"][0]["nodes"][1]["name"], attack)
        self.assertIn("Inferred component viewport (saved root 0 × 0)", page)
        svg = ET.fromstring(render.wireframe.scene_svg(projected))
        self.assertEqual(svg.findall(".//{http://www.w3.org/2000/svg}script"), [])

    def test_replay_publishes_fixed_diagrams_evidence_and_verified_source_lineage(self):
        result, reader, decoder = self.run_wrapper()
        self.assertEqual((result["scene_count"], result["node_count"]), (5, 10))
        reader.assert_called_once()
        self.assertEqual(decoder.call_count, 5)
        self.assertTrue(all(call.kwargs["limits"] is render.LIMITS for call in decoder.call_args_list))
        self.assertEqual(set(p.name for p in self.output.iterdir()),
                         {"index.html", "layouts.json", "source-receipt.json", "wireframe-index.json",
                          *[f"scene-{i:02d}.svg" for i in range(5)]})
        layouts = json.loads((self.output / "layouts.json").read_text())
        card = layouts["scenes"][-1]
        self.assertEqual(card["nodes"][0]["options"]["widget"]["size"], {"width": 0, "height": 0})
        self.assertEqual(card["source"]["original_path"], render.CSB_PATHS[-1])
        self.assertEqual(card["source"]["source_zip_sha256"], "c" * 64)
        self.assertTrue(card["source"]["decoded_FHSH_verified"])
        self.assertEqual(list(self.root.glob(".card-battle-render-*")), [])
        self.assertFalse((self.output / "files").exists())

    def test_profile_verification_failure_does_not_publish_or_keep_private_stage(self):
        with patch.object(render.ranges, "read_ranges", side_effect=render.ranges.RangeReadError("pinned profile mismatch")), \
                self.assertRaisesRegex(render.CardBattleRenderError, "pinned profile mismatch"):
            render.render_pack(self.root / "unverified.zip", self.output)
        self.assert_unpublished()

    def test_existing_output_and_dangling_symlink_preserved_before_pack_verification(self):
        self.output.mkdir()
        marker = self.output / "existing.txt"
        marker.write_text("preserve this")
        with patch.object(render.ranges, "read_ranges") as reader, self.assertRaisesRegex(render.CardBattleRenderError, "preserve research"):
            render.render_pack(self.root / "pack.zip", self.output)
        reader.assert_not_called()
        self.assertEqual(marker.read_text(), "preserve this")
        link = self.root / "dangling"
        link.symlink_to(self.root / "missing")
        with self.assertRaises(render.CardBattleRenderError):
            render.render_pack(self.root / "pack.zip", link)
        self.assertTrue(link.is_symlink())

    def test_combined_bytes_and_nodes_are_bounded_before_publication(self):
        for name, value, message in (("MAX_CSB_TOTAL_BYTES", 1, "combined byte"),
                                     ("MAX_TOTAL_NODES", 1, "combined node")):
            with self.subTest(bound=name), patch.object(render, name, value), \
                    self.assertRaisesRegex(render.CardBattleRenderError, message):
                self.run_wrapper()
            self.assert_unpublished()

    def test_changed_verified_file_and_missing_fixed_scene_fail_closed(self):
        for mutation in ("hash", "missing"):
            def changed_reader(pack, destination):
                receipt = self.fake_reader(pack, destination)
                if mutation == "hash":
                    receipt["files"][0]["decoded_sha256"] = "f" * 64
                else:
                    receipt["files"].pop()
                return receipt
            with self.subTest(mutation=mutation), patch.object(render.ranges, "read_ranges", side_effect=changed_reader), \
                    patch.object(render.csb, "decode_scene", side_effect=self.fake_decoder), \
                    self.assertRaises(render.CardBattleRenderError):
                render.render_pack(self.root / "pack.zip", self.output)
            self.assert_unpublished()

    def test_publish_failure_removes_owned_files_but_preserves_concurrent_user_file(self):
        def interrupted_copy(incoming, outgoing):
            outgoing.write(b"partial")
            (self.output / "user-added.txt").write_text("preserve concurrent file")
            raise OSError("synthetic write interruption")
        with patch.object(render.shutil, "copyfileobj", side_effect=interrupted_copy), \
                self.assertRaisesRegex(OSError, "write interruption"):
            self.run_wrapper()
        self.assertEqual([p.name for p in self.output.iterdir()], ["user-added.txt"])
        self.assertEqual(list(self.root.glob(".card-battle-render-*")), [])


if __name__ == "__main__":
    unittest.main()
