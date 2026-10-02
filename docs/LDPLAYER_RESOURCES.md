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
ไฟล์ `dnplayer.exe` เป็นตัวเปิด LDPlayer ไม่ใช่ ADB การที่ `Test-Path` เป็น True
บอกเพียงว่ามีไฟล์นั้นอยู่ ให้เลือก `adb.exe` เครื่องมือปฏิเสธชื่อ executable อื่น

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

บนคลาวด์ทดสอบ ADB helper ผ่าน 22 tests ด้วยอุปกรณ์และ filesystem จำลอง
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

## เมื่อย้าย Windows profile หรือไม่พบไฟล์ tool

ถ้า error ระบุ `can't open file …tools\inventory_android_resources.py` แสดงว่า
สคริปต์ไม่อยู่ใน working directory นั้น กรณีล่าสุด prompt อยู่ใต้
`C:\Users\ASUS\Downloads\Lord-of-Mysteries-Roguelike-Deck-Building-main`
และเลือก `dnplayer.exe` ให้ใช้ workspace สำหรับ research ที่อิง Windows profile
ปัจจุบันแทน path ที่เจาะจง `MSi` หรือจำนวนชั้นของ ZIP repository

เปิด LDPlayer ที่มีเกมและ local ADB ไว้ แล้วคัดลอกบล็อกนี้ทั้งชุด:

```powershell
$chaosResearchDir = Join-Path $env:USERPROFILE "Downloads\chaos-research"
New-Item -ItemType Directory -Path "$chaosResearchDir\tools" -Force | Out-Null
Set-Location -LiteralPath $chaosResearchDir

foreach ($toolFile in @("inventory_android_resources.py", "export_android_research.py")) {
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/$toolFile" -OutFile ".\tools\$toolFile" -ErrorAction Stop
}

py .\tools\inventory_android_resources.py --adb "D:\LDPlayer\LDPlayer14\adb.exe" --output ".local/ldplayer-resources-v1"

if ($LASTEXITCODE -eq 0) {
  py .\tools\export_android_research.py --adb "D:\LDPlayer\LDPlayer14\adb.exe" --report ".local/ldplayer-resources-v1/report.json" --output ".local/chaos-runtime-export-v1"
  if ($LASTEXITCODE -eq 0) {
    Invoke-Item .\.local\chaos-runtime-export-v1
  }
}
```

workspace นี้ใช้ Python standard library และ helper สองไฟล์ ไม่ต้องติดตั้งเกม
ต้นแบบหรือหา repository root ก่อนตรวจ emulator `adb.exe` path อิง installation
folder ที่ผู้ใช้ระบุ ให้เปลี่ยนเฉพาะเมื่อไฟล์ ADB อยู่ที่อื่น

ถ้าสำเร็จ แนบ ZIP ทั้งสองไฟล์ตามส่วน export ด้านบน หาก inventory/export หยุด
ให้ส่งข้อความ error และ report ที่สร้างได้ ชุด selected resources ผูกกับ paths
และ sizes จาก inventory เดิม การเปลี่ยน game patch อาจทำให้ต้องเลือกชุดใหม่
ถ้าเคยใช้ workspace นี้แล้ว ให้เปลี่ยน output directory เป็นชื่อใหม่ทั้งสองขั้น
และเปลี่ยน `--report` ให้ตรงกับ directory ของ inventory ใหม่

## เมื่อ package query ได้ error: closed

error นี้เกิดตอน ADB เรียก Android shell ไม่สำเร็จ การดาวน์โหลด helper และ
การเลือก `adb.exe` อาจผ่านแล้ว แต่ยังตรวจไม่ได้ว่า package ติดตั้งอยู่หรือไม่
ข้อความเครื่องมือปัจจุบันแยก transport failure, successful empty response
และ malformed response แทนการเหมารวมว่าเกมไม่ได้ติดตั้ง

บันทึก local ADB setting แล้ว restart LDPlayer instance ผ่านหน้าจอโปรแกรม
รอ Android บูตเสร็จ จากนั้นรีเซ็ต local ADB server ด้วย executable ตัวเดิม:

```powershell
$ldAdbPath = "D:\LDPlayer\LDPlayer14\adb.exe"
& $ldAdbPath -P 5037 kill-server
& $ldAdbPath -P 5037 start-server
& $ldAdbPath -P 5037 devices -l
```

