# งานที่รับช่วงต่อ

อัปเดต 2026-10-03 เวลาไทย

**คำขอล่าสุด:** ผู้ใช้ถามว่าทำไมส่งภาพน้อย ยังมีอะไรไม่ได้ถอด แล้วขอ
**“ขอทั้งหมดเลย”** ให้รับและส่งทรัพยากรอ้างอิงทั้งหมดที่มี ไม่จำกัดตัวอย่าง
ดู [PLAYER_VISION](../PLAYER_VISION.md) และ [DECISIONS](DECISIONS.md)

## สิ่งที่ส่งมอบรอบนี้

- ตรวจและถอด English group ที่ได้รับครบ 36 resources พบ SCT อีก 29 ภาพ
  เป็น localized UI/banner/status/stage-clear; gallery รวม **140 PNG** และ
  raw SCSP/atlas **10 ชุด** ยังไม่มี reconstructed character animations
- Full private catalog มี 87,529 paths; 55 มี verified container bytes แล้ว
  อีก 87,474 มีเพียง metadata แยก bootstrap จาก APK ออกจาก runtime rows
  ทั้ง manifest ระบุ stored payload 7.70 GiB ไม่ใช่จำนวน unique content
- รวมภาพ bootstrap ทั้งแพ็ก, English text, selected DB/CSB/layout results,
  raw runtime chunks/JBIN และ native split ต้นฉบับที่ hash ตรง เป็น ZIP ส่วนตัว
  แต่ละไฟล์ไม่เกิน 30 MiB พร้อม catalog/provenance; ไม่รวม account data/นิยาย
- ทำ exporter ครบทุก manifest row แบบ stream/split/resume และ independent reader
  source/index/CRC/SHA/Zstd/FHSH ใช้ `tools/EXPORT-ALL-CZN.cmd` สำหรับผู้ใช้
  Windows; toolkit พร้อมดาวน์โหลด รายละเอียด [ALL_CZN_RESOURCES](../ALL_CZN_RESOURCES.md)
  รักษา exporter เดิมที่เลือก 18 paths ไว้ ไม่ลด pins หรือสั่งโหลด endpoints ที่เดา
- เก็บผลส่งมอบที่ `.local/research/all-resource-delivery/` พร้อม delivery-index
  และ gallery-preview จริง ไม่เก็บ reference bytes ใน Git หรือ APK

ตรวจ Python suite **402 tests ผ่าน ไม่มี skips**; actual byte replay ของ
37 resources จาก whole chunks ที่ได้รับ และ selected 18 resources ผ่าน
independent reader; catalogs รายงาน partial ถูกต้อง การจำลอง full manifest
ประมาณ 285 ZIP / 7,915 coalesced reads ไม่ใช่ผลรันจาก Windows ของผู้ใช้
Standalone toolkit imports/actual manifest replay และ browser จริงตรวจ
87529 catalog rows/140 loaded images/filtering ผ่าน ไม่มี JS errors
Startup cloud draft revision22 เก็บขั้นตอนใหม่แล้ว ไม่ได้ publish snapshot

## ขั้นที่ต้องทำต่อ

คลาวด์เข้าถึง LDPlayer ของผู้ใช้ไม่ได้ ให้ผู้ใช้แตก toolkit และดับเบิลคลิก
`EXPORT-ALL-CZN.cmd` ครั้งเดียว ส่ง `all-export-report.json`,
`chaos-all-source.zip`, `chaos-all-000001.zip` กลับ แล้วตามด้วย batches ถัดไป
อย่าขอ inventories/ZIP เดิมที่รับแล้วซ้ำ โปรแกรมรายงาน resource ที่ยังไม่ติดตั้ง
และหยุดเมื่อ manifest เปลี่ยน ไม่มีการยืนยันทุกไฟล์/เวอร์ชันบนเซิร์ฟเวอร์

เมื่อ batches มาถึง ใช้ reader `--batch-dir` กับ source ที่ pin แล้ว รับเข้า
private output เดิมได้ ตรวจ decoded FHSH และถอดภาพ SCT ที่ได้รับทั้งหมดต่อ
พร้อม gallery แยกภาพตัวละคร/การ์ด/ฉาก/UI อย่านับ manifest-only ว่าเป็นภาพ
SCSP, model_data, audio BANK และ cached V8 ยังต้องอ่าน schema/ถอดรูปแบบเพิ่ม
container decode ไม่ใช่ complete animation/source JS/runtime behavior

## เป้าหมายเกมที่ยังต่อเนื่อง

เกม Android LoTM/CoI ต้องมีฉาก ตัวละคร/ศัตรู และภาพการ์ดของเรา ลดข้อความ
และมีคอมโบที่ให้การตัดสินใจต่างกัน งานภาพถัดไปคือ illustrated combat slice
ที่เล่นได้ ตรวจ native viewport/touch แล้ว build APK และส่งภาพจากเกมที่รันจริง
ไม่ใช้ counts/diagram/concept/engine tests แทนคุณภาพงานภาพ

APK 0.2.0 เดิมยังมี placeholder; รอบวิจัยนี้ **ไม่ได้เปลี่ยน APK**
ไม่มี Android hardware test หรือ full local-resource transfer ที่ยืนยันแล้ว
Supabase มี adapter/schema แต่ยังไม่มี live project เกมยังเล่นและเซฟออฟไลน์ได้
ค้น lore จาก private Chinese index เฉพาะส่วนที่ใช้ สร้าง product art/text ใหม่
ไม่คัดลอก source art/นิยายลงเกมหรือ Git และไม่รัน code จากไฟล์อ้างอิง
