# รายงาน XAPK รอบแรกจากผู้ใช้

รายงานนี้เก็บประวัติข้อผิดพลาดรอบแรก สถานะปัจจุบันอยู่ที่
[รายงานรอบสอง](CHAOS_NESTED_REPORT.md) ซึ่งอ่าน APK ย่อยได้แล้ว

หลักฐานนี้เป็นรายงานที่ผู้ใช้รันในเครื่อง Windows แล้วแนบมา ไม่ใช่การตรวจ archive
จริงในคลาวด์ ข้อเท็จจริงข้างล่างเป็นค่าที่อ่านจากรายงาน ไม่ได้ตรวจ SHA ของ XAPK ซ้ำ

| สิ่งที่รายงานระบุ | ค่า |
|---|---|
| ชื่อ input | `Chaos+Zero+Nightmare_1.0.811_APKPure.xapk` |
| ขนาด input | 152,845,071 bytes (145.76 MiB) |
| SHA-256 ของ XAPK ตามรายงาน | `b95e115282272289c73abc1569b81a5bbf62b1f4f638c15d76cc2c7b2f120be0` |
| รายการชั้นนอก | 13 entries: APK ย่อย 11, icon.png, manifest.json |
| APK หลัก | `com.smilegate.chaoszero.stove.google.apk`, 129,147,167 bytes |
| APK ตามชื่อ arm64 | `config.arm64_v8a.apk`, 22,979,689 bytes |
| ข้อมูลข้อความที่อ่าน | manifest.json, 1,972 bytes; โครงสร้าง key เท่านั้น |
| APK ย่อยที่อ่านได้ | 0 จาก 11 |
| สาเหตุข้าม APK | `nested_read_failed`, `FileNotFoundError` ทั้ง 11 |
| Engine | unknown; ยังไม่มีข้อมูลจาก APK ย่อย |

ชื่อ split เช่น `config.en.apk`, `config.mdpi.apk` เป็นหลักฐานระดับชื่อไฟล์
ยังไม่ยืนยันภาษาในเกมทั้งหมด, display layout, rendering engine หรือ SDK behavior
top-level manifest keys เช่น `version_name` ไม่มีค่าปรากฏในรายงานนี้
จึงยังยืนยันหมายเลขเวอร์ชันจาก manifest หรือสถานะ release ล่าสุดไม่ได้

## Provenance

- `report.json` ที่แนบ: SHA-256 `c2c861ca29232bf8703a280064d59bbfb0ffc9b425741745dd87bccbd4cd5e2e`
- `summary.md` ที่แนบ: SHA-256 `ca60f82f6dc52974a66b6d9d8915d503776221090e8dc528ccdc1139ee49c6b9`
- รายงานระบุ `created_utc`: `2026-10-02T07:47:21.266326+00:00`
- เก็บไฟล์ที่แนบไว้ใน `.local/research/uploaded-outer-report/` ไม่อยู่ใน Git

## ปัญหาเครื่องมือและสิ่งที่แก้แล้ว

โค้ดเดิมเรียก `tempfile.TemporaryFile(..., dir='/tmp')` ซึ่งทำงานบน Linux
แต่ Windows ของผู้ใช้ไม่มีโฟลเดอร์นี้ จึงล้มเหลวก่อนอ่าน APK ย่อย
โค้ดเดิมยังไม่ได้รวม nested read failures ลง `errors` ทำให้มี `errors: []`
แม้ไฟล์สำคัญอ่านไม่ได้ทั้งหมด ข้อนี้เป็นข้อบกพร่องเครื่องมือ ไม่ใช่ข้อพิสูจน์ว่า
archive เสียหรือไม่มี resource ของเกม

รุ่นแก้ไขใช้ platform temp directory, ทำเครื่องหมาย analysis ที่ไม่สมบูรณ์,
คืน exit code 1 เมื่อมี read failure และรักษาการข้ามตาม limits ให้แยกกัน
regression fixtures จำลองระบบที่ไม่มี POSIX `/tmp` และตรวจว่ารายการ/hash/hints
ใน APK ย่อยอ่านได้ การทดสอบนี้ไม่ใช่การรันบน Windows จริงหรืออ่านเกมจริง

## รันใหม่บน Windows

เปิด PowerShell ในโฟลเดอร์ที่มี `README.md`, `tools` และ XAPK
หากไม่แน่ใจ ให้ `Test-Path .\tools\analyze_apk.py` แล้วตรวจว่าเป็น `True`
ดาวน์โหลดเฉพาะเครื่องมือที่แก้ไขเพื่อรักษาไฟล์ XAPK และรายงานเดิม:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/analyze_apk.py" -OutFile ".\tools\analyze_apk.py"
py .\tools\analyze_apk.py "Chaos+Zero+Nightmare_1.0.811_APKPure.xapk" --output ".local/chaos-report-v2" --extract-text
Invoke-Item .\.local\chaos-report-v2
```

ใช้ชื่อ output ใหม่เสมอ เครื่องมือไม่เขียนทับผลเดิม ส่ง `report.json` กับ `summary.md`
รอบใหม่กลับมา จากนั้นเลือกข้อความหรือ asset ที่จำเป็นตาม evidence paths ในรายงาน
ไม่ต้องรันเกมหรือส่ง asset ทั้งหมดในขั้นนี้
