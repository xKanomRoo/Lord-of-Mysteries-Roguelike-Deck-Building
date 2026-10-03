# รับทรัพยากร CZN ทั้งหมดที่ติดตั้งไว้

คำขอผู้ใช้วันที่ 3 ตุลาคม 2026: **“ขอทั้งหมดเลย”** จึงขยายจากตัวอย่าง
18 DB/CSB เป็นทุก resource ที่ manifest รุ่นที่ได้รับระบุ ไม่ต้องเลือกรายชื่อเอง
เครื่องมือชุดเดิมยังรักษาขอบเขตและการตรวจเดิมไว้

## ดาวน์โหลดและดูสิ่งที่มีแล้ว

ไฟล์ส่งมอบอยู่ในข้อความตอบของแชตและพื้นที่ส่วนตัว
`.local/research/all-resource-delivery/` ไม่เก็บภาพอ้างอิงหรือนิยายใน Git
แกลเลอรีรวมมี **140 PNG**: bootstrap เดิม 111 ภาพ และ texture ภาษาอังกฤษ
29 ภาพที่เพิ่งถอดครบ พร้อม **SCSP/atlas 10 ชุด** ที่ยังไม่ได้ประกอบแอนิเมชัน
ภาพภาษาอังกฤษเป็น banner/ข้อความสถานะ/ผลจบด่าน ไม่ใช่ภาพตัวละครเพิ่ม

ชุดภาษาอังกฤษมีภาพอยู่แล้วแต่ก่อนหน้านี้ยังไม่ได้ถอดให้ครบ จึงแก้โดยอ่าน
36 resources ทั้งกลุ่มภาษาอังกฤษ ตรวจ chunk/SSRC/Zstd/FHSH และถอด SCT
29 ไฟล์จริง ไม่ใช้จำนวนรายชื่อแทนจำนวนภาพ ดู
[ผลภาพและข้อจำกัด](REFERENCE_VISUAL_RESULTS.md)

รายการเต็มมี **87,529 paths** รวม stored payload **8,268,841,848 bytes
(7.70 GiB)** และ decoded container **9,092,590,042 bytes (8.47 GiB)**
รวมหลายภาษา/variants ไม่ใช่จำนวนการ์ด ตัวละคร หรือฉากที่เล่นได้
ขณะนี้มี payload 55 paths ใน manifest; ส่วนที่เหลือ 87,474 paths ยังไม่ได้รับ
bootstrap จาก APK เป็นอีกชุดแยกต่างหาก อย่านำมาบวกรวมกับ runtime paths
การถอด compression/container ไม่ได้แปลว่าอ่าน schema หรือเล่น resource นั้นได้

## ส่งออกจาก LDPlayer ในขั้นเดียว

1. เปิด LDPlayer และเกม รอการดาวน์โหลด resource เสร็จ เปิด ADB ภายในเครื่อง
   ตามที่ใช้งานได้แล้ว ไม่ต้องเปลี่ยนเป็น root หรือเปิดให้เชื่อมต่อจากอินเทอร์เน็ต
2. ดาวน์โหลด **ชุดเครื่องมือส่งออกทั้งหมด** จากข้อความตอบ แตก ZIP แล้ว
   ดับเบิลคลิก `EXPORT-ALL-CZN.cmd` เครื่องที่ติดตั้ง Python 3.14 แล้วใช้ได้
   โปรแกรมใช้ `D:\LDPlayer\LDPlayer14\adb.exe` และ `emulator-5554` ตามเครื่อง
   ที่ตรวจสำเร็จก่อนหน้า หากหา ADB ไม่พบจะให้เลือก `adb.exe`
3. โปรแกรมสร้าง ZIP แบ่งชุดใน
   `%USERPROFILE%\Downloads\chaos-research\.local\chaos-all-resources`
   แล้วเปิดโฟลเดอร์ผลลัพธ์ ส่ง `all-export-report.json`, `chaos-all-source.zip`
   และ `chaos-all-000001.zip` กลับมาก่อน จากนั้นส่ง `chaos-all-*.zip` ชุดถัดไป
   ไฟล์ `export-state.sqlite3` ใช้ทำต่อในเครื่อง ไม่ต้องแนบ
   ไม่ต้องส่ง account data, preferences, tokens หรือไฟล์ดิสก์ LDPlayer ทั้งลูก

แต่ละ ZIP ไม่เกิน **30 MiB** เพื่อรับผ่านช่องทางแนบไฟล์ที่รองรับ 32 MiB
ไฟล์ใหญ่ เช่น `sound/master.bank` ขนาด 344.57 MiB แบ่งเป็น fragment แล้ว
ตรวจและประกอบคืนบนคลาวด์ การส่งออกครบอาจมี ZIP หลายร้อยชุด
เตรียมพื้นที่ว่างอย่างน้อยประมาณ **12 GiB** สำหรับชุดส่งออก และรอจนรายงาน
สรุปผลเสร็จ หากหยุดกลางทาง เปิดไฟล์เดิมเพื่อทำต่อจาก ZIP ที่ตรวจแล้วได้

