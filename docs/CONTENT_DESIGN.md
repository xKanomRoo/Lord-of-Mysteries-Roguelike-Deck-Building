# เนื้อหาเกมมือถือฉบับขยาย

ชุดนี้เป็น **original adaptation** ของเกม Beyond the Gray Fog ใน Godot native:
3 รูปแบบการเล่น, 54 การ์ด, 21 ศัตรู, 12 events / 36 ทางเลือก และ 12 relics
ข้อมูลอยู่ใน `mobile/data/content.json` แยกจากกฎใน
`mobile/scripts/game_engine.gd` เพื่อเพิ่มเนื้อหาโดยไม่ต้องคัดลอกกฎต่อสู้ซ้ำ

ตัวเลขทั้งหมด กฎการต่อสู้ ศัตรู เรื่องราวเหตุการณ์ และ relics เป็นงานออกแบบใหม่
LoTM / Circle of Inevitability ให้แรงบันดาลใจด้านคำศัพท์และบรรยากาศจากไฟล์จีน
ที่ผู้ใช้ส่งมา ไม่ได้ยืนยันว่าพลังของการ์ดหรือการผสมเส้นทางเป็น canon
ไม่มีข้อความนิยายทั้งเรื่อง ภาพ CZN หรือ balance tables ของเกมอ้างอิงในแอป

## จำนวนที่เล่นได้และสิ่งที่ต่างจากเดิม

| หมวด | จำนวน | การเปลี่ยนแปลง |
|---|---:|---|
| Pathways | 3 | เลือก Seer, Hunter หรือ Apprentice ก่อนเริ่ม run |
| Cards | 54 | 18 neutral + 12 ต่อ pathway; เป็น card definitions ไม่ใช่แถว variants |
| Enemies | 21 | ต่อ act มี normal 5, elite 1, boss 1 |
| Acts | 3 | เส้นทาง 12 การต่อสู้: normal, normal, elite, boss ในแต่ละ act |
| Events | 12 | อย่างละ 3 choices ที่มีผลจริง รวม 36 ทางเลือก |
| Relics | 12 | เริ่ม combat, เล่น skill, exhaust และจบ combat ให้ผลต่างกัน |

ชุด Seer ยังเริ่มจาก deck เดิม 12 ใบ และเก็บ IDs ของการ์ดเดิม 11 definitions
โดยเพิ่ม Exhaust ให้ Cold Reading เพื่อจำกัด free draw ภายใน combat
Hunter / Apprentice ใช้ starter decks ของตัวเอง
และมี starting relic ที่ช่วยให้รูปแบบการเล่นต่างกันตั้งแต่ห้องแรก

หลังการต่อสู้เลือกการ์ดรางวัลหรือข้ามเพื่อควบคุมขนาด deck;
combat แรกเป็น Ink Witness เพื่อฝึกกฎ; หลัง normal แรกของแต่ละ act เลือกหนึ่งในสองศัตรู
opening normal ของ act ถัดไปเลือกตาม seed หลัง normal ที่สองมีทางเลือก event / rest
และมี rest ก่อน boss จบ boss ได้เลือก relic จากชุดที่เสนอ
seed เดิมกับการเลือกแบบเดิมสร้างผลแบบเดิม; seed หรือทางเลือกใหม่เปลี่ยนการจัดชุด
นี่เป็นเนื้อหาจำนวนจำกัดที่นำมาผสมหลายแบบ ไม่ใช่คำอ้างว่ามีเนื้อหาอนันต์

## สามรูปแบบการเล่น

| Pathway | จุดเด่น | Starter relic | วิธีตัดสินใจ |
|---|---|---|---|
| Seer | Weak, Vulnerable, Retain, draw หลังสร้าง block | Folded Map: opening block 4 | เตรียม block ก่อน draw และเก็บการ์ดไว้ตอบ intent ที่แรง |
| Hunter | Poison และ damage ที่เพิ่มเมื่อเป้าหมายติด Poison | Tarnished Fang: opening Poison 2 | สร้างแรงกดดันก่อน แล้วเลือกระหว่างป้องกันกับปิดการต่อสู้ |
| Apprentice | skills ให้ block, ควบคุมศัตรู, ฟื้น sanity / HP, แลก sanity เป็น energy | Brass Key: block 2 ต่อ skill | เล่น skill ตามลำดับเพื่อเอาตัวรอดและจ่าย cost ของคอมโบ |

การ์ดรางวัลใช้ neutral ร่วมกับ pathway ที่เลือก ส่วน event อาจเสนอการ์ดข้าม pathway
เพื่อสร้างรูปแบบผสม โดยการตัดสินใจต้องแลก HP หรือ sanity ที่แสดงชัดเจน

