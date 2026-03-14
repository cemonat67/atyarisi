# 🚀 GALOP — Railway Deploy Kılavuzu

## Adım 1 — GitHub'a yükle

```bash
cd galop-deploy
git init
git add .
git commit -m "initial: GALOP at yarışı analiz sistemi"

# GitHub'da yeni repo oluştur: github.com/new
# Repo adı: galop (private önerilir)

git remote add origin https://github.com/KULLANICI_ADI/galop.git
git push -u origin main
```

---

## Adım 2 — Railway hesabı & proje oluştur

1. **railway.app** → "Start a New Project"
2. **"Deploy from GitHub repo"** seç
3. `galop` reposunu seç
4. Railway otomatik Dockerfile'ı algılar → **Deploy** tıkla

---

## Adım 3 — Environment Variables (Railway Dashboard)

Railway → Settings → Variables → Add:

```
PORT=8000
TZ=Europe/Istanbul
```

İsteğe bağlı (gelecekte):
```
SECRET_KEY=rastgele_uzun_string
```

---

## Adım 4 — Kalıcı Disk (SQLite için ÖNEMLİ)

Railway → Settings → **Volumes** → Add Volume:
- Mount path: `/app/data`
- Size: 1 GB

> ⚠️ Bu yapılmazsa her deploy'da DB sıfırlanır!

---

## Adım 5 — Domain al

Railway → Settings → **Networking** → Generate Domain
→ `galop-api.up.railway.app` gibi bir URL verilir

---

## Adım 6 — Canlı test

```bash
# Health check
curl https://galop-api.up.railway.app/api/health

# Bugünkü koşular (scraper startup'ta otomatik çalışır)
curl https://galop-api.up.railway.app/api/races/today

# DB durumu
curl https://galop-api.up.railway.app/api/scraper/status

# 2 yıllık veri çekimi başlat (arka planda)
curl -X POST "https://galop-api.up.railway.app/api/scraper/run?from_date=14/03/2024&to_date=14/03/2026"
```

---

## Adım 7 — UI Erişimi

```
https://galop-api.up.railway.app/
```

Frontend ve backend aynı origin'den sunuluyor → CORS sorunu yok.

---

## 📊 Railway Ücretsiz Tier Limitleri

| Kaynak | Limit | Yeterli mi? |
|--------|-------|-------------|
| RAM | 512 MB | ✅ (Playwright ~200MB) |
| CPU | Paylaşımlı | ✅ |
| Disk | Volume ile 1GB | ✅ (2 yıl veri ~200MB) |
| Aylık çalışma | 500 saat | ✅ (~21 gün) |
| Bandwidth | 100 GB | ✅ |

> 500 saat/ay aşılırsa aylık $5 Hobby planına geç.

---

## 🔄 Otomatik Deploy

Bundan sonra her `git push origin main` → Railway otomatik yeniden deploy eder.

```bash
# Kod değişikliği yaptıktan sonra
git add .
git commit -m "güncelleme açıklaması"
git push origin main
# → Railway 2-3 dakikada deploy eder
```

---

## 🗓️ Otomatik Scraping

Uygulama her gün sabah **07:00 İstanbul saatinde** otomatik olarak:
1. Tüm Türkiye hipodromlarının programını çeker
2. SQLite DB'ye kaydeder
3. Tahmin motorunu günceller

Manuel tetikleme:
```bash
curl -X POST https://galop-api.up.railway.app/api/scraper/today
```
