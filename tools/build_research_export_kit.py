#!/usr/bin/env python3
"""Package the reviewed local Windows exporter; never include game resources."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile

MODULES = (
    "export_all_game_resources_windows.py", "export_all_game_resources.py",
    "export_ssra_ranges.py", "export_android_research.py",
    "inventory_android_resources.py", "read_ssra_manifest.py",
    "EXPORT-ALL-CZN.cmd",
)
README = """เริ่มที่นี่ — ส่งออกทรัพยากร CZN ทั้งหมดที่มีใน LDPlayer

1. เปิด LDPlayer และเกม รอเกมดาวน์โหลด resources เสร็จ ใช้ ADB ภายในเครื่อง
2. แตก ZIP นี้ทั้งหมด แล้วดับเบิลคลิก EXPORT-ALL-CZN.cmd
   ใช้ Python 3.12 ขึ้นไป (Python 3.14 ที่มีอยู่แล้วใช้ได้) ไม่ต้องลง packages เพิ่ม
   โปรแกรมใช้ D:\\LDPlayer\\LDPlayer14\\adb.exe และ emulator-5554
   ถ้าหา ADB ไม่เจอ จะมีหน้าต่างให้เลือก adb.exe (ไม่ใช่ dnplayer.exe)
3. ผลอยู่ใน Downloads\\chaos-research\\.local\\chaos-all-resources
   ส่ง all-export-report.json + chaos-all-source.zip + chaos-all-000001.zip กลับ
   จากนั้นส่ง chaos-all-*.zip ชุดถัดไป ไม่ต้องส่ง export-state.sqlite3

แต่ละ ZIP ไม่เกิน 30 MiB ทั้งหมดราว 7.70 GiB / ประมาณ 285 ชุด ถ้ามีไฟล์ครบ
เตรียมพื้นที่ว่างประมาณ 12 GiB รันซ้ำได้เพื่อทำต่อ หากหยุดกลางทาง
โปรแกรมอ่านทุก resource ตาม manifest รุ่นที่ตรวจแล้ว ไม่ใช่เลือกแค่สิบไฟล์
ถ้าไฟล์ยังไม่ติดตั้ง จะระบุ partial และรายชื่อที่ขาด ไม่ดึงจากเซิร์ฟเวอร์เอง
ถ้า manifest เปลี่ยน จะหยุดให้ตรวจใหม่ ไม่ลดการตรวจ hash
Cloud เข้าถึงเครื่องคุณโดยตรงไม่ได้ ต้องรันบน Windows ที่เปิด LDPlayer

อ่านเฉพาะ external gameres manifest/chunks ของเกม ไม่อ่านบัญชีหรือ app data
ไม่มี root, authentication bypass, restart emulator หรือ network request
เกม scripts/config เก็บเป็น inert bytes ไม่ execute แอนิเมชัน/เสียง/รูปยังต้องถอดต่อ

ไฟล์ใน ZIP นี้เป็น source เครื่องมือที่เราเขียน ไม่มีไฟล์เกม ภาพอ้างอิง บัญชี หรือ keys
kit-index.json ระบุ SHA-256 ของ source ทุกไฟล์
คู่มือทีม: docs/ALL_CZN_RESOURCES.md ใน repository
"""


def build(output: Path) -> dict:
    root = Path(__file__).resolve().parent
    files = {}
    for name in MODULES:
        path = root / name
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"Kit source must be a regular nonsymlink file: {name}")
        data = path.read_bytes()
        if len(data) > 1024 * 1024:
            raise ValueError(f"Kit source exceeds 1 MiB: {name}")
        files[name] = data
    files["README-เริ่มที่นี่.txt"] = README.encode("utf-8-sig")
    index = {
        "schema_version": 1, "purpose": "local Windows resource-only exporter",
        "game_resources_included": False,
        "files": [{"filename": name, "bytes": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()],
    }
    files["kit-index.json"] = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(files):
            raise ValueError("Kit ZIP member/CRC verification failed")
        for name, data in files.items():
            if archive.read(name) != data:
                raise ValueError(f"Kit source changed: {name}")
    return {"filename": output.name, "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "verified_members": len(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(argv)
    print(json.dumps(build(options.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
