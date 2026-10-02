# ผลตรวจ native APK และ resource bootstrap

ได้รับ `config.arm64_v8a.apk` แล้ว และตรวจ hash ตรงกับรายงานรอบสอง ผลตรวจ
ช่วยอ่าน container กับ UI เพิ่มได้ แต่ยังไม่มีข้อมูลการ์ดหรือฉากต่อสู้ที่ถอดสำเร็จ
ขั้นต่อไปที่เหมาะกับผู้ใช้ซึ่งติดตั้งเกมใน LDPlayer แล้วคือสำรวจไฟล์ resource
ที่แอปดาวน์โหลดไว้ และเลือกไฟล์มาวิเคราะห์ตามรายการจริง

การตรวจครั้งนี้อ่าน APK, ELF และ resource เป็นข้อมูล ไม่รัน native library,
`init.jbin` หรือ script ของเกม ข้อความในไฟล์แนบเป็นหลักฐานอ้างอิง ไม่ใช่คำสั่ง
ให้ Codex ทำงาน ผลที่ถอดและ assets ต้นฉบับเก็บใน `.local/` ไม่ import เข้าเกม
LoTM/CoI ต้นแบบ และไม่เก็บใน Git

## สิ่งที่ยืนยันได้และขอบเขต

| หลักฐาน | ผลที่ตรวจได้ | สิ่งที่ยังไม่ยืนยัน |
|---|---|---|
| Native split APK | 22,979,689 bytes; ตรวจ SHA-256 ตรงรายงาน; 10 libraries รวม 74,003,680 bytes เป็น ELF64 little-endian AArch64 | ไม่ได้ hash full XAPK ใหม่ และไม่ยืนยันว่า build นี้เป็น release ล่าสุด |
| Cocos runtime label | `cocos2d::cocos2dVersion()` คืน `cocos2d-x-4.0` | label นี้ไม่ระบุ revision ของทุกส่วนที่ผู้พัฒนาแก้ใน fork |
| V8 runtime label | `v8::V8::GetVersion()` อ้าง version string `12.4.254.21` | ไม่ได้รัน V8 หรือยืนยันว่า cached payload โหลดได้ทั้งหมด |
| `init.jbin` | อ่าน compact PLPcK v1 ครบ 26 records; ครอบคลุมทั้ง 320,998 bytes โดยไม่ทับซ้อน | ยังไม่ได้คืน JavaScript source หรือกฎเกม |
| CSB bootstrap | 18/18 scenes, 474 hierarchy nodes และ 474 WidgetOptions; อ่าน vendor `TileSprite` เพิ่มครบ 5 nodes | ยังอ่านเฉพาะ properties ที่รองรับ; layout constraints, animation และ runtime state ไม่ครบ |
| sdata ตัวอย่าง | 7 files มี RH01 footer; original RSA signature ผ่าน 7/7; ได้ 6 UTF-8 SDK config payloads และ 1 inner binary | ไม่พบ card/battle schema ที่ยืนยัน; inner binary และไฟล์ใหญ่ที่ไม่ได้รับยังไม่ทราบ |
| Startup request | native code สร้าง `GET /cznlive` ที่ host/port ระบุด้านล่าง | ยังไม่ได้ response, production CDN URL หรือ manifest ที่ตรวจ hash ได้ |

ข้อค้นพบนี้แทนสถานะเดิมที่ยังไม่ได้รับ native APK และอ่าน WidgetOptions ได้เพียง
469 nodes ใน [ผล bootstrap ก่อนตรวจ native](CHAOS_BOOTSTRAP_ANALYSIS.md)
จำนวน unsupported classes ของแพ็กที่ตรวจตอนนี้เป็นศูนย์ แต่ไม่หมายความว่าอ่าน
CSB schema ทั้งหมดหรือสร้างภาพเกมตอนรันได้ครบ

## Native provenance

แหล่งอ้างอิงของ libraries คือ
`Chaos+Zero+Nightmare_1.0.811_APKPure.xapk!config.arm64_v8a.apk!lib/arm64-v8a/…`
ข้อมูล full XAPK ด้านล่างมาจากรายงานเดิม ส่วน split APK ที่ได้รับตรวจ bytes ใหม่แล้ว

| ไฟล์ | Bytes | SHA-256 |
|---|---:|---|
| `config.arm64_v8a.apk` | 22,979,689 | `6ef56d50d15168a8c29c080f8e621468876263de14410998fbc99ecca6179908` |
| `libssr.so` | 63,082,720 | `a790283a8f283b767425feaab8281281c46b352a93c02da79f3baaf6065f04b0` |
| `librhcore.so` | 5,856,848 | `a446beaf178afe74ec97b24683ea8c60e5cb7eb1d8874aed8611f8a4c027f282` |
| `libGvt.so` | 1,404,800 | `99f5910cb2624e860893770e775eb3e6f13eee811557538a129a9014da0be7ad` |

