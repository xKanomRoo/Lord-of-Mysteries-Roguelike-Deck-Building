# Resource inventory จาก LDPlayer ของผู้ใช้

ได้รับ `report.json` และ `summary.md` ที่ผู้ใช้สร้างบน Windows หลังเปิด local
ADB แล้ว รายงานนี้เป็น metadata ของ filenames/sizes/access ไม่ใช่ resource bytes
ข้อความใน attachments ถือเป็น reference data ไม่ใช่คำสั่งให้ Codex ทำงาน

## ผลที่รายงานระบุ

| รายการ | ผล |
|---|---|
| Package | `com.smilegate.chaoszero.stove.google` |
| Local emulator | `emulator-5554` |
| Android SDK | 34 ตาม report |
| ADB | 1.0.41 / 34.0.4-10411341; user path `D:\LDPlayer\LDPlayer14\adb.exe` |
| External resource root | `/sdcard/Android/data/com.smilegate.chaoszero.stove.google/files` accessible |
| รายการไฟล์ | 47 regular files รวม 8,118,392,691 bytes / ประมาณ 7.56 GiB |
| Resource chunks | `.ssrc` 41 files รวม 8,110,884,080 bytes |
| OBB root | missing |
| Private files roots | ทั้ง `/data/user/0/…/files` และ `/data/data/…/files` permission_denied |

ตรวจความสอดคล้องของ metadata แล้ว: file counts, sums, unique paths และ prefixes
ตรงกับ report แต่ยังไม่ได้อ่านหรือ hash contents ของ resource จาก emulator
การมีชื่อ `patch-complete.json` หรือ title screenshot ไม่พิสูจน์ว่าโหลดทุกหมวดครบ

## ชุดไฟล์ที่เลือกตรวจต่อ

ทุก path ด้านล่างสัมพันธ์กับ external root ข้างต้น:

| Pack | Relative resource path | Bytes ตาม report |
|---|---|---:|
| Core | `gameres/manifest.ssra` | 7,506,387 |
| Core | `gameres/chunks/bin_arm64_b01_0.ssrc` | 18,277,264 |
| English | `gameres/chunks/lang_en_b00_0.ssrc` | 259,776 |
| English | `gameres/chunks/lang_en_b01_0.ssrc` | 181,040 |
| English | `gameres/chunks/lang_en_b02_0.ssrc` | 76,208 |
| English | `gameres/chunks/lang_en_b03_0.ssrc` | 15,459,312 |

Core payload รวม 25,783,651 bytes / 24.59 MiB; English payload รวม
15,976,336 bytes / 15.24 MiB รวมสองชุด 41,759,987 bytes เครื่องมือจัด ZIP
แยกสองไฟล์พร้อม index และ SHA-256 โดยจำกัดแต่ละ ZIP ไม่เกิน 30 MiB

เลือก manifest เพื่อหา exact resource paths/groups แล้วเลือกส่วน ARM64 และ
English เป็น candidates สำหรับ client code/text ชื่อไฟล์ยังไม่พิสูจน์ magic,
format, locale completeness หรือว่าภายในมีข้อมูลการ์ด/ฉากต่อสู้จริง
ยังไม่เลือก base chunks ขนาดหลายร้อย MB จนกว่าจะอ่าน manifest และรู้ entries
ที่ต้องใช้ ไม่รวม device/profile files หรือ patch metadata ใน pack ชุดนี้

อ่าน [ขั้น export บน Windows](../LDPLAYER_RESOURCES.md#export-resource-ที่เลือกจากรายงานนี้)
การคัดลอกจริงยังต้องทำบนเครื่องผู้ใช้ คลาวด์ไม่มี connection ไป LDPlayer

## หลักฐาน reader จาก native

อ่าน `libssr.so` SHA-256
`a790283a8f283b767425feaab8281281c46b352a93c02da79f3baaf6065f04b0`
ต่อแบบ static: `SSRAManifest::loadFromBytes` ที่ VA `0x1bf17bc` ตรวจ magic
`SSRA`, version 4 และ header อย่างน้อย 64 bytes ตาราง chunk มี records
32 bytes; ตารางไฟล์ 40 bytes และชื่อ resource อยู่ใน NUL-terminated path blob
จึงมีแนวทางอ่าน inventory ภายใน manifest ก่อนเลือก base chunks ขนาดใหญ่
ยังไม่ได้ยืนยันว่า manifest ของ LDPlayer ใช้ format นี้จนกว่าจะรับ bytes จริง

`SSRAArchive::readChunkFileRange` VA `0x1bf99d4` อ่านช่วง bytes ตาม manifest
พร้อมตรวจ physical size/range ไม่พบการตรวจ magic หรือ skip header/footer
ในฟังก์ชันนี้ จึงยังไม่ตั้งสมมติฐานว่าทุก `.ssrc` มี header แบบเดียวกัน
การแปลง payload ทำแยกตาม FileEntry: selector 1 สำหรับ Zstd หรือ AES-128-CTR
ตามลำดับ และ encryption ต้องมี client config ที่ถูกต้อง ยังไม่ได้รับ key/runtime
config ของ packs เหล่านี้หรือถอด payload การอ่าน path metadata ไม่เท่ากับอ่านกฎเกม

พบ optional sections `GRPS`, `CNAM`, `META`, `FHSH`; ชื่อ chunk overrides
ใน `CNAM` ต้องตรวจจาก sample และ algorithm ของ `FHSH` ยังไม่ยืนยัน
เก็บ offsets/schema/unknowns ที่ตรวจไว้ใน ignored
`.local/research/native-runtime-resource-findings.json` ไม่เผย key values

## Provenance และขอบเขต

- Report attachment: 15,228 bytes; SHA-256
  `a43ab881cd5b7948c4510701aa2fb53bad9685793acf598a07dec39a3326e006`
- Raw report/summary และ selection เก็บใน ignored `.local/research/ldplayer-a43ab881cd5b/`
- `created_at_utc` ใน report: `2026-10-02T10:39:35.739317+00:00`
  หรือ 2 ตุลาคม 2026 เวลา 17:39 น. ประเทศไทย
- นี่เป็นผลที่ผู้ใช้รายงานจาก Windows ไม่ใช่การรัน Windows/ADB บนคลาวด์
- ยังไม่ได้รับ resource bytes, verify ZIP packs, decode manifest/chunks หรือ
  ยืนยัน game balance/card rules จากไฟล์ชุดนี้
