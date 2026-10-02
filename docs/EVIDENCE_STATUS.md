# สถานะหลักฐาน

| ประเด็น | สถานะ | หลักฐาน/ผลที่ตรวจได้ |
|---|---|---|
| Repository เริ่มต้น | ตรวจแล้ว | checkout ว่าง ไม่มี commit และ GitHub ไม่คืน refs |
| ไฟล์ที่ผู้ใช้แนบ | รับเข้าเครื่องไม่ได้ | `Chaos+Zero+Nightmare_1.0.811_APKPure.xapk`; เครื่องมือรับไฟล์จำกัด 32 MiB |
| เวอร์ชันล่าสุดของเกม | ยังไม่ยืนยัน | ชื่อไฟล์อย่างเดียวไม่ยืนยัน release ล่าสุด |
| รายการไฟล์ชั้นนอก | ได้รับรายงานจากผู้ใช้ | 13 entries มี APK ย่อย 11 ไฟล์; ดู docs/research/CHAOS_OUTER_REPORT.md |
| Engine, assets, UI, กฎจาก APK ย่อย | ยังไม่ทราบ | รายงานอ่าน APK ย่อยล้มเหลวทั้ง 11 ไฟล์ด้วย FileNotFoundError |
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

ข้อผิดพลาด Windows ที่พบจากรายงาน: เครื่องมือใช้ `/tmp` แบบเจาะจง ทำให้สร้าง
temporary file ไม่ได้ รุ่นแก้ไขให้ Python เลือก temp directory ของระบบ และบันทึก
read failure ใน `errors` พร้อม `analysis_status: incomplete` และ exit code 1
การแก้ไขผ่าน regression fixtures แล้ว แต่ยังต้องรัน XAPK จริงบน Windows อีกครั้ง
