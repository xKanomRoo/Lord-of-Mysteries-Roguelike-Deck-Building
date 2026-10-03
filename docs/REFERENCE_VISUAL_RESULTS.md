# ภาพที่ได้รับจริงจาก CZN และช่องว่างงานภาพของเกมเรา

ตรวจ bytes ในเครื่องซ้ำวันที่ 3 ตุลาคม 2026 ตามเวลาไทย หลังผู้ใช้ถามว่า
ทำไมเกม native มีแต่ข้อความ ทั้งที่มีข้อมูลของเกมอ้างอิงแล้ว

อัปเดตหลังคำขอ **“ขอทั้งหมดเลย”**: ถอด English resources ที่ได้รับแต่ยังไม่
ถอดก่อนหน้าเพิ่ม 29 textures เป็น PNG แล้ว แกลเลอรีปัจจุบันรวม **140 PNG /
10 SCSP+atlas ชุด** ภาพที่เพิ่มเป็น localized UI/status/banner/stage-clear
ดู [ผลและวิธีรับทรัพยากรทั้งหมด](ALL_CZN_RESOURCES.md)
ตาราง bootstrap ด้านล่างยังบอกขอบเขตแพ็กเริ่มเกมเดิม ไม่ใช่ยอดรวมปัจจุบัน

**มีภาพจริงอยู่แล้ว** เกม native รุ่น 0.2.0 ยังใช้ procedural placeholder
เพราะ implementation ไม่ได้พัฒนางานภาพตามความต้องการของผู้ใช้
จำนวน card definitions ไม่เท่ากับจำนวนภาพการ์ด และการผ่าน engine/UI tests
ไม่ได้พิสูจน์คุณภาพศิลปะหรือความน่าเล่น

## สิ่งที่มี bytes และตรวจได้จริง

| ประเภท | ได้รับ/ถอดแล้ว | ตัวอย่างและสถานะ |
|---|---:|---|
| Texture images | 108 PNG | SCT1 2 + SCT2 ASTC 106; source/PNG hashes และ dimensions ตรวจจากไฟล์ |
| PNG เดิม | 3 | ภาพปุ่มใน bootstrap; แยกจาก 108 textures |
| SCSP + atlas | 7 ชุด | มี serialized animation/skeleton resources กับ atlas text; ยังไม่ได้ประกอบ rig/animation กลับ |
| Bootstrap UI scenes | 18 | title/download/login/modal layouts; 474 nodes |
| Card/hand/battle components | 5 | selected CSBs; 683 nodes; ผัง serialized component ไม่ใช่ complete gameplay screenshot |
| Selected card/effect/condition data | 8 DB shards | 2,691 rows รวม 278 card rows/variants; อ่าน cost/effect links ได้ แต่สูตรต่อสู้ครบยังไม่ยืนยัน |
| English text | 108,306 entries | localization ที่ถอดแล้ว; card fields 4,725 entries ไม่ใช่จำนวนการ์ดที่เล่นได้ |

ภาพที่เปิดตรวจจริง:

| Source ใน APK | ภาพที่ถอดได้ | Source SCT SHA-256 |
|---|---|---|
| `assets/pre/ui/title_terrascion.sct` | 1604×852 ตัวละครหลายคน สถาปัตยกรรม/ยาน พื้นหลังและแสง | `e053fcf513033fb4b81552fc719b769e8d4893e352decd080a73114ed5768136` |
| `assets/pre/effect/20035.sct` | 424×1104 ชิ้นส่วนหน้า ผม เสื้อผ้า แขน ขาและอุปกรณ์ตัวละคร 2D | `6e6e9d4d1f006f95a2aa72e15234de2e5b81102b1cba14aea73e33de2b2fbfc7` |
| `assets/pre/effect/lobby_bg.sct` | 2031×1617 atlas ส่วนห้อง ทางเดิน จอ เมืองและ effects | `af012b1643e73a118be9502364822108a96d1eb32fce0b56cd4500f3067d145f` |

ภาพแรกเป็น resource illustration ไม่ใช่การจับหน้าจอขณะเล่นเกม
atlas มีหลายชิ้นอยู่ในภาพเดียว ต้องใช้ข้อมูลประกอบเพื่อวางเป็นฉากหรือตัวละคร
มี SCSP ของ `20035` อยู่จริง แต่ยังไม่มี reconstructed animation ที่ตรวจว่าเล่นได้
ยังไม่มีโมเดล 3D/Live2D ที่ยืนยันว่าถอดและเปิดใช้งานสำเร็จ

## สิ่งที่มีรายชื่อ แต่ยังไม่ได้รับ bytes

manifest SHA-256
`45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15`
มี 87,529 unique paths รายชื่อในนั้นไม่เท่ากับไฟล์ที่ได้รับในคลาวด์

| หมวด manifest | รายการที่พบ | สถานะในคลาวด์ |
|---|---:|---|
| `face/character/` | 2,019 SCT | ยังไม่ได้รับ payloads หมวดนี้ |
| `face/portrait/` | 235 SCT + 235 SCSP + 235 atlas | มีชื่อ 235 ชุด ไม่ยืนยันจำนวนตัวละครหรือ variants |
| `card_illustration/` | 1,004 SCT | มีรายชื่อภาพการ์ด ไม่ใช่ภาพที่ถอดแล้ว |
| `model/` | 1,302 SCT + 1,294 SCSP + 1,294 atlas | ชื่อหมวด model ไม่พิสูจน์ว่าเป็นโมเดล 3D |
| `background/` | 397 SCT | runtime backgrounds ยังไม่ได้รับ; แยกจาก lobby atlas ใน bootstrap |
| `fields/` | 5,981 SCT | ไม่ยืนยันจำนวนแผนที่ที่เล่นได้ |
| `sound/` | 988 BANK | ยังไม่มี decoded sound จาก payloads เหล่านี้ |

