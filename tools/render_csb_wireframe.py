#!/usr/bin/env python3
"""Render decoded CSB layouts as an offline evidence browser, without game assets."""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import sys


MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_SCENES = 128
MAX_NODES = 20000
COLORS = {"Button": "#ffcc73", "Text": "#adcdff", "TextField": "#adcdff",
          "ImageView": "#78d5c8", "Sprite": "#78d5c8", "LoadingBar": "#fa90ad",
          "Panel": "#b8a1ed", "ScrollView": "#b8a1ed", "ListView": "#b8a1ed",
          "CheckBox": "#ffcc73", "Node": "#667990", "SingleNode": "#667990",
          "ProjectNode": "#e7a577"}
LIMITATIONS = [
    "Approximate projection of serialized local values; this is not a runtime screenshot.",
    "The frame uses the root's logical size, not the device viewport. Outside-frame shapes are cropped.",
    "Position, scale and anchor size are composed through the hierarchy. Nonzero rotationSkew, flips and custom classes are not interpreted; affected estimates are dashed.",
    "Layout constraints, animations, clipping, text metrics, nine-slice textures and runtime visibility/position changes are not reconstructed.",
    "Multiple login, language or state variants can overlap in the saved scene. The branch filter only isolates serialized nodes; it does not infer the active game state.",
    "Colors and labels are diagram aids. No reference textures or fonts are included.",
]


class WireframeError(ValueError):
    pass


def number(value, default=0):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WireframeError("Geometry must contain finite numbers")
    if not math.isfinite(value) or abs(value) > 10000000:
        raise WireframeError("Geometry number exceeds bounds")
    return value


def pair(widget, name, keys=("x", "y"), defaults=(0, 0)):
    value = widget.get(name) or {}
    if not isinstance(value, dict):
        raise WireframeError("Invalid geometry object")
    return tuple(number(value.get(key), default) for key, default in zip(keys, defaults))


def project_scene(scene):
    """Compose scale/translation/anchor in Cocos coordinates, then flip Y for SVG."""
    if not isinstance(scene, dict) or not isinstance(scene.get("nodes"), list):
        raise WireframeError("Scene must contain a node list")
    raw_nodes = scene["nodes"]
    if not raw_nodes or len(raw_nodes) > MAX_NODES:
        raise WireframeError("Scene node count exceeds bounds")
    by_id = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict) or type(raw.get("id")) is not int:
            raise WireframeError("Node IDs must be integers")
        if raw["id"] in by_id:
            raise WireframeError("Duplicate node ID")
        by_id[raw["id"]] = raw
    roots = [raw for raw in raw_nodes if raw.get("parent_id") is None]
    if len(roots) != 1:
        raise WireframeError("A scene must have exactly one root")
    root = roots[0]
    root_widget = root.get("options", {}).get("widget", {})
    width, height = pair(root_widget, "size", ("width", "height"), (1280, 720))
    if width <= 0 or height <= 0:
        raise WireframeError("Root logical frame must have positive dimensions")
    projected, active = {}, set()

    def visit(node_id):
        if node_id in projected:
            return projected[node_id]
        if node_id in active:
            raise WireframeError("Cycle in node hierarchy")
        active.add(node_id)
        raw = by_id[node_id]
        parent_id = raw.get("parent_id")
        if parent_id is not None and (type(parent_id) is not int or parent_id not in by_id):
            raise WireframeError("Unknown parent node ID")
        parent = visit(parent_id) if parent_id is not None else None
        options = raw.get("options") or {}
        widget = options.get("widget")
        if widget is None:
            widget = {}
        if not isinstance(widget, dict):
            raise WireframeError("Invalid widget options")
        x, y = pair(widget, "position")
        sx, sy = pair(widget, "scale", defaults=(1, 1))
        ax, ay = pair(widget, "anchorPoint")
        w, h = pair(widget, "size", ("width", "height"))
        if w < 0 or h < 0:
            raise WireframeError("Node size cannot be negative")
        psx, psy, px, py = parent["transform"] if parent else (1, 1, 0, 0)
        tx, ty = px + psx * (x - sx * ax * w), py + psy * (y - sy * ay * h)
        wsx, wsy = psx * sx, psy * sy
        if not all(math.isfinite(v) and abs(v) <= 1e12 for v in (tx, ty, wsx, wsy, wsx*w, wsy*h)):
            raise WireframeError("Composed geometry exceeds bounds")
        left, bottom = min(tx, tx + wsx*w), min(ty, ty + wsy*h)
        bw, bh = abs(wsx*w), abs(wsy*h)
        reasons = list(parent["estimate_reasons"]) if parent else []
        if not options.get("widget"):
            reasons.append("unsupported custom class/options; local geometry unavailable")
        if any(pair(widget, "rotationSkew")):
            reasons.append("rotationSkew ignored")
        if widget.get("flipX") or widget.get("flipY"):
            reasons.append("visual flip ignored")
        visible = bool(widget.get("visible", True)) and number(widget.get("alpha"), 255) > 0
        visible = visible and (parent["effective_visible"] if parent else True)
        result = {"id": node_id, "parent_id": parent_id,
                  "name": str(widget.get("name", "")), "classname": str(raw.get("classname", "unknown")),
                  "transform": [wsx, wsy, tx, ty], "rect": [left, height-bottom-bh, bw, bh],
                  "origin": [px+psx*x, height-(py+psy*y)], "effective_visible": visible,
                  "has_widget": bool(options.get("widget")), "estimate_reasons": sorted(set(reasons)),
                  "node": raw}
        projected[node_id] = result
        active.remove(node_id)
        return result

    for node_id in by_id:
        visit(node_id)
    return {"name": str(scene.get("source", {}).get("original_path", "unnamed scene")),
            "source": scene.get("source", {}), "width": width, "height": height,
            "root_id": root["id"], "nodes": [projected[n["id"]] for n in raw_nodes],
            "limitations": scene.get("limitations", [])}


