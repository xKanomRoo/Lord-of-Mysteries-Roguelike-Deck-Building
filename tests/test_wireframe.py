import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.render_csb_wireframe import WireframeError, project_scene, render_layouts, safe_json, scene_svg


def node(id, parent=None, position=(0, 0), size=(0, 0), scale=(1, 1), anchor=(0, 0), visible=1):
    return {"id": id, "parent_id": parent, "classname": "Button", "evidence": {"table_offset": 64},
            "options": {"widget": {"name": f"node{id}", "position": dict(zip(("x", "y"), position)),
                                    "size": dict(zip(("width", "height"), size)),
                                    "scale": dict(zip(("x", "y"), scale)),
                                    "anchorPoint": dict(zip(("x", "y"), anchor)), "visible": visible}}}


class WireframeTests(unittest.TestCase):
    def setUp(self):
        self.scene = {"source": {"original_path": "assets/pre/ui/example.csb", "original_sha256": "a"*64},
                      "nodes": [node(0, size=(1280, 720)),
                                node(1, 0, position=(200, 100), size=(100, 50), scale=(2, 3), anchor=(.5, .5)),
                                node(2, 1, position=(20, 10), size=(10, 8), anchor=(.5, .5))]}

    def test_anchor_scale_hierarchy_and_cocos_y_projection(self):
        result = project_scene(self.scene)
        parent, child = result["nodes"][1:]
        self.assertEqual(parent["rect"], [100, 545, 200, 150])
        self.assertEqual(child["rect"], [130, 653, 20, 24])
        # Negative parent scale mirrors the descendant rectangle without a negative SVG size.
        self.scene["nodes"][1]["options"]["widget"]["scale"]["x"] = -2
        child = project_scene(self.scene)["nodes"][2]
        self.assertEqual(child["rect"], [250, 653, 20, 24])

    def test_visibility_and_unsupported_rotation_propagate(self):
        widget = self.scene["nodes"][1]["options"]["widget"]
        widget["visible"] = 0
        widget["rotationSkew"] = {"x": 45, "y": 45}
        result = project_scene(self.scene)
        self.assertFalse(result["nodes"][2]["effective_visible"])
        self.assertIn("rotationSkew ignored", result["nodes"][2]["estimate_reasons"])

    def test_malformed_hierarchy_and_geometry_are_rejected(self):
        for mutation in ("cycle", "unknown", "duplicate", "nan"):
            scene = copy.deepcopy(self.scene)
            if mutation == "cycle":
                scene["nodes"][1]["parent_id"] = 2
            elif mutation == "unknown":
                scene["nodes"][1]["parent_id"] = 99
            elif mutation == "duplicate":
                scene["nodes"][2]["id"] = 1
            else:
                scene["nodes"][1]["options"]["widget"]["position"]["x"] = float("nan")
            with self.subTest(mutation=mutation), self.assertRaises(WireframeError):
                project_scene(scene)

    def test_untrusted_strings_cannot_close_json_script_or_svg_text(self):
        attack = '</script><script>alert(1)</script><img src=x onerror=alert(2)>&\u2028'
        encoded = safe_json({"value": attack})
        self.assertNotIn("<", encoded)
        self.assertEqual(json.loads(encoded)["value"], attack)
        self.scene["nodes"][1]["options"]["widget"]["name"] = attack
        svg = scene_svg(project_scene(self.scene))
        root = ET.fromstring(svg)
        self.assertEqual(len(root.findall(".//{http://www.w3.org/2000/svg}script")), 0)
        self.assertIn("&lt;/script&gt;", svg)

    def test_existing_outputs_preserved_and_archive_paths_never_used_as_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layouts = root / "layouts.json"
            self.scene["source"]["original_path"] = "../../outside.html"
            layouts.write_text(json.dumps({"scenes": [self.scene]}))
            output = root / "output"
            summary = render_layouts(layouts, output)
            self.assertEqual(summary["files"][0]["svg"], "scene-00.svg")
            self.assertTrue((output / "index.html").exists())
            self.assertFalse((root / "outside.html").exists())
            with self.assertRaisesRegex(WireframeError, "preserved"):
                render_layouts(layouts, output)


if __name__ == "__main__":
    unittest.main()