หมวดเหล่านี้อยู่ใน manifest group 12 ส่วน core/English chunks ที่ได้รับก่อนหน้า
เป็น groups 9/2 และ range ZIP 18 resources เลือก DB/CSB การเลือกดึงข้อมูลก่อนหน้า
จึงให้ระบบกับผัง UI มากกว่างานภาพ character/card/battlefield
ดู [bootstrap](research/CHAOS_BOOTSTRAP_ANALYSIS.md),
[runtime](research/CHAOS_RUNTIME_ANALYSIS.md) และ
[card/battle](research/CHAOS_CARD_BATTLE_ANALYSIS.md)

## ผลลัพธ์ภาพที่ส่งให้ดู

ผลตรวจและแกลเลอรีส่วนตัวอยู่ `.local/research/visual-audit/`:

- `czn-recovered-pictures.zip`: PNG และ original SCSP/atlas ที่ได้รับ
- `index.html`: เปิดบนเครื่องหลังแตก ZIP; มีภาพจริงและชื่อ source
- catalogs JSON/CSV: source SHA-256, PNG SHA-256, dimensions และประเภท
- `asset-audit.json`: inventory และการตรวจภาพจาก bytes จริง
- `design/review.md`: ช่องว่างของ native UI เทียบกับหลักฐานภาพ
- `design/composition-diagram.svg`: ผังพื้นที่ภาพใหม่ เป็น diagram ไม่ใช่ screenshot เกม

แกลเลอรีเป็นผลวิจัยจากไฟล์ของผู้ใช้ เก็บนอก Git และไม่ได้อยู่ใน APK ของเรา
ลิงก์ดาวน์โหลดอยู่ในข้อความส่งมอบของแชต repository เก็บรายงาน metadata
ไม่เก็บ reference art ส่วนตัว ไฟล์นิยายหรือ account/session data

## เหตุผลที่ native รุ่นก่อนมีแต่ข้อความ

`mobile/scripts/main.gd` ใช้ `Atmosphere`, `EnemyPortrait` และ `Sigil`
วาดรูปเรขาคณิต ยังไม่ได้โหลด character/environment/card art หรือ custom font
21 enemy definitions ใช้ภาพ hood รูปแบบเดียวที่เปลี่ยนตาม 3 acts
54 card definitions ใช้สัญลักษณ์ 3 categories ในพื้นที่ประมาณ 30 units
ข้อมูล LoTM/CoI ช่วยด้านธีมและกฎ ไม่ได้สร้างภาพตัวละครโดยอัตโนมัติ

สิ่งที่นำจากหลักฐานไปออกแบบงานภาพได้แล้ว:

1. ให้ฉาก ตัวละครและศัตรูเป็นภาพหลัก มี foreground/background และแสงแยกจุดสนใจ
   ภาพ title แสดงองค์ประกอบนี้ได้ แม้ยังไม่ใช่หลักฐาน battle HUD
2. ใช้ card/hand components เป็นตัวอย่างการแยกกรอบ ภาพ cost title และ touch area
   selected hand layout มีห้าใบจัดโค้งใน saved state; ไม่ใช่ข้อสรุป hand limit
3. สร้างภาพการ์ดกับ portraits ที่มีเอกลักษณ์ตาม IDs ลดข้อความที่เห็นพร้อมกัน
   แสดง effect สั้นบนการ์ดและเปิดรายละเอียดเมื่อต้องการ โดยไม่ซ่อนข้อมูลตัดสินใจ
4. ทำฟอนต์ hierarchy, hit/card-flight/idle feedback และตรวจภาพจากเกมที่รันจริง
   ภาพที่ยังไม่ได้รวมในเกมไม่ใช่หลักฐานว่า APK มีงานภาพนั้นแล้ว

งานภาพถัดไปควรเป็น illustrated combat stage, original character portraits และ
card artwork ก่อนเพิ่มข้อความ/definitions อีก CZN ให้ตัวอย่างด้าน composition
และ components; เกม LoTM/CoI ของเรายังต้องทำ art direction และรวมภาพกับ renderer

เตรียม metadata เลือก art runtime เพิ่มไว้ใน
`.local/research/visual-audit/proposed-art-selection.json`: 10 resources,
stored bytes 3,608,239 ครอบคลุม model/portrait/card art/frame/energy/background
นี่เป็น proposal ไม่ใช่ plan ที่รันกับ exporter เดิมซึ่ง pin เฉพาะ 18 DB/CSB paths
ต้องเพิ่ม art profile/exporter/reader ที่ตรวจ exact paths/hashes/ranges ก่อนใช้
ไม่ต้องส่งทั้งเกมหรือ account data เพื่อเลือกดูงานภาพชุดเล็กนี้

คำขอล่าสุดให้รับทั้งหมดแทนชุดตัวอย่างนี้ ใช้ exporter/reader ใหม่ตาม
[ALL_CZN_RESOURCES](ALL_CZN_RESOURCES.md); proposal สิบไฟล์ยังเป็น metadata
อย่านำไปเรียก exporter เดิมหรืออ้างว่ารับภาพ runtime หมวดนั้นแล้ว
