# ผลตรวจในเครื่องคลาวด์

## เกม native Android รุ่น 0.2.0

ตรวจเมื่อ 3 ตุลาคม 2026 ตามเวลาไทย ด้วย Godot 4.6.3 official,
Temurin JDK 17.0.18+8 และ Android build-tools 36.0.0
เกมมี 3 pathways, 54 cards, 21 enemies, 12 events / 36 choices และ 12 relics
ผ่าน 3 acts / 12 combats; ข้อมูลและกฎเป็น original adaptation

| Check | ผลล่าสุด |
|---|---|
| Python suite ทั้ง repository | ผ่าน 344 tests ไม่มี skipped; รวม novel importer 15, public cloud config 6 และ mobile content 9 เพิ่มจาก research baseline 314 |
| Native engine | ผ่าน 1,497 assertions; เล่นครบ 12 combats ด้วย legal actions ทั้ง Seer, Hunter และ Apprentice; validate เซฟระหว่าง transitions |
| Native UI ที่ render จริง | ผ่าน 1,801 checks, 266 GUI clicks และ 1 InputEventScreenTouch; ครบ 12 combats และ victory; ตรวจข้อความทั้ง 54 cards, 36 event choices และ 12 relic choices |
| Native layout | ภาพจริงที่ 960×540, 1280×720, 1600×720 และ 1600×900; ปุ่มและข้อความอยู่ใน viewport/card/choice bounds; ใช้ Linux X11 + Mesa llvmpipe ไม่ใช่มือถือ Android |
| Native runtime log | ไม่มี SCRIPT ERROR / ERROR; Mesa รายงาน unsupported VSync ซึ่งไม่ขัดขวางการ render |
| Fresh source import | copy `mobile/` โดยไม่มี `.godot` cache, ใช้ XDG directories ใหม่; import + 1,497 engine assertions + 41 cloud protocol checks ผ่าน |
| Cloud adapter | 41 checks ผ่านด้วย protocol fixtures ไม่มี network requests; schema constants ตรง native save v2 |
| SQL / RLS ที่รันจริง | PostgreSQL 17.11 local: 18 checks ผ่าน; own read, cross-account / anonymous denial, restricted updates, revisions, timestamps และ JSON bounds; rollback แล้วไม่มี test tables/roles ค้าง |
| APK export | สร้างและตรวจ signed debug APK จริง 27,854,139 bytes; version 0.2.0/code 2, package `org.grayfog.deckbuilder`, ARM64, landscape, min API 24 / target 36 |
| APK integrity | CRC, v2/v3 signature และ SHA ผ่าน; native libraries และ DEX ตรง official Godot Android template; `assets/data/content.json` ตรง source bytes |
| Public config / CI modes | offline, publishable, legacy anon และ invalid/secret/missing-config cases ตรวจผ่าน; workflow กดเองพร้อม build/upload source; ยังไม่ได้รัน GitHub Actions จาก GitHub จริง |
| นิยายจีนใน private index | GB18030 strict roundtrip; 13,904 chapter-bounded chunks; SQLite integrity ผ่านและ derive ทุก chunk ใหม่ตรง source; 6 bounded query matches ตรวจ hashes/lines/offsets ซ้ำ |
| Browser production build | `npm run build` ผ่าน; browser source เดิมไม่มีการแก้ใน native task |

APK SHA-256:
`7a6cdb88d8d9f82f1d1bcc403cd388c2a1313122ded91797c457863dc9ee9c02`

Content SHA-256:
`8e0620664eb9a91e6ad53682b02b73e4f9160b1798e8289dec8b3206481e87f2`

APK อยู่ `.local/android-artifacts/gray-fog-debug.apk` พร้อม hash และ verification
receipt; ไม่ commit SDK, keystore, APK, novels, private indexes หรือ reference assets
ใน Git ภาพ `docs/images/native-gameplay.png` จับจาก project ที่ render จริง
และ source hashes ก่อน/หลัง UI run ตรงกัน

