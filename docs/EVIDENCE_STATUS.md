# สถานะหลักฐาน

| ประเด็น | สถานะ | หลักฐาน/ผลที่ตรวจได้ |
|---|---|---|
| Repository เริ่มต้น | ตรวจแล้ว | checkout ว่าง ไม่มี commit และ GitHub ไม่คืน refs |
| Full XAPK ที่ผู้ใช้แนบ | รับเข้าเครื่องไม่ได้ | เกิน 32 MiB; รับ bootstrap ZIP 3.41 MiB ภายหลังแล้ว |
| เวอร์ชัน build | ยืนยัน 1.0.811 | manifest JSON และ binary Android manifest ตรงกัน; latest release ยังไม่ยืนยัน |
| รายการไฟล์ชั้นนอก | ได้รับรายงานจากผู้ใช้ | 13 entries มี APK ย่อย 11 ไฟล์ |
| รายการใน APK ย่อย | ได้รับรายงานรอบใหม่ | อ่าน APK ย่อยครบ 11, รวม 1,417 entries, errors ว่าง; ดู docs/research/CHAOS_NESTED_REPORT.md |
| Scene format / engine evidence | ยืนยัน Cocos Studio format และ native version labels | returned cocos2d-x-4.0 / V8 12.4.254.21; ไม่ใช่หลักฐานเวอร์ชัน engine fork ทั้งหมด |
| กฎเกม / combat UI | อ่าน selected costs/effects และ UI components จริงแล้ว | English card@4,725entries; DB card rows278รวมvariants/effect rows1,139; Gear Bag cost1/DRAWvalue2; runtime damage formulas และ complete combat HUD ยังไม่ยืนยัน |
| UI layouts | อ่าน 18/18 ฉาก, 474 nodes / WidgetOptions | รวม vendor TileSprite 5 จาก native reader; properties/animation/constraints ยังอ่านไม่ครบ; wireframe เป็น serialized projection |
| Native APK | ได้รับและตรวจ hash แล้ว | 22,979,689 bytes; ARM64 libraries 10 ไฟล์; ไม่ execute |
| PLPcK bootstrap | ตรวจ container 26 records | 25 V8 cached-data payloads; bootstrap modules ไม่ใช่ decoded gameplay spec |
| sdata ตัวอย่าง | อ่าน RH01 wrapper 7 ไฟล์ | original RSA signatures ผ่าน 7/7; SDK text configs 6 และ inner binary 1; ไม่พบ card/battle schema |
| Entry/config URL | ยืนยันจาก native references | GET `/cznlive` บน host ใน docs/SERVER_RESOURCES.md; ยังไม่มี asset manifest/CDN response |
| Cloud entry request | ถูก proxy CONNECT ปฏิเสธ 403 | ยังไม่ถึง game server จึงไม่ทราบ upstream status/authentication |
| LDPlayer resources | ได้รับ runtime ZIPs แล้ว | payload 6 files /41,759,987 bytes ผ่าน CRC/SHA; manifest v4 มี 87,529 paths/57chunk entries; manifest list ไม่ได้พิสูจน์ทุก chunk อยู่ใน emulator |
| English text DB | ถอดและตรวจ container ครบ | PLPcK216,616records/108,306texts; card@4,725 entries รวม variants; exact sizes/FHSH/native source hash ตรวจผ่าน; ดู runtime analysis |
| main.jbin | คลาย Zstd/FHSH ผ่าน; linked metadata บางส่วน | 2,167records/2,166V8cache; compact parser ยังปฏิเสธ complete coverage; ไม่ execute หรือคืน source JS |
| Card/battle range export | ได้รับและตรวจ ZIP แล้ว | source indexประกาศToybox backend; 18payloads622,458stored/1,342,080decodedbytesผ่านCRC/SHA/manifestrows/Zstd/FHSH; surrounding span/fullchunk hashes และ exporter scope assertions ยังไม่ independently verified |
| Selected DB shards | อ่านแปด shards ครบ | 2,691rows/5,780records; source-pinned wrapper/schema/index/bucket/fullcoverageผ่าน; trailer38bytesตรวจตรงแต่purposeunknown; fulltablesไม่commit |
| Card/hand UI | อ่านห้าฉากครบ documented subset | 683nodes/682WidgetOptions/unsupportedTileSprite1; cardroot0x0จริงและdiagramviewportinferred; handbranches1–13เป็นsavedalternatives; fullHUD/animation/assetsยังไม่ยืนยัน |
| Texture images | ถอด PNG ได้ 108 ไฟล์ และ PNG เดิม 3 | มี title illustration พร้อมตัวละคร, character-parts atlas และ lobby atlas จริง; ดู REFERENCE_VISUAL_RESULTS; ไม่ใช่ screenshot เกมที่ประกอบแล้ว |
| SCSP / model art | รับ SCSP/atlas 7 ชุดใน bootstrap | ยังไม่ได้ประกอบ animation/rig; ไม่มี verified reconstructed 3D/Live2D; runtime portrait/card/model art มีชื่อใน manifest แต่ payloads ยังไม่ได้รับ |
| กฎต้นแบบใน repository นี้ | งานออกแบบใหม่ | browser demo ใน `src/`; Godot native Android ใน `mobile/`; ไม่ใช่ recovered CZN runtime |
| Native mobile content | original adaptation แยกจาก research | 3pathways/54cards/21enemies/12events36choices/12relics, 3acts12combats; source และ save schemas มี tests; ดู CONTENT_DESIGN |
| นิยายจีนผู้ใช้ | อ่านและนำเข้า private corpus แล้ว | 2files17,812,214bytes strict/roundtripGB18030,13,904chunks; hashes/chapters/line offsets ตรวจจริง; edition/completenessไม่ยืนยัน; fulltext/indexไม่เข้าGit/APK |
| Online player saves | source/schema พร้อม; ยังไม่มี live project | Supabase owner RLS + revision guards; localPG17.11ผ่าน18checks/Godotprotocol41; ผู้ใช้ต้องสร้างprojectและใส่publicconfigเอง |
| ภาพและข้อความต้นแบบ | งานออกแบบใหม่; native ยังเป็น placeholder art | CSS/SVG เดิมและ Godot procedural geometry; ยังไม่มี character/environment/card illustrations; จำนวน card definitions ไม่ใช่จำนวนภาพการ์ด |
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
และผล runtime resources/text DB อยู่ใน
[CHAOS_RUNTIME_ANALYSIS.md](research/CHAOS_RUNTIME_ANALYSIS.md)

ข้อผิดพลาด Windows ที่พบจากรายงาน: เครื่องมือใช้ `/tmp` แบบเจาะจง ทำให้สร้าง
temporary file ไม่ได้ รุ่นแก้ไขให้ Python เลือก temp directory ของระบบ และบันทึก
read failure ใน `errors` พร้อม `analysis_status: incomplete` และ exit code 1
การแก้ไขผ่าน regression fixtures และได้รับรายงานผู้ใช้รอบใหม่ตามรายละเอียดด้านล่าง

อัปเดตจากรายงานผู้ใช้รอบสอง: `analysis_status: completed`, APK ย่อยอ่านได้ทั้ง 11
และไม่มี read errors แสดงว่าอุปสรรคการอ่าน nested APK รอบแรกผ่านแล้วในรายงานผู้ใช้
คำว่า completed หมายถึง inventory ตามขอบเขต static ไม่ใช่ decode UI/binary/game rules ครบ
