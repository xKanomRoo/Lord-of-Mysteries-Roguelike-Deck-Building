# ขั้นถัดไป: Android APK และเซฟออนไลน์

ตัวเกม Android อยู่ที่ `mobile/` เป็น Godot native ใช้ UI และ engine ในเครื่อง
ไม่ต้องเปิดเว็บไซต์เพื่อเล่น APK บรรจุภาพและข้อมูลการ์ดที่เราออกแบบเอง
การอ่าน APK อ้างอิงและนิยายเป็นงานวิจัยแยกจากไฟล์ที่แจกให้ผู้เล่น

## 1. ติดตั้งและเล่นบนมือถือก่อน

ดาวน์โหลด `gray-fog-debug.apk` จากผล build ที่แนบในแชต หรือ GitHub Actions
ส่งไฟล์ไปมือถือ Android แล้วเปิดด้วยแอป Files ของมือถือ
หากระบบถาม ให้เปิดสิทธิ์ติดตั้งแอปสำหรับแอป Files ที่ใช้เปิด APK แล้วติดตั้ง
เปิด **Beyond the Gray Fog** และลองเล่นหนึ่ง run, บันทึก, ปิดแอป และโหลดเซฟ
คำแนะนำละเอียดและวิธี build อยู่ที่ [ANDROID_BUILD.md](ANDROID_BUILD.md)
เลือกสายการเล่นและอ่านคอมโบ/อีเวนต์ที่ [CONTENT_DESIGN.md](CONTENT_DESIGN.md)

APK debug ใช้ทดสอบส่วนตัว การอัปเดตแอปเดิมต้องใช้ package ID และ signing key
เดิม เก็บ keystore ส่วนตัวไว้นอก Git; การลบแอปจะลบเซฟในเครื่องด้วย
ก่อนแจกจริงให้สร้าง release signing key ที่เก็บถาวรและ build รุ่น release

## 2. ใช้นิยายเป็นข้อมูลให้ Codex

นำเข้าข้อความจีนด้วยเครื่องมือที่ [LORE_SOURCES.md](LORE_SOURCES.md) อธิบาย
ดัชนีเก็บไว้ใน `.local/` ค้นชื่อ/ศัพท์ภาษาจีน แล้วแนบเฉพาะข้อความที่เกี่ยวข้อง
พร้อม source hash, บทและตำแหน่งให้ Codex ใช้ประกอบการออกแบบ
ดู [ใบรับแหล่งนิยาย](research/LOTM_COI_SOURCE_RECEIPT.md)

ไฟล์ที่ได้รับเป็นข้อความตามที่ผู้ใช้ระบุชื่อเรื่อง ยังไม่ยืนยัน edition,
ความครบถ้วนหรือความถูกต้องกับฉบับสำนักพิมพ์ การมีดัชนีช่วยค้น context
ไม่ได้เปลี่ยนน้ำหนักโมเดล และตัวเกมไม่บรรจุนิยายเต็มเรื่อง

## 3. เปิดบัญชีและเซฟออนไลน์

ใช้ Supabase Free เป็นจุดเริ่มต้น ทำตาม [ONLINE_BACKEND.md](ONLINE_BACKEND.md):
สร้างโปรเจกต์, รัน SQL ของเรา, ตั้ง Auth และใส่ Project URL/public key
จากนั้น build APK ที่มี config แล้วทดสอบสองบัญชีแยกกัน หากใช้ GitHub:

1. เข้า repository → Settings → Secrets and variables → Actions → Variables
2. เพิ่ม `SUPABASE_URL` และ `SUPABASE_PUBLISHABLE_KEY` เป็น repository variables
   ใช้เฉพาะ URL กับ publishable/anon public key จากโปรเจกต์ของคุณ
3. ไป Actions → **Build Android APK** → **Run workflow** เลือก `main`
4. เมื่อ build ผ่าน ดาวน์โหลด artifact `gray-fog-debug-apk`, แตก ZIP และติดตั้ง APK

ถ้ายังไม่ตั้งสอง variables นี้ workflow จะสร้างเกมสำหรับเล่นออฟไลน์
ข้อมูลในฐานนี้เป็นเซฟของเกมเรา ไม่ใช่ backend ของ Chaos Zero Nightmare

ในรุ่นเริ่มต้น เซิร์ฟเวอร์ทำงานเมื่อสมัคร/ล็อกอิน/อัปโหลดหรือโหลดเซฟ
ไม่ต้องส่งทุกเฟรมหรือเปิดเครื่องเกมไว้ตลอดเวลา ผู้เล่นจึงเล่นต่อแบบออฟไลน์ได้
แยก player data จากข้อมูลใน APK ตามนี้:

| ข้อมูล | ตำแหน่งเริ่มต้น |
| --- | --- |
| ภาพ, เสียง, UI, การ์ดและกฎของเรา | ใน APK |
| บัญชีและข้อมูลยืนยันตัวตน | Supabase Auth |
| เซฟที่ต้องการข้ามเครื่อง | private table ที่ตรวจเจ้าของทุก request |
| นิยายเต็มและ assets เกมอ้างอิง | private research storage ของผู้พัฒนา |

เซฟจาก client ยังไม่ใช่หลักฐานตรวจโกง สำหรับเงินที่ซื้อจริง,
leaderboard หรือ PvP ต้องเพิ่มการตรวจผลฝั่งเซิร์ฟเวอร์ก่อนนำมาใช้
รุ่นนี้เป็นออนไลน์สำหรับบัญชีและเซฟ; multiplayer แบบ realtime เป็นงานเพิ่มต่างหาก

## 4. คุมค่าใช้จ่าย

เริ่มด้วย Android sideload และเซฟขนาดเล็ก เก็บเซฟล่าสุดต่อผู้เล่น
ส่งข้อมูลเมื่อผู้เล่นกดสำรองหรือโหลด ใช้ APK แจก assets แทนดาวน์โหลดจากฐานข้อมูล
ตั้งการแจ้งเตือน usage และตรวจโควตา database/storage/egress/active users
ใน dashboard ก่อนเปิดให้คนจำนวนมากใช้

แพ็กเกจฟรีมีข้อจำกัด และเงื่อนไขอาจเปลี่ยนตามผู้ให้บริการ
เราไม่ได้ยืนยันตัวเลขโควตาปัจจุบัน เพราะเอกสาร pricing ถูก cloud proxy ปฏิเสธ
ดู [Supabase pricing](https://supabase.com/pricing) และ
[GitHub Actions billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions)
ก่อนเพิ่มผู้เล่นหรือเปิด build อัตโนมัติ คู่มือแนะนำ workflow แบบกดเองเพื่อควบคุม build

งานใน repository เตรียม source/build/backend schema ให้แล้ว การเปิดบริการจริง
ยังต้องสร้างบัญชีและโปรเจกต์ Supabase ของคุณเอง ไม่มี project credentials อยู่ในแชตนี้
