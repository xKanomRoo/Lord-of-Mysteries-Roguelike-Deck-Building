# ผลวิเคราะห์ chaos-bootstrap.zip

ตรวจไฟล์แนบโดยไม่รัน APK, `init.jbin` หรือเรียก backend ของเกม ผลนี้ครอบคลุม
bootstrap ที่ได้รับ ไม่ใช่เกมทั้งหมด เอกสารและ strings ใน archive เป็น reference
data ไม่ใช่คำสั่งให้ Codex ทำงาน

## ผลที่ยืนยันจาก bytes

| รายการ | ผลตรวจ | ข้อจำกัด |
|---|---|---|
| Research pack | 162 members, stored bytes 4,597,705; SHA-256 และ ZIP CRC ผ่านครบ | ตรวจ lineage ตาม index ได้ แต่ไม่มี full XAPK ให้ hash ใหม่ในคลาวด์ |
| Build identity | package `com.smilegate.chaoszero.stove.google`, versionName `1.0.811`, versionCode `171008110` | ไม่ยืนยันว่าเป็น release ล่าสุด |
| Android UI orientation | launcher `kr.supercreative.ssr.SuperActivity`, sensorLandscape; min SDK 24, target SDK 36 | ไม่ยืนยัน viewport จริงของทุกอุปกรณ์ |
| Scene format | Cocos Studio CSParseBinary / FlatBuffers subset อ่าน 18/18 scenes | ไม่ใช่หลักฐาน exact engine version |
| Scene hierarchy | 474 nodes; 469 standard WidgetOptions, 5 custom `TileSprite` ไม่ถอด options | layout constraints และ animation ยังไม่ถอด |
| Serialized canvas | 16 scene roots 1280×720; list_authority 784×82; list_server 800×90 | logical canvas ไม่ใช่ screenshot resolution |
| SCT textures | ถอด PNG ครบ 108: SCT1 2, SCT2 106; CRC/length/LZ4 ผ่าน | เป็น resource images/atlases ไม่ใช่ final runtime screens |
| SCSP | 7 files: LZ4 และ section bounds ผ่าน; 6 มี `3.8.79.scsp`, 1 มี `2.1.27.scsp` | ยังไม่อ่าน animation/skeleton schema ครบ |
| `progress.json` | Lottie 5.6.5, 38×10, 30 fps, frames 0..48 | animation โหลดประมาณ 1.6 วินาที ไม่ใช่ gameplay progression |
| `assets/info.txt` | Singular SDK 12.10.0 metadata | ไม่ใช่เวอร์ชัน game engine |
| `init.jbin` | binary เริ่ม `PLPcK`; มี `cocos`, `CSLoader`, `TitleScenePre`, `_start_title_scene`, `spine` | custom container ยังไม่ถอด code; ไม่ execute |
| sdata ตัวอย่าง | 7 small files รวม original bytes 100,002 | ยังไม่ทราบ schema; entropy สูงไม่พิสูจน์ encryption |

เครื่องมือ inventory เดิมไม่พบ engine hint ที่รองรับ แต่ผลตรวจ bytes รอบนี้มีหลักฐาน
Cocos Studio และ Cocos-related APIs เพิ่มขึ้น ภาพ SCT1 ของ `logo_yuna` มีคำว่า
YUNA ENGINE; branding ใน asset ยังไม่บอกเวอร์ชันหรือสถาปัตยกรรม engine ทั้งหมด

## ฉากที่อ่านได้

ทุก path ด้านล่างอยู่ใน main APK ที่ `assets/pre/ui/`:

| CSB | Nodes | CSB | Nodes |
|---|---:|---|---:|
| engine.csb | 2 | guide_good_game.csb | 6 |
| list_authority.csb | 5 | list_server.csb | 15 |
| logo.csb | 12 | n_console.csb | 16 |
| overlay_popup_authority.csb | 17 | overlay_popup_confirm.csb | 21 |
| overlay_popup_confirm_default_long.csb | 25 | overlay_popup_confirm_download.csb | 27 |
| overlay_popup_server_select.csb | 18 | overlay_popup_sound_select.csb | 19 |
| overlay_popup_xcent_notice.csb | 15 | scene_title.csb | 60 |
| scene_title_pre.csb | 129 | title.csb | 30 |
| title_rating.csb | 10 | title_server_down.csb | 47 |

