# ผลอ่านข้อมูลการ์ดและ UI จาก range ZIP

ได้รับ `chaos-card-battle-ranges.zip` แล้ว อ่านครบ 18 resources ที่เลือกจาก
manifest เดิม: DB 13 และ CSB 5 ตรวจ CRC/SHA, rows/physical segments,
bounded Zstd และ decoded FHSH ผ่านทั้งหมด โดยไม่เล่นเกมหรือ execute game code
ข้อมูลการ์ดเชื่อมกับฐานข้อความอังกฤษได้ และสร้างผัง UI แบบออฟไลน์ได้
ผลนี้เป็นชุดข้อมูลที่เลือกมา ไม่ใช่ complete game catalog หรือ recovered runtime

## Source และการตรวจ

| Source | Bytes | SHA-256 |
| --- | ---: | --- |
| Range ZIP | 8,153,934 | `a9c3e7951c9c3c24694e44aca09585a304ad079e3f3b3e8d052d9215e0acf18d` |
| Manifest ใน ZIP | 7,506,387 | `45a0093589720c98ac0e9b91bd711f26ce34b74d0d5db4fe21f21aa141edce15` |
| Tracked selection plan | — | `41469430707c308be5b662a0a520d1b453446239cd5a737e50fde658a6a00003` |

ZIP มี 20 members: index, manifest และ ordinal payloads 18 รายการ
stored payload รวม 622,458 bytes; หลัง Zstd รวม 1,342,080 bytes
`tools/read_ssra_ranges.py` ใช้ tracked plan และ manifest pin เพื่อคำนวณ rows,
chunk segments และ aligned read selectors ใหม่ ไม่เชื่อ scope/probe assertions
จากไฟล์แนบ และเขียนเฉพาะ ordinal decoded files กับ sanitized index
ข้อมูลใน private stage ผ่านการตรวจทั้งหมดก่อน publish พร้อม rollback เมื่อย้ายล้มเหลว

index ประกาศ reader `system-toybox-dd` และได้รับ bytes ที่ตรวจผ่านจริงแล้ว
จึงผ่านอุปสรรคการดึงข้อมูลชุดนี้ ภาพก่อนหน้ายืนยันว่า bare `dd` ตอบ
`no such tool`; helper จึงตรวจและเลือก `/system/bin/toybox dd`
metadata ของ probes ไม่ใช่ independent proof ว่าคำสั่งฝั่ง emulator ทำอะไรทั้งหมด
ZIP ไม่มี surrounding aligned bytes หรือ full chunks จึงตรวจ span/whole-chunk
hash ซ้ำไม่ได้ และยังไม่ยืนยัน CDN authenticity

## Database format และ rows ที่อ่านได้

DB เล็กห้ารายการ (`card.db`, `skill_eff.db`, `cs.db`, `cond_card.db`,
`battle_system_effect.db`) เป็น `YUNADBSET` filter lists ที่อ้าง shards
ไม่ใช่ SQLite schema ส่วนอีกแปดรายการมี local file wrapper แบบเดียวกับ text DB
ใช้ exact source-pinned `libssr.so` SHA `a790283a…` อ่าน table เป็นข้อมูล
แล้ว transform ด้วย file-size seed ภายในเครื่อง ไม่เผยแพร่ table หรือ execute library
ดู [native/text lineage](CHAOS_RUNTIME_ANALYSIS.md)

หลัง transform เป็น PLPcK ที่มี `\tcols`, `\trows`, sequential column keys,
row indexes และ NUL-separated UTF-8 string fields `tools/read_card_database.py`
ตรวจ bucket hash, pointer bounds/cycles, metadata, row IDs, field offsets
และ complete nonoverlapping byte coverage โดยรักษา values เป็น serialized strings
ไม่ eval expressions หรือแปลง enum เป็น behavior ที่ยังไม่พิสูจน์

ทั้งแปดไฟล์มี primary header counter 0 และ appended header 38 bytes ซึ่ง
เหมือน header แรกทุก byte ยกเว้น updated counter ที่ตรงกับ linked record count
parser ตรวจ trailer นี้ทุก byte; เหตุผลที่ writer ต่อ header ยังไม่ยืนยัน
จึงไม่เรียกมัน recovery journal และไม่ได้ผ่อน generic PLPcK/text readers เดิม