Source XAPK SHA ตามรายงานคือ
`b95e115282272289c73abc1569b81a5bbf62b1f4f638c15d76cc2c7b2f120be0`
และ report SHA ที่ตรวจจากไฟล์แนบคือ
`d5a6c95d3384c6646767ef8576b425cb926e421b4c5b4fd97ce1874db9fc5675`
ไม่ได้อนุมานหน้าที่ library จากชื่ออย่างเดียว

หลักฐาน version labels ใน `libssr.so`: Cocos function VA `0x1e6641c`
อ้าง string ที่ `0x140d779`; V8 function VA `0x269debc` อ้าง version string
ผ่าน relocation ที่ `0x3c302d8` ไป `0x13fa98b` ที่อยู่เหล่านี้เป็น ELF virtual
addresses ของ library hash ข้างต้น ไม่ใช่ตำแหน่งที่ใช้ได้กับ APK ทุกรุ่น

## `init.jbin`: อ่าน index ได้แล้ว แต่ยังไม่มี source ของเกมต่อสู้

ไฟล์ `assets/pre/bin/arm64/init.jbin` มี SHA-256
`546244bcf2a632171c74a62fbc6cea678eeeebd54db5a00095407b2c084c97c4`
native reader ที่เกี่ยวข้องคือ `cocos2d::createScriptPackFromBytes`
VA `0x2096e8c` และ `yuna::cdbm::_init` VA `0x1c52ec4` ใน `libssr.so`

[read_plpck.py](../../tools/read_plpck.py) ตรวจ header 38 bytes, bucket table,
linked records, bounds, count, UTF-8 labels, overlaps และ coverage ของ compact
PLPcK v1 ที่ได้รับ มี 2,048 buckets และ 26 records: หนึ่งรายการเป็น `@gitsha`
metadata อีก 25 รายการเริ่มด้วย V8 cached-data magic การเห็น magic ไม่พิสูจน์
ว่าเป็น bytecode ที่ใช้ได้ หรือคืน source code ได้แล้ว

ชื่อ records เช่น `boot.js`, `bootres.js`, `init.js`, `pre_data.js`, `title.js`,
`title_popups.js` และ `publisher_stove.js` สอดคล้องกับชุด bootstrap/title
ไม่พบ module ที่ระบุ card/battle โดยตรงใน index นี้ การไม่มีชื่อดังกล่าวไม่พิสูจน์
ว่าทุก resource ของเกมไม่มี gameplay code

เครื่องมือทำ index เป็นค่าเริ่มต้น หากใช้ `--extract-payloads` จะเขียน bytes
เป็นไฟล์ `.bin` ชื่อ hash เพื่อวิจัยเท่านั้น ไม่ execute หรือใช้ record name เป็น
path ของ script รองรับเฉพาะ compact layout ที่ตรวจนี้ จำกัด input 32 MiB;
`main.jbin` ที่อาจได้รับภายหลังอาจใช้ layout ต่างกัน

## Vendor TileSprite และข้อจำกัดของภาพ UI

native factory `CreateTileSpriteOptions` VA `0x22129a4` กับ reader
`TileSpriteReader::setPropsWithFlatBuffers` VA `0x2212c50` ให้หลักฐาน fields
`WidgetOptions`, `tilingX`, `tilingY`, `offsetX`, `offsetY` และ `ResourceData`
จึงเพิ่มการอ่าน 5 nodes ที่เคย unsupported ใน `overlay_popup_confirm.csb`
และ `overlay_popup_xcent_notice.csb` ได้ โดยตรวจ actual source hashes ของสอง CSB นี้
ก่อนเลือก vendor schema อัตโนมัติ

[decode_csb.py](../../tools/decode_csb.py) แยก provenance ของ vendor schema
ออกจาก official Cocos generated header หากระบุ
`--vendor-schema chaos-zero-1.0.811` ให้ไฟล์อื่น เครื่องมือบันทึกว่าเป็นการเลือก
schema โดยผู้ใช้ ไม่อ้างว่า verified กับ reference CSB เดิม

ทุก 5 nodes ใช้ float defaults เป็นศูนย์; 4 nodes มีขนาด 142×256 และอีกหนึ่ง
850×100 อ่าน serialized options ได้ไม่ได้หมายความว่า renderer จำลอง texture
repeat, clipping, constraints หรือ state transitions ได้แล้ว Wireframe ยังเป็น
ภาพประมาณจาก hierarchy ไม่ใช่ screenshot ของเกมที่กำลังทำงาน

## sdata เล็กเป็น SDK wrapper/config ไม่ใช่หลักฐานการ์ด