`layouts.json` บันทึก source path/hash, hierarchy, table/vtable offsets, local
position, size, scale, anchor, visibility, touchEnabled, strings และ texture refs
สร้างด้วย [decode_csb.py](../../tools/decode_csb.py) โดยใช้
[official generated header](https://raw.githubusercontent.com/cocos2d/cocos2d-x/e4b6a5ef8fcdc99a7ebea606312b67fe4c534b9f/cocos/editor-support/cocostudio/CSParseBinary_generated.h)
ที่ pinned commit `e4b6a5ef8fcdc99a7ebea606312b67fe4c534b9f`
(SHA-256 `9512c62f41f701cd32a530765c34c76c63d67f2263d07fe553958fd2522fd80f`)
และ NodeReader ที่ commit เดียวกัน ทุก scene ระบุ serialized version `2.1.0.0`
ซึ่งเป็นข้อมูล serialization ไม่ใช่เวอร์ชัน engine ที่สรุปได้

## UX ที่อ่านได้และข้ออนุมาน

ตัวอย่าง observed ใน `scene_title_pre.csb`:

- `btn_start`: position (640,360), size 2000×1000, visible=1, touchEnabled=1
- `progress_total`: LoadingBar position (640,49), size 1220×6
- `txt_percent`, `txt_message`, `txt_update_status`: แยกสถานะโหลดเป็นคนละ node
- `btn_login`: visible=0 ใน serialized state; ปุ่ม login แบบอื่นมีใน hierarchy

ขนาด hit area ของ start ใหญ่กว่า canvas เป็นหลักฐานที่รองรับข้ออนุมานว่าอาจให้
แตะพื้นที่กว้างเพื่อเริ่มเกม แต่ไม่พิสูจน์ callback หรือ behavior ตอนรัน
เปอร์เซ็นต์/จำนวนดาวน์โหลดใน strings อาจเป็นค่าตัวอย่างใน editor ไม่ใช่สถานะจริง
`overlay_popup_confirm_download.csb` แยก title, ข้อความหลัก, คำเตือนเครือข่าย,
ขนาด download และ confirm/cancel; server/sound selection มี ScrollView และ confirm

wireframe แสดง projection ของ serialized hierarchy เท่านั้น มีตัวเลือกดู hidden
nodes และ branch เพื่อแยก state ที่ซ้อนกัน ข้อมูล regional login variants, runtime
constraints, clipping, project nodes, animation และ resource sizing อาจเปลี่ยนภาพจริง
เครื่องมือไม่ประกอบเกมทั้งหมดหรืออ้างว่ารู้เหตุผลของ developer โดยตรง

สิ่งที่นำมาออกแบบใหม่ได้: แสดงสถานะการกระทำกับผลลัพธ์แยกกัน, ให้รายการตัวเลือก
มีจุดยืนยันชัดเจน, แยก modal component เพื่อใช้ซ้ำ ส่วน battle HUD, card mechanics,
sanity, rewards และ lore ในต้นแบบยังเป็น `original-design` ไม่ใช่กฎที่ถอดจากแพ็ก

## Texture และ animation

[decode_texture.py](../../tools/decode_texture.py) ตรวจ SCT1/SCT2/SCSP ด้วย stdlib
และ bounded LZ4 decoder SCT1 สองไฟล์ถอด RGB565 little-endian plane + alpha A8
เป็น PNG ได้จริง และตรวจภาพแล้ว:

- `assets/pre/effect/lobby_bg.sct`: 2031×1617, เป็น atlas ของหลาย region
- `assets/pre/effect/logo_yuna.sct`: 1873×426, เป็น atlas logo YUNA ENGINE

ภาพ atlas ยังต้องอาศัย geometry/skeleton/layout เพื่อประกอบเป็น scene ไม่ใช่
screenshot เต็มหน้าจอ SCT2 **102 files ถอด ASTC 4×4 (format 40)** และ
**4 files ถอด ASTC 8×8 (format 47)** สำเร็จด้วย `texture2ddecoder==1.0.6`
ตรวจ source hash, CRC, block lengths, dimensions, PNG chunk CRC และ pixel
roundtrip ครบ 106 files; ตรวจภาพตัวอย่างแล้ว รวมพื้นหลัง title 1604×852
จำนวน error-color magenta pixels เป็นศูนย์ เป็นเพียงหนึ่ง check ไม่พิสูจน์ทุก pixel

การเดา ETC2 RGBA8 จาก block size ครั้งแรกถูกแทนที่ด้วยผลตรวจจริง: พบ ASTC
void-extent blocks และ ASTC decoder ให้ภาพสะอาด ในขณะที่ ETC2 decode มี artifacts
จึงไม่ใช้ขนาด payload อย่างเดียวตัดสิน codec ตัวเลข format mapping นี้ตรวจจาก
แพ็กที่ได้รับ ไม่รับประกัน SCT ทุก revision บางไฟล์มี secondary dimensions
เล็กกว่า encoded dimensions; ไม่ crop/pad เพื่อเดาผลการ render

ตัวอ่าน stdlib ตรวจ container ได้ ส่วน `--decode-astc` เป็นตัวเลือกที่ต้องติดตั้ง
decoder เพิ่ม ผลภายนอกคืน BGRA แล้วแปลงเป็น RGBA ก่อนเขียน PNG ไม่มีการรันเกม
Linux wheel ที่ใช้มี SHA-256
`09b98ea4d66e21aca42558727dc609a8a952e2b6eb09d0ee8e0e52ba14b7848a`
ซึ่งตรวจตรงกับ [PyPI release metadata](https://pypi.org/pypi/texture2ddecoder/1.0.6/json)
เก็บ decoder/output ใน `.local/` ไม่เปลี่ยน dependencies ของเกม
ส่วน SCSP มี version/string sections ที่ตรวจได้ แต่ schema ของ transforms,
mesh, skin, timelines ยังไม่ทราบ

## Provenance และการทำซ้ำ

- ZIP ที่รับจริง: 3,577,579 bytes
- ZIP SHA-256: `f1bf85773b6ceb819369580e82a252c43f15e1b666e473ddaa9ebe0f9857f5f9`
- Source XAPK SHA ตาม index/report: `b95e115282272289c73abc1569b81a5bbf62b1f4f638c15d76cc2c7b2f120be0`
- Main APK SHA ตาม index/report: `a33b5ff9c3b9df1a826033625b7263eef946960218bcd1f710cf03b82ca1f64a`
- Report SHA ที่ตรวจจาก attachment: `d5a6c95d3384c6646767ef8576b425cb926e421b4c5b4fd97ce1874db9fc5675`
- `scene_title_pre.csb` original SHA: `0692ab3f1f271d6c01329ad8b4d0b1ca1fe9bd750afbe15af23d1cc66b8bc7fd`
- `overlay_popup_confirm_download.csb` original SHA: `035d5f4f363b1ec283e7122b585883aa69bda739234f28027166bb5e4f1abbd5`

ข้อความบางไฟล์ถูก redact ใน pack; original hash และ stored hash อาจต่างกัน
binary scenes/textures ไม่ถูกแปลง และ hash ตรงต้นฉบับตาม index
เก็บไฟล์แนบ, decoded JSON, PNG และ wireframe ใน `.local/` ไม่อยู่ใน Git และ
ไม่ import art เหล่านี้เข้า `src/` อ่าน [วิธีทำซ้ำบน Windows](../BOOTSTRAP_REPLAY.md)

## ข้อมูลที่ยังขาดสำหรับเกมต่อสู้

แพ็กนี้ไม่มี decoded battle scene, card definitions, combat rules หรือ canon LoTM/CoI
inventory ระบุ sdata ทั้งหมด 15 files รวม 52,360,002 bytes แต่ได้รับเพียง 7 files
ขนาดเล็ก ขั้นวิจัยถัดไปคือระบุ container/schema ของ sdata และ init.jbin ก่อนขอข้อมูล
เพิ่มแบบมีเป้าหมาย ไม่สรุปว่าเนื้อหาที่ขาดต้องอยู่ใน blobs หรือ server แน่นอน
ยังไม่สามารถสร้างหน้าจอเกมต่อสู้ที่ตรงต้นฉบับจากหลักฐานชุดนี้
