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

บนคลาวด์ทดสอบ ADB helper ผ่าน 16 tests ด้วยอุปกรณ์และ filesystem จำลอง
ภายหลังได้รับ inventory ที่ผู้ใช้สร้างบน Windows/Android SDK 34 แล้วตามส่วนถัดไป
ผลนี้ไม่ได้เป็นการรัน Windows บนคลาวด์ และยังไม่ได้ตรวจ resource contents

## Export resource ที่เลือกจากรายงานนี้

ได้รับ inventory ผู้ใช้แล้ว: external files root อ่านรายการได้ 47 files / 7.56 GiB
มี manifest และ resource chunks; private roots ยัง permission_denied
ดู [หลักฐานจากรายงาน](research/CHAOS_LDPLAYER_INVENTORY.md)
ขั้นนี้คัดลอกเพียง 6 files ที่เลือกผ่าน ADB ของเครื่องเดิม ใช้ report เดิมเพื่อ
เทียบ paths/sizes และบันทึก source hash ไม่ต้องสร้าง inventory ซ้ำเมื่อไฟล์ไม่เปลี่ยน

เปิด LDPlayer instance เดิมและ local ADB ค้างไว้ รันใน PowerShell:

```powershell
Set-Location -LiteralPath "C:\Users\MSi\Downloads\Lord-of-Mysteries-Roguelike-Deck-Building-main\Lord-of-Mysteries-Roguelike-Deck-Building-main"

$runtimeTools = @("inventory_android_resources.py", "export_android_research.py")
foreach ($toolFile in $runtimeTools) {
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/$toolFile" -OutFile ".\tools\$toolFile"
}

py .\tools\export_android_research.py --adb "D:\LDPlayer\LDPlayer14\adb.exe" --report ".local/ldplayer-resources-v1/report.json" --output ".local/chaos-runtime-export-v1"

if ($LASTEXITCODE -eq 0) {
  Invoke-Item .\.local\chaos-runtime-export-v1
}
```

paths ของ repository, ADB และ report ข้างต้นอิง screenshots/report ของผู้ใช้
หากย้ายไฟล์ให้เปลี่ยน path ให้ตรง ถ้า output มีผลเก่าให้ใช้ชื่อใหม่ เช่น
`chaos-runtime-export-v2` เครื่องมือจะไม่เขียนทับ directory เดิม

แนบไฟล์สองรายการจากโฟลเดอร์ที่เปิด:

- **chaos-runtime-core.zip**: manifest และ ARM64 chunk; payload ประมาณ 24.59 MiB
- **chaos-runtime-lang-en.zip**: English chunks 4 files; payload ประมาณ 15.24 MiB

แต่ละ ZIP มี `research-index.json` ซึ่งระบุ source report SHA-256, resource
paths/sizes และ hash ของ bytes ที่คัดลอกจริง เครื่องมือตรวจ device/package,
remote regular-file sizes, local limits และ ZIP size ก่อน publish ผลจาก staging
การตรวจ size และ hash ของไฟล์ที่ copy ไม่ได้ยืนยันว่ามันตรงกับ original CDN
manifest hash ซึ่งยังไม่ได้อ่าน
ระหว่าง `adb pull` เครื่องมือเช็กขนาดไฟล์บน disk เป็นระยะ ขนาดอาจเกินชั่วคราว
ระหว่างการตรวจได้ แต่ไฟล์ที่ขนาดไม่ตรงจะถูกปฏิเสธและล้าง staging ก่อน publish

หาก pull ล้มเหลวหรือขนาดไม่ตรงให้ส่งข้อความ error การเปลี่ยน patch ระหว่าง
inventory กับ export อาจทำให้ขนาดเปลี่ยนและต้องตรวจรายการใหม่
ขั้นนี้ยังไม่ได้ execute หรือ decode scripts/resources และยังไม่พิสูจน์ข้อมูลการ์ด
