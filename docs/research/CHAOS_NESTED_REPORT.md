# รายงาน XAPK รอบสอง: nested inventory สำเร็จ

เอกสารนี้บันทึกสิ่งที่ทราบตอนรับ inventory; ผลตรวจ bytes/layouts ภายหลังอยู่ใน
[bootstrap analysis](CHAOS_BOOTSTRAP_ANALYSIS.md) ข้อความ unknown ด้านล่างเป็นสถานะ
ของรอบนี้ ไม่ใช่ข้อสรุปล่าสุด

แหล่งหลักฐานคือ `report.json` และ `summary.md` ที่ผู้ใช้รันบน Windows แล้วแนบมา
ไฟล์ XAPK ต้นฉบับยังไม่มีในคลาวด์ จึงยังไม่ได้ตรวจ raw bytes หรือ hash ของ XAPK ซ้ำ

## สิ่งที่รายงานระบุ

| รายการ | ผล |
|---|---|
| XAPK | 152,845,071 bytes; hash ตรงกับ input ที่รายงานรอบแรกระบุ |
| analysis_status | completed |
| APK ย่อย | อ่านได้ 11 จาก 11; total archives รวมชั้นนอกเป็น 12 |
| Inventory | 1,417 entries; main APK 1,262 entries |
| Read errors | 0 |
| Candidate text entries | 862; ในนี้เป็น binary/encoded 806 และ UTF-8 text 56 |
| Binary resource tables | 10, ยังต้องมี decoder |
| Engine hints | ไม่พบในรูปแบบ Unity/Godot/Unreal ที่เครื่องมือรู้จัก; engine ยัง unknown |
| ฉากที่ควรตรวจ | .csb 18 ไฟล์, รวม 171,872 bytes |
| Asset data blobs | assets/sdata/ 15 ไฟล์, รวม 52,360,002 bytes; ยังไม่ทราบ format/เนื้อหา |

รายงานอ่านสำเร็จตามขอบเขต inventory ไม่ได้แปลว่า XML binary ทั้งหมดถูก decode
หรือว่า UTF-8 text ทุกไฟล์เป็นข้อความของเกม ส่วนมากเป็น license และ SDK resources
การไม่มี supported engine hint ไม่พิสูจน์ว่าไม่มี engine หรือว่า engine ชนิดใดแน่นอน

## UI และข้อมูลที่เลือกตรวจต่อ

ไฟล์ `assets/pre/ui/scene_title.csb`, `scene_title_pre.csb`, `list_server.csb`,
`overlay_popup_confirm_download.csb`, `overlay_popup_server_select.csb` เป็นชื่อที่ชี้
เป้าหมายสำหรับตรวจ title/server/download flow ยังไม่เห็น hierarchy, positions,
interaction หรือ screenshot จริง `.csb` เป็นเหตุให้ตรวจ format ที่คล้าย scene bundle
ของ Cocos Studio แต่ extension อย่างเดียวไม่ยืนยัน engine หรือ schema

ไฟล์ `.sct`, `.scsp`, `.atlas`, `.cfx`, `init.jbin` และ blob ที่ไม่มี extension
ต้องตรวจ bytes ก่อนเลือก decoder ไม่สรุปว่า encrypted หรือเป็น game rules จากชื่อ
`assets/progress.json` มี keys `v`, `fr`, `ip`, `op`, `w`, `h`, `layers` ฯลฯ
คล้าย animation metadata; ชื่อ progress ไม่ใช่หลักฐานว่าเป็น gameplay progression

ข้อความที่มี provenance และเหมาะอ่านต่อ:

- XAPK `manifest.json`: ตรวจค่าชื่อ package/version ที่รายงานไม่ได้แนบค่ามา
- `assets/info.txt`: ข้อมูล bootstrap ที่ยังไม่ได้เห็นข้อความ
- `assets/progress.json`: ตรวจบทบาทและ structure ของ animation candidate
- `assets/pre/bin/gitsha.txt`: build metadata candidate; ไม่ใช่ canon หรือ balance

Native libraries อยู่ใน `config.arm64_v8a.apk` เช่น `libssr.so` 63,082,720 bytes,
`librhcore.so` 5,856,848 bytes และ FMOD libraries เป็นรายการไฟล์ที่รายงานพบ
ยังไม่ยืนยัน responsibilities หรือ rendering engine ขณะนี้ไม่ต้องส่ง native binaries
หรือ fonts เพื่อเริ่มตรวจ scene resources ขนาดเล็ก

## Provenance

- XAPK SHA-256 ตามรายงาน: `b95e115282272289c73abc1569b81a5bbf62b1f4f638c15d76cc2c7b2f120be0`
- Main APK SHA-256 ตามรายงาน: `a33b5ff9c3b9df1a826033625b7263eef946960218bcd1f710cf03b82ca1f64a`
- report.json SHA-256 ที่ตรวจจากไฟล์แนบ: `d5a6c95d3384c6646767ef8576b425cb926e421b4c5b4fd97ce1874db9fc5675`
- summary.md SHA-256 ที่ตรวจจากไฟล์แนบ: `fe94b254c181b75aee916efd324030a45e13d1323f18506acfc7d1a0aea42968`
- Report created_utc: `2026-10-02T08:04:16.552591+00:00`
- เก็บรายงานแนบใน `.local/research/uploaded-nested-report/` ซึ่งไม่อยู่ใน Git

## ขั้นต่อไป

สร้าง research pack ของ bootstrap metadata, scene resources และตัวอย่าง binary
ขนาดเล็ก โดยรักษา source paths/hash ใน pack index และจำกัด ZIP ไม่เกิน 30 MiB
ไฟล์อ้างอิงใน pack ใช้ตรวจ static เท่านั้น ไม่รันและไม่นำเข้าเกมต้นแบบโดยอัตโนมัติ
ดู [คำสั่งสร้างชุดไฟล์](../RESEARCH_PACK.md)
