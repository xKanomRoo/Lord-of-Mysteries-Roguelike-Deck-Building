# LoTM และ Circle of Inevitability บนคลาวด์

ได้รับ `诡秘之主.txt` และ `宿命之环.txt` ที่ผู้ใช้ระบุว่าเป็น **Lord of Mysteries**
และ **Circle of Inevitability (CoI)** ภาษาจีนแล้ว อ่านเป็น GB18030 แบบ strict
พร้อมตรวจ SHA-256 และสร้างดัชนีค้นข้อความออฟไลน์ได้จริง โดยไม่ต้องเรียกเว็บหรือ API
ดู [ใบรับและขอบเขตหลักฐาน](research/LOTM_COI_SOURCE_RECEIPT.md)

ชื่อเรื่อง/ตัวตนของฉบับ/ความครบถ้วน/สิทธิ์การใช้ยังเป็นข้อมูลที่ผู้ใช้และไฟล์ระบุ
ไม่ได้ยืนยันกับฉบับต้นทาง ต้นแบบเกมและ `lore/sources.json` ยังเป็น original design
อย่าเปลี่ยนสถานะงานเขียนเดิมให้เป็น canon เพียงเพราะมีไฟล์อ้างอิงเพิ่ม

## ใช้สองไฟล์ที่ได้รับต่อได้ทันที

ดัชนีส่วนตัวใน task นี้อยู่ที่ `.local/lore/novels-zh/index.sqlite3`
ต้นฉบับและ manifest อยู่ในไดเรกทอรีเดียวกัน ซึ่งถูก ignore ทั้งหมด
เครื่องมือใหม่ใช้ SQLite ใน Python standard library จึงไม่ต้องมีบัญชี embedding
หรือ subscription เพิ่ม และไม่เปลี่ยน API ของ `tools/lore_index.py` เดิม

```sh
python tools/import_novel_lore.py search --index .local/lore/novels-zh/index.sqlite3 --query "克莱恩" --source lotm-zh --limit 2
python tools/import_novel_lore.py search --index .local/lore/novels-zh/index.sqlite3 --query "卢米安" --source coi-zh --limit 2
python tools/import_novel_lore.py search --index .local/lore/novels-zh/index.sqlite3 --query "途径" --limit 2
```

แต่ละผลให้ชื่อบท/เล่มที่ตรวจพบ, source SHA-256, chunk SHA-256, excerpt SHA-256
และตำแหน่งบรรทัด/ตัวอักษร ข้อความผลละไม่เกิน 480 ตัวอักษร
ค้นจีนหลายตัวอักษรและคำสองตัวอักษรได้ ไม่ต้องแบ่งคำจีนก่อน
คำที่คั่นด้วยช่องว่างต้องอยู่ใน chunk เดียวกันทั้งหมด ค้น literal แบบตรงตัวตามลำดับไฟล์
ไม่ใช่ semantic search, translation หรือการฝึก weights ของ Codex

ให้ Codex ค้นหัวข้อที่กำลังออกแบบ เช่น `魔药`, `占卜`, `猎人`, `封印物`
อ่านช่วงที่จำเป็น แล้วบันทึกข้อเท็จจริงพร้อมชื่อบท/บรรทัด/แหล่ง
แยกกฎเกมที่แต่งใหม่ออกจากข้อเท็จจริงของนิยายเสมอ ผลค้นแรกยังไม่พอพิสูจน์
กฎของทั้งเรื่อง และคำศัพท์ไทยต้องตรวจ/แปลตามบริบทก่อนเผยแพร่

## นำเข้าสำหรับเครื่องหรือ task ใหม่

วางไฟล์ที่ผู้ใช้เตรียมไว้ในเครื่อง เช่น Windows `Downloads` แล้วจากราก repository รัน:

```powershell
py .\tools\import_novel_lore.py import --lotm "$env:USERPROFILE\Downloads\诡秘之主.txt" --coi "$env:USERPROFILE\Downloads\宿命之环.txt" --output ".local/lore/novels-zh"
py .\tools\import_novel_lore.py search --index ".local/lore/novels-zh/index.sqlite3" --query "卢米安" --source coi-zh --limit 2
```

