# ข้อมูลเกมที่ดาวน์โหลดหลังติดตั้ง

ผู้ใช้ขอให้ตรวจวิธีรับข้อมูลเกมจากเซิร์ฟเวอร์ต่อจาก APK เป้าหมายที่ตรวจได้คือ
resource ที่ client ดาวน์โหลด เช่น scenes, textures, localization หรือ client config
ไม่ใช่การอ้างว่าเข้าถึงฐานข้อมูลผู้เล่นหรือกฎที่ทำงานเฉพาะในเซิร์ฟเวอร์ได้

**ขั้นปัจจุบัน:** ผู้ใช้ติดตั้งเกมใน Windows LDPlayer แล้ว ใช้
[LDPLAYER_RESOURCES.md](LDPLAYER_RESOURCES.md) ตรวจ resource ที่ client เก็บไว้
ก่อนเลือก export คลาวด์ไม่สามารถเชื่อมกับ emulator บนเครื่องผู้ใช้โดยตรง

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
การตรวจ bootstrap ขั้นนี้ไม่ได้ execute APK/scripts/libraries

## ผล native และ request ภายหลัง

ได้รับ `config.arm64_v8a.apk` และตรวจ hash ตรงกับรายงานแล้ว Native references
ใน `libssr.so` ยืนยัน entry/version-config request ดังนี้:

```text
GET https://live-czn-entry2lx2fz.game.playstove.com:13001/cznlive
X-App-Id: cznlive
X-App-NS: ssr-stove-260930
```

มี query สำหรับ Android, package, build 811 และ buildx ตาม native environment
ค่า locale ใช้ `en` เป็นสมมติฐาน; device/publisher identifiers เว้นว่าง และไม่ได้
ส่ง optional permit token เพราะ shipped value ว่าง ดู provenance และข้อจำกัดที่
[CHAOS_NATIVE_ANALYSIS.md](research/CHAOS_NATIVE_ANALYSIS.md)
นี่คือ entry/config endpoint ยังไม่ใช่ URL asset CDN ที่ยืนยันแล้ว

ส่ง bounded GET จากคลาวด์หนึ่งครั้งแล้ว: proxy ปฏิเสธ CONNECT ด้วย 403 ก่อน TLS
หรือ response จาก game server จึงไม่ใช่หลักฐานว่าเกมปฏิเสธบัญชีหรือ URL ผิด
เพิ่ม hostname ตรงนี้ใน network draft แล้ว; saved draft ไม่ได้ยืนยัน runtime
propagation และยังไม่มี manifest/asset response ที่ตรวจ hash ได้

เครื่องมือสำหรับตรวจ request บนเครื่องผู้ใช้ (เป็นทางเลือก หากต้องการตรวจ entry):

```powershell
py .\tools\fetch_game_entry.py ".local/chaos-native/config.arm64_v8a.apk" --output ".local/chaos-entry-v1"
```

ต้องดาวน์โหลด helper นี้จาก repository รุ่นปัจจุบันก่อน เครื่องมือตรวจ source hash,
ใช้ endpoint/profile คงที่, TLS ปกติ, timeout 20 วินาที, body ไม่เกิน 1 MiB,
ไม่ตาม redirects และบันทึก `result.json` เพื่อแยก proxy error กับ upstream status
response เป็น reference data: ยังไม่ execute หรือแปลว่าได้ gameplay assets

## ทางเลือกตามชนิดข้อมูล

| สิ่งที่ต้องการ | วิธีที่ใช้ได้ | สิ่งที่ต้องรู้ก่อน |
|---|---|---|
| ไฟล์ patch/CDN ที่เผยแพร่ให้ client ดาวน์โหลด | อ่าน version/manifest ที่ระบุ endpoint จริง แล้วดาวน์โหลด files ตาม manifest | URL, version/region, paths, size/hash และรูปแบบ container |
| Resource ที่ client ต้องล็อกอินหรือรับ config ตอนรันก่อนโหลด | ใช้แอปทางการกับบัญชีที่ผู้ใช้มีสิทธิ์ ให้ดาวน์โหลด แล้วเก็บ manifest/resources ที่เข้าถึงได้ | การเข้าถึง storage ของอุปกรณ์และรูปแบบไฟล์; ไม่ส่ง password/token เข้าแชต |
| ข้อมูลบัญชีที่ API อนุญาตให้บัญชีนั้นอ่าน | API/export ที่มีสิทธิ์ตรงกับข้อมูล | documented endpoint และ authentication ที่จัดการในเครื่องผู้ใช้ |
| ฐานข้อมูลอื่นหรือ server-only logic | export, API หรือเอกสารจากผู้ดูแลระบบ | สิทธิ์จากเจ้าของระบบ; resource download ของ client ไม่ให้สิทธิ์นี้ |

การไม่มีเว็บไซต์ API ไม่ได้ปิดทางดาวน์โหลด binary ผ่าน HTTPS แต่การเพิ่ม domain
ใน cloud network settings ไม่ได้สร้าง endpoint, authentication หรือสิทธิ์เข้าถึง
เอง ในคลาวด์นี้ HTTPS ใช้งานได้บางปลายทาง แต่ entry request ถูก proxy ปฏิเสธ
และยังไม่มี asset manifest/schema ที่ยืนยัน การมี LDPlayer ช่วยให้ตรวจไฟล์ที่
แอปทางการดาวน์โหลดไว้แล้วได้โดยไม่ต้องแก้ปัญหา request เส้นทางนี้ก่อน

## ขั้นที่ทำต่อได้ตอนนี้

ไม่ต้องส่ง native APK ซ้ำ อ่าน [ผล native](research/CHAOS_NATIVE_ANALYSIS.md)
แล้วใช้ [LDPlayer inventory](LDPLAYER_RESOURCES.md) เพื่อระบุ resource paths จริง
ชื่อจาก native เช่น `main.jbin` และ `gameres/manifest.ssra` เป็นเพียง search
candidates ยังไม่ยืนยัน directory หรือว่ามีไฟล์เหล่านี้บนเครื่องผู้ใช้

ถ้า endpoint/config หาได้เฉพาะตอนรัน จะจัดขั้นตอนให้แอปทางการดาวน์โหลด patch
บนอุปกรณ์หรือ Android emulator ของผู้ใช้ ภาพ title ที่ส่งมาแสดงว่าเปิดเกมได้
แต่ไม่พิสูจน์ว่า resource ทุกหมวดถูกดาวน์โหลดครบ ยังไม่ทราบ directory ในเครื่องนี้
Android scoped storage/private app data อาจอ่านไม่ได้ด้วย `adb pull` ตามปกติ
จึงต้องตรวจ storage/access จริงก่อนสอน path หรือสัญญาว่าดึงได้ครบ

เมื่อเข้าถึงไฟล์ได้ ส่งเฉพาะ resource manifest และไฟล์ที่จำเป็นพร้อม source hash
ไม่ส่ง account database, credentials, session cookies หรือ traffic ทั้ง session
ถ้าพบ authentication, signed URL, rate/access restriction จะใช้ช่องทางที่ผู้ใช้
มีสิทธิ์หรือ file export ไม่ข้ามข้อจำกัดด้วยการแต่ง tokens หรือแก้ certificate pinning

ผลดาวน์โหลดจะเก็บใน `.local/` เพื่อวิจัย static ต่อ การมีไฟล์เพิ่มไม่ยืนยันว่า
server-only balance/logic หรือภาพ runtime ทั้งหมดอยู่ใน files และ assets อ้างอิง
จะไม่ถูก import เข้าเกม LoTM ต้นแบบโดยอัตโนมัติ