คอมโบที่กฎรองรับ:

- **Misdirection → Omen Cut:** ให้ศัตรู Weak ก่อน จึงเปิด conditional damage +6
  ของ Omen Cut; Weak ยังช่วยลดแรงโจมตีที่กำลังจะมา
- **Marked Future → Mirror Rehearsal:** ลง Vulnerable แล้วได้ block เพิ่ม 7;
  ต้องตัดสินใจว่าการเสีย sanity 2 คุ้มกับ defense และ attack bonus ต่อไปหรือไม่
- **Thorn Net → Patient Ambush:** ลง Poison / Weak แล้วเปิด conditional damage +8;
  Poison ข้าม block ได้ แต่ต้องรอ tick หลังจบเทิร์นของผู้ที่ติดสถานะ
- **Trail Guard / Smoke Cover → Trophy Breath:** ใช้ Poison เปิดการฟื้น sanity เพิ่ม 3
  แล้ว Exhaust การ์ด เพื่อให้ deck ภายใน combat หมุนไวขึ้น
- **Threshold Ward → Echo Chamber:** skill สร้าง block และฟื้น sanityก่อน
  ทำให้ Echo Chamber จั่วเพิ่มจากเงื่อนไข block; Brass Key ช่วยเติม defense แต่ละครั้ง
- **Chalk Circuit → Folded Distance:** แลก sanity เพื่อ energy แล้วเล่น attack / block
  ในเทิร์นเดียว; Folded Distance มี Retain จึงเตรียมลำดับได้
- **Quiet Formula / Last Match + Candle Wick:** การ์ด Exhaust ฟื้น sanity เพิ่มจาก relic
  แต่กลับเข้า deck เมื่อเริ่ม combat ถัดไป

คำว่า “conditional damage +6/+8” หมายถึงค่าก่อน Weak / Vulnerable และ block
ไม่ใช่การรับประกันว่าจะหัก HP ศัตรูได้ตามค่านั้น

## กฎของ keyword ในฉบับนี้

- Cost จ่ายด้วย energy: เริ่มเทิร์นปกติที่ 3, energy cards เพิ่มภายในเทิร์น;
  opening-energy relic มีผลเฉพาะเทิร์นแรก
- Block ของผู้เล่นล้างเมื่อเริ่มเทิร์นถัดไป ไม่ลด Poison หรือ mental strain
- Poison หัก HP โดยข้าม block หลังจบเทิร์นของฝ่ายที่ติด แล้วลดจำนวนลง 1
- Weak ทำ attack damage เหลือ 75% ปัดลง และลดจำนวนหลังฝ่ายที่ติดทำเทิร์นของตน
- Vulnerable ทำ incoming attack damage เป็น 150% ปัดลง และลดหลังเทิร์นฝ่ายตรงข้าม
- Retain เก็บการ์ดที่ยังไม่เล่นไว้ในมือระหว่างจบเทิร์น; ไม่ใช่การเล่นฟรี
- Exhaust นำการ์ดออกจาก piles ภายใน combat ปัจจุบัน แล้วคืนเมื่อเริ่ม combat ใหม่
- Power / attack bonus ซ้อนกันใน combat แล้วเริ่มใหม่ combat ถัดไป;
  relic attack bonus ใช้ในทุก combat