โฟลเดอร์ปลายทางต้องเป็นชื่อใหม่ เครื่องมือไม่ทับข้อมูลเดิม
fresh Git checkout ไม่ได้มีไฟล์ที่อยู่ใน `.local/` นี้ ให้แนบต้นฉบับหรือใช้พื้นที่ส่วนตัว
ที่ได้รับอนุญาตแล้วรัน import ส่วน task/snapshot ที่รักษา `.local/` ไว้ใช้ดัชนีเดิมได้
ไม่ใส่ต้นฉบับนิยายทั้งหมด ดัชนีที่มีข้อความเต็ม หรือข้อมูลเกมอ้างอิงลง APK,
repository สาธารณะ หรือเซิร์ฟเวอร์ผู้เล่น เก็บในงานวิจัยส่วนตัวและผลิตเนื้อหาดัดแปลง
ที่โครงการมีสิทธิ์ใช้แยกต่างหาก

## ไม่จำเป็นต้องมี API เสมอไป

เครื่องคลาวด์เรียก HTTPS ด้วย Python/curl ได้ หาก policy อนุญาตปลายทาง
การไม่มี browser tool ไม่ได้แปลว่าเข้าถึงหน้า HTML ไม่ได้ แต่เว็บไซต์อาจมี login,
JavaScript, anti-bot หรือข้อจำกัดการใช้งานเป็นอีกชั้นหนึ่ง
ผลทดสอบในเครื่องนี้: Wikipedia และ Webnovel ถูก proxy ปฏิเสธ `403` ส่วน npm ใช้งานได้

บันทึกโดเมนที่ต้องใช้ใน environment draft แบบ additive:
`en.wikipedia.org`, `www.webnovel.com` โดยคง package-manager preset
หลังผู้ใช้บันทึกการตั้งค่าที่มีผลต่อ runtime ให้ทดสอบการเข้าถึงใหม่
การอนุญาตโดเมนไม่รับประกันว่าจะผ่าน login หรืออ่านเนื้อหาที่มี paywall ได้

## ดัชนี JSON สำหรับ original design และสรุปขนาดเล็ก

1. ใช้ไฟล์ข้อความ/Markdown ที่ผู้ใช้มีสิทธิ์ใช้ หรือสรุปจากแหล่งที่เปิดอ่านได้
2. บันทึก `title`, `provenance_url`, `rights`, `status` ใน manifest
   และใส่ edition, chapter references, spoiler level ในฟิลด์ `notes`
3. แยก canon source, reference summary และ original design อย่ารวมความเชื่อมั่นกัน
4. Build index แล้วค้นเฉพาะส่วนที่ต้องใช้ใน task โมเดลไม่ต้องเรียกเว็บระหว่างพัฒนา

```sh
npm run lore:build
python tools/lore_index.py search --index .local/lore-index.json \
  --query "ritual memory" --limit 3
```

ดู schema ที่ `lore/sources.json` และ `python tools/lore_index.py --help`
ตัวอย่างใน repository เป็น original design ไม่ได้ดึงบทนิยายมาโดยอัตโนมัติ
เครื่องมือนี้จำกัด source ละ 1 MiB จึงไม่ใช้กับสองไฟล์นิยายเต็มที่ได้รับ
ใช้ `import_novel_lore.py` ด้านบนสำหรับแหล่งขนาดใหญ่แทน
สำหรับข้อความต้นฉบับที่ไม่ควรเผยแพร่ลง Git เก็บในตำแหน่ง local ที่ถูก ignore
แล้วลงทะเบียนแหล่งใน manifest ส่วนตัว

## แหล่งเริ่มตรวจสอบ

- [Wikipedia: Lord of Mysteries](https://en.wikipedia.org/wiki/Lord_of_Mysteries)
  ใช้ตรวจข้อมูลภาพรวมหลังอนุญาตโดเมน ไม่ใช่แหล่ง balance หรือกฎทุกระบบ
- [Webnovel](https://www.webnovel.com/) ค้นชื่อเรื่องและตรวจผู้แต่ง/edition จากหน้าต้นทาง
  ไม่คัดลอกเนื้อหาที่ต้องซื้อหรือใช้ credential โดยไม่ได้รับสิทธิ์
- เอกสาร canon/สรุปที่ผู้ใช้เตรียมเองพร้อม chapter references ใช้ทำงานออฟไลน์ได้ทันที

ลิงก์เหล่านี้เป็นจุดเริ่มต้น ยังไม่ได้ดึงหรือตรวจเนื้อหาจากเว็บใน session นี้
การค้นสองไฟล์ที่ผู้ใช้ให้มาไม่ต้องเข้าลิงก์เหล่านี้
ไม่จำเป็นต้องติดตั้ง plugin เพิ่มสำหรับอ่านไฟล์ในเครื่องหรือเรียก HTTPS
หากต้องจัดการข้อมูลจำนวนมาก ค่อยเลือก app ที่เก็บเอกสารและที่ผู้ใช้มีสิทธิ์เข้าถึง
