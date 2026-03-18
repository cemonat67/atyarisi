"""
orchestrator.py — GALOPUM Agent Orchestrator
Her 5 dakikada çalışır:
- TJK'dan canlı veri çeker
- Oranları günceller
- Tahminleri yeniler
- Sürpriz anomalileri tespit eder
- WebSocket ile UI'ya push eder
"""

import asyncio
import logging
import json
import os
from datetime import date, datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from models.database import SessionLocal, Race, HorseRace

log = logging.getLogger(__name__)

# ── Global state — UI'ya push edilecek ──
state = {
    "last_update": None,
    "active_races": [],
    "alerts": [],
    "odds_changes": {},
}

# WebSocket bağlantıları
ws_clients = set()


# ── GÖREVLER ──────────────────────────────────────────────────

async def task_fetch_today():
    """Her 5 dakikada bugünkü veriyi güncelle"""
    try:
        from scrapers.tjk_real import get_city_links, scrape_city, save
        today = date.today().strftime("%d/%m/%Y")

        cities = await get_city_links(today)
        if not cities:
            log.debug("Bugün aktif hipodrom yok")
            return

        db = SessionLocal()
        total = 0
        try:
            for c in cities:
                races = await scrape_city(c["url"], c["city_id"], c["city_name"], today)
                if races:
                    n = save(db, races)
                    total += n
                await asyncio.sleep(1)
        finally:
            db.close()

        state["last_update"] = datetime.now().isoformat()
        log.info(f"Orchestrator: {total} yeni koşu kaydedildi")

        # UI'ya bildir
        await broadcast({"type": "data_update", "races_added": total, "time": state["last_update"]})

    except Exception as e:
        log.error(f"task_fetch_today hatası: {e}")


async def task_detect_odds_anomaly():
    """
    Ganyan oran anomalilerini tespit et.
    Bir atta ani oran düşüşü = insider bilgisi sinyali.
    """
    try:
        db = SessionLocal()
        today = date.today().strftime("%d/%m/%Y")

        # Bugünkü koşulardaki atları al
        hrs = (
            db.query(HorseRace, Race)
            .join(Race)
            .filter(Race.race_date == today, HorseRace.ganyan_odds.isnot(None))
            .all()
        )
        db.close()

        alerts = []
        for hr, r in hrs:
            key = f"{r.id}_{hr.horse_id}"
            prev = state["odds_changes"].get(key)
            curr = hr.ganyan_odds

            if prev and curr:
                change_pct = (prev - curr) / prev * 100
                # %20+ ani düşüş = alert
                if change_pct > 20:
                    alert = {
                        "type": "odds_drop",
                        "horse": hr.horse.name,
                        "race": f"{r.city} {r.race_no}. Koşu",
                        "prev_odds": prev,
                        "curr_odds": curr,
                        "drop_pct": round(change_pct, 1),
                        "message": f"⚡ {hr.horse.name} — oran {prev:.1f}→{curr:.1f} ({change_pct:.0f}% düşüş!)"
                    }
                    alerts.append(alert)
                    log.warning(f"ORAN ANOMALİSİ: {alert['message']}")

            state["odds_changes"][key] = curr

        if alerts:
            state["alerts"] = alerts[-10:]  # Son 10 alert
            await broadcast({"type": "odds_alert", "alerts": alerts})

    except Exception as e:
        log.error(f"task_detect_odds_anomaly hatası: {e}")


async def task_daily_briefing():
    """Her sabah 07:30'da AI brifing üret"""
    try:
        from agent import daily_briefing
        log.info("Günlük AI brifing üretiliyor...")
        briefing = daily_briefing()

        # Dosyaya kaydet
        with open("/app/data/daily_briefing.json", "w", encoding="utf-8") as f:
            json.dump({
                "date": date.today().isoformat(),
                "briefing": briefing,
                "generated_at": datetime.now().isoformat()
            }, f, ensure_ascii=False)

        await broadcast({"type": "daily_briefing", "briefing": briefing})
        log.info("Günlük brifing tamamlandı")

    except Exception as e:
        log.error(f"task_daily_briefing hatası: {e}")


async def task_heartbeat():
    """Her 30 saniyede UI'ya heartbeat gönder"""
    db = SessionLocal()
    try:
        from sqlalchemy import func
        total = db.query(func.count(Race.id)).scalar()
        today_count = db.query(func.count(Race.id)).filter(
            Race.race_date == date.today().strftime("%d/%m/%Y")
        ).scalar()
    finally:
        db.close()

    await broadcast({
        "type": "heartbeat",
        "time": datetime.now().isoformat(),
        "total_races": total,
        "today_races": today_count,
        "alerts_count": len(state["alerts"]),
    })


# ── WEBSOCKET BROADCAST ───────────────────────────────────────

async def broadcast(data: dict):
    """Tüm bağlı WebSocket client'larına mesaj gönder"""
    if not ws_clients:
        return
    msg = json.dumps(data, ensure_ascii=False)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    ws_clients -= dead


# ── SCHEDULER BAŞLAT ─────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Her 5 dakikada veri çek
    scheduler.add_job(
        task_fetch_today,
        IntervalTrigger(minutes=5),
        id="fetch_today",
        replace_existing=True,
    )

    # Her 3 dakikada oran anomali tespiti
    scheduler.add_job(
        task_detect_odds_anomaly,
        IntervalTrigger(minutes=3),
        id="odds_anomaly",
        replace_existing=True,
    )

    # Her 30 saniyede heartbeat
    scheduler.add_job(
        task_heartbeat,
        IntervalTrigger(seconds=30),
        id="heartbeat",
        replace_existing=True,
    )

    # Her sabah 07:30'da AI brifing
    scheduler.add_job(
        task_daily_briefing,
        CronTrigger(hour=7, minute=30, timezone="Europe/Istanbul"),
        id="daily_briefing",
        replace_existing=True,
    )

    return scheduler