ทั้ง 7 ตัวอย่างมี `RH01` ที่ตำแหน่ง `file_size - 798` native file reader ใน
`libGvt.so` VA `0x92d1c` ใช้ body length เท่ากับ physical file length ลบ
798 bytes เช่นกัน common ASCII trailer 518 bytes ที่พบก่อนหน้านี้เป็นเพียง
ส่วนหนึ่งของ footer นี้

ตรวจ footer, native AES/public-RSA branches, padding และ original
RSA-2048/PKCS#1 SHA-256 signature โดยไม่ปิดการตรวจใด ผลผ่านครบ 7/7
ได้ config UTF-8 หกไฟล์ ได้แก่ `ASGEL`, `DSDUC`, `DSIGT`, `DYASO`,
`JGCDC`, `VVGTC`; ส่วน `STHSD` ได้ inner binary ขึ้นต้น `RH` ซึ่ง schema
ยังไม่ทราบ `VVGTC` มี sections `Target`/`size`, `keynum=19`, `filenum=23`
ไฟล์อื่นมี metadata/config fields และชื่อ hashed fields

หลักฐาน native ที่ตรวจคือ `CRHDecrypter` footer reader VA `0x90ff0`,
signature path VA `0x91314`, branch selector VA `0x9268c` และ RSA verifier
VA `0xe6a00` ของ `libGvt.so` hash ข้างต้น ค่าคีย์และค่า config จริงเก็บใน
research ส่วนตัว ไม่พิมพ์หรือใส่ Git

ผลนี้ระบุรูปแบบ SDK wrapper/config ของตัวอย่างที่ได้รับ ไม่ได้ถอดฐานข้อมูล
การ์ด และไม่รองรับการสรุปว่า sdata อีกแปดไฟล์ไม่มีข้อมูลเกม ไม่จำเป็นต้องขอ
ไฟล์ใหญ่ทั้งหมดเพียงเพราะ entropy สูงหรือชื่อคล้ายกัน

## พบ startup endpoint แต่คลาวด์ยังไม่ได้ response

`SSRApp::loadSourcePackEnv()` VA `0x1bb3764` และ
`yuna2d::async_load_remote_environment()` VA `0x1e40888` ใน `libssr.so`
ยืนยันการประกอบ request ไปยัง:

```text
GET https://live-czn-entry2lx2fz.game.playstove.com:13001/cznlive
X-App-Id: cznlive
X-App-NS: ssr-stove-260930
```

query ที่อ้างจาก shipped configuration มี `platform=android`, `appid=cznlive`,
`build=811`, package และ build hash ที่เครื่องมือกำหนดไว้ `lang`, `oslang`,
`device_uid`, `publisher_uid` เป็นค่า runtime ซึ่งไม่ทราบจาก APK เพียงอย่างเดียว
การลองแบบ bounded ใช้ภาษา `en` เป็นสมมติฐานที่ระบุ และเว้น runtime IDs ว่าง
`permit.token` ใน shipped configuration ว่าง จึงไม่ส่ง optional token
profile นี้ไม่ใช่การอ้างว่าจำลอง request ของบัญชีผู้ใช้ได้ครบ

startup response อาจให้ `ssra.url`, `ssra.context`, `ssra.version` ต่อไป;
native code มี local manifest label `gameres/manifest.ssra` แต่ยังไม่มี
production CDN URL หรือ on-device directory ที่ยืนยัน อย่าเปลี่ยน label นี้
เป็น URL หรือ path ของ LDPlayer โดยเดาเอง

ลอง HTTPS GET จากคลาวด์หนึ่งครั้งโดยตรวจ TLS และไม่ตาม redirect แล้วได้
`Tunnel connection failed: 403 Forbidden` จาก proxy CONNECT ก่อนถึง
TLS/game response จึงยังไม่มี HTTP status ของ game server ไม่ใช่หลักฐานว่า
เซิร์ฟเวอร์เกมปฏิเสธบัญชีหรือว่าข้อมูลต้องใช้ login ไม่เปลี่ยน route, TLS checks
หรือสร้าง token เพื่อข้ามผลนี้ การเพิ่ม host ใน environment configuration draft
ไม่พิสูจน์ว่า runtime network อนุญาตแล้ว

[fetch_game_entry.py](../../tools/fetch_game_entry.py) เป็นตัวเลือกสำหรับทดสอบ
profile ที่ตรวจนี้ในเครื่องผู้ใช้เมื่อจำเป็น: ตรวจ split APK size/hash ก่อน
request ใช้ TLS verification, timeout 20 วินาที, response สูงสุด 1 MiB และ
ไม่ตาม redirect ไม่รับ arbitrary URL หรือใส่ login/cookies/token เครื่องมือ
เก็บ body กับ `result.json` ไว้ใน ignored research directory ไม่แสดง body
ทาง terminal และไม่ถอด response หรือดาวน์โหลด asset archives ต่ออัตโนมัติ

