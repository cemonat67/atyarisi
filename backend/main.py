"""
GALOP Backend — FastAPI + APScheduler
Otomatik günlük scraping dahil
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from routers import races, horses, predictions, scraper
from models.database import init_db
from datetime import date
import logging
import os

log = logging.getLogger(__name__)

app = FastAPI(title="GALOP API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(races.router,       prefix="/api/races",       tags=["Races"])
app.include_router(horses.router,      prefix="/api/horses",      tags=["Horses"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["Predictions"])
app.include_router(scraper.router,     prefix="/api/scraper",     tags=["Scraper"])

# Frontend static
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "date": date.today().isoformat()}

scheduler = AsyncIOScheduler()

async def daily_scrape():
    from scrapers.tjk_playwright import fetch_today_sync, CITIES
    from scrapers.tjk import save_races_to_db, fetch_city_races
    from models.database import SessionLocal

    log.info("Gunluk otomatik scraping basladi")
    today = date.today().strftime("%d/%m/%Y")
    db = SessionLocal()
    total = 0
    try:
        for city_id, city_name in CITIES.items():
            races_data = fetch_city_races(city_id, city_name, today)
            if not races_data:
                races_data = fetch_today_sync(city_id, city_name)
            if races_data:
                n = save_races_to_db(db, races_data)
                total += n
    except Exception as e:
        log.error(f"Scraping hatasi: {e}")
    finally:
        db.close()
    log.info(f"Gunluk scraping tamamlandi — {total} kosu")

@app.on_event("startup")
async def startup():
    init_db()
    scheduler.add_job(
        daily_scrape,
        CronTrigger(hour=7, minute=0, timezone="Europe/Istanbul"),
        id="daily_scrape",
        replace_existing=True,
    )
    scheduler.start()
    await daily_scrape()

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
