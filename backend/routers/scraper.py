"""routers/scraper.py — Scraper tetikleme ve durum endpoint'leri"""

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from models.database import Race, ScrapeLog, get_db
from scrapers.tjk import scrape_date_range, CITIES, fetch_city_races, save_races_to_db
from datetime import date, timedelta
import threading

router = APIRouter()

# Scraper durumu (thread-safe basit state)
_scraper_state = {"running": False, "progress": "", "stats": {}}


@router.post("/run")
def run_scraper(
    from_date: str = None,   # GG/AA/YYYY
    to_date:   str = None,
    city_ids:  list[int] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Arka planda scraper başlat.
    from_date/to_date boş ise bugün çalışır.
    """
    if _scraper_state["running"]:
        return {"status": "already_running", "progress": _scraper_state["progress"]}

    today = date.today().strftime("%d/%m/%Y")
    fd = from_date or today
    td = to_date   or today

    def _run():
        _scraper_state["running"]  = True
        _scraper_state["progress"] = f"{fd} → {td} çalışıyor..."
        try:
            stats = scrape_date_range(fd, td, city_ids)
            _scraper_state["stats"]    = stats
            _scraper_state["progress"] = "Tamamlandı"
        except Exception as e:
            _scraper_state["progress"] = f"Hata: {e}"
        finally:
            _scraper_state["running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"status": "started", "from": fd, "to": td}


@router.post("/today")
def scrape_today(db: Session = Depends(get_db)):
    """Sadece bugünü çek (senkron)"""
    today = date.today().strftime("%d/%m/%Y")
    total = 0
    for city_id, city_name in CITIES.items():
        races = fetch_city_races(city_id, city_name, today)
        if races:
            n = save_races_to_db(db, races)
            total += n
    return {"date": today, "races_saved": total}


@router.get("/status")
def scraper_status(db: Session = Depends(get_db)):
    """Scraper durumu + DB istatistikleri"""
    total_races  = db.query(func.count(Race.id)).scalar()
    total_days   = db.query(func.count(func.distinct(Race.race_date))).scalar()
    last_date    = db.query(func.max(Race.race_date)).scalar()
    first_date   = db.query(func.min(Race.race_date)).scalar()

    city_counts = (
        db.query(Race.city, func.count(Race.id).label("n"))
        .group_by(Race.city)
        .order_by(desc("n"))
        .all()
    )

    return {
        "scraper":    _scraper_state,
        "db": {
            "total_races":  total_races,
            "total_days":   total_days,
            "date_range":   {"from": first_date, "to": last_date},
            "cities":       [{"city": c, "races": n} for c, n in city_counts],
        }
    }


@router.get("/log")
def get_scrape_log(limit: int = 50, db: Session = Depends(get_db)):
    """Son scrape log kayıtları"""
    logs = (
        db.query(ScrapeLog)
        .order_by(desc(ScrapeLog.scraped_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "date":       l.race_date,
            "city_id":    l.city_id,
            "status":     l.status,
            "races_found":l.races_found,
            "scraped_at": str(l.scraped_at),
        }
        for l in logs
    ]
