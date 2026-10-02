# ข้อมูลเกมที่ดาวน์โหลดหลังติดตั้ง

ผู้ใช้ขอให้ตรวจวิธีรับข้อมูลเกมจากเซิร์ฟเวอร์ต่อจาก APK เป้าหมายที่ตรวจได้คือ
resource ที่ client ดาวน์โหลด เช่น scenes, textures, localization หรือ client config
ไม่ใช่การอ้างว่าเข้าถึงฐานข้อมูลผู้เล่นหรือกฎที่ทำงานเฉพาะในเซิร์ฟเวอร์ได้

## หลักฐานที่พบในไฟล์ที่ได้รับ

ตรวจ bounded ASCII/UTF-16 URL candidates จาก bootstrap pack 162 members แล้ว
ยังไม่ระบุ public patch/CDN endpoint ที่ยืนยันจาก strings ที่อ่านได้
ไม่แปลว่าไม่มี URL ที่ถูก encode หรือสร้างตอนรัน

`assets/pre/bin/arm64/init.jbin` (SHA-256
`546244bcf2a632171c74a62fbc6cea678eeeebd54db5a00095407b2c084c97c4`)
มี symbols ต่อไปนี้ที่ byte offsets:

| Symbol | Offsets |
|---|---|
| `_get_version_json` | 39853, 201758 |
| `getTargetVersionInfo` | 32571, 201964 |
| `startPatch` | 42821, 220140 |
| `patch_status_collecting_manifest` | 81535 |
| `patch.extract_total` | 136704 |
| `_start_patch_dolphin` | 222651 |

ชื่อเหล่านี้รองรับว่ามี bootstrap hooks สำหรับ patch/manifest แต่ไม่ได้ decode
URL formation, protocol, callback behavior หรือยืนยันว่าทุก hook ถูกใช้ใน build นี้
URL ที่อ่านได้ใน init เป็น paths ของ policy/legal บน `game.qq.com` และ
`rule.tencent.com`; store/DTD/metadata URLs ในไฟล์อื่นไม่ได้เป็น game CDN
ยังไม่ได้ส่ง request ไป game server และไม่ได้ execute APK/scripts/libraries

## ทางเลือกตามชนิดข้อมูล

| สิ่งที่ต้องการ | วิธีที่ใช้ได้ | สิ่งที่ต้องรู้ก่อน |
|---|---|---|
| ไฟล์ patch/CDN ที่เผยแพร่ให้ client ดาวน์โหลด | อ่าน version/manifest ที่ระบุ endpoint จริง แล้วดาวน์โหลด files ตาม manifest | URL, version/region, paths, size/hash และรูปแบบ container |
| Resource ที่ client ต้องล็อกอินหรือรับ config ตอนรันก่อนโหลด | ใช้แอปทางการกับบัญชีที่ผู้ใช้มีสิทธิ์ ให้ดาวน์โหลด แล้วเก็บ manifest/resources ที่เข้าถึงได้ | การเข้าถึง storage ของอุปกรณ์และรูปแบบไฟล์; ไม่ส่ง password/token เข้าแชต |
| ข้อมูลบัญชีที่ API อนุญาตให้บัญชีนั้นอ่าน | API/export ที่มีสิทธิ์ตรงกับข้อมูล | documented endpoint และ authentication ที่จัดการในเครื่องผู้ใช้ |
| ฐานข้อมูลอื่นหรือ server-only logic | export, API หรือเอกสารจากผู้ดูแลระบบ | สิทธิ์จากเจ้าของระบบ; resource download ของ client ไม่ให้สิทธิ์นี้ |

การไม่มีเว็บไซต์ API ไม่ได้ปิดทางดาวน์โหลด binary ผ่าน HTTPS แต่การเพิ่ม domain
ใน cloud network settings ไม่ได้สร้าง endpoint, authentication หรือสิทธิ์เข้าถึง
เอง ในคลาวด์นี้ HTTPS ใช้งานได้บางปลายทาง อุปสรรคตอนนี้คือยังไม่มี patch URL
และ manifest schema ที่ยืนยัน ไม่ใช่การขาด browser สำหรับดูวิดีโอ

## ขั้นที่ทำต่อได้ตอนนี้

ใช้ [NEXT_APK_STEP.md](NEXT_APK_STEP.md) แยกและส่ง `config.arm64_v8a.apk`
21.92 MiB เครื่องมือใหม่ตรวจ input/report/hash และจำกัด output ไม่เกิน 30 MiB
เมื่อได้รับจึงอ่าน native libraries เพื่อดู references และส่วนประกอบ URL/reader
หากพบ endpoint ที่แจก public resource จริง จึงทดลอง bounded HTTPS GET พร้อม
บันทึก provenance และ verify hashes ตาม manifest ไม่ลองเดา private API paths

ถ้า endpoint/config หาได้เฉพาะตอนรัน จะจัดขั้นตอนให้แอปทางการดาวน์โหลด patch
บนอุปกรณ์หรือ Android emulator ของผู้ใช้ การเปิดถึงหน้าโหลด resource ไม่ต้อง
เล่น combat หรือดูวิดีโอ แต่ยังไม่ทราบ directory ของ resource ใน build นี้
Android scoped storage/private app data อาจอ่านไม่ได้ด้วย `adb pull` ตามปกติ
จึงต้องตรวจ storage/access จริงก่อนสอน path หรือสัญญาว่าดึงได้ครบ

เมื่อเข้าถึงไฟล์ได้ ส่งเฉพาะ resource manifest และไฟล์ที่จำเป็นพร้อม source hash
ไม่ส่ง account database, credentials, session cookies หรือ traffic ทั้ง session
ถ้าพบ authentication, signed URL, rate/access restriction จะใช้ช่องทางที่ผู้ใช้
มีสิทธิ์หรือ file export ไม่ข้ามข้อจำกัดด้วยการแต่ง tokens หรือแก้ certificate pinning

ผลดาวน์โหลดจะเก็บใน `.local/` เพื่อวิจัย static ต่อ การมีไฟล์เพิ่มไม่ยืนยันว่า
server-only balance/logic หรือภาพ runtime ทั้งหมดอยู่ใน files และ assets อ้างอิง
จะไม่ถูก import เข้าเกม LoTM ต้นแบบโดยอัตโนมัติ
