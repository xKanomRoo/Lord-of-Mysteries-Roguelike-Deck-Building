# ส่งชุดไฟล์สำหรับวิจัย static

รายงาน inventory บอก path/size/hash บางส่วน แต่ไม่ได้แนบเนื้อหาของ scene หรือภาพ
เครื่องมือ `tools/create_research_pack.py` อ่าน XAPK ที่มีอยู่ในเครื่องผู้ใช้ แล้วเลือก
ไฟล์ bootstrap ที่จำเป็นเก็บเป็น ZIP ไม่เกิน 30 MiB สำหรับส่งเข้าแชตได้
ต้องใช้ `tools/analyze_apk.py` รุ่นปัจจุบันซึ่งผู้ใช้อัปเดตแล้วในการวิเคราะห์รอบสอง

## Windows

เปิด PowerShell ในโฟลเดอร์ที่มี `README.md`, `tools` และ XAPK

```powershell
Test-Path .\tools\analyze_apk.py
```

ต้องขึ้น `True` แล้วดาวน์โหลด helper ที่ repository จัดทำ:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/create_research_pack.py" -OutFile ".\tools\create_research_pack.py"
```

สร้างชุดไฟล์โดยอ้างรายงานรอบสอง:

```powershell
py .\tools\create_research_pack.py "Chaos+Zero+Nightmare_1.0.811_APKPure.xapk" --report ".local/chaos-report-v2/report.json" --output ".local/chaos-bootstrap.zip"
```

เมื่อสำเร็จ ให้เปิดโฟลเดอร์แล้วแนบ **chaos-bootstrap.zip** กลับมา:

```powershell
Invoke-Item .\.local
```

หาก output ชื่อนี้มีอยู่แล้ว ให้ใช้ชื่อใหม่ ไม่ลบหรือเขียนทับผลเดิม
ถ้ารายงานรอบสองอยู่โฟลเดอร์อื่น แก้ค่า `--report` ให้ตรงกับไฟล์นั้น

## ขอบเขต

เลือก outer manifest, main Android manifest/resources, bootstrap metadata,
UI/effect resources ที่มีขนาดจำกัด, ARM64 init.jbin หนึ่งชุด และตัวอย่าง `sdata`
ที่เล็กกว่าเกณฑ์ เครื่องมือข้าม fonts, native libraries, DEX และ blobs ขนาดใหญ่
จึงไม่ต้องส่ง XAPK 146 MiB ทั้งก้อน

เมื่อใช้ selector กับ metadata ของรายงานรอบสอง จะได้ 162 candidate files
รวม source bytes 4,571,298 (4.36 MiB) รวม `.csb` ครบ 18 ไฟล์และ sdata เล็ก 7 ไฟล์
นี่เป็น source bytes จากรายงาน; แพ็กที่ผู้ใช้ส่งกลับมามี stored bytes 4,597,705
หลัง text redaction/formatting และ ZIP 3,577,579 bytes ตรวจ member hashes ครบแล้ว

ตรวจ hash ของ XAPK และ APK ย่อยเทียบกับ report ก่อนใช้ข้อมูล source ใน pack
ข้อมูล report เป็น reference data เท่านั้น ไม่ใช่รายการคำสั่งให้ execute
pack index เก็บ evidence path, raw source hash และ hash ของไฟล์ที่ถูกแปลง/redact
ชื่อไฟล์ใน ZIP เป็นชื่อที่ helper สร้างเพื่อไม่ใช้ archive path ที่ไม่ปลอดภัยโดยตรง

ข้อความที่อ่านได้จะผ่าน heuristic redaction; binary ยังเป็นข้อมูลสำหรับตรวจ static
ไม่ได้ decrypt/decompile อัตโนมัติ ไม่รัน init.jbin และไม่เรียก backend ของเกม
ไฟล์ research pack ไม่ใช่ game assets ที่จะนำเข้า `src/` และไม่ต้อง commit ลง Git

ได้รับ pack และตรวจ header/schema แล้ว: CSB 18 ฉาก / 474 nodes, PNG textures 108
และ SCSP wrapper 7 ไฟล์ ดู [ผลจริงและ provenance](research/CHAOS_BOOTSTRAP_ANALYSIS.md)
กับ [วิธีเปิด wireframe](BOOTSTRAP_REPLAY.md) ต่อให้ decode title UI ได้ ก็ยังไม่ยืนยัน
combat UI หรือ card rules ทั้งเกม
