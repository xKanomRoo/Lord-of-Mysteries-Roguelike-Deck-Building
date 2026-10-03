#!/usr/bin/env python3
"""Deliver a complete private resource catalog from already verified research.

This reader never runs game code. Manifest labels are metadata, not paths to
write or proof of received assets. Full outputs stay outside Git in .local/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import shutil
import stat
import struct
import zipfile
import zlib

try:
    from . import extract_ssra_resources as extractor
    from . import read_ssra_manifest as ssra
except ImportError:
    import extract_ssra_resources as extractor
    import read_ssra_manifest as ssra

MANIFEST_SHA = '45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15'
MAX_FILE = 128 * 1024 * 1024
MAX_ZIP = 30 * 1024 * 1024
STATUSES = {'metadata_only': 'มีรายชื่อ ยังไม่มีไฟล์',
            'received_container': 'ได้รับไฟล์ ถอด container แล้ว',
            'decoded_png': 'ถอดเป็นภาพ PNG แล้ว'}


class CatalogError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_bytes(path: Path, expected_sha: str | None = None,
                  expected_size: int | None = None) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
        raise CatalogError('Only bounded, regular, nonsymlink files are accepted')
    if expected_size is not None and info.st_size != expected_size:
        raise CatalogError('Source size differs from its receipt')
    data = path.read_bytes()
    if len(data) != info.st_size or expected_sha is not None and digest(data) != expected_sha:
        raise CatalogError('Source bytes differ from their receipt')
    return data


def read_json(path: Path) -> dict:
    value = json.loads(checked_bytes(path))
    if not isinstance(value, dict):
        raise CatalogError('An object receipt is required')
    return value


def source_label(label: str) -> str:
    if (not isinstance(label, str) or not label or label.startswith('/') or '\\' in label
            or ':' in label or any(ord(c) < 32 or ord(c) == 127 for c in label)
            or any(c in ('', '.', '..') for c in label.split('/'))):
        raise CatalogError('Invalid resource label')
    return label


def check_decoded_receipt(manifest: dict, receipt: dict, root: Path) -> dict:
    if receipt.get('source_manifest', {}).get('sha256') != MANIFEST_SHA:
        raise CatalogError('Resource receipt is for a different manifest')
    by_path = {r['path']: r for r in manifest['files']}
    found = {}
    for entry in receipt['files']:
        name = source_label(entry['resource_path'])
        if name in found or name not in by_path:
            raise CatalogError('Duplicate or unknown received resource')
        row = by_path[name]
        for key, receipt_key in [('row', 'manifest_file_row'), ('group_id', 'group_id'),
                                 ('stored_length', 'stored_bytes'), ('decoded_length', 'decoded_bytes')]:
            if row[key] != entry[receipt_key]:
                raise CatalogError('Receipt resource differs from manifest row')
        label = source_label(entry['archive_path'])
        # Source receipts emitted by our readers use only ordinal inert members.
        if not label.startswith('files/') or len(label.split('/')) != 2 or not label.endswith('.bin'):
            raise CatalogError('Expected an ordinal source member')
        data = checked_bytes(root / label, entry['decoded_sha256'], row['decoded_length'])
        if ssra.xxh64(data) != row['file_hash64'] or not entry.get('fhsh_verified'):
            raise CatalogError('Decoded FHSH mismatch or missing verification')
        found[name] = dict(entry)
    return found


def png_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise CatalogError('Invalid PNG signature')
    cursor = 8
    dimensions = None
    idat = bytearray()
    ended = False
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise CatalogError('Truncated PNG chunk')
        size = struct.unpack_from('>I', data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        end = cursor + 12 + size
        if end > len(data):
            raise CatalogError('Truncated PNG payload')
        payload = data[cursor + 8:cursor + 8 + size]
        expected = struct.unpack_from('>I', data, cursor + 8 + size)[0]
        if zlib.crc32(kind + payload) & 0xffffffff != expected:
            raise CatalogError('PNG CRC mismatch')
        if kind == b'IHDR':
            if cursor != 8 or size != 13:
                raise CatalogError('Invalid PNG header')
            dimensions = struct.unpack_from('>II', payload)
            if not all(0 < d <= 8192 for d in dimensions):
                raise CatalogError('Invalid PNG dimensions')
        elif kind == b'IDAT':
            idat.extend(payload)
        elif kind == b'IEND':
            if size or end != len(data):
                raise CatalogError('Invalid PNG end')
            ended = True
        cursor = end
    if dimensions is None or not ended or not idat:
        raise CatalogError('Incomplete PNG')
    return dimensions


def category(name: str) -> str:
    return name.split('/', 1)[0]


def build_catalog(manifest: dict, received: dict, images: dict) -> tuple[list[dict], dict]:
    rows = []
    seen = set()
    group_names = {g['id']: g['name'] for g in manifest['groups']}
    for item in manifest['files']:
        name = source_label(item['path'])
        if name in seen:
            raise CatalogError('Duplicate manifest path')
        seen.add(name)
        evidence = received.get(name)
        image = images.get(name)
        status = 'decoded_png' if image else 'received_container' if evidence else 'metadata_only'
        rows.append({'row': item['row'], 'path': name, 'extension': Path(name).suffix,
                     'category': category(name), 'group': group_names[item['group_id']],
                     'group_id': item['group_id'], 'stored_bytes': item['stored_length'],
                     'declared_decoded_bytes': item['decoded_length'], 'status': status,
                     'received': evidence is not None,
                     'container_decoded': evidence is not None,
                     'decoded_sha256': evidence['decoded_sha256'] if evidence else None,
                     'stored_sha256': evidence['stored_sha256'] if evidence else None,
                     'fhsh_xxh64': f"{item['file_hash64']:016x}",
                     'png_path': image['png_path'] if image else None,
                     'format_inspection': ('PNG texture/atlas; not composed screenshot' if image else
                         'V8 cache/container; not plaintext or complete logic' if name.endswith('.jbin') and evidence else
                         'Animation container; rig/timelines not reconstructed' if name.endswith('.scsp') and evidence else
                         'Static received reference; complete runtime assembly unverified' if evidence else
                         'Metadata label only; actual content unknown')})
    if set(received) - seen or set(images) - seen:
        raise CatalogError('Evidence points outside the manifest')
    summary = {'manifest_resources': len(rows),
               'received_manifest_resources': sum(r['received'] for r in rows),
               'metadata_only_resources': sum(not r['received'] for r in rows),
               'manifest_stored_bytes_sum': sum(r['stored_bytes'] for r in rows),
               'manifest_declared_decoded_bytes_sum': sum(r['declared_decoded_bytes'] for r in rows),
               'status_counts': dict(Counter(r['status'] for r in rows)),
               'extensions': dict(Counter(r['extension'] for r in rows).most_common()),
               'categories': dict(Counter(r['category'] for r in rows).most_common())}
    return rows, summary


def write_catalog_html(path: Path, rows: list[dict], summary: dict) -> None:
    # Compact arrays keep this fully offline file usable without a fetch/server.
    small = [[r[k] for k in ('path', 'extension', 'category', 'status', 'stored_bytes', 'declared_decoded_bytes')]
             for r in rows]
    data = json.dumps(small, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    body = '''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>รายการทรัพยากร CZN ทั้งหมด</title>
<style>body{font:16px system-ui;background:#121827;color:#eef1fa;margin:24px}a{color:#a9ccff}input,select,button{font:inherit;padding:8px;margin:5px;background:#252f43;color:white;border:1px solid #52607a}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #354158;text-align:left}td:first-child{overflow-wrap:anywhere}small{color:#bec8dc}</style>
<h1>รายการทรัพยากร CZN ทั้งหมด</h1><p>รายชื่อจาก manifest ไม่เท่ากับภาพหรือไฟล์ที่ได้รับในคลาวด์ จำนวนรายการรวม variants และส่วนประกอบ ไม่ใช่จำนวนตัวละคร การ์ด หรือฉากที่เล่นได้</p>
<p id="summary"></p><p><a href="resources.csv" download>ดาวน์โหลด CSV ครบทุกแถว</a> · <a href="catalog.json" download>JSON และหลักฐาน</a> · <a href="gallery/index.html">ดูภาพที่ถอดได้ทั้งหมด</a></p>
<label>ค้นหา <input id="query" placeholder="เช่น card_illustration, model, sound"></label><label>หมวด <select id="category"><option value="">ทั้งหมด</option></select></label><label>สถานะ <select id="status"><option value="">ทั้งหมด</option><option value="metadata_only">มีรายชื่อ ยังไม่มีไฟล์</option><option value="received_container">ได้รับไฟล์ ถอด container แล้ว</option><option value="decoded_png">ถอดเป็น PNG แล้ว</option></select></label><label>ชนิดไฟล์ <select id="extension"><option value="">ทั้งหมด</option></select></label>
<p id="count"></p><button id="prev">หน้าก่อน</button><button id="next">หน้าถัดไป</button><table><thead><tr><th>ชื่อ resource</th><th>สถานะ</th><th>stored bytes ตาม manifest</th><th>decoded bytes ตาม manifest</th></tr></thead><tbody id="rows"></tbody></table>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),labels={metadata_only:'มีรายชื่อ ยังไม่มีไฟล์',received_container:'ได้รับไฟล์ ถอด container แล้ว',decoded_png:'ถอดเป็นภาพ PNG แล้ว'};
const els=Object.fromEntries(['query','category','status','extension','rows','count','prev','next'].map(k=>[k,document.getElementById(k)]));let page=0;let filtered=[];
for(const [id,col] of [['category',2],['extension',1]])for(const v of [...new Set(data.map(r=>r[col]))].sort()){const o=document.createElement('option');o.value=v;o.textContent=v||'(ไม่มีนามสกุล)';els[id].append(o);}
function render(){const q=els.query.value.toLowerCase();filtered=data.filter(r=>(!q||r[0].toLowerCase().includes(q))&&(!els.category.value||r[2]===els.category.value)&&(!els.status.value||r[3]===els.status.value)&&(!els.extension.value||r[1]===els.extension.value));const total=Math.max(1,Math.ceil(filtered.length/200));page=Math.max(0,Math.min(page,total-1));els.rows.replaceChildren();for(const r of filtered.slice(page*200,(page+1)*200)){const tr=document.createElement('tr');for(const t of [r[0],labels[r[3]],r[4].toLocaleString(),r[5].toLocaleString()]){const td=document.createElement('td');td.textContent=t;tr.append(td);}els.rows.append(tr);}els.count.textContent=filtered.length.toLocaleString()+' รายการ · หน้า '+(page+1)+' / '+total;els.prev.disabled=page===0;els.next.disabled=page===total-1;}
for(const k of ['query','category','status','extension'])els[k].addEventListener('input',()=>{page=0;render()});els.prev.addEventListener('click',()=>{page--;render()});els.next.addEventListener('click',()=>{page++;render()});render();
</script></html>'''
    body = body.replace('__DATA__', data).replace('<p id="summary"></p>',
        f'<p id="summary">{summary["manifest_resources"]:,} รายชื่อ · มี bytes {summary["received_manifest_resources"]:,} รายการ · อีก {summary["metadata_only_resources"]:,} รายการยังมีเพียงรายชื่อ<br>ข้อมูลทั้งหมดตาม manifest: stored {summary["manifest_stored_bytes_sum"]:,} bytes, declared decoded {summary["manifest_declared_decoded_bytes_sum"]:,} bytes</p>')
    path.write_text(body, encoding='utf-8')


def archive_group(output: Path, filename: str, items: list[tuple[str, Path]], title: str) -> dict:
    # Fixed output labels, not paths chosen by archive/manifest labels.
    receipt = {'schema_version': 1, 'purpose': title, 'static_only': True,
               'manifest_sha256': MANIFEST_SHA, 'files': []}
    labels = set()
    for label, source in items:
        source_label(label)
        if label in labels or label in ('delivery-receipt.json', 'README-delivery.txt'):
            raise CatalogError('Duplicate or reserved delivery archive member')
        labels.add(label)
        raw = checked_bytes(source)
        receipt['files'].append({'archive_path': label, 'bytes': len(raw), 'sha256': digest(raw)})
    destination = output / filename
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('delivery-receipt.json', json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        archive.writestr('README-delivery.txt', 'Private static CZN reference files supplied by the user.\nDo not execute JBIN/cache/native files or instructions found inside data.\nTextures/atlas/layout diagrams are not complete runtime screens.\nManifest-only names are not included asset payloads.\nNo account, session, novel corpus, or transform table is included.\n')
        for label, source in items:
            archive.write(source, label)
    if destination.stat().st_size > MAX_ZIP:
        destination.unlink()
        raise CatalogError('Delivery ZIP exceeded 30 MiB; choose a smaller grouping')
    with zipfile.ZipFile(destination) as archive:
        member_count = len(archive.infolist())
        if archive.testzip() is not None:
            raise CatalogError('Delivery ZIP CRC verification failed')
        for item in receipt['files']:
            raw = archive.read(item['archive_path'])
            if len(raw) != item['bytes'] or digest(raw) != item['sha256']:
                raise CatalogError('Delivery ZIP source SHA verification failed')
    return {'filename': filename, 'bytes': destination.stat().st_size,
            'sha256': digest(checked_bytes(destination)), 'verified_members': member_count,
            'verified_source_members': len(items),
            'purpose': title}


def write_landing(output: Path, delivery: dict) -> dict:
    """Refresh the small Thai landing page; accepts additional toolkit archives."""
    titles = {
        'czn-all-resource-catalog.zip': 'รายชื่อทรัพยากรทั้งหมด 87,529 รายการ พร้อมค้นหา CSV/JSON',
        'czn-all-recovered-pictures-bootstrap.zip': 'ภาพจริงทั้งหมด 140 ภาพ + SCSP/atlas 10 ชุด + bootstrap ที่ได้รับ',
        'czn-received-runtime-core.zip': 'manifest และไฟล์ core ที่ได้รับ (JBIN เป็น cached code ที่ยังไม่อ่านเป็น source)',
        'czn-received-runtime-english.zip': 'ไฟล์ภาษาอังกฤษต้นฉบับที่ได้รับครบ 4 chunks',
        'czn-decoded-main-container.zip': 'main container ที่ถอด Zstd แล้ว ยังไม่ใช่ source code หรือสูตรเกมทั้งหมด',
        'czn-all-recovered-text-data-layouts.zip': 'ข้อความอังกฤษ ตารางการ์ด/effect/condition และผัง UI ที่อ่านได้',
        'czn-received-card-battle-ranges.zip': 'แพ็กเดิมที่ได้รับ: card/battle 18 resources พร้อม manifest/index',
        'czn-export-all-toolkit.zip': 'เครื่องมือส่งออกไฟล์เกมทั้งหมดที่มีใน LDPlayer พร้อมกลับมาถอดในคลาวด์',
        'czn-received-native-source.zip': 'split APK ARM64 ที่ผู้ใช้ส่งมา พร้อมข้อมูล native libraries ที่ตรวจแล้ว',
    }
    s = delivery['summary']
    rows = []
    for entry in delivery['archives']:
        name = source_label(entry['filename'])
        rows.append(f'<article><h2><a href="{html.escape(name)}" download>{html.escape(titles.get(name, entry["purpose"]))}</a></h2>'
                    f'<p>{html.escape(name)} · {entry["bytes"] / 1048576:.2f} MiB</p>'
                    f'<small>SHA-256: {html.escape(entry["sha256"])}</small></article>')
    page = '''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>เริ่มดูไฟล์ CZN ทั้งหมดตรงนี้</title><style>body{font:17px system-ui;background:#101622;color:#e7edf8;max-width:1040px;margin:auto;padding:24px}a{color:#add0ff}article{padding:16px;background:#222c3e;margin:14px 0;border-radius:12px}h2{font-size:19px}small{overflow-wrap:anywhere;color:#b7c7df}strong{color:#c4e9ff}</style><h1>ข้อมูล CZN ทั้งหมดที่ส่งมอบได้ตอนนี้</h1>'''
    page += (f'<p><strong>{s["total_png_images"]} ภาพจริง</strong> · {s["received_scsp_atlas_sets"]} ชุด SCSP/atlas · '
             f'{s["received_manifest_resources"]} resources ใน manifest ที่ได้รับ/ถอด container แล้ว · '
             f'{s["bootstrap_received_resources"]} bootstrap resources จาก APK</p>'
             f'<p>manifest มี {s["manifest_resources"]:,} รายชื่อ อีก {s["metadata_only_resources"]:,} รายการยังไม่มีไฟล์ในคลาวด์ '
             'รวมภาพตัวละคร การ์ด ฉาก เพลง และเสียงส่วนใหญ่ รายชื่อเหล่านี้ไม่ใช่ภาพที่ซ่อนไว้หรือภาพที่ถอดแล้ว '
             'ต้องนำไฟล์ทรัพยากรจากเครื่อง LDPlayer ของผู้ใช้มารับก่อนจึงจะถอดได้</p>'
             '<p>29 ภาพที่ถอดเพิ่มเป็น UI/ข้อความ/effect ภาษาอังกฤษ ภาพ140ภาพไม่ใช่ภาพตัวละคร140ตัว '
             'SCSP/atlas ยังไม่ได้ประกอบเป็นตัวละครเคลื่อนไหว รูป atlas และผัง CSB ยังไม่ใช่ภาพเกมขณะเล่น</p>'
             '<p>ขนาด resource ทั้งหมดตาม manifest: stored 7.70 GiB, declared decoded 8.47 GiB '
             'ขนาดนี้เป็น metadata ของทุกกลุ่มภาษา/ระบบ ไม่ใช่ bytes ที่เรามีในคลาวด์</p>'
             '<p><a href="resources.html">ค้นหารายชื่อครบทุก resource</a> · <a href="gallery/index.html">เปิดแกลเลอรีภาพจริงทั้งหมด</a> · '
             '<a href="delivery-index.json">ใบรับรอง hashes และสถานะ</a></p>'
             '<p>ดาวน์โหลดแพ็กที่ต้องการแล้วแตกไฟล์ลงโฟลเดอร์เดียวกันเพื่อเปิดดูแบบออฟไลน์ '
             'ทุก ZIP ต่ำกว่า30MiB ข้อมูลภาพ/ตาราง/ข้อความเป็นงานวิจัยส่วนตัวนอกGit '
             'ไม่มีข้อมูลบัญชี session นิยาย หรือ private transform table และไม่ควรรัน code/cache ในไฟล์เกม</p>')
    page += ''.join(rows) + '</html>'
    (output / 'index.html').write_text(page, encoding='utf-8')
    return archive_group(output, 'OPEN-THIS-FIRST.zip',
                         [(name, output / name) for name in ('index.html', 'delivery-index.json', 'summary.json', 'README.txt')],
                         'เริ่มเปิดหน้ารวมภาษาไทยและใบตรวจ SHA ของแพ็กทั้งหมด')


def add_native_archive(repo: Path, output: Path, apk: Path) -> dict:
    """Re-deliver only the exact uploaded architecture APK, never execute it."""
    source_sha = '6ef56d50d15168a8c29c080f8e621468876263de14410998fbc99ecca6179908'
    raw = checked_bytes(apk, source_sha, 22979689)
    index_path = repo / '.local/research/native-inventory-tool-v1/native-index.json'
    index = read_json(index_path)
    if index['input']['sha256'] != source_sha or index['library_count'] != 10:
        raise CatalogError('Native source index is not the exact received architecture APK')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() is not None:
            raise CatalogError('Received native APK has invalid ZIP CRC')
        for entry in index['files']:
            data = archive.read(source_label(entry['original_path']))
            if digest(data) != entry['sha256'] or len(data) != entry['bytes']:
                raise CatalogError('Native APK member differs from verified library index')
    notes = output / 'native-source-note.txt'
    notes.write_text('split APK ARM64 ที่ผู้ใช้ส่งมาตรวจแบบ static มี10native libraries รวม74,003,680bytes\n'
                     'ยังไม่เคย execute APKหรือlibraries ไม่ใช่ developer source code และไม่ใช่APKติดตั้งเดี่ยว\n'
                     'ไม่มี disassembly, private transform table หรือ decoded SDK config ในแพ็กนี้\n'
                     'ตัวเต็มXAPKยังไม่ได้รับในคลาวด์\n', encoding='utf-8')
    return archive_group(output, 'czn-received-native-source.zip',
                         [('config.arm64_v8a.apk', apk), ('native-index.json', index_path),
                          ('native-source-note.txt', notes)],
                         'Exact received ARM64 architecture split APK and sanitized structural native inventory; never executed')


def generate(repo: Path, output: Path, card_range_zip: Path | None = None,
             native_apk: Path | None = None) -> dict:
    research = repo / '.local/research'
    output.mkdir(parents=True, exist_ok=True)
    source, actual_manifest_sha, raw_runtime = extractor._load_resources(research / 'runtime-received-45a009358972')
    if actual_manifest_sha != MANIFEST_SHA:
        raise CatalogError('Unexpected source manifest')
    manifest = ssra.parse_ssra(raw_runtime['files/00.bin'])
    supplied = {Path(t.relative_path).name: (f'files/{i:02d}.bin', raw_runtime[f'files/{i:02d}.bin'])
                for i, t in enumerate(extractor.TARGETS) if i}
    for chunk in manifest['chunks']:
        if chunk['filename'] in supplied:
            extractor._verify_chunk(chunk, supplied[chunk['filename']][1])
    roots = [research / 'runtime-extracted-45a009358972',
             research / 'card-battle-received-a9c3e7951c9c', output / 'english-extracted']
    received = {}
    for root in roots:
        receipt = read_json(root / 'resource-index.json')
        more = check_decoded_receipt(manifest, receipt, root)
        for name, entry in more.items():
            if name in received and received[name]['decoded_sha256'] != entry['decoded_sha256']:
                raise CatalogError('Conflicting decoded source receipts')
            received[name] = entry
    # Check physically supplied groups have been fully extracted, not overlooked.
    for row in manifest['files']:
        if row['group_id'] in (2, 9) and row['path'] not in received:
            raise CatalogError('Available English/core resource has not been extracted')
    bootstrap = research / 'verified-bootstrap'
    bootstrap_index = read_json(bootstrap / 'pack-index.json')
    for entry in bootstrap_index['files']:
        checked_bytes(bootstrap / source_label(entry['stored_path']), entry['stored_sha256'], entry['stored_bytes'])
    prior_gallery = read_json(research / 'visual-audit/catalog.json')
    new_gallery = read_json(output / 'english-image-receipt.json')
    if new_gallery.get('failures'):
        raise CatalogError('Not all available English textures were decoded')
    gallery = output / 'gallery'
    (gallery / 'images').mkdir(parents=True, exist_ok=True)
    pictures = []
    for collection, catalog, source_root in [('bootstrap', prior_gallery, research / 'visual-audit'),
                                            ('runtime_english', new_gallery, output)]:
        for image in catalog['images']:
            raw = checked_bytes(source_root / source_label(image['png_path']), image['png_sha256'], image['png_bytes'])
            if png_dimensions(raw) != (image['width'], image['height']):
                raise CatalogError('Gallery PNG dimensions differ from source receipt')
            name = f'images/{len(pictures):03d}-{image["png_sha256"][:12]}.png'
            (gallery / name).write_bytes(raw)
            record = dict(image, png_path='gallery/' + name, source_collection=collection)
            pictures.append(record)
    image_map = {i['source_name']: i for i in pictures if i['source_collection'] == 'runtime_english'}
    for image in image_map.values():
        if image['source_sha256'] != received[image['source_name']]['decoded_sha256']:
            raise CatalogError('Image source identity differs from decoded resource receipt')
    raw_rigs = gallery / 'raw-2d-rigs'
    raw_rigs.mkdir(exist_ok=True)
    rig_sets = []
    for collection, entries, source_root, name_key, path_key, size_key, hash_key in [
            ('bootstrap', bootstrap_index['files'], bootstrap, 'original_path', 'stored_path', 'stored_bytes', 'stored_sha256'),
            ('runtime_english', read_json(roots[2] / 'resource-index.json')['files'], roots[2],
             'resource_path', 'archive_path', 'decoded_bytes', 'decoded_sha256')]:
        by_name = {entry[name_key]: entry for entry in entries}
        for name in sorted(by_name):
            if not name.endswith('.scsp'):
                continue
            atlas_name = name[:-5] + '.atlas'
            if atlas_name not in by_name:
                raise CatalogError('Received SCSP set has no matching atlas')
            files = []
            for source_name, extension in ((name, '.scsp'), (atlas_name, '.atlas')):
                entry = by_name[source_name]
                data = checked_bytes(source_root / source_label(entry[path_key]), entry[hash_key], entry[size_key])
                label = f'raw-2d-rigs/{len(rig_sets):02d}{extension}'
                (gallery / label).write_bytes(data)
                files.append({'source_name': source_name, 'path': label, 'bytes': len(data), 'sha256': digest(data)})
            rig_sets.append({'source_collection': collection, 'source_name': name[:-5], 'files': files,
                             'status': 'Raw serialized2D animation/skeleton and atlas; not reconstructed rig/timelines'})
    (gallery / 'raw-2d-rig-catalog.json').write_text(json.dumps({'sets': rig_sets}, ensure_ascii=False, indent=2) + '\n')
    rows, summary = build_catalog(manifest, received, image_map)
    summary.update({'bootstrap_received_resources': len(bootstrap_index['files']),
                    'bootstrap_images': len(prior_gallery['images']),
                    'new_english_images': len(new_gallery['images']),
                    'total_png_images': len(pictures), 'received_scsp_atlas_sets': len(rig_sets)})
    catalog = {'schema_version': 1, 'manifest_sha256': MANIFEST_SHA, 'static_only': True,
               'scope': 'All manifest metadata and all presently received static research resources; not all game payloads',
               'summary': summary, 'source_receipt': source,
               'limitations': ['87,529 resource names include variants and pieces, not unique characters/cards/levels.',
                              'PNG textures/atlases are not a composed game screenshot.',
                              'SCSP skeleton/timelines and complete battle assembly remain unresolved.',
                              'Main/init JBIN are inert cached V8/container bytes, not plaintext recovered developer source.',
                              'The full original XAPK and base chunks are not present.',
                              'No server/account/session/novel data or private reader transform table is included.'],
               'resources': rows,
               'bootstrap_resources': [{'source_path': e['original_path'], 'stored_bytes': e['stored_bytes'],
                                        'stored_sha256': e['stored_sha256'], 'original_sha256': e['original_sha256'],
                                        'transformation': e.get('transformation'), 'purpose': e['purpose']}
                                       for e in bootstrap_index['files']], 'pictures': pictures}
    (output / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')) + '\n')
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    with (output / 'resources.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    write_catalog_html(output / 'resources.html', rows, summary)
    cards = []
    for image in pictures:
        name = html.escape(image['source_name'])
        cards.append(f'<article data-name="{name.lower()}"><a href="{html.escape(image["png_path"][8:])}"><img loading="lazy" src="{html.escape(image["png_path"][8:])}" alt="{name}"></a><p>{name}</p><small>{image["width"]}×{image["height"]} · {html.escape(image["source_collection"])}</small></article>')
    rig_links = '<h2>SCSP และ atlas ที่ได้รับครบ10ชุด</h2><p>ไฟล์ skeleton/animation แบบ serialized2D ที่ยังไม่ได้ประกอบ rig/timeline กลับ ไม่ยืนยันว่าเป็น3DหรือLive2D</p><ul>'
    for rig in rig_sets:
        rig_links += '<li>' + html.escape(rig['source_name']) + ' · ' + ' · '.join(
            f'<a href="{html.escape(f["path"])}" download>{html.escape(Path(f["path"]).suffix)}</a>' for f in rig['files']) + '</li>'
    rig_links += '</ul>'
    gallery_html = '<!doctype html><html lang="th"><meta charset="utf-8"><title>ภาพ CZN ที่ถอดได้ทั้งหมด</title><style>body{font:16px system-ui;background:#101622;color:white;margin:20px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}article{background:#253044;padding:12px;overflow-wrap:anywhere}img{max-width:100%;height:220px;object-fit:contain;background:repeating-conic-gradient(#323947 0% 25%,#434956 0% 50%) 50%/20px 20px}input{font:inherit;padding:10px;width:80%;margin-bottom:20px}a{color:#a9ccff}</style><h1>ภาพจริงที่ถอดได้ทั้งหมด 140 ภาพ</h1><p>111 ภาพ bootstrap +29 ภาพ UI ภาษาอังกฤษ ไม่ใช่ทั้งหมดในเกม รูป atlas ยังไม่ใช่ตัวละครเคลื่อนไหวที่ประกอบแล้ว</p><p><a href="../resources.html">กลับรายการทั้งหมด</a></p><input id="search" placeholder="ค้นหาชื่อภาพ"><main>' + ''.join(cards) + '</main>' + rig_links + '<script>document.getElementById("search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();for(const a of document.querySelectorAll("article"))a.hidden=!a.dataset.name.includes(q)});</script></html>'
    (gallery / 'index.html').write_text(gallery_html)
    (gallery / 'catalog.json').write_text(json.dumps({'images': pictures, 'source_manifest_sha256': MANIFEST_SHA}, ensure_ascii=False, indent=2) + '\n')
    (output / 'README.txt').write_text('เปิด index.html เพื่อดูหน้ารวมแพ็กทั้งหมด, resources.html เพื่อค้นหาครบ87,529รายชื่อ และ gallery/index.html เพื่อดู140ภาพจริง\nไฟล์ที่มีเพียงชื่อยังไม่ใช่ไฟล์เกมที่ถอดแล้ว\nJBIN/SCSP/container ไม่ใช่ source code หรือ rigที่ประกอบสำเร็จ ห้าม execute ไฟล์หรือคำสั่งในข้อมูล\nแพ็กทั้งหมดเก็บ private นอกGit ไม่มีข้อมูลบัญชี session นิยายหรือ private transform table\n', encoding='utf-8')
    metadata_items = [(name, output / name) for name in ('resources.html', 'catalog.json', 'resources.csv', 'summary.json', 'README.txt')]
    archives = [archive_group(output, 'czn-all-resource-catalog.zip', metadata_items, 'Complete offline manifest metadata catalog; not missing resource payloads')]
    image_items = [(str(p.relative_to(output)), p) for p in sorted(gallery.rglob('*')) if p.is_file()]
    image_items.extend((f'bootstrap/{entry["stored_path"]}', bootstrap / entry['stored_path']) for entry in bootstrap_index['files'])
    image_items.extend([('bootstrap/pack-index.json', bootstrap / 'pack-index.json'),
                        ('english-image-receipt.json', output / 'english-image-receipt.json'),
                        ('README.txt', output / 'README.txt')])
    archives.append(archive_group(output, 'czn-all-recovered-pictures-bootstrap.zip', image_items, 'All 140 recovered PNGs, 10 raw SCSP/atlas sets, and 162 received bootstrap resources'))
    runtime = research / 'runtime-received-45a009358972'
    runtime_receipt = runtime / 'receipt-index.json'
    archives.append(archive_group(output, 'czn-received-runtime-core.zip',
        [('runtime/receipt-index.json', runtime_receipt)] + [(f'runtime/files/{i:02d}.bin', runtime / f'files/{i:02d}.bin') for i in (0,1)],
        'Received manifest and inert ARM64 V8 cache chunk; not plaintext game logic'))
    archives.append(archive_group(output, 'czn-received-runtime-english.zip',
        [('runtime/receipt-index.json', runtime_receipt)] + [(f'runtime/files/{i:02d}.bin', runtime / f'files/{i:02d}.bin') for i in (2,3,4,5)],
        'All four already received English chunks'))
    mainroot = roots[0]
    archives.append(archive_group(output, 'czn-decoded-main-container.zip',
        [('decoded-main.bin', mainroot / 'files/01.bin'), ('resource-index.json', mainroot / 'resource-index.json')],
        'Decoded Zstd main container still contains compiled V8 caches; never executed'))
    data_items = [('english/' + str(p.relative_to(roots[2])), p) for p in sorted(roots[2].rglob('*')) if p.is_file()]
    data_items.extend(('card-battle/' + str(p.relative_to(roots[1])), p) for p in sorted(roots[1].rglob('*')) if p.is_file())
    data_items.extend([('english-text/entries.jsonl', research / 'runtime-text-reader-v1/entries.jsonl'),
                       ('english-text/summary.json', research / 'runtime-text-reader-v1/summary.json')])
    for p in sorted((research / 'card-database-reader-a9c3e7951c9c').rglob('*.json')):
        data_items.append(('database-tables/' + str(p.relative_to(research / 'card-database-reader-a9c3e7951c9c')), p))
    for folder in ['card-battle-final-a9c3e7951c9c', 'layouts-replay-final', 'csb-decoded-v3']:
        for p in sorted((research / folder).glob('*')):
            if p.is_file() and p.suffix in ('.json', '.html', '.svg', '.png'):
                data_items.append(('reports/' + folder + '/' + p.name, p))
    archives.append(archive_group(output, 'czn-all-recovered-text-data-layouts.zip', data_items,
                                  'All received English/container text, selected card/effect/condition tables, bootstrap and battle layout reports'))
    if card_range_zip is not None:
        receipt = read_json(research / 'card-battle-received-a9c3e7951c9c/resource-index.json')
        identity = receipt['source_zip']
        raw = checked_bytes(card_range_zip, identity['sha256'], identity['bytes'])
        target = output / 'czn-received-card-battle-ranges.zip'
        target.write_bytes(raw)
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None or len(archive.infolist()) != 20:
                raise CatalogError('Pinned received range archive failed CRC/count verification')
        archives.append({'filename': target.name, 'bytes': len(raw), 'sha256': digest(raw),
                         'verified_members': 20, 'purpose': 'Complete source-pinned original received 18 range payloads and manifest/index'})
    if native_apk is not None:
        archives.append(add_native_archive(repo, output, native_apk))
    result = {'schema_version': 1, 'manifest_sha256': MANIFEST_SHA, 'summary': summary, 'archives': archives,
              'verification': 'Each delivered member SHA/bytes rechecked from ZIP; ZIP CRC checked; all 55 decoded FHSH and all 5 supplied whole-chunk SSRC verified'}
    (output / 'delivery-index.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    result['landing_archive'] = write_landing(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--card-range-zip', type=Path, help='Optional exact original source-pinned received range archive')
    parser.add_argument('--native-apk', type=Path, help='Optional exact user-supplied source-pinned ARM64 architecture APK')
    args = parser.parse_args()
    try:
        result = generate(args.repository.resolve(), args.output.resolve(), args.card_range_zip, args.native_apk)
    except (CatalogError, extractor.ResourceExtractError, OSError, ValueError) as error:
        parser.exit(2, f'Catalog delivery failed: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