| Resource / ordinal | Columns | Rows | Linked records |
| --- | ---: | ---: | ---: |
| `db/card(public)@card.db` / 03 | 42 | 54 | 152 |
| `db/card(ikarus)@card.db` / 04 | 42 | 224 | 492 |
| `db/card(public)@skill_eff.db` / 05 | 77 | 100 | 279 |
| `db/card(ikarus)@skill_eff.db` / 06 | 77 | 507 | 1,093 |
| `db/cs(card1)@cs.db` / 07 | 28 | 435 | 900 |
| `db/cs(card1)@skill_eff.db` / 08 | 77 | 532 | 1,143 |
| `db/condition@cond_card.db` / 10 | 23 | 754 | 1,533 |
| `db/battle_system_effect@battle_system_effect.db` / 12 | 16 | 85 | 188 |

รวม 2,691 rows / 5,780 linked records มี card rows 278 รวม variants
ไม่ใช่จำนวน playable cards ทั้งเกม effect links ที่ระบุใน card shards เชื่อมได้
89/89 สำหรับ public และ 495/495 สำหรับ ikarus กับ effect shard ที่สอดคล้องกัน
public cards ทั้ง 54 มี name/description keys ใน English DB; ikarus มี name keys
84 และ description keys 201 จาก 224 rows จึงไม่เติมชื่อ variant ที่ไม่พบขึ้นเอง
พบ serialized `cost=-1` สอง rows แต่ยังไม่ตีความว่าเป็นการคืนพลังงาน

## ตัวอย่างที่เชื่อมข้อมูลจริง

| Card ID / English name | Serialized cost | Linked effect fields |
| --- | ---: | --- |
| `card_ne_00026` / Gear Bag | 1 | `SKILL_EFF_CARD_DRAW`, `eff_value=2` |
| `card_ne_00010` / Attack! | 0 | `SKILL_EFF_CARD_DRAW`, value 1; filter `[CARD_ATK]`, deck → hand |
| `c_1040_srt1` / Launcher | 1 | `SKILL_EFF_DMG`, value 100 |
| `c_1040_srt2` / Charge Launcher | 2 | `SKILL_EFF_DMG`, value 220 |
| `c_1040_uni1_rsp3` / variant ไม่มี name key โดยตรง | 3 | DMG value 500; conditional `SKILL_EFF_CS_SET_ADD`, value 1 |

Gear Bag เชื่อม `link_skill_eff_id=[card_ne_00026_00]` ไป effect value 2 และ
English key `card@desc@card_ne_00026` ที่มี `$Draw$ #result_ev_0#`
จึงได้ค่าตารางสำหรับ placeholder นี้ พร้อม `VALUE_COMMON`/active operation
การเติมข้อความ preview ยังต้องใช้ formatter ที่ตรง markup/เงื่อนไขของ engine

ตัวอย่าง offsets สำหรับตรวจซ้ำ (byte positions หลัง local wrapper transform):

- public card DB SHA `94dd31c1…`: Gear Bag `cost` @ 12,769
- public skill-effect DB SHA `dcd4e718…`: effect value @ 31,245
- English PLPcK SHA `f9792f1c…`: description record @ 11,295,775
- ikarus card DB SHA `a83e3e84…`: Launcher `cost` @ 4,181
- ikarus effect DB SHA `f273e24e…`: Launcher effect value @ 8,779

ค่าดาเมจ 100/220/500 เป็น serialized scalars/coefficients ยังไม่ใช่หลักฐาน
flat HP damage: stat scaling, mitigation, runtime modifiers, target attributes,
rounding และ server behavior ยังไม่ได้ execute หรือพิสูจน์ครบ
variant ตัวอย่างเชื่อม condition `cd_card3_under_next_turn` กับ CS `cs00_0053`
เป็นหลักฐานความสัมพันธ์ของข้อมูล ไม่ใช่ runtime trace ของ trigger

## UI ที่อ่านจากไฟล์จริง

| Resource | Decoded bytes | Nodes | Saved root size |
| --- | ---: | ---: | --- |
| `wnd/scene_battle_field.csb` | 19,356 | 65 | 1280 × 720 |
| `wnd/game_hud_hand.csb` | 35,500 | 148 | 1280 × 720 |
| `ui/game_hud_handpiles.csb` | 74,464 | 252 | 960 × 220 |
| `wnd/game_card_select_hand.csb` | 10,008 | 34 | 1280 × 720 |
| `wnd/card.csb` | 55,956 | 184 | 0 × 0 |

รวม 683 hierarchy nodes, 682 decoded WidgetOptions และ unsupported TileSprite 1
ตาม documented subset เดิม serialized label `2.1.0.0` ไม่ใช่ complete engine version
ทุก node มี source hash และ FlatBuffer table offsets สำหรับ inspect

