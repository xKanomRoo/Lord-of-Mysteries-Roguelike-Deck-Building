# ผลตรวจในเครื่องคลาวด์

สภาพแวดล้อมที่ทดสอบ: Node 24.19.0, npm 11.9.0, Python 3.12.14,
Vite 7.3.6 จาก lockfile และ Chromium 151 บน Linux

| Check | ผล |
|---|---|
| ติดตั้งด้วย `npm ci` | ผ่าน; hash ของ package-lock.json ก่อน/หลังตรงกัน |
| `npm test` | ผ่าน 12 tests, ไม่มี skipped |
| `npm run test:python` | ผ่าน 34 tests, ไม่มี skipped; รวม regression สำหรับ temp directory และ incomplete reports |
| `npm run build` | ผ่าน; ได้ production bundle |
| `npm run lore:build` และค้น `ritual memory` | ผ่าน; 1 original-design source, 2 chunks, source/hash/line refs |
| `npm run smoke` | ผ่านใน Chromium จริง; ชนะสามห้องด้วย 50 การกระทำและเลือกสองรางวัล |
| UI interaction | กดการ์ดใช้ energy, จบเทิร์น, เปิด/ปิด deck, restart และ HP ตรง engine |
| Mobile 390×844 | ไม่มี page overflow; สำรับมือเลื่อนในพื้นที่ของตัวเอง |
| Browser runtime | ไม่พบ uncaught exception หรือ console error ใน run ที่ทดสอบ |
| APK จริงที่แนบ | คลาวด์ยังไม่มีไฟล์; ได้รับรายงานชั้นนอก แต่ APK ย่อยอ่านล้มเหลวทั้งหมด รอรันใหม่ด้วยเครื่องมือแก้ไข |
| เว็บไซต์ lore | HEAD ถูก proxy ปฏิเสธ 403; draft domains ยังไม่ยืนยัน runtime propagation |

ภาพใน `docs/images/` มาจากเกมต้นแบบนี้ใน Chromium เป็นภาพและ UI ที่สร้างใหม่
ไม่ใช่ภาพหน้าจอ Chaos Zero Nightmare

การผ่าน tests ของ archive ใช้ข้อมูลจำลอง ไม่พิสูจน์ผลกับ XAPK จริง
การทดสอบไม่มี POSIX `/tmp` เป็น regression fixture บน Linux ยังไม่ได้รัน Windows จริง
ผลข้างต้นตรวจ current instance; การบันทึก draft ไม่ใช่การ publish snapshot
และยังไม่ได้ตรวจการ restore ใน cloud task ใหม่