การ reset server ตัด ADB sessions ชั่วคราว จากรายการ devices เลือก serial
จริงที่มี status `device` หากแสดง `emulator-5554 device` ใช้:

```powershell
& $ldAdbPath -P 5037 -s "emulator-5554" shell echo adb-ok
& $ldAdbPath -P 5037 -s "emulator-5554" shell pm path com.smilegate.chaoszero.stove.google
```

ถ้า serial ต่างให้แทนค่าตามรายการจริง ทดสอบ echo ก่อน package query
เมื่อได้ `adb-ok` และ package query คืน `package:/…apk` จึงรัน inventory
และ export ตามขั้นก่อนหน้า ถ้า echo ยัง `error: closed` ให้ส่ง output ของ
devices และ echo probe ยังไม่แก้ schema/package หรือเปลี่ยน resource paths
เพราะปัญหาอยู่ก่อนขั้นตรวจไฟล์ Tool ไม่ทำ restart/retry ให้โดยอัตโนมัติ

### cannot start server on remote host / connection refused 10061

คำสั่งเดิมที่ใส่ `-H 127.0.0.1` ทำให้ ADB ใช้ semantics ของ remote server
แม้ host จะเป็น loopback เมื่อไม่มี server ฟังพอร์ต 5037 จึงไม่ auto-start และ
ได้ `cannot start server on remote host` ให้เริ่ม server ด้วย local default host:

```powershell
$ldAdbPath = "D:\LDPlayer\LDPlayer14\adb.exe"
& $ldAdbPath -P 5037 start-server
& $ldAdbPath -P 5037 devices -l
```

เมื่อมี emulator serial status `device` จึงใช้ echo probe ข้างต้น ไม่ระบุ `-H`
helpers รุ่นปัจจุบันใช้ local default host/พอร์ต 5037 และล้าง remote ADB server
environment overrides เฉพาะ child process เพื่อให้ client auto-start local ADB
ได้ การแก้ startup ไม่ได้ยืนยันว่า shell error: closed ก่อนหน้านี้หายแล้ว

## หลัง shell echo ตอบ adb-ok บนเครื่อง ASUS

ภาพล่าสุดยืนยันว่า daemon เริ่มได้, `emulator-5554` มีสถานะ `device` และ
shell echo ตอบ `adb-ok` แล้ว ยังไม่ยืนยัน package query หรือ resource pull
เพราะ inventory รอบก่อนบน ASUS หยุดด้วย error: closed ให้เปิด LDPlayer ค้างไว้
แล้วรันชุดนี้จาก PowerShell ตำแหน่งใดก็ได้:

```powershell
& {
  $ErrorActionPreference = "Stop"
  $ldAdbPath = "D:\LDPlayer\LDPlayer14\adb.exe"
  $chaosResearchDir = Join-Path $env:USERPROFILE "Downloads\chaos-research"
  New-Item -ItemType Directory -Path "$chaosResearchDir\tools" -Force | Out-Null
  Set-Location -LiteralPath $chaosResearchDir

  foreach ($toolFile in @("inventory_android_resources.py", "export_android_research.py")) {
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/$toolFile" -OutFile ".\tools\$toolFile" -ErrorAction Stop
  }

  $chaosRunTag = Get-Date -Format "yyyyMMdd-HHmmss-fff"
  $chaosInventoryDir = ".local/ldplayer-resources-$chaosRunTag"
  $chaosExportDir = ".local/chaos-runtime-export-$chaosRunTag"

  py .\tools\inventory_android_resources.py --adb "$ldAdbPath" --serial "emulator-5554" --output "$chaosInventoryDir"
  if ($LASTEXITCODE -ne 0) { throw "Inventory failed; export was not started." }

  py .\tools\export_android_research.py --adb "$ldAdbPath" --report "$chaosInventoryDir/report.json" --output "$chaosExportDir"
  if ($LASTEXITCODE -ne 0) { throw "Export failed." }

  Invoke-Item -LiteralPath $chaosExportDir
}
```

ชื่อ output มี timestamp เพื่อไม่เขียนทับผลเก่า บล็อกหยุดเมื่อดาวน์โหลด helper,
inventory หรือ export ล้มเหลว ตัว exporter ตรวจ package และ paths/sizes จริง
ก่อน pull; ถ้า resources ไม่ตรงกับชุดที่เลือกไว้จะหยุดพร้อม error
เมื่อสำเร็จ แนบ `chaos-runtime-core.zip` และ `chaos-runtime-lang-en.zip`
จากโฟลเดอร์ที่เปิด ถ้ามี error ส่งข้อความนั้นเพื่อตรวจขั้นที่ล้มเหลว

