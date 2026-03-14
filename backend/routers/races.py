"""routers/races.py — Koşu endpoint'leri"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from models.database import Race, HorseRace, Horse, get_db
from datetime import date

router = APIRouter()


@router.get("/today")
def get_today_races(
    city: str | None = None,
    db: Session = Depends(get_db)
):
    """Bugünkü koşu programı"""
    today = date.today().strftime("%d/%m/%Y")
    q = db.query(Race).filter(Race.race_date == today)
    if city:
        q = q.filter(Race.city == city)
    races = q.order_by(Race.city, Race.race_no).all()
    return _format_races(races, db)


@router.get("/date/{date_str}")
def get_races_by_date(
    date_str: str,   # GG-AA-YYYY
    city: str | None = None,
    db: Session = Depends(get_db)
):
    """Belirli tarihteki koşular (format: GG-AA-YYYY)"""
    d = date_str.replace("-", "/")
    q = db.query(Race).filter(Race.race_date == d)
    if city:
        q = q.filter(Race.city == city)
    races = q.order_by(Race.race_no).all()
    return _format_races(races, db)


@router.get("/cities")
def get_active_cities(db: Session = Depends(get_db)):
    """Sistemdeki aktif hipodromlar"""
    rows = (
        db.query(Race.city, Race.city_id, func.count(Race.id).label("total"))
        .group_by(Race.city)
        .order_by(desc("total"))
        .all()
    )
    return [{"city": r.city, "city_id": r.city_id, "total_races": r.total} for r in rows]


@router.get("/{race_id}/horses")
def get_race_horses(race_id: int, db: Session = Depends(get_db)):
    """Bir koşunun at listesi + geçmiş performans"""
    race = db.query(Race).filter(Race.id == race_id).first()
    if not race:
        return {"error": "Koşu bulunamadı"}

    horse_races = (
        db.query(HorseRace)
        .filter(HorseRace.race_id == race_id)
        .order_by(HorseRace.start_no)
        .all()
    )

    horses_out = []
    for hr in horse_races:
        # Son 10 koşu geçmişi
        history = (
            db.query(HorseRace, Race)
            .join(Race, HorseRace.race_id == Race.id)
            .filter(
                HorseRace.horse_id == hr.horse_id,
                HorseRace.id != hr.id,
                HorseRace.finish_pos.isnot(None)
            )
            .order_by(desc(Race.race_date))
            .limit(10)
            .all()
        )

        horses_out.append({
            "start_no":     hr.start_no,
            "horse_name":   hr.horse.name,
            "age":          2026 - hr.horse.birth_year if hr.horse.birth_year else None,
            "gender":       hr.horse.gender,
            "sire":         hr.horse.sire,
            "dam":          hr.horse.dam,
            "jockey":       hr.jockey,
            "trainer":      hr.trainer,
            "owner":        hr.owner,
            "weight_kg":    hr.weight_kg,
            "handicap_pts": hr.handicap_pts,
            "kgs":          hr.kgs,
            "last_6_races": hr.last_6_races,
            "finish_pos":   hr.finish_pos,
            "ganyan_odds":  hr.ganyan_odds,
            "history": [
                {
                    "date":       r.race_date,
                    "city":       r.city,
                    "distance_m": r.distance_m,
                    "track":      r.track,
                    "finish_pos": h.finish_pos,
                    "finish_time":h.finish_time,
                    "ganyan_odds":h.ganyan_odds,
                    "jockey":     h.jockey,
                    "weight_kg":  h.weight_kg,
                }
                for h, r in history
            ]
        })

    return {
        "race": {
            "id":         race.id,
            "date":       race.race_date,
            "city":       race.city,
            "race_no":    race.race_no,
            "race_name":  race.race_name,
            "track":      race.track,
            "distance_m": race.distance_m,
            "start_time": race.start_time,
        },
        "horses": horses_out
    }


def _format_races(races, db):
    out = []
    for r in races:
        horse_count = db.query(HorseRace).filter(HorseRace.race_id == r.id).count()
        out.append({
            "id":           r.id,
            "date":         r.race_date,
            "city":         r.city,
            "city_id":      r.city_id,
            "race_no":      r.race_no,
            "race_name":    r.race_name,
            "track":        r.track,
            "track_cond":   r.track_condition,
            "distance_m":   r.distance_m,
            "start_time":   r.start_time,
            "horse_count":  horse_count,
        })
    return out
