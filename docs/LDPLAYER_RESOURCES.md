# ตรวจไฟล์ resource จาก LDPlayer บน Windows

เกมที่ดาวน์โหลด resource ไว้ใน LDPlayer อาจมีไฟล์เพิ่มจาก APK เช่น manifest,
script packs, scenes, textures และ client data เราตรวจไฟล์ที่เข้าถึงได้จาก
emulator ของผู้ใช้ผ่าน ADB ได้ คลาวด์นี้เชื่อมกับ Windows ของผู้ใช้โดยตรงไม่ได้
จึงต้องรันขั้นนี้ใน PowerShell บนเครื่องที่เปิด LDPlayer

ภาพ title ที่ส่งมาแสดงว่าเปิดเกมได้ แต่ยังไม่พิสูจน์ว่าดาวน์โหลด content ทุกหมวด
ครบหรือว่า ADB อ่าน private storage ได้ ให้เกมอัปเดต resource ที่จำเป็นจนเสร็จ
ไม่ต้องเล่น combat เพื่อสร้าง inventory

## 1. เปิด ADB สำหรับการเชื่อมต่อในเครื่อง

เปิด Settings ของ LDPlayer แล้วหา ADB debugging ซึ่งมักอยู่ใน Other settings
เลือกการเชื่อมต่อภายในเครื่อง (local connection) ชื่อเมนูอาจต่างตามรุ่น
หาก LDPlayer ขอ restart ให้ restart แล้วเปิดเกมอีกครั้ง
เครื่องมือด้านล่างไม่ได้เปิด ADB, root หรือเปลี่ยน settings ให้เอง

## 2. อยู่ในโฟลเดอร์ repository

ใน Explorer เปิดโฟลเดอร์ที่มี `README.md` กับ `tools` กด `Ctrl+L`, `Ctrl+C`
แล้วรันใน PowerShell:

```powershell
Set-Location -LiteralPath (Get-Clipboard)
Test-Path .\README.md
Test-Path .\tools
```

ทั้งสองรายการต้องเป็น `True` ถ้า prompt ยังเป็น `C:\Users\MSi` และผลเป็น
`False` ให้เปลี่ยน directory ก่อน อย่าเปลี่ยน path ของไฟล์ tool เพื่อแก้ผิดจุด

## 3. ดาวน์โหลด helper และตรวจรายการไฟล์

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/inventory_android_resources.py" -OutFile ".\tools\inventory_android_resources.py"
py .\tools\inventory_android_resources.py --output ".local/ldplayer-resources-v1"
```

ใช้ Python standard library และ ADB ที่ติดตั้งบนเครื่อง ค้น ADB จาก PATH
หรือโฟลเดอร์ LDPlayer ที่พบได้ทั่วไป หากหาไม่เจอ ระบุ `adb.exe` จริง เช่น:

```powershell
py .\tools\inventory_android_resources.py --adb "C:\LDPlayer\LDPlayer9\adb.exe" --output ".local/ldplayer-resources-v1"
```

ตัวอย่างนี้ใช้ได้เมื่อ path ตรงกับเครื่องเท่านั้น หา installation folder โดย
คลิกขวา shortcut LDPlayer แล้วเลือก Open file location; บางครั้งต้องเปิด
ตำแหน่งของ target ต่อ หากไม่มี `adb.exe` ให้ใช้ Android SDK Platform-Tools
จาก Google ที่ติดตั้งไว้และระบุ path ของมัน

helper เลือกเฉพาะ emulator ที่เชื่อมต่อในเครื่อง ถ้ามีหลาย instance ให้ดูรายการ:

```powershell
& "C:\LDPlayer\LDPlayer9\adb.exe" devices -l
py .\tools\inventory_android_resources.py --adb "C:\LDPlayer\LDPlayer9\adb.exe" --serial "emulator-5554" --output ".local/ldplayer-resources-v1"
```

แทน `emulator-5554` ด้วย serial ที่แสดงจริง เช่น `127.0.0.1:5555` ถ้าไม่พบ
device ให้ตรวจ local ADB setting และว่า instance เปิดอยู่ ไม่ต้องสุ่มพอร์ต
หาก output directory มีผลเก่า ให้ใช้ชื่อใหม่ เช่น `ldplayer-resources-v2`

## 4. ส่งรายงานเพื่อเลือก resource ที่ต้องอ่าน

```powershell
Invoke-Item .\.local\ldplayer-resources-v1
```

แนบ `report.json` และ `summary.md` ที่สร้างใหม่ รายงานเป็นรายการชื่อ/ขนาดไฟล์
กับสถานะการเข้าถึง ยังไม่คัดลอก contents จาก emulator

ตรวจ package คงที่ `com.smilegate.chaoszero.stove.google` และ directories:

```text
/sdcard/Android/data/com.smilegate.chaoszero.stove.google/files
/sdcard/Android/obb/com.smilegate.chaoszero.stove.google
/data/user/0/com.smilegate.chaoszero.stove.google/files
/data/data/com.smilegate.chaoszero.stove.google/files
```

private paths สองรายการท้ายอาจเป็น directory เดียวกันหรือได้ permission denied
ตาม Android/LDPlayer รุ่นที่ใช้ การไม่มีไฟล์ใน external path ไม่พิสูจน์ว่าเกม
ไม่มี resources และการอ่าน private path ไม่ได้ไม่ใช่ผลว่า APK ไม่มีข้อมูล

## หลังได้รับรายงาน

เลือก manifest กับ resource packs ที่สัมพันธ์กับข้อมูลเกม เช่น candidates
`main.jbin`, `gameres/manifest.ssra` หรือไฟล์ `.ssra` โดยอิง paths ที่พบจริง
ชื่อเหล่านี้มาจาก native references ยังไม่ยืนยันว่าต้องอยู่ใน LDPlayer รุ่นนี้
จากนั้นจึงให้คำสั่ง `adb pull` เฉพาะไฟล์ที่เลือก พร้อมตรวจ sizes และ SHA-256
ไม่ต้อง ZIP app data ทั้งหมดหรือดาวน์โหลดไฟล์เกมหลาย GB ซ้ำ

เครื่องมือไม่อ่าน account databases, preferences หรือ tokens และไม่ส่งข้อมูล
ออกจากเครื่อง ชื่อ/ขนาด resource database ทั่วไป เช่น `cards.db` ภายใน resource
roots อาจอยู่ในรายงาน แต่ไม่ได้เปิด contents รายงานใน `.local/` ไม่ถูก commit;
resources ที่รับมาจะใช้เป็น
หลักฐาน static แยกจากภาพ/ข้อความใหม่ของเกมต้นแบบ

บนคลาวด์ทดสอบ ADB helper ผ่าน 16 tests ด้วยอุปกรณ์และ filesystem จำลอง การเชื่อมต่อจริง,
Android toybox commands และ storage permissions ใน LDPlayer ของผู้ใช้ยังรอ
ผลรายงาน ขั้นนี้ยังไม่ยืนยันว่า export ไฟล์ resource ได้แล้ว
