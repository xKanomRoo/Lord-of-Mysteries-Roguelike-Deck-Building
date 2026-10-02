# LoTM และ Circle of Inevitability บนคลาวด์

ตีความ `Col` ในคำขอว่าเป็น **Circle of Inevitability (CoI)** หากหมายถึงเรื่องอื่น
ให้เปลี่ยน manifest และ spec ก่อนเพิ่มเนื้อหา ต้นแบบขณะนี้ใช้ธีม occult ที่ออกแบบใหม่
ไม่ใช่ฐานข้อมูล canon ของทั้งสองเรื่อง

## ไม่จำเป็นต้องมี API เสมอไป

เครื่องคลาวด์เรียก HTTPS ด้วย Python/curl ได้ หาก policy อนุญาตปลายทาง
การไม่มี browser tool ไม่ได้แปลว่าเข้าถึงหน้า HTML ไม่ได้ แต่เว็บไซต์อาจมี login,
JavaScript, anti-bot หรือข้อจำกัดการใช้งานเป็นอีกชั้นหนึ่ง
ผลทดสอบในเครื่องนี้: Wikipedia และ Webnovel ถูก proxy ปฏิเสธ `403` ส่วน npm ใช้งานได้

บันทึกโดเมนที่ต้องใช้ใน environment draft แบบ additive:
`en.wikipedia.org`, `www.webnovel.com` โดยคง package-manager preset
หลังผู้ใช้บันทึกการตั้งค่าที่มีผลต่อ runtime ให้ทดสอบการเข้าถึงใหม่
การอนุญาตโดเมนไม่รับประกันว่าจะผ่าน login หรืออ่านเนื้อหาที่มี paywall ได้

## แนวทางนำข้อมูลเข้า

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
สำหรับข้อความต้นฉบับที่ไม่ควรเผยแพร่ลง Git เก็บในตำแหน่ง local ที่ถูก ignore
แล้วลงทะเบียนแหล่งใน manifest ส่วนตัว

## แหล่งเริ่มตรวจสอบ

- [Wikipedia: Lord of Mysteries](https://en.wikipedia.org/wiki/Lord_of_Mysteries)
  ใช้ตรวจข้อมูลภาพรวมหลังอนุญาตโดเมน ไม่ใช่แหล่ง balance หรือกฎทุกระบบ
- [Webnovel](https://www.webnovel.com/) ค้นชื่อเรื่องและตรวจผู้แต่ง/edition จากหน้าต้นทาง
  ไม่คัดลอกเนื้อหาที่ต้องซื้อหรือใช้ credential โดยไม่ได้รับสิทธิ์
- เอกสาร canon/สรุปที่ผู้ใช้เตรียมเองพร้อม chapter references ใช้ทำงานออฟไลน์ได้ทันที

ลิงก์เหล่านี้เป็นจุดเริ่มต้น ยังไม่ได้ดึงหรือตรวจเนื้อหาใน session นี้
ไม่จำเป็นต้องติดตั้ง plugin เพิ่มสำหรับอ่านไฟล์ในเครื่องหรือเรียก HTTPS
หากต้องจัดการข้อมูลจำนวนมาก ค่อยเลือก app ที่เก็บเอกสารและที่ผู้ใช้มีสิทธิ์เข้าถึง