hand scene เก็บ branches 1–13 และจำนวน anchors ตรงกับชื่อ branch
รวม 91 anchors ใน alternatives; ยังไม่ยืนยัน hand limit หรือว่าแสดงพร้อมกัน
branch มือห้าใบมี x=360/500/640/780/920 และ y=17/29/33/29/17, scale ประมาณ 0.32
scene มี nonzero rotationSkew 84 nodes ผังรักษาค่าเป็น evidence แต่ projection
ยังไม่ใช้ rotation เหล่านั้น และไม่ expand ProjectNode ไปประกอบ nested CSB

card component มี energy container ที่ local (-145,267), title mask 304 × 50,
selection outline 486 × 700 และ touch button 440 × 680 ค่าตำแหน่งเหล่านี้เป็น
serialized local geometry; parent transforms และ runtime layout เปลี่ยนหน้าจอได้
root 0 × 0 เป็นค่าจริง การแสดง component ใช้ inferred viewport จาก child bounds
และระบุแยกจาก source; original root ยัง inspect ได้ ไม่เปลี่ยน validator เดิม

field scene มี minimap, scroll/zoom และ disaster-information branch จึงยังไม่ใช่
หลักฐานว่า complete combat HUD อยู่ที่ไฟล์นี้ ไม่พบ explicit AP/end-turn nodes
ใน selected five-scene hierarchy และยังมี referenced CSBs ที่ไม่ได้รับ
ตัวเลข sample `2`, `5 / 5`, ข้อความ placeholder ใน layout และ card groups สิบชุด
ไม่ถูกใช้เป็นกฎ balance, selection count หรือ draw/discard/exhaust semantics

wireframes ใช้กล่องและข้อความของเครื่องมือ ไม่ใช้ reference art/fonts
Chromium จริงเปิดครบห้าฉาก, เปลี่ยน branch, inspect node, toggle hidden/container
และตรวจ viewport bounds ได้ ไม่มี uncaught/console errors ใน run นี้
ภาพและ diagram เป็น approximate serialized projection; animation, clipping,
custom widgets, assets และ state selection ตอนเล่นจริงยังไม่ยืนยัน

## Replay และสิ่งที่จะนำไปออกแบบใหม่

เริ่มจาก repository ใช้ output directory ใหม่เพื่อรักษาผลเดิม:

```bash
.local/runtime-venv/bin/python tools/read_ssra_ranges.py \
  /path/to/chaos-card-battle-ranges.zip --output .local/card-battle-replay/resources

python tools/read_card_database.py \
  --input .local/card-battle-replay/resources/files/03.bin \
  --expected-sha256 230285d187c46d557a298f08043204b0f0d8f1ca848c8c908367fc4cd16d0df8 \
  --native-library /path/to/source-pinned/libssr.so \
  --output .local/card-battle-replay/public-cards

.local/runtime-venv/bin/python tools/render_card_battle.py \
  /path/to/chaos-card-battle-ranges.zip --output .local/card-battle-replay/wireframes
```

เปิด `wireframes/index.html` แบบออฟไลน์เพื่อเลือกฉาก/branch และ inspect node
เครื่องมือตรวจ ZIP ใหม่ใน temporary stage แล้วเก็บเฉพาะ HTML/SVG,
`layouts.json`, `source-receipt.json` และ `wireframe-index.json` ไม่เก็บ decoded DBs
ใน directory แผนผัง; root และค่าดิบเดิมอยู่ใน layout evidence

DB data ordinals คือ 03/04/05/06/07/08/10/12 ส่วนห้า YUNADBSET lists ไม่ใช่ inputs
ของ DB-row parser ทุกขั้นอ่านข้อมูลเป็น inert bytes และเก็บ full tables/text/artifacts
ไว้ใน `.local/` เท่านั้น ไม่ commit หรือ import into product

หลักการสำหรับต้นแบบ LoTM/CoI ของเราเป็น original design choices: แยก numerical
effects/conditions ออกจาก localization, ให้ description และ preview ใช้ parameter
source เดียวกัน, แยก card component จาก hand placement, และตรวจ variant links
ก่อนเผยแพร่ balance ข้อมูลโครงสร้างรองรับการแยกเหล่านี้ แต่ไม่พิสูจน์เหตุผลในใจ
developer หรือ canon ของนิยาย เรายังต้องเขียน rules/art/text ของเราและอ้างแหล่ง lore
ที่ตรวจได้ การมี parsers/evidence ใน repository ช่วยให้ Codex ใช้ context ต่อได้
โดยไม่ใช่การ fine-tune น้ำหนักโมเดล