**โปรแกรมอ่านได้เฉพาะสิ่งที่ติดตั้งในเครื่องคุณ** ถ้า chunk ยังไม่มีหรืออ่าน
ไม่ได้ จะรายงาน partial และรายการที่ขาด ไม่ดาวน์โหลดจาก endpoint ที่เดาขึ้น
ถ้าเกมอัปเดตจน manifest เปลี่ยน จะหยุดให้ตรวจ manifest ใหม่ก่อน
ไม่มีการยืนยันว่าได้ทุกไฟล์บนเซิร์ฟเวอร์ ทุกเวอร์ชัน หรือ live events ที่ไม่ได้
อยู่ใน manifest นี้ คลาวด์เข้าถึง Windows/LDPlayer ของคุณโดยตรงไม่ได้

## ทำซ้ำสำหรับทีม

Windows ใช้ Python standard library ในขั้นส่งออก ไม่มี package เพิ่ม:

```powershell
py .\tools\export_all_game_resources.py --adb "D:\LDPlayer\LDPlayer14\adb.exe" --serial "emulator-5554" --output ".local\chaos-all-resources" --resume
```

`tools/export_all_game_resources.py` อ่าน manifest SHA-256
`45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15`
แล้วใช้ mapping ที่ตรวจจาก manifest เท่านั้น ส่งออกทุกแถวเป็น inert ordinal
fragments รวม scripts/config ที่เป็น developer resources โดยไม่ execute
ไฟล์เกมหรือเข้า user databases โปรแกรมอ่านเฉพาะ external resource root
ของ package `com.smilegate.chaoszero.stove.google`

บนคลาวด์ใช้ `tools/read_all_game_resources.py` ตรวจ ZIP, source manifest,
row/segment identities และ fragment hashes ก่อนประกอบ resource ตรวจ decoded
FHSH แล้วเก็บเป็นไฟล์ ordinal ส่วนตัว ใช้ `.local/runtime-venv/bin/python`
ที่มี trusted `zstandard==0.25.0`; การถอด SCT2 ใช้ isolated
`.local/texture-venv` ที่มี `texture2ddecoder==1.0.6` อยู่แล้ว
รายงาน decoded หมายถึง byte container ไม่ใช่ source JS, rig ที่ประกอบแล้ว,
เสียงที่แปลงแล้ว หรือ screenshot เกมที่รันจริง

คำสั่ง reader รับ source ZIP หนึ่งไฟล์และ resource ZIP ที่ส่งถึงแล้วเท่านั้น
รับชุดถัดไปเข้า output เดิมได้ และตรวจใหม่ก่อนทำต่อ แทนการถือว่าการรายงาน
จากเครื่องส่งออกเป็นหลักฐานว่าคลาวด์ได้รับครบ:

```bash
.local/runtime-venv/bin/python tools/read_all_game_resources.py --source INPUT_DIR/chaos-all-source.zip --batch-dir INPUT_DIR --output .local/research/all-czn
```

เมื่อรับครบ reader เก็บ raw fragments และ decoded copies รวมประมาณ
16.17 GiB พร้อม metadata/temp จึงต้องมีพื้นที่ว่างประมาณ **18 GB** สำหรับ
output เพิ่มจาก ZIP ที่รับเข้ามา; ตรวจ disk ก่อน full ingest

## ผลตรวจที่ทำแล้ว

Python suite **402 tests ผ่าน ไม่มี skips** รวม new exporter 16, reader 33,
catalog 9 tests การทดสอบครอบคลุม source drift, missing chunks, split assets,
hash/CRC/manifest mapping, bounds, malformed ZIP/JSON, crash/resume,
cross-process key order และ partial coverage ไม่อ้างว่าครบเมื่อยังขาด
actual received chunks replay คืน 37 resources: 34,253,254 stored bytes เป็น
70,737,437 decoded bytes; independent selected 18-resource replay ผ่านเช่นกัน
ทั้งหมดใช้ actual file bytes กับ local test adapter ไม่ใช่ ADB ของเครื่องผู้ใช้

ตรวจ standalone toolkit ที่แตก ZIP แล้ว imports/manifest replay ใช้ได้โดย
ไม่มี package/network เพิ่ม ตรวจ gallery 140 images และ full catalog/filter
ด้วย Chromium จริงผ่าน ไม่มี JS errors ทุก delivery ZIP ตรวจ member CRC/SHA
แยก native original APK จาก resources; full XAPK ยังไม่ได้รับครบในคลาวด์

นี่เป็นงานรับและส่งผลวิจัยของไฟล์อ้างอิง ไม่เปลี่ยนภาพใน APK ของเรา
งานภาพผลิตภัณฑ์ยังต้องสร้างภาพของเราและรวมเข้าฉากต่อสู้จริง