def safe_json(value):
    """JSON in an inert script block must not contain an HTML closing tag."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def scene_svg(scene):
    width, height = scene["width"], scene["height"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" role="img">',
             '<title>'+html.escape(scene["name"])+" — approximate serialized layout</title>",
             f'<defs><clipPath id="frame"><rect width="{width:g}" height="{height:g}"/></clipPath></defs>',
             f'<rect width="{width:g}" height="{height:g}" fill="#101a27"/>',
             '<g clip-path="url(#frame)" font-family="sans-serif" font-size="12">']
    for node in scene["nodes"]:
        if not node["effective_visible"] or not node["has_widget"] or node["id"] == scene["root_id"]:
            continue
        x, y, w, h = node["rect"]
        if w <= 0 or h <= 0:
            continue
        color = COLORS.get(node["classname"], "#e7a577")
        dash = ' stroke-dasharray="6 4"' if node["estimate_reasons"] else ""
        label = html.escape(f'#{node["id"]} {node["classname"]}: {node["name"]}')
        parts.append(f'<g><title>{label}</title><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{color}" fill-opacity=".035" stroke="{color}" stroke-width="1"{dash}/>')
        if w >= 110 and h >= 28 and node["classname"] in ("Button", "Text", "LoadingBar", "Panel"):
            parts.append(f'<text x="{max(x+4, 4):g}" y="{max(y+14, 14):g}" fill="{color}">{html.escape(node["name"][:30])}</text>')
        parts.append('</g>')
    parts.extend(['</g>', f'<rect x=".5" y=".5" width="{width-1:g}" height="{height-1:g}" fill="none" stroke="#e2e8f0"/>', '</svg>'])
    return "\n".join(parts)


PAGE = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CSB layout evidence browser</title>
<style>
:root{color-scheme:dark;font:15px system-ui,sans-serif;background:#0a111c;color:#dbe4f0}*{box-sizing:border-box}body{margin:0}header{padding:22px 28px 12px;border-bottom:1px solid #28374a}h1{font-size:23px;margin:0 0 5px}p{line-height:1.5;margin:6px 0}.muted{color:#9cabbe}.controls{display:flex;gap:14px;flex-wrap:wrap;align-items:end;margin:16px 0 8px}label{display:grid;gap:5px;font-size:13px}label.check{display:flex;align-items:center;padding:7px 0}select,input{font:inherit;border:1px solid #42546b;background:#152132;color:#eaf0f8;padding:7px;border-radius:5px}select{max-width:100%}main{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:18px;padding:20px 28px}.diagram{background:#101a27;border:1px solid #42546b;border-radius:7px;overflow:hidden}svg{display:block;width:100%;height:auto}.shape{cursor:pointer}.shape:hover rect,.shape.selected rect{stroke-width:3;fill-opacity:.15}.shape:hover text,.shape.selected text{font-weight:700}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin:10px 0}.legend span:before{content:"";display:inline-block;width:9px;height:9px;margin-right:5px;background:var(--c)}aside{min-width:0}#node-select{width:100%;margin:8px 0}#details{font:12px/1.55 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#101a27;border:1px solid #28374a;border-radius:6px;padding:14px;max-height:620px;overflow:auto}details{font-size:13px;background:#101a27;padding:12px;margin-top:15px;border:1px solid #28374a;border-radius:6px}li{line-height:1.5;margin:7px 0}#provenance{font:12px/1.5 ui-monospace,monospace;overflow-wrap:anywhere;margin-top:14px}#scene{min-width:240px}#branch{max-width:270px}.warn{color:#ffce89}@media(max-width:950px){main{grid-template-columns:1fr;padding:16px}header{padding:18px}#details{max-height:400px}}
</style>
<header><h1>CSB layout evidence browser</h1><p class="muted">Offline diagrams of saved scene geometry. Click a shape or select a node to inspect its source evidence.</p><p class="warn">Approximate serialized projection — not a runtime screenshot. State variants may overlap.</p>
<div class="controls"><label>Scene<select id="scene"></select></label><label>Isolate branch<select id="branch"></select></label><label class="check"><input type="checkbox" id="hidden">Show hidden nodes</label><label class="check"><input type="checkbox" id="containers">Show zero-size containers</label><label class="check"><input type="checkbox" id="labels" checked>Labels</label></div></header>
<main><section><div id="caption" class="muted"></div><div class="legend"><span style="--c:#ffcc73">Button / checkbox</span><span style="--c:#adcdff">Text</span><span style="--c:#78d5c8">Image / sprite</span><span style="--c:#b8a1ed">Panel / scroll</span><span style="--c:#fa90ad">Progress</span><span style="--c:#667990">Container</span></div><div id="diagram" class="diagram"></div><div id="provenance"></div><details open><summary>Interpretation limits</summary><ul id="limits"></ul></details></section><aside><strong>Node evidence</strong><select id="node-select" aria-label="Node evidence"></select><div id="details">Select a node.</div></aside></main>
<script id="layout-data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('layout-data').textContent), scenes=data.scenes;
const $=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
const colors=data.colors; let current=0, selected=null;
function element(tag,attrs={},text=null){const el=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==null)el.textContent=text;return el}
function option(select,value,label){const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o)}
function byId(scene){return new Map(scene.nodes.map(n=>[n.id,n]))}
function belongs(n,branch,index){let p=n;while(p){if(p.id===branch)return true;p=index.get(p.parent_id)}return false}
function inspect(id){const s=scenes[current],n=s.nodes.find(n=>n.id===Number(id));if(!n)return;selected=n.id;$('node-select').value=String(n.id);const raw=n.node,w=raw.options?.widget??{};
 const evidence={node_id:n.id,parent_id:n.parent_id,name:n.name,classname:n.classname,custom_class:raw.customClassName||'',source_path:s.source.evidence_path||s.name,source_sha256:s.source.original_sha256||'',stored_sha256:s.source.stored_sha256||'',node_table:raw.evidence,options_wrapper:raw.options_wrapper,widget_table:w.evidence,local_position:w.position,size:w.size,anchor:w.anchorPoint,scale:w.scale,rotationSkew:w.rotationSkew,visible:w.visible,alpha:w.alpha,effective_serialized_visibility:n.effective_visible,touchEnabled:w.touchEnabled,estimated_svg_rectangle:n.rect,estimate_reasons:n.estimate_reasons,resources:raw.options?.resources??{},strings:raw.options?.strings??{},layout_component:w.layoutComponent};
 $('details').textContent=JSON.stringify(evidence,null,2);document.querySelectorAll('.shape').forEach(g=>g.classList.toggle('selected',g.dataset.node===String(selected)))}
function draw(){const s=scenes[current],index=byId(s),branch=Number($('branch').value),showHidden=$('hidden').checked,showContainers=$('containers').checked;const svg=element('svg',{viewBox:`0 0 ${s.width} ${s.height}`,role:'img','aria-label':s.name+' approximate serialized geometry'});const defs=element('defs'),clip=element('clipPath',{id:'logical-frame'});clip.append(element('rect',{width:s.width,height:s.height}));defs.append(clip);svg.append(defs);const layer=element('g',{'clip-path':'url(#logical-frame)'});svg.append(layer);
 const included=s.nodes.filter(n=>belongs(n,branch,index));let count=0;
 for(const n of included){if(n.id===s.root_id||(!showHidden&&!n.effective_visible))continue;const[x,y,w,h]=n.rect;if(!n.has_widget)continue;if((w===0||h===0)&&!showContainers)continue;count++;const color=colors[n.classname]||'#e7a577',g=element('g',{class:'shape','data-node':n.id,tabindex:0,role:'button','aria-label':`Node ${n.id} ${n.classname} ${n.name}`});g.append(element('title',{},`#${n.id} ${n.classname}: ${n.name}${n.estimate_reasons.length?' — estimated; '+n.estimate_reasons.join('; '):''}`));let labelX=x+4,labelY=y+14;
 if(w===0||h===0){const[ox,oy]=n.origin;g.append(element('rect',{x:ox-3,y:oy-3,width:6,height:6,fill:color,'fill-opacity':.3,stroke:color}));labelX=ox+6;labelY=oy-5}else{g.append(element('rect',{x,y,width:w,height:h,fill:color,'fill-opacity':n.effective_visible?.035:.01,stroke:color,'stroke-width':1,'stroke-dasharray':n.estimate_reasons.length||!n.effective_visible?'6 4':'none'}))}
 if($('labels').checked&&(w>=110&&h>=28&&['Button','Text','LoadingBar','Panel'].includes(n.classname)||showContainers&&(w===0||h===0))){g.append(element('text',{x:Math.max(4,labelX),y:Math.max(14,labelY),fill:color,'font-size':12,'font-family':'sans-serif','pointer-events':'none'},n.name.slice(0,30)))}
 g.addEventListener('pointerenter',()=>inspect(n.id));g.addEventListener('click',()=>inspect(n.id));g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspect(n.id)}});layer.append(g)}
 svg.append(element('rect',{x:.5,y:.5,width:s.width-1,height:s.height-1,fill:'none',stroke:'#dbe4f0','pointer-events':'none'}));$('diagram').replaceChildren(svg);$('caption').textContent=`Logical frame ${s.width} × ${s.height} · ${s.nodes.length} nodes · ${count} drawn · dashed = hidden / unsupported transform estimate`;
 if(selected!==null)inspect(selected)}
function changeScene(){current=Number($('scene').value);const s=scenes[current];selected=null;$('branch').replaceChildren();option($('branch'),s.root_id,'All serialized branches');for(const n of s.nodes){if(n.id!==s.root_id&&s.nodes.some(child=>child.parent_id===n.id))option($('branch'),n.id,`#${n.id} ${n.name||n.classname}`)}$('node-select').replaceChildren();for(const n of s.nodes)option($('node-select'),n.id,`#${n.id} ${n.classname}: ${n.name}${n.effective_visible?'':' [hidden]'}`);
 $('provenance').textContent=`Archive path: ${s.source.evidence_path||s.name}\nCSB SHA-256: ${s.source.original_sha256||'not provided'}\nLayouts JSON SHA-256: ${data.layouts_sha256}`;$('provenance').style.whiteSpace='pre-wrap';$('limits').replaceChildren();for(const text of data.limitations){const li=document.createElement('li');li.textContent=text;$('limits').append(li)}draw();inspect(s.root_id)}
scenes.forEach((s,i)=>option($('scene'),i,s.name.split('/').pop()));const initial=scenes.findIndex(s=>s.name.endsWith('/scene_title_pre.csb'));$('scene').value=String(initial>=0?initial:0);$('scene').addEventListener('change',changeScene);$('branch').addEventListener('change',draw);for(const id of ['hidden','containers','labels'])$(id).addEventListener('change',draw);$('node-select').addEventListener('change',()=>inspect($('node-select').value));changeScene();
</script></html>
'''


def render_layouts(layouts_path, output):
    layouts_path, output = Path(layouts_path), Path(output)
    if layouts_path.stat().st_size > MAX_INPUT_BYTES:
        raise WireframeError("Layouts JSON exceeds input size limit")
    raw = layouts_path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise WireframeError("Layouts JSON exceeds input size limit")
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise WireframeError("Invalid layouts JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("scenes"), list):
        raise WireframeError("Expected decoded layouts document")
    scenes = document["scenes"]
    if not 1 <= len(scenes) <= MAX_SCENES:
        raise WireframeError("Scene count exceeds bounds")
    if sum(len(s.get("nodes", [])) for s in scenes if isinstance(s, dict)) > MAX_NODES:
        raise WireframeError("Total node count exceeds bounds")
    projected = [project_scene(scene) for scene in scenes]
    provenance = {"layouts_sha256": hashlib.sha256(raw).hexdigest(),
                  "pack_index_sha256": document.get("pack_index_sha256"),
                  "pack_input": document.get("pack_input"),
                  "colors": COLORS, "limitations": LIMITATIONS, "scenes": projected}
    page = PAGE.replace("__DATA__", safe_json(provenance))
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise WireframeError("Output must be a new or empty directory; existing research is preserved")
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(page, encoding="utf-8")
    names = []
    # Fixed generated names avoid trusting archive paths as filesystem paths.
    for i, scene in enumerate(projected):
        name = f"scene-{i:02d}.svg"
        (output / name).write_text(scene_svg(scene), encoding="utf-8")
        names.append({"svg": name, "original_path": scene["name"]})
    summary = {"scene_count": len(projected), "node_count": sum(len(s["nodes"]) for s in projected),
               "layouts_sha256": provenance["layouts_sha256"], "files": names,
               "limitations": LIMITATIONS}
    (output / "wireframe-index.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layouts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New or empty ignored research directory")
    args = parser.parse_args(argv)
    try:
        summary = render_layouts(args.layouts, args.output)
    except (OSError, WireframeError, TypeError, RecursionError) as error:
        print(f"Wireframe failed: {error}", file=sys.stderr)
        return 1
    print(f"Rendered {summary['scene_count']} scenes / {summary['node_count']} nodes: {args.output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