APK ที่ให้ในแชตเล่นออฟไลน์และเซฟในเครื่องได้ ยังไม่มี Supabase project config
local SQL/protocol tests ไม่ใช่การ deploy และทดสอบกับ Supabase จริง
ยังไม่ได้ติดตั้ง/เปิด APK บน Android hardware หรือ LDPlayer จากคลาวด์
การผ่าน engine tests ไม่พิสูจน์ความสนุกระยะยาวหรือสมดุลทุก seed
ดู [วิธีติดตั้ง](ANDROID_BUILD.md), [ระบบที่ขยาย](CONTENT_DESIGN.md)
และ [เปิดเซฟออนไลน์](ONLINE_BACKEND.md)

## ต้นแบบเว็บและงานวิจัยก่อนขยายเป็น native

สภาพแวดล้อมที่ทดสอบ: Node 24.19.0, npm 11.9.0, Python 3.12.14,
Vite 7.3.6 จาก lockfile และ Chromium 151 บน Linux

| Check | ผล |
|---|---|
| ติดตั้งด้วย `npm ci` | ผ่าน; hash ของ package-lock.json ก่อน/หลังตรงกัน |
| `npm test` | ผ่าน 12 tests, ไม่มี skipped |
| Python research baseline | ก่อน native task ผ่าน 314 tests ไม่มี skipped; เพิ่ม fixed range ZIP reader 18, observed DB parser 12 และ five-scene replay 11 จาก suite เดิม 273; current full suite 344 ตามตารางด้านบน |
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
| Full XAPK / gameplay อ้างอิง | full XAPK ไม่มีในคลาวด์; inventory ผู้ใช้อ่าน APK ย่อยทั้ง 11 ได้; runtime text + selected DBs ให้ descriptions/costs/effect scalars และ selected CSBs ให้ geometry; runtime formulas/complete combat assembly ยังไม่ยืนยัน |
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
| English game text | 12 tests ผ่าน รวม Unicode casefold excerpt regression; actual native source-pinned wrapper+PLPcK อ่าน216,616records/108,306textsครบ; card@4,725textsรวมvariants; selected card/effect links ให้ parameters สำหรับบาง placeholders แล้ว แต่ complete formatter/runtime semantics ยังไม่ยืนยัน |
| Main cached modules | Zstd/FHSH ผ่าน; private static linked-record inventory2,167records/2,166V8cache; compact reader ปฏิเสธ incomplete coverage10,283bytes ตามจริง; ไม่ execute หรือคืน source JS |
| Bounded range exporter | 22 tests ผ่าน รวม local POSIX sh/dd/probe grammar, exact counts, failed bare-dd/successful Toybox backend regression และ fail-fast เมื่อไม่มี reader; profileจริง18resources622,458storedbytes/1,703,936alignedbytes deriveผ่าน offline; ZIPผู้ใช้มาถึงแล้วและ actual selected bytes ตรวจผ่าน; metadata ประกาศ system-toybox-dd แต่ไม่ได้รัน Windows exporter ในคลาวด์ |
| Received range ZIP | 18 tests ผ่าน; actual ZIP8,153,934bytes/20members ตรวจ CRC/SHA/pinned manifest/rederived rows/segments/read selectors; 18payloads ผ่าน bounded single-frame Zstd/FHSH, decoded1,342,080bytes; span/whole-chunk SHA และ CDN authenticity ไม่ได้พิสูจน์ |
| Selected DB rows | 12 tests ผ่าน; final CLI อ่าน8shardsครบ2,691rows/5,780records รวม278card rows/variants; complete coverage/columns/row indexes/field offsets/source-pinned local wrapper ผ่าน; primary counter0 + exact updated38-byte trailer validated แต่ trailer purpose ยังไม่ยืนยัน |
| Card/effect/text joins | public links89/89, ikarus495/495 เชื่อม compatible effect shards ได้; ตรวจ raw bytes/offsets/hash ซ้ำอิสระ5ตัวอย่าง/98fields พร้อม English sourceSHA; Gear Bag cost1/DRAW2; damage100/220/500 เป็น serialized scalars ไม่ใช่ verified flat HP damage |
| Card/battle wireframe replay | 11 tests ผ่าน; final CLI จาก actual range ZIP ได้5scenes/683nodes/682widgets/unsupportedTileSprite1; card root0×0 preserved และ viewport inference ระบุชัด; ไม่มี reference art/code ถูกโหลด |
| Card/battle browser | final tool-generated HTML ผ่าน Chromium จริงครบ5scenes, node inspection, branch/hidden/container toggles และ viewport bounds; ไม่มี uncaught/console errors; nested CSBs/rotation/runtime layout ยังไม่ประกอบ |
| Runtime research dependency | isolated zstandard0.25.0 wheel ตรวจ SHA ตรง official PyPI และ bounded decode probe ผ่าน; แยก .local/runtime-venv จากเกม |
| ADB package query | แยก transport failure จาก successful empty/malformed response; screenshot ผู้ใช้ยืนยัน adb-ok และภายหลังส่ง exportZIPs ครบ; ไม่ใช่ cloud execution ของ Windows commands |
| Local ADB startup | runners ใช้ -P5037 โดยไม่ใส่ -H; screenshot ผู้ใช้ยืนยัน daemon/device/adb-ok และได้รับ selected exportZIPsแล้ว; ADB34.0.4-10411341 exec-out echo ผ่าน; bare dd failure เดิมแก้ด้วย fixed backend detection และได้รับ rangeZIP ที่ตรวจ bytes ผ่านแล้ว |
| ADB executable selection | inventory/export ปฏิเสธ dnplayer.exe ก่อนสร้าง subprocess/ออกคำสั่ง; Windows filename comparison จำลองแบบไม่สนตัวพิมพ์ และ symlink ไป launcher ถูกปฏิเสธ; ไม่ได้ execute LDPlayer จริง |
| Export ขนาดจริงด้วย fake ADB | 6 synthetic payloads มี sizes ตรง profile จริง; Core ZIP 25,785,250 bytes และ English ZIP 15,978,834 bytes; member/ZIP SHA และ source report SHA ตรวจตรง ทั้งสองไฟล์ต่ำกว่า30MiB; ไม่ใช่เกม assets จริง |
| Wireframe หลัง native schema | สร้างใหม่ได้ 18 scenes / 474 nodes รวม geometry ของ TileSprite; browser check ที่รายงานด้านบนทำกับ bootstrap รุ่นก่อน native schema |
| เว็บไซต์ lore | HEAD ถูก proxy ปฏิเสธ 403; draft domains ยังไม่ยืนยัน runtime propagation |

ภาพ `prototype-*.png` ใน `docs/images/` มาจากต้นแบบเว็บใน Chromium
ส่วน `native-gameplay.png` มาจาก Godot บน Linux ภาพและ UI เป็นงานสร้างใหม่
ไม่ใช่ภาพหน้าจอ Chaos Zero Nightmare

การผ่าน tests ของ archive ใช้ข้อมูลจำลอง ไม่พิสูจน์ผลกับ XAPK จริง
การทดสอบไม่มี POSIX `/tmp` เป็น regression fixture บน Linux; รายงานรอบสองจากผู้ใช้
ยืนยันผลการอ่าน nested APK บนเครื่องผู้ใช้ภายหลัง แต่ไม่ใช่การรัน Windows ในคลาวด์
ผลข้างต้นตรวจ current instance; การบันทึก draft ไม่ใช่การ publish snapshot
และยังไม่ได้ตรวจการ restore ใน cloud task ใหม่
Draft บันทึก install/start สำหรับ native/runtime tools และขั้น LDPlayer แล้ว พร้อม exact
entry hostname ใน network settings; ยังไม่ยืนยัน runtime propagation ของ hostname