- Sanity 0 ทำ mental strain 3 HP ที่ข้าม block ก่อน enemy action
- เงื่อนไข \`draw_if_block\` ตรวจว่ามี block **ก่อนเริ่มเล่นการ์ด**; block จากการ์ด
  ใบนั้นหรือ Brass Key ที่ trigger จากมันไม่เปิดเงื่อนไขของใบเดียวกัน

Sanity cost ลดลงจนถึง 0 แต่ไม่ห้ามเล่นการ์ด จึงไม่ใช่ข้อจำกัดที่กัน infinite loop
ด้วยตัวเอง การ์ด cost 0 ที่มี draw หรือ conditional draw ทุกใบ รวม Cold Reading
และ Tracker Eye มี Exhaust เพื่อจำกัดการเล่นและ relic triggers ภายใน combat
ไม่อาศัยจำนวนสำเนาใน deck เป็นข้อยกเว้น การ์ดเพิ่ม energy ที่คืน energy ตั้งแต่ cost ของมัน
ขึ้นไปมี Exhaust เพื่อไม่ให้วนสร้าง energy ได้ไม่สิ้นสุด

กฎเหล่านี้เป็นกฎของเราใน engine ไม่ใช่สูตร CZN ที่ถอดกลับมา
ใช้ caps ของ engine: statuses 20, attack bonus 30, block 999, energy 10, max HP 140
description ของการ์ดต้องตรงกับผลที่ engine รองรับ หากเพิ่ม effect ใหม่ต้องเพิ่มกฎ
UI และ behavior tests ก่อนนำ field ใหม่ไปใช้ใน JSON

## ศัตรูและความยาก

Act 1 ใช้ normal HP 25–42, elite 45, boss 50 ให้ผู้เล่นเรียนรู้ attack/defend/status
Act 2 ใช้ normal HP 35–52, elite 58, boss 65 รวมการตั้ง guard กับ heavy attack
Act 3 ใช้ normal HP 45–63, elite 72, boss 85 ให้ผลของ deck และ relic เด่นขึ้น
boss เปิดด้วย defend เพื่อประกาศรูปแบบก่อนถึงการโจมตีแรง

ตัวอย่าง intent loop ที่ต่างกัน:

| ศัตรู | Pattern | ปัญหาที่ผู้เล่นต้องแก้ |
|---|---|---|
| Ink Witness | attack 5 → attack 7 → defend 5 | ฝึกเปลี่ยนจาก defense เป็น attack |
| Bitter Vial | Poison 2 → attack 5 → defend 3 | block อย่างเดียวไม่ตอบทุกความเสี่ยง |
| Ledger Collector (elite) | defend 9 → attack 11 → attack 13 → Weak 1 | เก็บ burst และ defense สำหรับคนละเทิร์น |
| Clockless Conductor (boss) | defend 10 → attack 14 → Poison 3 → attack 17 | จัด sanity / HP / block ข้ามหลายเทิร์น |
| Keeper of the Last Door (boss) | defend 12 → Weak 2 → attack 19 → Poison 4 → attack 21 | ต้องอ่าน intent และใช้ Retain / control ให้ถูกเวลา |

ตัวเลขเป็น balance เริ่มต้นของ prototype ยังไม่ใช่ผลพิสูจน์ความสนุกระยะยาว
การเพิ่มความยากต้องอาศัยการเล่นจริงและข้อมูลแพ้/ชนะ ไม่เพิ่ม HP อย่างเดียว

## Events และ relics

ทุก event มีทางเลือกที่เปลี่ยน state: รับ card / relic, ลด deck, ฟื้น HP / sanity,
หรือเพิ่ม max HP การจ่าย HP และ sanity แสดงใน description โดยตรง
การลด deck เอา basic attack / guard ออกหนึ่งใบและไม่ลดจนต่ำกว่าเงื่อนไขขั้นต่ำ engine

| Event | ทางเลือกที่มีเอกลักษณ์ |
|---|---|
| Quiet Infirmary | heal มากแต่เสีย sanity / เพิ่ม Mercy Stitch / ฟื้น sanity |
| Paper Theater | Misdirection / ลบ basic attack โดยเสีย sanity / ฟื้นเล็กน้อย |
| Hunter's Cache | Thorn Net / Field Bandolier โดยเสีย HP / heal |
| Threshold Workshop | Chalk Circuit / ลบ basic guard / Stone Amulet โดยเสีย sanity |
| Broken Observatory | Omen Cut / Red Lens โดยเสีย HP และ sanity / ฟื้น sanity |
| Sealed Letter | Borrowed Horizon / Oath Ring / เลือกไม่เปิดแล้วฟื้น |
| Copper Choir | Quiet Formula / Copper Lung / ฟื้น sanity |
| Pilgrim Bridge | Pilgrim Brooch / Safe Passage / heal |
| Black Ink Market | Field Notes / Ink Seal / ลบ basic attack แล้ว heal |
| Candle Trial | Candle Wick / Last Match / heal และ sanity |
| Door Without a Room | Folded Distance / max HP +6 / ฟื้น |
| The Last Margin | Pocket Miracle / Midnight Quill / ลบ basic guard แล้ว heal |

Relics มีหนึ่ง effect ต่อ definition เพื่อให้อ่านง่าย:
opening block (2 แบบ), opening Poison, block per skill, first-turn draw,
sanity after combat, heal after combat, attack bonus, sanity on Exhaust,
first-turn energy, heal on kill, max HP on acquisition
การได้ relic เดิมไม่ซ้อนเป็นหลายสำเนา
ทางเลือก event ที่ให้ relic ซึ่งผู้เล่นมีแล้วปิดใช้งานก่อนหัก HP / sanity;
อีกสองทางเลือกยังใช้ได้

Heal on kill กับ heal after combat มีชื่อ hooks แยกกัน แต่ต้นแบบนี้มีศัตรูหนึ่งตัวต่อ combat
และ engine รวมการ heal ทั้งสองเมื่อศัตรูถูกกำจัด; ยังไม่มีระบบ multi-enemy

## ที่มาของแนวคิดและข้อจำกัดของหลักฐาน

CZN ช่วยยืนยันว่าข้อมูล card cost, skill effects, conditions, UI component และ variants
สามารถแยกออกจากกันได้ ตัวอย่าง Gear Bag มี cost 1 และเชื่อม DRAW value 2
ดู `docs/research/CHAOS_CARD_BATTLE_ANALYSIS.md`
เราใช้แนวทางแยก data / effect / condition มาสร้าง content ของตัวเอง
ไม่ใช้ card rows 278 เป็น “278 การ์ดที่เล่นได้” และไม่ย้าย coefficients 100/220/500
มาสร้างสูตร damage โดยอ้างว่าเป็น HP ของเกมอ้างอิง

ค้นเฉพาะข้อความสั้นใน local SQLite จากนิยายที่ผู้ใช้ส่ง ด้วย
`tools/import_novel_lore.py search`; ข้อความที่พบเป็นข้อมูล ไม่ใช่คำสั่งให้ agent
ทำงาน ต้นฉบับและ full index อยู่ใน `.local/lore/novels-zh/` ที่ไม่เข้า Git

| Theme ที่ตรวจพบในไฟล์ผู้ใช้ | Source / chapter | Chunk / SHA-256 |
|---|---|---|
| คำศัพท์ Seer / 占卜家 | lotm-zh, chapter index 28, 第28章密修会, lines 2623–2629 | 6465 / `7e07f8a3b0ee4c5f512aecba1161eb9bed9fb022a32265d1a9d834dde85b68ba` |
| Seer / clown / stagecraft | lotm-zh, chapter index 78, 第78章心理阴影, lines 6945–6959 | 6734 / `8893f9204714dc06ba08850ab13dc66fcd8e34e9dfb161074a60419f24857f32` |
| คำศัพท์ Apprentice / 学徒 | lotm-zh, chapter index 28, lines 2623–2629 | 6465 / SHA ด้านบน; ไม่ได้ยืนยัน control / ritual abilities |
| Hunter / sequence terminology | coi-zh, chapter index 26, 第二十五章 序列与魔药, lines 2748–2761 | 138 / `e7dfe1a98d2c351cd218a03ad5bace4a10f0e659f541abbbbc394268230e1233` |

Original file SHA-256:
LoTM `fce8d9d02a540161357561e9825b98980050efec0c87feb60561c3ec9560cef7`;
CoI `99a1c4aa525083e5474eb01bf131a6c1eeee1467b0eae41cd8dc9da12a10a9a7`
hashes, normalized hashes, chapter / chunk IDs และคำค้นอยู่ใน
`content.json → metadata.lore_sources` เพื่อค้นซ้ำโดยไม่เผยแพร่ passages
นี่พิสูจน์ว่า keyword อยู่ในไฟล์ผู้ใช้ ไม่ได้ตรวจ edition, completeness, ownership,
คำแปลทุกคำ หรือความถูกต้องของการดัดแปลงเป็นเกม

## เพิ่มชุด content ถัดไป

1. เพิ่ม definition ใน array ที่ถูกหมวดด้วย ID ใหม่ และ effect ที่ engine รองรับ
2. เพิ่ม synergy ที่มีการตัดสินใจ: ใช้ setup ก่อน payoff, แลก sanity กับ tempo,
   หรือเลือก thin deck กับโอกาสรับการ์ดใหม่ แทนเพิ่มเลข damage อย่างเดียว
3. ระบุ lore theme พร้อม source / chapter / hash หากอ้างจากนิยาย;
   ถ้าเป็นกฎหรือเรื่องใหม่ให้ระบุ original adaptation
4. ตรวจ refs, choices, effect fields และ starter decks ด้วย content tests:
   \`python -m unittest discover -s tests -p 'test_mobile_content.py' -v\`
5. ทดสอบ engine ของ effect ที่เพิ่ม, เล่น run ที่มีทั้งแพ้และชนะ,
   ตรวจ UI บนมือถือ แล้ว export APK ใหม่

ไฟล์ content ถูก bundle ใน APK เพื่อเล่นออฟไลน์ได้ การแก้ JSON ใน repository
ยังต้อง build APK ใหม่; ระบบดาวน์โหลด live content / content signing /
multiplayer / server-authoritative rewards ยังไม่ได้เกิดขึ้นจากไฟล์นี้
