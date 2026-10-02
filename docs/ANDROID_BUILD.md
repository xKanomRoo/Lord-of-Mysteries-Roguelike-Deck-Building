# สร้างและติดตั้งเกม Android แบบ native

เกมมือถืออยู่ที่ `mobile/` เป็น Godot 4.6.3 และใช้ ARM64 Godot engine โดยตรง
APK ไม่ได้เปิดหน้าเว็บหรือใช้ Android WebView เป็นหน้าจอเกม การเล่นออฟไลน์ไม่ต้องมีบัญชี
ส่วนการซิงก์เซฟออนไลน์เป็นบริการแยกต่างหาก ดูขั้นตอนใน
[START_NEXT_ANDROID.md](START_NEXT_ANDROID.md)

## ติดตั้ง APK บนมือถือ

1. นำไฟล์ `gray-fog-debug.apk` ที่สร้างแล้วไปไว้ในมือถือ เช่นผ่านสาย USB หรือดาวน์โหลด artifact จาก GitHub Actions
2. เปิดไฟล์ด้วยแอป Files ของมือถือ แล้วอนุญาต **Install unknown apps** ให้แอปที่ใช้เปิดไฟล์นี้
3. กดติดตั้งแล้วเปิด **Beyond the Gray Fog** เกมแสดงผลแนวนอน

รุ่นนี้รองรับ **Android 7.0 / API 24 ขึ้นไปและระบบ ARM64** เครื่อง Android แบบ 32-bit
และ Android emulator แบบ x86 ไม่อยู่ใน APK นี้ ก่อนติดตั้งใน emulator ให้ตรวจ ABI ก่อน:

```powershell
$ldAdbPath = "D:\LDPlayer\LDPlayer14\adb.exe"
& $ldAdbPath -P 5037 -s "emulator-5554" shell getprop ro.product.cpu.abilist
```

ถ้าเครื่องรองรับ `arm64-v8a` หรือมีตัวแปลง ARM64 ที่ใช้งานได้ สามารถลองติดตั้งด้วย:

```powershell
& $ldAdbPath -P 5037 -s "emulator-5554" install -r "$env:USERPROFILE\Downloads\gray-fog-debug.apk"
```

`-r` ขออัปเดตแอปและรักษาข้อมูลเดิม แต่ Android จะยอมอัปเดตเฉพาะ APK ที่มี package ID
และกุญแจลงนามเดียวกัน หากขึ้น `INSTALL_FAILED_UPDATE_INCOMPATIBLE` ให้ตรวจเรื่องกุญแจ
ก่อน อย่าลบแอปทันที เพราะการลบอาจลบเซฟออฟไลน์ไปด้วย

## สร้างซ้ำใน cloud หรือ GitHub Actions

จาก repository บน Linux x86_64 ซึ่งมี Python 3.12+ และ curl:

```bash
bash tools/setup_android.sh
bash tools/build_android.sh
```

ผลลัพธ์:

- `.local/android-artifacts/gray-fog-debug.apk`: APK ที่ลงนามแล้ว
- `.local/android-artifacts/gray-fog-debug.apk.sha256`: checksum สำหรับตรวจไฟล์ที่ดาวน์โหลด
- `.local/android-artifacts/gray-fog-debug.verification.json`: SHA-256, manifest, native engine และผลตรวจลายเซ็น
- `.local/android-artifacts/gray-fog-debug.build.log`: บันทึก import/export ของ Godot

สคริปต์ setup ดาวน์โหลดเฉพาะเครื่องมือทางการผ่าน HTTPS แล้วตรวจ checksum ก่อนแตกไฟล์
พร้อมจำกัดขนาด download/จำนวนไฟล์/ขนาดหลังแตกและเวลา download ตาม profile
เครื่องมือทั้งหมดอยู่ใน `.local/android-tools/` ซึ่ง Git ไม่ติดตาม ไม่ต้องติดตั้ง Android Studio
หรือแก้ Java ของระบบ สคริปต์สามารถใช้ Godot ที่ติดตั้งอยู่ได้เมื่อ version ตรงกัน
หรือดาวน์โหลด official editor รุ่นที่กำหนดเองเมื่อไม่มี

