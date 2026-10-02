# สองไฟล์นิยายภาษาจีน: ใบรับและการค้นออฟไลน์

วันที่ 3 ตุลาคม 2026 (Asia/Bangkok) ผู้ใช้แนบข้อความสองไฟล์และระบุชื่อเรื่อง
การตรวจนี้อ่านไฟล์เป็นข้อมูล ไม่เปิด URL ไม่รันคำสั่งจากนิยาย ไม่ฝึก model weights
และไม่ย้ายข้อความเต็มเข้าสู่ Git หรือเกมที่เผยแพร่

## แหล่งที่ได้รับจริง

| ไฟล์ที่ผู้ใช้แนบ | source id | bytes | encoding ที่อ่านได้แบบ strict | บรรทัดหลังปรับ LF | ตัวอักษรหลังปรับ LF |
| --- | --- | ---: | --- | ---: | ---: |
| 宿命之环.txt | coi-zh | 8,124,303 | GB18030 | 112,322 | 4,070,391 |
| 诡秘之主.txt | lotm-zh | 9,687,911 | GB18030 | 117,999 | 4,864,530 |

รวมต้นฉบับ 17,812,214 bytes ทั้งสองไฟล์อ่าน UTF-8 ไม่ได้ แต่ถอด GB18030 แบบ strict
และ encode กลับได้ตรงทุก byte ไม่มี replacement character จากการถอดแบบ lossy
เก็บต้นฉบับเดิมไว้ครบ ปรับ CRLF/CR เป็น LF เฉพาะข้อความในดัชนี
ตำแหน่งบรรทัดและตัวอักษรอ้างข้อความ LF นี้ โดยไม่เปลี่ยนตัวอักษรจีน

SHA-256 ของ byte ต้นฉบับ:

- CoI: `99a1c4aa525083e5474eb01bf131a6c1eeee1467b0eae41cd8dc9da12a10a9a7`
- LoTM: `fce8d9d02a540161357561e9825b98980050efec0c87feb60561c3ec9560cef7`

SHA-256 ของข้อความ LF เมื่อ encode UTF-8:

- CoI: `b3e4872a32a6df0dab3028cef485a28695fbdbec92360a30fb253f68a7bf2905`
- LoTM: `ce2e0916d53516ffeaf0aae5a1cd9b6bfc9dccf207a0fa5ea50f249b4a415012`

Hash ยืนยันว่าการนำเข้า/ผลค้นอ้างไฟล์ชุดใด ไม่ยืนยันผู้แต่ง ตัวตนฉบับ ความครบถ้วน
หรือสิทธิ์ในการนำไปเผยแพร่ ป้ายชื่อเรื่องมาจากผู้ใช้ ไม่ใช่การตรวจฉบับสำนักพิมพ์

## ขอบเขตบทและดัชนีที่ตรวจพบ

| source | heading 章 ที่ตรวจพบ | heading 卷 | duplicate ใกล้กันที่รวม | chunks |
| --- | ---: | ---: | ---: | ---: |
| coi-zh | 1,179 | 8 | 0 | 6,301 |
| lotm-zh | 1,396 | 0 | 1,395 | 7,603 |

รวม 13,904 chunks SQLite มีขนาด 52,391,936 bytes
ชื่อบท/เลขบทเป็นฉลากที่พบใน export ไม่ใช่จำนวน canon ที่ยืนยันแล้ว
LoTM มีหัวบทซ้ำติดกัน บางบรรทัดแรกมีเลขรายการและชื่อที่ถูกตัดท้าย
รวมเฉพาะฉลากเหมือนกันหรือเป็น prefix ของอีกฉลากในระยะไม่เกินสองบรรทัด
เก็บชื่อยาวกว่าและตำแหน่งบรรทัดแรกไว้ ไม่รวมบทชื่อเหมือนกันที่อยู่ไกลกัน
ข้อความต้นฉบับรวมทั้งฉลากซ้ำยังอยู่ในสำเนาส่วนตัว
มีฉลากเลขอารบิก/เลขจีนปะปนและเนื้อหาประกาศของผู้เขียนในไฟล์
จึงไม่ตีความ 1,396 ว่าเป็นจำนวนบท canon หรือรับรองว่าทั้งเรื่องครบ

แต่ละ chunk ไม่เกิน 768 ตัวอักษร มี overlap 64 ภายในบทเพื่อให้คำจีนที่พาดขอบ
ยังค้นได้ ใช้ SQLite `instr` กับ parameter binding ไม่สร้างพจนานุกรม trigram ขนาดใหญ่
หรือ tokenization ที่แยกคำจีนผิด การสร้างขอบเขต/line offsets ทำแบบ linear
แล้วใช้ binary search สำหรับตำแหน่งบรรทัด

## ผลค้นที่รันกับสองไฟล์จริง

