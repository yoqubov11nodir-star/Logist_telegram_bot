# 🚛 OMON Logistics Bot

Telegram orqali ishlaydigan to'liq logistika boshqaruv tizimi.  
Buyurtma yaratishdan tortib to'lovgacha bo'lgan barcha jarayonlar avtomatlashtirilgan.

---

## 📁 Loyiha tuzilmasi

```
LogisticsBot/
├── main.py                         # Asosiy kirish nuqtasi
├── requirements.txt                # Kutubxonalar
├── .env.example                    # Muhit o'zgaruvchilari namunasi
│
├── database/
│   ├── models.py                   # SQLAlchemy modellari
│   └── session.py                  # DB ulanish
│
└── bot/
    ├── handler/
    │   ├── logist.py               # Logist handlerlari
    │   ├── dispatcher.py           # Dispetcher handlerlari
    │   ├── driver.py               # Haydovchi handlerlari
    │   ├── cashier.py              # Kassir handlerlari
    │   ├── founder.py              # Founder handlerlari
    │   └── client.py               # Mijoz handlerlari
    │
    ├── keyboards/
    │   ├── logist_kb.py
    │   ├── dispatcher_kb.py
    │   ├── driver_kb.py
    │   ├── cashier_kb.py
    │   ├── founder_kb.py
    │   ├── client_kb.py
    │   └── admin_kb.py
    │
    ├── middlewares/
    │   └── auth.py                 # Avtomatik foydalanuvchi ro'yxatdan o'tkazish
    │
    └── states/
        ├── order_states.py
        ├── logist_states.py
        ├── driver_states.py
        └── cashier_states.py
```

---

## ⚙️ O'rnatish

### 1. Talablar
- Python 3.11+
- PostgreSQL 14+

### 2. Klonlash va muhit sozlash

```bash
git clone <repo_url>
cd LogisticsBot

python -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 3. `.env` fayl yaratish

`.env.example` ni ko'chirib `.env` deb nomlang va to'ldiring:

```env
BOT_TOKEN=your_bot_token_here
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/logistics_db
FOUNDER_ID=your_telegram_id_here
```

`BOT_TOKEN` — [@BotFather](https://t.me/BotFather) orqali oling.  
`FOUNDER_ID` — [@userinfobot](https://t.me/userinfobot) orqali oling.

### 4. PostgreSQL bazani yaratish

```sql
CREATE DATABASE logistics_db;
```

### 5. Botni ishga tushirish

```bash
python main.py
```

Birinchi ishga tushirishda jadvallar avtomatik yaratiladi.

---

## 👥 Rollar

| Rol | Vazifasi |
|-----|----------|
| **Founder** | Barcha buyurtmalar, foyda statistikasi, xodimlar ro'yxati |
| **Logist** | Buyurtma yaratish, dispetcher biriktirish, shot-faktura yuborish |
| **Dispatcher** | Haydovchi biriktirish, media tasdiqlash, lokatsiya tasdiqlash |
| **Driver** | Status yangilash, media/lokatsiya yuborish, karta ma'lumotlari |
| **Cashier** | To'lov qilish, chek yuborish |
| **Client** | Buyurtma statusi ko'rish, lokatsiya so'rash |

### Rol berish jarayoni
1. Yangi foydalanuvchi `/start` bosadi
2. Telefon raqamini yuboradi
3. **Founderga** xabar keladi — rol tanlash tugmalari bilan
4. Founder rol beradi → foydalanuvchiga xabar → `/start` bossin

---

## 📦 Buyurtma statuslari

| Status | Ma'nosi |
|--------|---------|
| `NEW` | Logist yaratdi, dispetcher biriktirilmagan |
| `DISPATCHER_ASSIGNED` | Dispetcher biriktirildi |
| `DRIVER_ASSIGNED` | Haydovchi va mashina biriktirildi |
| `ARRIVED_A` | Haydovchi yuklash joyida |
| `LOADING` | Yuk ortildi, dispetcher tasdiqladi |
| `ON_WAY` | Yo'lda |
| `ARRIVED_B` | Tushirish joyida |
| `DIDOX_TASDIQDA` | Logist faktura yubordi, tushirish ruxsat |
| `UNLOADED` | Yuk tushirildi, to'lov kutilmoqda |
| `COMPLETED` | To'lov amalga oshirildi |
| `CANCELLED` | Bekor qilindi |

---

## 🔄 Buyurtma hayot aylanishi

```
LOGIST buyurtma yaratadi
    ↓  (dispetcher tanlaydi)
