# GALOP — At Yarışı Analiz Sistemi

## 🏗️ Proje Yapısı

```
galop/
├── backend/
│   ├── main.py               ← FastAPI app
│   ├── requirements.txt
│   ├── models/
│   │   └── database.py       ← SQLAlchemy ORM + DB init
│   ├── routers/
│   │   ├── races.py          ← Koşu endpoint'leri
│   │   ├── horses.py         ← At sorgulama
│   │   ├── predictions.py    ← Tahmin motoru
│   │   └── scraper.py        ← Scraper tetikleme
│   └── scrapers/
│       └── tjk.py            ← TJK.org scraper
└── frontend/
    └── index.html            ← UI (API entegreli)
```

---

## 🚀 Kurulum

### 1. Backend

```bash
cd galop/backend
pip install -r requirements.txt

# DB oluştur
python -c "from models.database import init_db; init_db()"

# Sunucu başlat
python main.py
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### 2. Frontend

```bash
# Herhangi bir static server ile aç
cd galop/frontend
python -m http.server 3000
# → http://localhost:3000
```

Veya direkt `index.html` browser'da aç (CORS için backend çalışıyor olmalı).

---

## 📡 API Endpoint'leri

| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/api/races/today` | Bugünkü koşular |
| GET | `/api/races/date/{GG-AA-YYYY}` | Tarihe göre koşular |
| GET | `/api/races/{id}/horses` | Koşunun at listesi + geçmiş |
| GET | `/api/horses/search?q=KARAKIR` | At arama |
| GET | `/api/horses/{name}/profile` | Tam at profili |
| GET | `/api/horses/{name}/stats?track=Çim&distance=1200` | Filtreli istatistik |
| GET | `/api/predictions/{race_id}` | Tahmin üret |
| POST | `/api/scraper/today` | Bugünü çek |
| POST | `/api/scraper/run?from_date=...&to_date=...` | Tarih aralığı çek |
| GET | `/api/scraper/status` | DB istatistikleri |

---

## ⚡ İlk Veri Yükleme

```bash
# 1. Bugünü çek (hızlı test)
curl -X POST http://localhost:8000/api/scraper/today

# 2. Son 1 ay (arka planda)
curl -X POST "http://localhost:8000/api/scraper/run?from_date=14/02/2026&to_date=14/03/2026"

# 3. Tam 2 yıl (arka planda, uzun sürer)
curl -X POST "http://localhost:8000/api/scraper/run?from_date=14/03/2024&to_date=14/03/2026"

# Durum kontrol
curl http://localhost:8000/api/scraper/status
```

---

## 🧮 Tahmin Modeli

Ağırlıklı skor sistemi:

| Faktör | Ağırlık | Açıklama |
|--------|---------|----------|
| Form Eğrisi | %25 | Son koşuların üstel ağırlıklı ortalaması |
| Pist Uyumu | %20 | O pistte tarihsel başarı oranı |
| Mesafe Uyumu | %18 | ±100m toleranslı mesafe başarısı |
| Bayesian | %15 | Beta dağılımı prior + son 6 likelihood |
| Jokey Sinerji | %10 | At-jokey birliktelik skoru |
| HP Normalize | %7 | Handikap puanı 0-1 skalası |
| ELO Rating | %5 | Dinamik ELO sistemi |

**Sürpriz tespiti:** Beklenen Değer (EV = oran × olasılık - 1) > 0.3 olan ve pist/mesafe uyumu yüksek atları ayrıca işaretler.

---

## ⚠️ Notlar

- TJK'nın sitesi JavaScript ile yüklüyorsa Playwright gerekebilir
- İlk çalıştırmada parser TJK HTML yapısına göre ayarlanmalıdır
- Rate limiting için `DELAY = 1.5` saniye ayarlı (config'den değiştirilebilir)
