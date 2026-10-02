# ขั้นถัดไป: ตรวจ native reader ของเกม

ผู้ใช้เลือกวิจัย APK ต่อเพื่อหาข้อมูลการ์ดและฉากต่อสู้ หลังถอด bootstrap UI แล้ว
เป้าหมายรอบนี้คือหา evidence ว่า client อ่าน `sdata` และ `init.jbin` อย่างไร
ก่อนเลือกข้อมูลเพิ่มเพื่อถอด gameplay ไม่ได้ยืนยันว่า card rules อยู่ใน native code
หรือว่า APK จะมี content ที่โหลดจาก server ครบ

## ทำไมขอไฟล์นี้

รายงานรอบสองมี `config.arm64_v8a.apk` ขนาด **22,979,689 bytes / 21.92 MiB**
ส่งเข้าแชตได้ภายใต้ขีดจำกัด 32 MiB โดยไม่แบ่งไฟล์ ภายใน inventory ระบุ
`lib/arm64-v8a/libssr.so` 63,082,720 bytes และ `librhcore.so` 5,856,848 bytes
native libraries บีบอัดอยู่ใน APK นี้ ไม่ต้องส่ง `.so` ที่ขยายแล้วแยก
ยังไม่สรุปหน้าที่ของ library จากชื่อเพียงอย่างเดียว

ข้อมูลที่มีแล้วเพิ่มเหตุผลให้ตรวจ reader: sdata เล็กทั้ง 7 ไฟล์มีท้ายไฟล์ 518 bytes
ที่ XOR ด้วย `0x76` แล้วอ่านเป็น hexadecimal ได้ 259 bytes เริ่มด้วย `10 00 10`
ตามด้วย 256 bytes ที่แตกต่างกันในแต่ละไฟล์ ส่วนก่อนท้ายนี้มีขนาด modulo 16 = 8
นี่เป็น observed container pattern ไม่พิสูจน์ encryption, key, compression หรือ
card schema จึงไม่ขอ blobs ใหญ่ทั้ง 49.84 MiB ก่อนเข้าใจรูปแบบ

## Windows: ทำตามสี่ขั้นนี้

### 1. อยู่ในโฟลเดอร์ repository ให้ถูกต้อง

ใน Explorer เปิดโฟลเดอร์ที่มี `README.md`, `tools`, XAPK คลิก address bar
หรือกด `Ctrl+L` แล้ว `Ctrl+C` จากนั้นใน PowerShell:

```powershell
Set-Location -LiteralPath (Get-Clipboard)
Test-Path ".\Chaos+Zero+Nightmare_1.0.811_APKPure.xapk"
Test-Path ".\.local\chaos-report-v2\report.json"
```

ทั้งสองรายการต้องเป็น `True` ถ้ารายงานอยู่ที่อื่น ให้แก้ `--report` ในขั้นที่ 3
ให้ตรงกับไฟล์จริง ไม่ต้องสร้าง inventory เดิมซ้ำเมื่อ source XAPK ไม่เปลี่ยน

### 2. ดาวน์โหลด helper และไฟล์ที่ใช้ร่วมกัน

```powershell
$apkResearchTools = @("analyze_apk.py", "create_research_pack.py", "extract_nested_apk.py")
foreach ($toolFile in $apkResearchTools) {
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/$toolFile" -OutFile ".\tools\$toolFile"
}
```

helper ใช้ Python standard library ตัวเดิม ไม่ต้องติดตั้ง Android emulator

### 3. แยก native APK พร้อมตรวจ hash

```powershell
py .\tools\extract_nested_apk.py "Chaos+Zero+Nightmare_1.0.811_APKPure.xapk" --report ".local/chaos-report-v2/report.json" --entry "config.arm64_v8a.apk" --output ".local/chaos-native/config.arm64_v8a.apk"
```

เครื่องมือ hash XAPK เทียบกับ report, ตรวจ ZIP metadata, CRC และ hash ของ APK
ที่แยกก่อนสร้าง output จำกัด 30 MiB และไม่เขียนทับผลเดิม หาก path นี้มีแล้วให้
เปลี่ยนเป็น directory ใหม่ เช่น `.local/chaos-native-v2/config.arm64_v8a.apk`

ผลที่คาดตาม report:

- bytes: `22979689`
- SHA-256: `6ef56d50d15168a8c29c080f8e621468876263de14410998fbc99ecca6179908`

หาก hash ไม่ตรง เครื่องมือจะหยุด ให้ตรวจว่าใช้ XAPK และ report คู่เดียวกัน
ไม่แก้ expected hash เพื่อข้ามการตรวจ

### 4. ส่งไฟล์ที่แยกกลับเข้าแชต

```powershell
Invoke-Item .\.local\chaos-native
```

แนบ **config.arm64_v8a.apk** จากโฟลเดอร์ที่เปิด ไม่ใช่ XAPK ทั้งก้อน
ไม่ต้องเปิดหรือติดตั้ง APK เพื่อส่งไฟล์

## สิ่งที่จะตรวจเมื่อได้รับ APK นี้

1. ตรวจ hash เทียบรายงาน แล้วอ่าน ELF architecture, sections และ symbols
2. ตรวจ references ที่สัมพันธ์กับ `PLPcK`, CSLoader และ container pattern ที่พบ
   โดยไม่ execute library, bootstrap scripts หรือเรียก backend
3. หากได้ schema/reader ที่ตรวจได้ จึงเลือก sdata ที่จำเป็นและทดลอง decode
4. แยก observed, inferred และ unknown หากข้อมูล battle/card อยู่ใน downloaded
   resources หรือยังอ่านไม่ได้ จะรายงานข้อจำกัดแทนการแต่งกฎว่าเป็นของต้นฉบับ

คลาวด์นี้มี `readelf`, `nm`, `objdump`, `strings` และ `file` สำหรับเริ่มตรวจ static
ยังไม่ได้ติดตั้ง Ghidra/radare2 และยังไม่ได้รับ native APK จริงเพื่อทดสอบเครื่องมือ
การแยก archive ผ่าน synthetic fixtures; ขนาด/hash ที่คาดข้างต้นมาจากรายงานผู้ใช้
เก็บ APK, libraries, strings และผลวิเคราะห์ใน `.local/` ไม่ import เข้าเกมหรือ Git

หากข้อมูลไม่ได้อยู่ใน APK อ่าน [การรับ resource หลังติดตั้ง](SERVER_RESOURCES.md)
ซึ่งแยก public patch/CDN, resource ที่ client ดาวน์โหลดด้วยสิทธิ์ของผู้ใช้ และ
ข้อมูลภายในเซิร์ฟเวอร์ พร้อมผลตรวจ bootstrap patch symbols ที่มีแล้ว
