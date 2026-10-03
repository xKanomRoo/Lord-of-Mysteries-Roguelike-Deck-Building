#!/usr/bin/env python3
"""Friendly Windows entry point for the user's local resource-only export."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

try:
    from . import inventory_android_resources as android
except ImportError:
    import inventory_android_resources as android


def find_adb(explicit: str | None = None) -> Path:
    if explicit:
        return android.locate_adb(Path(explicit))
    known = Path("D:/LDPlayer/LDPlayer14/adb.exe")
    if known.is_file():
        return android.locate_adb(known)
    try:
        return android.locate_adb()
    except android.InventoryError:
        pass
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as error:
        raise android.InventoryError("หา adb.exe ไม่พบ ใช้ --adb ตามด้วยตำแหน่ง adb.exe ของ LDPlayer") from error
    try:
        window = tkinter.Tk()
        window.withdraw()
        try:
            filename = filedialog.askopenfilename(
                title="เลือก adb.exe ในโฟลเดอร์ LDPlayer (ไม่ใช่ dnplayer.exe)",
                filetypes=[("Android Debug Bridge", "adb.exe")],
            )
        finally:
            window.destroy()
    except tkinter.TclError as error:
        raise android.InventoryError("หา adb.exe ไม่พบ ใช้ --adb ตามด้วยตำแหน่ง adb.exe ของ LDPlayer") from error
    if not filename:
        raise android.InventoryError("ยังไม่ได้เลือก adb.exe จึงยังไม่อ่านไฟล์เกม")
    return android.locate_adb(Path(filename))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", help="Optional explicit LDPlayer adb.exe")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        print("ต้องใช้ Python 3.12 ขึ้นไป; เครื่องที่ใช้ Python 3.14 อยู่แล้วใช้ได้", file=sys.stderr)
        return 1
    try:
        adb = find_adb(options.adb)
    except (android.InventoryError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    output = options.output or (
        Path(os.environ.get("USERPROFILE", str(Path.home())))
        / "Downloads" / "chaos-research" / ".local" / "chaos-all-resources"
    )
    print("ส่งออกไฟล์ทรัพยากรที่ติดตั้งอยู่ใน LDPlayer เป็น ZIP แบ่งชุด")
    print("ไม่เปิดเกมให้เอง; เปิด LDPlayer และรอเกมดาวน์โหลดให้เสร็จก่อน")
    print(f"โฟลเดอร์ผลลัพธ์: {output}")
    print("รันซ้ำเพื่อทำต่อได้; ถ้าเวอร์ชัน manifest เปลี่ยน โปรแกรมจะหยุดให้ตรวจใหม่")
    try:
        from . import export_all_game_resources
    except ImportError:
        import export_all_game_resources
    status = export_all_game_resources.main([
        "--adb", str(adb), "--serial", options.serial,
        "--output", str(output), "--resume",
    ])
    if os.name == "nt" and output.is_dir():
        try:
            os.startfile(output)
        except OSError:
            print(f"เปิดโฟลเดอร์นี้ด้วย Explorer ได้เอง: {output}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