DISPATCHER buyurtmani qabul qiladi
    ↓  (haydovchi va mashina biriktiradi)
DRIVER A nuqtaga boradi
    ↓  (media: 1 video + 2 rasm yuboradi)
DISPATCHER media tasdiqlaydi
    ↓
DRIVER yo'lga chiqadi (lokatsiya yuboradi)
    ↓  (dispatcher tasdiqlaydi → mijozga xabar)
DRIVER B nuqtaga yetadi (1-3 video + 2-4 rasm)
    ↓  (dispatcher tasdiqlaydi)
LOGIST Didoxdan shot-faktura yuboradi
    ↓  (haydovchiga ruxsat, mijozga PDF)
DRIVER yuk tushiradi (1 video + 2 rasm)
    ↓  (dispatcher tasdiqlaydi)
CASHIER to'lov qiladi → chek yuboradi
    ↓
FOUNDER yakuniy hisobot oladi (foyda bilan)
```

---

## 📨 Xabarnomalar jadvali

| Hodisa | Kimga xabar ketadi |
|--------|--------------------|
| Buyurtma yaratildi | Logistga |
| Dispetcher biriktirildi | Dispetcherga (A/B nuqta + yuk + limit) |
| Haydovchi biriktirildi | Haydovchiga (to'liq marshrut + ko'rsatma), Mijozga |
| A nuqta media keldi | Dispetcherga (rasmlar + tasdiqlash tugmasi) |
| Loading tasdiqlandi | Haydovchiga |
| Loading rad etildi | Haydovchiga (sabab bilan) |
| Yo'lga chiqdi | Dispetcherga (lokatsiya + tasdiqlash) |
| Yo'lga chiqish tasdiqlandi | Mijozga |
| Mijoz lokatsiya so'radi | Logistga + Dispetcherga + Haydovchiga |
| 15 min lokatsiya yo'q | Dispetcherga + Logistga (ogohlantirish) |
| B nuqta media keldi | Dispetcherga (rasmlar + tasdiqlash) |
| B nuqta tasdiqlandi | Logistga (faktura so'rovi), Haydovchiga (kuting) |
| Shot-faktura yuborildi | Haydovchiga (ruxsat), Dispetcherga, Mijozga (PDF) |
| Tushirish media keldi | Dispetcherga (tasdiqlash) |
| Tushirish tasdiqlandi | Haydovchiga, Kassirga (karta+summa), Logistga, Mijozga |
| Kassir chek yubordi | Haydovchiga (chek), Dispetcherga, Founderga (foyda hisoboti) |

---

## 💰 Narx maxfiyligi

```
Mijoz narxi (Sotish)  →  Faqat FOUNDER ko'radi
Haydovchi narxi (Xarajat)  →  Logist + Dispetcher ko'radi
Foyda = Sotish - Xarajat  →  Faqat FOUNDER ko'radi
```

---

## ⏱ 15 daqiqalik taymer

Mijoz lokatsiya so'ragandan keyin haydovchi **15 daqiqa ichida** lokatsiya yubormasa:
- **Dispetcherga**: "Haydovchi 15 daqiqadan beri lokatsiya yubormadi!"
- **Logistga**: xuddi shunday ogohlantirish

---

## 🛠 Texnik stack

| Komponent | Texnologiya |
|-----------|-------------|
| Bot framework | aiogram 3.x |
| Database ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL + asyncpg |
| State management | aiogram FSM |
| Env config | python-dotenv |

---

## 🐛 Tez-tez uchraydigan muammolar

**Bot ishga tushmaydi:**
```bash
# .env to'g'ri to'ldirilganini tekshiring
cat .env

# PostgreSQL ishlab turganini tekshiring
pg_isready
```

**`ModuleNotFoundError`:**
```bash
# Virtual muhit faollashtirilganini tekshiring
source .venv/bin/activate
pip install -r requirements.txt
```

**`asyncpg` ulanish xatosi:**
```
# DATABASE_URL ni tekshiring:
# postgresql+asyncpg://user:password@host:port/dbname
```

---

## 📝 Litsenziya

Ushbu kod OMON Logistics uchun yozilgan. Barcha huquqlar himoyalangan.