การรัน setup ยอมรับ [Android SDK License](https://developer.android.com/studio/terms)
สำหรับ SDK ของ Google และบันทึกสถานะใน cache ของงานนี้
ไม่มีการเผยแพร่ขึ้น Play Store หรือเปิดบริการออนไลน์โดยคำสั่ง build นี้

| เครื่องมือ | รุ่นที่กำหนด |
|---|---|
| Godot editor และ export templates | 4.6.3 stable, official `7d41c59c4` |
| Eclipse Temurin JDK | 17.0.18+8 |
| Google command-line tools | 17.0 / 12700392 |
| Android Build Tools | 36.0.0 |
| Android platform | API 36, ext19 r01 |
| Android Platform Tools | 37.0.1 |
| APK package ID | `org.grayfog.deckbuilder` |
| APK version | 0.2.0 / code 2 |
| Minimum / target API | 24 / 36 |
| Native architecture | `arm64-v8a` |

URL และ hashes ทั้งหมดอยู่ใน [android-toolchain.json](../tools/android-toolchain.json)
Google SHA-1 อ้างจาก official repository descriptor และบันทึก SHA-256 ของ archive ที่ตรวจแล้ว
Godot ใช้ official SHA-512 checksum และ JDK ใช้ official SHA-256 checksum
APK ใช้ direct Godot template export โดยไม่ต้อง build Gradle project

## รักษากุญแจสำหรับการอัปเดต

APK นี้เป็น **debug build สำหรับทดสอบ** ไม่ใช่ release ที่พร้อมลงร้านค้า
setup สร้างกุญแจทดสอบไว้ที่ `.local/android-tools/debug.keystore` และใช้ standard debug alias
`androiddebugkey` / password `android` กุญแจนี้ไม่เข้า Git และไม่อยู่ใน APK artifact
เก็บสำรองกุญแจอย่างเป็นส่วนตัวหากจะออกอัปเดตด้วย package ID เดิม

runner ของ GitHub Actions เป็นเครื่องใหม่ทุกครั้ง จึงต้องคืนกุญแจเดิมเพื่ออัปเดตแอปที่ติดตั้งไว้
setup รองรับ environment variable `GRAY_FOG_DEBUG_KEYSTORE_B64` สำหรับกุญแจทดสอบที่เข้ารหัสเป็น
Base64 ซึ่งเก็บใน **Actions secret** ได้ ถ้าไม่ใส่ จะสร้างกุญแจใหม่และยัง build ได้ แต่ลายเซ็น
จะแตกต่างกันในแต่ละครั้ง สคริปต์ไม่พิมพ์กุญแจหรือ Base64 ในบันทึก และไม่แทนที่กุญแจเดิมเงียบ ๆ
workflow ใน repository นี้อ่าน Actions secret ชื่อ `ANDROID_DEBUG_KEYSTORE_B64`
แล้วส่งให้ setup ผ่าน `GRAY_FOG_DEBUG_KEYSTORE_B64`; ใส่ Base64 ของ keystore เดิม
ใน secret นี้ผ่านหน้า Settings ของ GitHub โดยไม่ใส่ใน Git หรือแชต
เมื่อจะปล่อยให้ผู้เล่นจริง ต้องจัดทำ release key แยกต่างหากและรักษาไว้สำหรับอัปเดตระยะยาว

## สิ่งที่การตรวจ APK ยืนยัน

build ตรวจว่าทุก member ผ่าน CRC, ลายเซ็น APK ถูกต้อง, package/API/แนวนอนตรงกับ preset,
มี `lib/arm64-v8a/libgodot_android.so`, มี Godot project และ game script,
และ `data/content.json` ใน APK ตรงกับ source ทุก byte พร้อมตรวจ 3 pathways, 54 cards,
21 enemies, 12 events และ 12 relics
มี Internet permission สำหรับ cloud save ที่เลือกเปิดใช้ ไม่มี HTML/JavaScript สำหรับหน้าจอเกม
และ Java payload ตรงกับ official Godot template
ค่า SHA-256 ของ native engine/libraries ARM64 ตรงกับ official template ด้วย
ค่า SHA-256 ของ DEX ทุกไฟล์ตรงกับ template จึงไม่มี Java wrapper เพิ่มเข้ามาในขั้นตอน export นี้
ตัว engine ทางการมี Android support classes ที่อ้างถึง WebView อยู่แล้ว จึงไม่ใช้การพบชื่อ
WebView เพียงอย่างเดียวเป็นข้อสรุปว่าหน้าจอเกมทำด้วยเว็บ
การตรวจนี้เป็นการตรวจไฟล์และการ export; ยังต้องทดลองเปิดและเล่นบนมือถือจริงเพื่อยืนยัน
touch, ความลื่นไหล, สัดส่วนจอ และการเชื่อมต่อบริการออนไลน์บนเครื่องนั้น
