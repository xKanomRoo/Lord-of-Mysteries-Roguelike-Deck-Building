# เก็บบัญชีและเซฟออนไลน์ด้วยงบเริ่มต้นน้อย

เกมใน `mobile/` เป็นแอป Godot native ที่ติดตั้งเป็น APK และเล่นออฟไลน์ได้
บริการออนไลน์ที่เตรียมไว้คือ **บัญชีผู้เล่นและสำรองเซฟส่วนตัว** ด้วย Supabase Auth
กับ PostgreSQL ไม่ต้องเช่า VPS หรือเขียนเซิร์ฟเวอร์ Node เพิ่มสำหรับขั้นแรก
ยังไม่มีบริการที่เปิดใช้งานจริงจนกว่าคุณจะสร้างโปรเจกต์และใส่ public configuration

```text
APK บนมือถือ ── HTTPS + session ผู้เล่น ── Supabase Auth
             └─ HTTPS + session ผู้เล่น ── cloud_saves
                                           └─ อ่าน/เขียนได้เฉพาะเจ้าของ
```

ตัวเกม กฎ และภาพต้นฉบับอยู่ใน APK เซิร์ฟเวอร์เก็บเพียง JSON เซฟขนาดเล็กของแต่ละบัญชี
ไม่ต้องอัปโหลด APK, ไฟล์ Chaos Zero Nightmare หรือไฟล์นิยายทั้งเรื่องลงฐานข้อมูล
เลือก Supabase Free สำหรับการทดลองได้ แต่ตรวจโควตา การพักโปรเจกต์ และเงื่อนไขปัจจุบัน
ใน [หน้าราคาอย่างเป็นทางการ](https://supabase.com/pricing) ก่อนเปิดให้คนจำนวนมากใช้
เอกสารราคาเปิดจาก cloud งานนี้ไม่สำเร็จ จึงไม่อ้างจำนวนผู้เล่นหรือพื้นที่ฟรีที่ยืนยันไม่ได้

## 1. สร้างฐานข้อมูลของคุณ

1. เข้า [Supabase Dashboard](https://supabase.com/dashboard) จากเบราว์เซอร์บนเครื่องคุณ
   สร้างบัญชีและโปรเจกต์ เลือกแผน Free และภูมิภาคใกล้ผู้เล่น เช่น Singapore หากมีให้เลือก
2. ไปที่ SQL Editor คัดลอก [schema.sql](../backend/supabase/schema.sql) แล้วกด Run **ครั้งเดียว**
   ไฟล์นี้สร้าง `public.cloud_saves`, RLS และ trigger ตรวจ revision ไม่มีข้อมูลจริงของผู้เล่นในไฟล์
   อย่ารัน `test_local.sql` ในโปรเจกต์จริง เพราะเป็น fixture สำหรับฐานข้อมูลทดสอบเท่านั้น
3. ไป Authentication เปิด Email sign-up/sign-in และ **Anonymous sign-ins**
   หากต้องการเปลี่ยน guest เป็นบัญชีอีเมล ให้เปิด manual linking ตามการตั้งค่าของ Auth
   คงขั้นตอนยืนยันอีเมลไว้ และตั้งค่าการส่งอีเมล/SMTP หาก Dashboard แจ้งว่าจำเป็น
4. จากหน้า Connect หรือ API Settings คัดลอก **Project URL** และ **publishable key**
   หรือ legacy `anon` public key เท่านั้น ห้ามใส่ `service_role`, `sb_secret_...`,
   รหัสผ่านฐานข้อมูล หรือ access/refresh token ใน APK หรือ Git

RLS จำกัดแต่ละ session ให้เข้าถึง `user_id = auth.uid()` แม้ public key อยู่ใน APK
คีย์ public เป็นตัวระบุแอปที่แจกได้ ส่วน session ของผู้เล่นสร้างหลังเข้าสู่ระบบ
ถูกเก็บใน app-private `user://cloud-session.json` และไม่เข้า repository

## 2. ใส่ public configuration แล้วสร้าง APK ใหม่

คัดลอก `mobile/cloud-config.example.json` เป็น `mobile/cloud-config.json`:

```json
{
  "base_url": "https://YOUR-PROJECT.supabase.co",
  "public_key": "sb_publishable_YOUR_PUBLIC_KEY"
}
```

ไฟล์จริงถูก Git ignore แทนค่าด้วยข้อมูลโปรเจกต์ของคุณ แล้วสร้าง APK ตาม
[ANDROID_BUILD.md](ANDROID_BUILD.md) ตัว APK ที่สร้างก่อนใส่ configuration ยังเล่นออฟไลน์ได้
และจะไม่เชื่อมต่อโปรเจกต์ของคุณเองโดยอัตโนมัติ HTTPS ตรวจ certificate/hostname;
HTTP ธรรมดาและ service-role key ถูกปฏิเสธ

หากใช้ GitHub Actions ให้เข้า repository → Settings → Secrets and variables → Actions → Variables
เพิ่ม **`SUPABASE_URL`** และ **`SUPABASE_PUBLISHABLE_KEY`** เป็น repository variables
แล้วรัน workflow **Build Android APK** ใหม่ ดูขั้นตอนใน
[START_NEXT_ANDROID.md](START_NEXT_ANDROID.md) workflow สร้าง public configuration ให้ระหว่าง build
อย่าเก็บ session หรือรหัสผ่านผู้เล่นใน Actions configuration
public URL/key เปิดเผยได้ แต่ควรแยกโปรเจกต์ทดสอบกับโปรเจกต์ที่มีผู้เล่นจริง

## 3. ทดลองบัญชีและเซฟบนมือถือ

1. เปิด APK เล่นหนึ่ง run และเปิดหน้าต่าง **Cloud**
2. กด **Guest** สำหรับการทดลอง หรือ **Register** ด้วยอีเมล/รหัสผ่าน
   หากต้องยืนยันอีเมล ให้เปิดอีเมลยืนยัน แล้วกลับมากด **Login**
   Register ขณะอยู่ใน guest จะขอผูกอีเมลกับ guest เดิมเพื่อรักษาเจ้าของเซฟ
3. แอปตรวจว่าบัญชีนี้มี backup หรือยัง จากนั้นกด **Back up** เพื่อส่งเซฟของเครื่องนี้
   แอปไม่แทนที่เซฟในมือถือเองเมื่อเข้าสู่ระบบ
4. เปิด SQL Editor หรือ Table Editor ใน Dashboard ตรวจว่ามีแถวของบัญชีนี้
   `revision` เริ่มที่ 1 และเพิ่มครั้งละ 1 เมื่อ backup สำเร็จ
5. หากใช้บัญชีอีเมลเดียวกันบนอีกมือถือ กด Login แล้ว **Check** และ **Restore**
   Restore ต้องยืนยันก่อนแทนที่เซฟในเครื่อง

Guest ใช้ได้กับ session เดิมในเครื่องเดิมเท่านั้น การลบแอป/ข้อมูล หรือ Clear session
ก่อนผูกอีเมลทำให้เข้าถึง guest backup เดิมไม่ได้ รหัสผ่านขั้นต่ำใน UI คือ 8 ตัวอักษร;
ตั้งค่ากฎรหัสผ่านฝั่ง Supabase เพิ่มได้ตามที่ต้องการ

เมื่อสองเครื่องเขียนพร้อมกัน แอปส่ง revision ที่อ่านล่าสุดไปกับ PATCH
เครื่องที่เขียนช้าจะพบ conflict และต้อง Check ใหม่ การเขียนที่ขาดการตอบกลับก็ต้อง Check ใหม่
ไม่ retry โดยเขียนทับทันที เซฟในเครื่องยังอยู่เมื่อ offline, timeout หรือ request ล้มเหลว

## ขอบเขตของระบบนี้และค่าใช้จ่าย

นี่เป็น **cloud backup** ไม่ใช่ multiplayer แบบเล่นพร้อมกัน และไม่ใช่ระบบป้องกันโกง
ผู้เล่นยังควบคุม client และเซฟของตนได้ อย่านำเงินพรีเมียม การซื้อของ อันดับแข่งขัน
หรือรางวัลที่มีมูลค่าไปเชื่อข้อมูลใน JSON นี้ หากเพิ่มระบบเหล่านั้นภายหลัง ต้องมี API
ฝั่งเซิร์ฟเวอร์ที่ตรวจธุรกรรมและคำนวณผลที่สำคัญเอง

เริ่มด้วยการ backup ตามที่ผู้เล่นกดหรือจบ run แทนการส่งทุกครั้งที่กดการ์ด
adapter จำกัดเซฟ 64 KiB, response 256 KiB, timeout 15 วินาที และมี request ได้ครั้งละหนึ่งงาน
ฐานข้อมูลกำหนดเพดาน JSON 128 KiB เพื่อเผื่อรูปแบบจัดเก็บของ PostgreSQL
`cloud_saves.schema_version = 1` คือรุ่นของ protocol จัดเก็บ ส่วนรุ่นเซฟเกมอยู่ภายใน
`payload` และ adapter ใช้ `SAVE_VERSION`/`ENGINE_ID` จาก engine เดียวกับ APK
เซฟจาก engine ที่ไม่รองรับถูกปฏิเสธ; การอัปเดตเกมภายหลังต้องเพิ่ม migration ก่อนรับเซฟรุ่นเก่า
ไม่เก็บนิยาย ภาพ เกมอ้างอิง หรือข้อมูล research ในเซฟผู้เล่น
ตรวจ usage ใน Dashboard และสำรองข้อมูลของคุณก่อนพ้นโควตาหรือเปลี่ยนแผน

## ตรวจระบบก่อนแจก

รัน fixture ของ adapter โดยไม่ใช้บัญชีหรือเครือข่าย:

```bash
bash tools/setup_android.sh --force-local-godot
mkdir -p .local/cloud-tests/data .local/cloud-tests/config .local/cloud-tests/cache
gray_fog_godot=$(python3 -c 'import json; print(json.load(open(".local/android-tools/toolchain-paths.json"))["godot"])')
XDG_DATA_HOME="$PWD/.local/cloud-tests/data" \
XDG_CONFIG_HOME="$PWD/.local/cloud-tests/config" \
XDG_CACHE_HOME="$PWD/.local/cloud-tests/cache" \
"$gray_fog_godot" --headless --path mobile --editor --import --quit
XDG_DATA_HOME="$PWD/.local/cloud-tests/data" \
XDG_CONFIG_HOME="$PWD/.local/cloud-tests/config" \
XDG_CACHE_HOME="$PWD/.local/cloud-tests/cache" \
"$gray_fog_godot" --headless --path mobile --script res://tests/test_cloud_save.gd
```

fixture ทดสอบ auth response, HTTPS/public-key checks, session refresh,
read-before-write, stale revision/conflict, payload bounds, และ request ที่ซ้อนกัน
SQL runtime fixture ใช้ฐานข้อมูล PostgreSQL เปล่าในเครื่องเท่านั้น ต้องมี `psql`
และบัญชี superuser ของฐานข้อมูลทดสอบแยก เพราะ fixture สร้าง roles จำลองแล้ว rollback:

```bash
python3 backend/supabase/run_local_test.py --dsn 'dbname=gray_fog_test'
```

ผลที่ตรวจในงานนี้: Godot 4.6.3 ผ่าน protocol fixtures **41 checks** โดยไม่ติดต่อเครือข่าย
และ PostgreSQL 17.11 ที่เปิดเฉพาะ Unix socket ใน cloud ผ่าน SQL fixtures **18 checks**
รวมการเข้าถึงข้ามบัญชี การแก้ revision เก่า สิทธิ์คอลัมน์ และเพดาน payload
fixture rollback ทั้งหมดแล้วและปิดฐานข้อมูลทดสอบ ผลนี้ยังไม่ใช่การทดสอบโปรเจกต์ Supabase จริง

หลังตั้งโปรเจกต์จริง ให้ทดสอบสองบัญชีและสองมือถือ: บัญชี A ต้องอ่าน/แก้ backup ของ B ไม่ได้,
การเขียนจาก revision เก่าต้องไม่เปลี่ยนแถวใหม่, เปิด airplane mode แล้วยังเล่น/เซฟในเครื่องได้
ผล fixture ใน cloud ไม่แทนการทดสอบ TLS, Auth settings และอีเมลของโปรเจกต์จริง

อ้างอิง: [Anonymous sign-ins](https://supabase.com/docs/guides/auth/auth-anonymous),
[Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security),
[API keys](https://supabase.com/docs/guides/api/api-keys),
[REST API](https://supabase.com/docs/guides/api).
