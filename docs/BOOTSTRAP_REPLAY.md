# เปิด wireframe จากไฟล์ที่ส่งมา บน Windows

ทำใน PowerShell ที่อยู่โฟลเดอร์ repository เดิม หาก prompt ยังอยู่ `C:\Users\MSi`
ให้เปิดโฟลเดอร์ repository ใน Explorer คลิก address bar แล้ว copy path จากนั้น:

```powershell
Set-Location -LiteralPath (Get-Clipboard)
Test-Path .\README.md
Test-Path .\.local\chaos-bootstrap.zip
```

ทั้งสองรายการต้องเป็น `True` หาก ZIP อยู่ที่อื่น ใช้ path นั้นในคำสั่งขั้นที่ 2
เครื่องมือใช้ Python standard library ไม่ต้องติดตั้ง Unity, Cocos, Java หรือ APK emulator

## 1. ดาวน์โหลดเครื่องมือใหม่

```powershell
$researchTools = @("read_research_pack.py", "decode_csb.py", "render_csb_wireframe.py", "decode_texture.py")
foreach ($toolFile in $researchTools) {
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xKanomRoo/Lord-of-Mysteries-Roguelike-Deck-Building/main/tools/$toolFile" -OutFile ".\tools\$toolFile"
}
```

## 2. ตรวจ hash แล้วอ่านแพ็ก

```powershell
py .\tools\read_research_pack.py ".local/chaos-bootstrap.zip" --output ".local/chaos-bootstrap-read" --expected-input-sha256 "b95e115282272289c73abc1569b81a5bbf62b1f4f638c15d76cc2c7b2f120be0"
```

ผลที่คาด: `verified_file_count: 162` และ `verified_bytes: 4597705`
ค่า hash ยืนยัน contents ของ pack และ source identity ที่ index ระบุ ไม่ได้ hash
full XAPK ใหม่จากไฟล์นี้ เครื่องมือไม่ execute ไฟล์ที่ unpack

## 3. อ่านโครงสร้างฉาก

```powershell
py .\tools\decode_csb.py --pack-index ".local/chaos-bootstrap-read/pack-index.json" --output ".local/chaos-layouts"
```

ผลที่คาด: decoded scenes 18/18 และ nodes 474; อ่าน details ใน `layouts.json`

## 4. สร้างและเปิดภาพ

```powershell
py .\tools\render_csb_wireframe.py --layouts ".local/chaos-layouts/layouts.json" --output ".local/chaos-wireframes"
Invoke-Item .\.local\chaos-wireframes\index.html
```

เลือก scene จากรายการ ตรวจชื่อ/ขนาด/ตำแหน่ง/source ของ node และเปิดดู hidden nodes
ภาพเป็น wireframe ของ serialized layout ไม่ใช่ภาพที่จับจากเกมจริง
อ่าน [ผลวิเคราะห์และข้อจำกัด](research/CHAOS_BOOTSTRAP_ANALYSIS.md)

หากเคยรันแล้ว output directory ไม่ว่าง ให้เปลี่ยนชื่อ output เป็นชื่อใหม่ เช่น
`chaos-layouts-v2`, `chaos-wireframes-v2` และแก้ input path ขั้นถัดไปให้ตรง
เครื่องมือไม่ลบหรือเขียนทับผลเดิม ไม่ต้องแนบ ZIP เดิมซ้ำเพื่อดู wireframe

## ดูภาพ texture ที่ถอดได้ (ทำเพิ่มเมื่ออยากดู asset)

wireframe ไม่ต้องติดตั้ง decoder ภายนอก ส่วนการถอด SCT2 เป็น PNG ต้องใช้
`texture2ddecoder==1.0.6` เพิ่ม เลือก virtual environment ภายใน `.local`:

```powershell
py -m venv .local\texture-venv
.\.local\texture-venv\Scripts\python.exe -m pip install "texture2ddecoder==1.0.6"
```

หา path ของภาพ title ผ่าน pack index แล้วถอดโดยไม่รันเกม:

```powershell
$packFiles = Get-Content -Raw ".local/chaos-bootstrap-read/pack-index.json" | ConvertFrom-Json
$titleTexture = $packFiles.files | Where-Object { $_.original_path -eq "assets/pre/ui/title_terrascion.sct" }
.\.local\texture-venv\Scripts\python.exe .\tools\decode_texture.py (Join-Path ".local/chaos-bootstrap-read" $titleTexture.stored_path) --output ".local/chaos-title-texture" --decode-astc
Invoke-Item .\.local\chaos-title-texture\texture.png
```

ภาพที่ได้คือ title resource 1604×852 ไม่ใช่หน้าจอที่รวม UI แล้ว อย่านำภาพอ้างอิง
เข้าเกมต้นแบบอัตโนมัติ เก็บไว้ใน `.local` ซึ่ง Git ignore อยู่

## ส่งงานให้ Codex ต่อ

```text
อ่าน AGENTS.md และ docs/research/CHAOS_BOOTSTRAP_ANALYSIS.md
ใช้ decoded layouts เป็นหลักฐานสำหรับ title/download/modal UX เท่านั้น
เสนอการปรับต้นแบบด้วยภาพและข้อความใหม่ พร้อมแยก observed/inferred/original-design
อย่าอ้างว่า battle/card rules หรือ lore canon ถูกถอดจาก bootstrap pack แล้ว
```