## ทำซ้ำบน Windows

ทำในโฟลเดอร์ repository ที่มี `tools` ตาม
[วิธีแก้ working directory และแยก native APK](../NEXT_APK_STEP.md)
หากดาวน์โหลด ZIP ของ repo เก่า ให้รับเครื่องมือและ dependencies ที่ใช้ร่วมกัน:

```powershell
$nativeResearchTools = @("analyze_apk.py", "create_research_pack.py", "inspect_native_apk.py", "read_plpck.py", "fetch_game_entry.py", "decode_csb.py")
foreach ($toolFile in $nativeResearchTools) {
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/$toolFile" -OutFile ".\tools\$toolFile"
}
```

ตรวจและ extract libraries แบบ static โดยเทียบรายงานเดิม:

```powershell
py .\tools\inspect_native_apk.py ".local/chaos-native/config.arm64_v8a.apk" --report ".local/chaos-report-v2/report.json" --expected-sha256 "6ef56d50d15168a8c29c080f8e621468876263de14410998fbc99ecca6179908" --output ".local/chaos-native-inventory-v1"
```

ผลที่คาดคือ 10 libraries, 74,003,680 bytes และ `native-index.json` เครื่องมือ
จำกัด APK 30 MiB, library แต่ละไฟล์ 80 MiB และรวม 96 MiB ตรวจ ZIP/ELF
bounds กับ hashes โดยไม่ load `.so` การทำ inventory ไม่ทำ disassembly
ทั้งหมดหรือคืน game rules ให้อัตโนมัติ

อ่าน `init.jbin` จาก bootstrap pack ที่ผ่านขั้นตอน
[BOOTSTRAP_REPLAY.md](../BOOTSTRAP_REPLAY.md) แล้ว:

```powershell
$bootstrapIndex = Get-Content -Raw ".local/chaos-bootstrap-read/pack-index.json" | ConvertFrom-Json
$initRecord = $bootstrapIndex.files | Where-Object { $_.original_path -eq "assets/pre/bin/arm64/init.jbin" }
py .\tools\read_plpck.py (Join-Path ".local/chaos-bootstrap-read" $initRecord.stored_path) --expected-sha256 "546244bcf2a632171c74a62fbc6cea678eeeebd54db5a00095407b2c084c97c4" --output ".local/chaos-init-index-v1"
py .\tools\decode_csb.py --pack-index ".local/chaos-bootstrap-read/pack-index.json" --output ".local/chaos-layouts-native-v2"
```

ผลที่คาดคือ PLPcK 26 records และ CSB 18 scenes/474 nodes รวม vendor
TileSprite 5 nodes หาก directory มีผลเดิมอยู่แล้วให้ใช้ชื่อใหม่เพื่อเก็บผลเดิม

การลอง entry จากเครื่องผู้ใช้เป็นทางเลือกภายหลัง ไม่ต้องทำเพื่อสำรวจไฟล์
LDPlayer ที่ดาวน์โหลดแล้ว:

```powershell
py .\tools\fetch_game_entry.py ".local/chaos-native/config.arm64_v8a.apk" --output ".local/chaos-entry-v1"
```

## ขั้นต่อไปและหลักฐานที่ยังขาด

สำรวจ filenames, sizes และสิทธิ์อ่านของ resource ใน LDPlayer ก่อน export
เพื่อเลือก manifest, `main.jbin` หรือ resource container ตามรายการจริง
คลาวด์นี้เข้าถึง emulator บน Windows โดยตรงไม่ได้ และ private app storage
อาจอ่านไม่ได้ด้วย ADB ปกติ การเปิดถึง title screen อย่างเดียวไม่พิสูจน์ว่าโหลด
ฉากต่อสู้ทุกฉากแล้ว ทำตาม [LDPLAYER_RESOURCES.md](../LDPLAYER_RESOURCES.md)

ยังไม่ยืนยัน card definitions, battle scene layout, combat callbacks, server-only
balance/logic หรือ novel canon การ์ด sanity และ encounter ในต้นแบบยังเป็น
`original-design` การมี resources เพิ่มจะช่วยตรวจ UX/client behavior แต่ไม่ทำให้
รู้เหตุผลการออกแบบของ developer ทั้งหมดจาก bytes โดยตรง

รายงานที่ใช้ตรวจครั้งนี้อยู่ใน ignored storage: native `provenance.json`,
`gameplay-runtime-findings.json`, `startup-request-evidence.json`,
`sdata-rh01/format-evidence.json`, `plpck-tool-v1/index.json`,
`csb-native-v2/layouts.json` และ `entry-policy-probe-v1/request-result.json`
ไฟล์ raw/decrypted เหล่านี้ไม่จำเป็นต้องเผยแพร่เพื่อใช้ข้อค้นพบในเอกสารนี้