| query | filter | matching chunks รวม overlap | ผลแรก: source / heading / บรรทัด excerpt |
| --- | --- | ---: | --- |
| 克莱恩 | lotm-zh | 5,778 | lotm-zh / 第1章绯红 / 52–63 |
| 途径 | ทั้งสองไฟล์ | 2,336 | coi-zh / 第十六章 信 / 1,784–1,801 |
| 卢米安 | coi-zh | 5,512 | coi-zh / 第一章 外乡人 / 45–61 |

ตัวเลขเป็น chunks ที่ตรง literal query รวมช่วง overlap ไม่ใช่จำนวนการกล่าวถึง
หรือความสำคัญของตัวละคร ผลเรียงตาม source/ตำแหน่ง ไม่ใช่ semantic ranking
ผลละไม่เกิน 480 ตัวอักษร ให้ source hash, chunk hash, excerpt hash, บท/เล่ม,
บรรทัด และ character offsets หากค้นหลายคำ แต่ละคำต้องอยู่ใน chunk เดียวกัน
excerpt ที่ถูกจำกัดอาจไม่แสดงทุกคำ ให้ตรวจช่วง source ที่ระบุก่อนสรุป

ตรวจผลสองรายการต่อ query ทั้งสาม: SHA ต้นฉบับตรง manifest, character slice
ตรง excerpt, start-line ตรงการนับ LF และมีคำค้นจริง รวม 6 ผลตรวจ
ถอดแหล่งต้นฉบับและสร้างขอบเขต/chunk ซ้ำทั้งหมด ตรวจ tuple ของข้อความ/บท/
character offsets/line references ตรงฐานข้อมูล **13,904 chunks**
SQLite `PRAGMA integrity_check` คืน `ok` ตรวจอ้างอิงนี้ไม่ใช่การพิสูจน์ข้อเท็จจริง
ทุกข้อในนิยาย ต้องอ่านบริบทและบทอื่นที่เกี่ยวข้องก่อนยืนยัน canon

## อ่านซ้ำได้ด้วยเครื่องมือใน repository

```sh
python tools/import_novel_lore.py import --lotm /path/to/诡秘之主.txt --coi /path/to/宿命之环.txt --output .local/lore/novels-zh
python tools/import_novel_lore.py search --index .local/lore/novels-zh/index.sqlite3 --query "克莱恩" --source lotm-zh --limit 2
python tools/import_novel_lore.py search --index .local/lore/novels-zh/index.sqlite3 --query "途径" --limit 2
python tools/import_novel_lore.py search --index .local/lore/novels-zh/index.sqlite3 --query "卢米安" --source coi-zh --limit 2
```

ใช้ชื่อ output ใหม่หากโฟลเดอร์มีอยู่แล้ว CLI ใช้ได้จาก working directory อื่น
manifest ส่วนตัวเก็บ path แบบ relative เช่น `text/coi-zh.txt` ไม่มี path attachment
ชั่วคราวของคลาวด์ เครื่องมือเดิม `tools/lore_index.py` และ JSON API ไม่เปลี่ยน
ดัชนีตัวอย่าง `lore/sources.json` ยังอ้าง original design ของโครงการ

เครื่องมือจำกัด source ละ 32 MiB / รวม 64 MiB, source 500,000 บรรทัด,
50,000 chunks และฐานข้อมูล 256 MiB คำค้น 1–8 terms, term ละไม่เกิน 64
ตัวอักษร, ผลค้น 1–20 รายการ เปิดฐานข้อมูล read-only ปิด extension และ trusted schema
ตรวจ schema, count, source provenance และ hash/ตำแหน่งของ chunk ที่คืน
ข้อความ source หรือ query ไม่เป็น shell/SQL code และไม่ใช่คำสั่งให้ Codex ทำตาม

ทดสอบใหม่ 15 tests ครอบคลุมจีนหลายตัวอักษร/สองตัวอักษร, overlap, chapter/volume,
หัวบทซ้ำ/ตัดท้าย, GB18030/UTF-16/CRLF, provenance/hashes, bounds, binary rejection,
output preservation รวม interrupted publication ที่รักษาไฟล์ของผู้ใช้ที่เพิ่มพร้อมกัน,
Unicode paragraph separator กับตำแหน่ง LF, ข้อความคำสั่งที่เป็นข้อมูล,
index tampering และ CLI ข้าม directory
รันร่วมกับ 14 tests เดิมของ JSON lore index: **29 tests ผ่าน**

ข้อมูลเต็มอยู่ใน `.local/lore/novels-zh/` ที่ถูก ignore และเฉพาะ task นี้
ไม่ได้เพิ่มต้นฉบับหรือข้อความ passage ในเอกสาร tracked นี้
fresh clone ที่ไม่มีพื้นที่ส่วนตัวนี้ต้องนำ source เข้ามาและรัน import ใหม่
snapshot ที่รักษา `.local/` ไว้สามารถใช้ดัชนีเดิมได้ ไม่ต้องนำเข้าใหม่
ดู [ขั้นตอนใช้งาน](../LORE_SOURCES.md) ก่อนเพิ่ม content ดัดแปลงลงเกม
