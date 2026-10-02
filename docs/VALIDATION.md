# ผลตรวจในเครื่องคลาวด์

สภาพแวดล้อมที่ทดสอบ: Node 24.19.0, npm 11.9.0, Python 3.12.14,
Vite 7.3.6 จาก lockfile และ Chromium 151 บน Linux

| Check | ผล |
|---|---|
| ติดตั้งด้วย `npm ci` | ผ่าน; hash ของ package-lock.json ก่อน/หลังตรงกัน |
| `npm test` | ผ่าน 12 tests, ไม่มี skipped |
| `npm run test:python` | ผ่าน 111 tests, ไม่มี skipped; รวม pack reader, CSB, LZ4/SCT/SCSP, optional ASTC, wireframe และ native APK extraction |
| `npm run build` | ผ่าน; ได้ production bundle |
| `npm run lore:build` และค้น `ritual memory` | ผ่าน; 1 original-design source, 2 chunks, source/hash/line refs |
| `npm run smoke` | ผ่านใน Chromium จริง; ชนะสามห้องด้วย 50 การกระทำและเลือกสองรางวัล |
| UI interaction | กดการ์ดใช้ energy, จบเทิร์น, เปิด/ปิด deck, restart และ HP ตรง engine |
| Mobile 390×844 | ไม่มี page overflow; สำรับมือเลื่อนในพื้นที่ของตัวเอง |
| Browser runtime | ไม่พบ uncaught exception หรือ console error ใน run ที่ทดสอบ |
| Research pack | รับ ZIP ผู้ใช้ 3,577,579 bytes แล้ว; ตรวจ member hashes/CRCs ครบ 162; stored bytes 4,597,705 |
| CSB ข้อมูลจริง | อ่าน 18/18 scenes, 474 nodes; standard WidgetOptions 469, custom TileSprite 5 ยังไม่ถอด |
| Texture/container ข้อมูลจริง | SCT 108 + SCSP 7 ผ่าน lengths/CRC/LZ4; PNG 108 ผ่าน byte sizes/dimensions/CRC/pixel roundtrip |
| Optional ASTC decoder | texture2ddecoder 1.0.6 Linux wheel ตรวจ SHA ตรง official PyPI, แยกใน .local; format40 ASTC4×4,47 ASTC8×8 ของ pack นี้ |
| Wireframe browser | Chromium ผ่าน 18 scenes, scene/branch/hidden toggles และ node inspection; zero runtime errors; ภาพเป็น serialized diagram |
| Full XAPK / gameplay อ้างอิง | full XAPK ไม่มีในคลาวด์; inventory ผู้ใช้อ่าน APK ย่อยทั้ง 11 ได้; ไม่มี decoded combat rules หรือ battle layouts |
| Native APK helper | 9 synthetic tests ผ่าน: standalone CLI/import, report lineage, CRC/hash/limits, preserving outputs และ tempfile/atomic publish lifecycle; ยังไม่ได้รับ native APK จริงหรือรันบน NTFS จริง |
| เว็บไซต์ lore | HEAD ถูก proxy ปฏิเสธ 403; draft domains ยังไม่ยืนยัน runtime propagation |

ภาพใน `docs/images/` มาจากเกมต้นแบบนี้ใน Chromium เป็นภาพและ UI ที่สร้างใหม่
ไม่ใช่ภาพหน้าจอ Chaos Zero Nightmare

การผ่าน tests ของ archive ใช้ข้อมูลจำลอง ไม่พิสูจน์ผลกับ XAPK จริง
การทดสอบไม่มี POSIX `/tmp` เป็น regression fixture บน Linux; รายงานรอบสองจากผู้ใช้
ยืนยันผลการอ่าน nested APK บนเครื่องผู้ใช้ภายหลัง แต่ไม่ใช่การรัน Windows ในคลาวด์
ผลข้างต้นตรวจ current instance; การบันทึก draft ไม่ใช่การ publish snapshot
และยังไม่ได้ตรวจการ restore ใน cloud task ใหม่
