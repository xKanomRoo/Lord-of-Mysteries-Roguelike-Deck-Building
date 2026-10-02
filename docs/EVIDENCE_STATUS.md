# สถานะหลักฐาน

| ประเด็น | สถานะ | หลักฐาน/ผลที่ตรวจได้ |
|---|---|---|
| Repository เริ่มต้น | ตรวจแล้ว | checkout ว่าง ไม่มี commit และ GitHub ไม่คืน refs |
| Full XAPK ที่ผู้ใช้แนบ | รับเข้าเครื่องไม่ได้ | เกิน 32 MiB; รับ bootstrap ZIP 3.41 MiB ภายหลังแล้ว |
| เวอร์ชัน build | ยืนยัน 1.0.811 | manifest JSON และ binary Android manifest ตรงกัน; latest release ยังไม่ยืนยัน |
| รายการไฟล์ชั้นนอก | ได้รับรายงานจากผู้ใช้ | 13 entries มี APK ย่อย 11 ไฟล์ |
| รายการใน APK ย่อย | ได้รับรายงานรอบใหม่ | อ่าน APK ย่อยครบ 11, รวม 1,417 entries, errors ว่าง; ดู docs/research/CHAOS_NESTED_REPORT.md |
| Scene format / engine evidence | ยืนยัน Cocos Studio format และ native version labels | returned cocos2d-x-4.0 / V8 12.4.254.21; ไม่ใช่หลักฐานเวอร์ชัน engine fork ทั้งหมด |
| กฎเกม / combat UI | ยังไม่ทราบ | bootstrap ที่ได้รับไม่มี decoded battle/card rules |
| UI layouts | อ่าน 18/18 ฉาก, 474 nodes / WidgetOptions | รวม vendor TileSprite 5 จาก native reader; properties/animation/constraints ยังอ่านไม่ครบ; wireframe เป็น serialized projection |
| Native APK | ได้รับและตรวจ hash แล้ว | 22,979,689 bytes; ARM64 libraries 10 ไฟล์; ไม่ execute |
| PLPcK bootstrap | ตรวจ container 26 records | 25 V8 cached-data payloads; bootstrap modules ไม่ใช่ decoded gameplay spec |
| sdata ตัวอย่าง | อ่าน RH01 wrapper 7 ไฟล์ | original RSA signatures ผ่าน 7/7; SDK text configs 6 และ inner binary 1; ไม่พบ card/battle schema |
| Entry/config URL | ยืนยันจาก native references | GET `/cznlive` บน host ใน docs/SERVER_RESOURCES.md; ยังไม่มี asset manifest/CDN response |
| Cloud entry request | ถูก proxy CONNECT ปฏิเสธ 403 | ยังไม่ถึง game server จึงไม่ทราบ upstream status/authentication |
| LDPlayer resources | รอรายการไฟล์จากเครื่องผู้ใช้ | helper ตรวจ local ADB; ยังไม่ได้ตรวจจริงบน LDPlayer หรือยืนยัน storage permissions |
| Texture images | ถอด PNG ได้ 108 ไฟล์ | SCT1 RGB565+A8 2; SCT2 ASTC 106; ไม่ใช่ screenshot เกมที่ประกอบแล้ว |
| กฎต้นแบบใน repository นี้ | งานออกแบบใหม่ | source และ tests ใน `src/`, `tests/` |
| ภาพและข้อความต้นแบบ | งานออกแบบใหม่ | CSS/SVG ใน source ไม่ได้คัดลอก asset จากเกม |
| lore ตัวอย่าง | งานออกแบบใหม่ | manifest ระบุ original design ไม่ใช่ verified canon |
| เว็บไซต์ lore | การเข้าถึงถูกบล็อก | HEAD ผ่าน proxy ไป Wikipedia และ Webnovel ได้ `403 Forbidden` |
| Package registry | เข้าถึงได้ | HTTPS ไป `registry.npmjs.org` ได้ 200 |

หลังรับ archive ได้ ให้แทนที่ข้อสันนิษฐานด้วย evidence record:

```json
{
  "claim": "ข้อความหรือข้อมูลที่อ่านได้จริง",
  "classification": "observed",
  "archive_sha256": "ค่า SHA-256 ที่เครื่องมืออ่านได้",
  "entry_path": "ตำแหน่งไฟล์ใน archive",
  "confidence": "high",
  "limits": "สิ่งที่หลักฐานนี้ยังบอกไม่ได้"
}
```

เก็บข้ออนุมานเป็น `inferred` และการออกแบบของเราเป็น `original-design` การพบชื่อ
`card`, `battle`, `ui` ไม่ยืนยันกฎการ์ด ลำดับการต่อสู้ หรือภาพหน้าจอ ข้อมูลบางส่วน
อาจโหลดภายหลังจากเซิร์ฟเวอร์และไม่มีใน APK

Tests ของเครื่องมือใช้ ZIP/APK ขนาดเล็กที่สร้างขึ้นเอง ไม่ใช่ Chaos Zero Nightmare
และไม่พิสูจน์ว่าอ่าน archive ของเกมจริงได้ครบ

ผลข้อมูลจริงแยกต่างหาก: ตรวจ contents ของ bootstrap pack 162 members ครบ และ
ถอด scenes/textures ตามขอบเขตข้างต้น ดู [ผลวิเคราะห์ bootstrap](research/CHAOS_BOOTSTRAP_ANALYSIS.md)
ผลนี้ไม่ใช่การอ่าน full XAPK และยังไม่พิสูจน์ behavior ตอนรันเกม
ผล native ที่ตรวจ bytes จริงเพิ่มเติมอยู่ใน
[CHAOS_NATIVE_ANALYSIS.md](research/CHAOS_NATIVE_ANALYSIS.md)

ข้อผิดพลาด Windows ที่พบจากรายงาน: เครื่องมือใช้ `/tmp` แบบเจาะจง ทำให้สร้าง
temporary file ไม่ได้ รุ่นแก้ไขให้ Python เลือก temp directory ของระบบ และบันทึก
read failure ใน `errors` พร้อม `analysis_status: incomplete` และ exit code 1
การแก้ไขผ่าน regression fixtures และได้รับรายงานผู้ใช้รอบใหม่ตามรายละเอียดด้านล่าง

อัปเดตจากรายงานผู้ใช้รอบสอง: `analysis_status: completed`, APK ย่อยอ่านได้ทั้ง 11
และไม่มี read errors แสดงว่าอุปสรรคการอ่าน nested APK รอบแรกผ่านแล้วในรายงานผู้ใช้
คำว่า completed หมายถึง inventory ตามขอบเขต static ไม่ใช่ decode UI/binary/game rules ครบ