## ดึงค่าการ์ดและฉากต่อสู้เป็น byte ranges

ได้รับ core/English ZIPs แล้ว อ่าน manifest และฐานข้อความอังกฤษได้จริง
รวม card text 4,725 entries (ชื่อ/คำอธิบาย/variants ไม่ใช่จำนวน playable cards)
ดู [ผลวิเคราะห์](research/CHAOS_RUNTIME_ANALYSIS.md)
ค่าตัวเลขยังเป็น placeholders และ combat CSBs ยังไม่มี contents ในคลาวด์
เลือกเพิ่ม 18 resources จาก manifest จริง: DB 13 และ CSB 5

เครื่องมือใหม่อ่านเฉพาะช่วงที่ครอบคลุม stored payload 622,458 bytes
aligned chunk readback รวม 1,703,936 bytes และอ่าน manifest 7,506,387 bytes
เพื่อเทียบ source hash ก่อนดึงข้อมูล รวม transfer ที่คาดไว้ 9,210,323 bytes
ไม่ต้องคัดลอก base chunks หลาย GB ตัว export ไม่เติมค่าการ์ดหรือ decode assets
และยังไม่ได้ตรวจ Windows exec-out/dd จริงจนกว่าผู้ใช้รันขั้นนี้

เปิด LDPlayer เดิมค้างไว้ คัดลอกบล็อกนี้ทั้งหมดลง PowerShell:

```powershell
& {
  $ErrorActionPreference = "Stop"
  $ldAdbPath = "D:\LDPlayer\LDPlayer14\adb.exe"
  $chaosResearchDir = Join-Path $env:USERPROFILE "Downloads\chaos-research"
  New-Item -ItemType Directory -Path "$chaosResearchDir\tools" -Force | Out-Null
  Set-Location -LiteralPath $chaosResearchDir
  $chaosRepoRaw = "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main"

  foreach ($toolFile in @("inventory_android_resources.py", "export_android_research.py", "read_ssra_manifest.py", "export_ssra_ranges.py")) {
    Invoke-WebRequest -UseBasicParsing -Uri "$chaosRepoRaw/tools/$toolFile" -OutFile ".\tools\$toolFile" -ErrorAction Stop
  }
  Invoke-WebRequest -UseBasicParsing -Uri "$chaosRepoRaw/docs/research/profiles/chaos-card-battle-ranges-45a009358972.json" -OutFile ".\tools\chaos-card-battle-ranges.json" -ErrorAction Stop

  $chaosRangeOutput = ".local/chaos-card-battle-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
  py .\tools\export_ssra_ranges.py --adb "$ldAdbPath" --serial "emulator-5554" --plan ".\tools\chaos-card-battle-ranges.json" --output "$chaosRangeOutput"
  if ($LASTEXITCODE -ne 0) { throw "Range export failed." }
  Invoke-Item -LiteralPath $chaosRangeOutput
}
```

เมื่อสำเร็จแนบ **chaos-card-battle-ranges.zip** ไฟล์เดียวจากโฟลเดอร์ที่เปิด
ZIP มี manifest และ 18 stored resource blobs พร้อม index/hash; คาดขนาดประมาณ
8 MB ถ้ามี error ส่งข้อความนั้น หาก manifest เปลี่ยน patch เครื่องมือจะหยุด
แทนการใช้ offsets เก่า และต้องวิเคราะห์ manifest ใหม่เพื่อปรับ selection

ADB ใช้ `exec-out` กับ Android `dd` เพื่ออ่าน binary spans และตัด surrounding
aligned bytes ออกก่อนบรรจุ ZIP ตรวจ byte count และขนาด chunk ก่อน/หลัง
การคัดลอก แต่ยังไม่ตรวจ whole-chunk hash เพราะไม่ได้อ่านทั้ง chunk
decoded FHSH ตรวจภายหลังบนคลาวด์เมื่อคลาย stored blobs และไม่ execute resources
ตัว manifest pin/hash ใช้ยืนยันชุดข้อมูล ไม่ใช่ CDN signature
