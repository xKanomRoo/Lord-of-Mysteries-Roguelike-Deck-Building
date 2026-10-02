# ผลตรวจในเครื่องคลาวด์

สภาพแวดล้อมที่ทดสอบ: Node 24.19.0, npm 11.9.0, Python 3.12.14,
Vite 7.3.6 จาก lockfile และ Chromium 151 บน Linux

| Check | ผล |
|---|---|
| ติดตั้งด้วย `npm ci` | ผ่าน; hash ของ package-lock.json ก่อน/หลังตรงกัน |
| `npm test` | ผ่าน 12 tests, ไม่มี skipped |
| `npm run test:python` | ผ่าน 273 tests, ไม่มี skipped; รวม runtime ZIP/SSRA/resource/text readers และ bounded byte-range export/backend detection/diagnostics เพิ่มจาก ADB/native/entry/PLPcK/CSB/texture/lore/archive tests เดิม |
| `npm run build` | ผ่าน; ได้ production bundle |
| `npm run lore:build` และค้น `ritual memory` | ผ่าน; 1 original-design source, 2 chunks, source/hash/line refs |
| `npm run smoke` | ผ่านใน Chromium จริง; ชนะสามห้องด้วย 50 การกระทำและเลือกสองรางวัล |
| UI interaction | กดการ์ดใช้ energy, จบเทิร์น, เปิด/ปิด deck, restart และ HP ตรง engine |
| Mobile 390×844 | ไม่มี page overflow; สำรับมือเลื่อนในพื้นที่ของตัวเอง |
| Browser runtime | ไม่พบ uncaught exception หรือ console error ใน run ที่ทดสอบ |
| Research pack | รับ ZIP ผู้ใช้ 3,577,579 bytes แล้ว; ตรวจ member hashes/CRCs ครบ 162; stored bytes 4,597,705 |
| CSB ข้อมูลจริง | อ่าน 18/18 scenes, 474 nodes / WidgetOptions รวม vendor TileSprite 5 จาก source-verified native schema; properties/constraints/animation ยังบางส่วน |
| Texture/container ข้อมูลจริง | SCT 108 + SCSP 7 ผ่าน lengths/CRC/LZ4; PNG 108 ผ่าน byte sizes/dimensions/CRC/pixel roundtrip |
| Optional ASTC decoder | texture2ddecoder 1.0.6 Linux wheel ตรวจ SHA ตรง official PyPI, แยกใน .local; format40 ASTC4×4,47 ASTC8×8 ของ pack นี้ |
| Wireframe browser | Chromium ผ่าน 18 scenes, scene/branch/hidden toggles และ node inspection; zero runtime errors; ภาพเป็น serialized diagram |
| Full XAPK / gameplay อ้างอิง | full XAPK ไม่มีในคลาวด์; inventory ผู้ใช้อ่าน APK ย่อยทั้ง 11 ได้; runtime text ให้ card descriptions จริง แต่ numeric rules และ battle layouts ยังไม่ decode |
| Native APK extraction helper | 9 synthetic tests ผ่าน: standalone CLI/import, report lineage, CRC/hash/limits, preserving outputs และ tempfile/atomic publish lifecycle; ยังไม่รัน extraction บน NTFS จริง |
| Native APK inventory | 7 tests ผ่าน; APK ผู้ใช้ตรวจ SHA ตรงรายงาน, ARM64 ELF 10 libraries รวม 74,003,680 bytes ตรวจ CRC/hash/bounds จริงแล้ว; ไม่ execute |
| Native static dependencies | Capstone 5.0.7 และ pyelftools 0.32 ใช้งานได้ใน isolated .local/native-venv; Linux wheels ตรวจ hashes ตาม official PyPI |
| PLPcK | 11 tests ผ่าน; init.jbin จริงตรวจ 26 records และ complete nonoverlapping coverage 320,998 bytes; ไม่ได้คืน JS source |
| RH01 samples | footer/native format ตรงกัน 7 files; original RSA signatures ผ่าน 7/7; SDK text configs 6 และ inner binary 1; ไม่ใช่ card database |
| Entry request | 14 offline tests ผ่าน รวม upstream 403/incomplete body และ proxy CONNECT แยกกัน; actual cloud GET ครั้งเดียวถูก proxy CONNECT403 ก่อน response เกม |
| LDPlayer inventory helper | 22 tests ผ่านกับ fake ADB/subprocess และ synthetic filesystem; ภายหลังได้รับ Windows report ผู้ใช้: SDK34, emulator-5554, external root47files/7.56GiB, private roots permission_denied; ไม่ใช่การรัน Windows บนคลาวด์ |
| Selected resource exporter | 23 synthetic tests ผ่าน; ได้รับ core/English ZIP outputs ผู้ใช้แล้วพร้อม six payloads ขนาดตรง profile; CRC/SHA bytes ผ่าน; export scope จาก metadata ไม่ถูกอ้างว่า independently verified |
| Runtime ZIP reader | 18 tests ผ่าน; ZIPs จริง2ไฟล์/6payloads41,759,987bytes ผ่าน CRC/SHA/paths/sizes; source inventory hash indexes ตรงกัน แต่รายงานรอบนี้ไม่ได้แนบและ original CDN authenticity ยังไม่ยืนยัน |
| SSRA metadata | 11 tests ผ่าน; final-source CLI อ่าน manifest จริง87,529unique paths/57chunks/13groups; complete coverage/pathXXH64/group mapping ผ่าน; U+200B2pathsเก็บ exactbytes/escaped inventory |
| SSRA resource extraction | 19 tests ผ่าน; actual text.db22,214,156bytes และ main.jbin47,516,297bytes ผ่าน boundedZstd/SSRC/decodedFHSH; receipt payload SHA ตรวจใหม่; resource code ไม่ execute |
| English game text | 12 tests ผ่าน รวม Unicode casefold excerpt regression; actual native source-pinned wrapper+PLPcK อ่าน216,616records/108,306textsครบ; card@4,725textsรวมvariants; numeric placeholders ยังไม่เติม |
| Main cached modules | Zstd/FHSH ผ่าน; private static linked-record inventory2,167records/2,166V8cache; compact reader ปฏิเสธ incomplete coverage10,283bytes ตามจริง; ไม่ execute หรือคืน source JS |
| Bounded range exporter | 22 tests ผ่าน รวม local POSIX sh/dd/probe grammar, exact counts, failed bare-dd/successful Toybox backend regression และ fail-fast เมื่อไม่มี reader; profileจริง18resources622,458storedbytes/1,703,936alignedbytes deriveผ่าน offline; Windows diagnostic ยืนยัน bare dd no such tool/127 แต่ Toybox dd help รองรับ; full Toybox export และ ZIPใหม่ยังรอผู้ใช้ |
| Runtime research dependency | isolated zstandard0.25.0 wheel ตรวจ SHA ตรง official PyPI และ bounded decode probe ผ่าน; แยก .local/runtime-venv จากเกม |
| ADB package query | แยก transport failure จาก successful empty/malformed response; screenshot ผู้ใช้ยืนยัน adb-ok และภายหลังส่ง exportZIPs ครบ; ไม่ใช่ cloud execution ของ Windows commands |
| Local ADB startup | runners ใช้ -P5037 โดยไม่ใส่ -H; screenshot ผู้ใช้ยืนยัน daemon/device/adb-ok และได้รับ selected exportZIPsแล้ว; ADB34.0.4-10411341 exec-out echo ผ่าน; binary read หยุดเพราะ bare dd no such tool ไม่ใช่ startup failure |
| ADB executable selection | inventory/export ปฏิเสธ dnplayer.exe ก่อนสร้าง subprocess/ออกคำสั่ง; Windows filename comparison จำลองแบบไม่สนตัวพิมพ์ และ symlink ไป launcher ถูกปฏิเสธ; ไม่ได้ execute LDPlayer จริง |
| Export ขนาดจริงด้วย fake ADB | 6 synthetic payloads มี sizes ตรง profile จริง; Core ZIP 25,785,250 bytes และ English ZIP 15,978,834 bytes; member/ZIP SHA และ source report SHA ตรวจตรง ทั้งสองไฟล์ต่ำกว่า30MiB; ไม่ใช่เกม assets จริง |
| Wireframe หลัง native schema | สร้างใหม่ได้ 18 scenes / 474 nodes รวม geometry ของ TileSprite; browser check ที่รายงานด้านบนทำกับ bootstrap รุ่นก่อน native schema |
| เว็บไซต์ lore | HEAD ถูก proxy ปฏิเสธ 403; draft domains ยังไม่ยืนยัน runtime propagation |

ภาพใน `docs/images/` มาจากเกมต้นแบบนี้ใน Chromium เป็นภาพและ UI ที่สร้างใหม่
ไม่ใช่ภาพหน้าจอ Chaos Zero Nightmare

การผ่าน tests ของ archive ใช้ข้อมูลจำลอง ไม่พิสูจน์ผลกับ XAPK จริง
การทดสอบไม่มี POSIX `/tmp` เป็น regression fixture บน Linux; รายงานรอบสองจากผู้ใช้
ยืนยันผลการอ่าน nested APK บนเครื่องผู้ใช้ภายหลัง แต่ไม่ใช่การรัน Windows ในคลาวด์
ผลข้างต้นตรวจ current instance; การบันทึก draft ไม่ใช่การ publish snapshot
และยังไม่ได้ตรวจการ restore ใน cloud task ใหม่
Draft บันทึก install/start สำหรับ native/runtime tools และขั้น LDPlayer แล้ว พร้อม exact
entry hostname ใน network settings; ยังไม่ยืนยัน runtime propagation ของ hostname
