"""routers/horses.py — At sorgulama endpoint'leri"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from models.database import Horse, HorseRace, Race, get_db

router = APIRouter()


@router.get("/search")
def search_horses(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db)
):
    """At adına göre arama"""
    horses = (
        db.query(Horse)
        .filter(Horse.name.ilike(f"%{q}%"))
        .limit(20)
        .all()
    )
    return [_horse_summary(h, db) for h in horses]


@router.get("/{name}/profile")
def get_horse_profile(name: str, db: Session = Depends(get_db)):
    """At'ın tam profili + tüm istatistikler"""
    horse = db.query(Horse).filter(Horse.name.ilike(name)).first()
    if not horse:
        return {"error": "At bulunamadı"}

    return _horse_full_profile(horse, db)


@router.get("/{name}/stats")
def get_horse_stats(
    name: str,
    track: str | None  = None,
    distance: int | None = None,
    db: Session = Depends(get_db)
):
    """Pist/mesafe filtreli istatistik"""
    horse = db.query(Horse).filter(Horse.name.ilike(name)).first()
    if not horse:
        return {"error": "At bulunamadı"}

    q = (
        db.query(HorseRace, Race)
        .join(Race)
        .filter(
            HorseRace.horse_id == horse.id,
            HorseRace.finish_pos.isnot(None)
        )
    )
    if track:
        q = q.filter(Race.track == track)
    if distance:
        q = q.filter(Race.distance_m == distance)

    results = q.all()
    if not results:
        return {"total": 0, "stats": {}}

    positions = [hr.finish_pos for hr, r in results if hr.finish_pos]
    return {
        "filter":   {"track": track, "distance": distance},
        "total":    len(results),
        "wins":     sum(1 for p in positions if p == 1),
        "top3":     sum(1 for p in positions if p <= 3),
        "win_rate": round(sum(1 for p in positions if p == 1) / len(positions) * 100, 1),
        "top3_rate":round(sum(1 for p in positions if p <= 3) / len(positions) * 100, 1),
        "avg_pos":  round(sum(positions) / len(positions), 2),
    }


# ── HELPERS ──────────────────────────────────────────────────

def _horse_summary(horse: Horse, db: Session) -> dict:
    total = db.query(HorseRace).filter(
        HorseRace.horse_id == horse.id,
        HorseRace.finish_pos.isnot(None)
    ).count()

    wins = db.query(HorseRace).filter(
        HorseRace.horse_id == horse.id,
        HorseRace.finish_pos == 1
    ).count()

    return {
        "id":         horse.id,
        "name":       horse.name,
        "birth_year": horse.birth_year,
        "gender":     horse.gender,
        "sire":       horse.sire,
        "dam":        horse.dam,
        "active":     bool(horse.active),
        "total_races":total,
        "wins":       wins,
        "win_rate":   round(wins / total * 100, 1) if total else 0,
    }


def _horse_full_profile(horse: Horse, db: Session) -> dict:
    summary = _horse_summary(horse, db)

    # Son 20 koşu
    recent = (
        db.query(HorseRace, Race)
        .join(Race)
        .filter(HorseRace.horse_id == horse.id)
        .order_by(desc(Race.race_date))
        .limit(20)
        .all()
    )

    # Pist bazlı istatistik
    track_stats = {}
    for track in ["Çim", "Kum", "Sentetik"]:
        rows = [hr for hr, r in recent if r.track == track and hr.finish_pos]
        if rows:
            wins = sum(1 for hr in rows if hr.finish_pos == 1)
            track_stats[track] = {
                "total":    len(rows),
                "wins":     wins,
                "win_rate": round(wins / len(rows) * 100, 1),
            }

    # Mesafe bazlı istatistik
    dist_stats = {}
    for hr, r in recent:
        if r.distance_m and hr.finish_pos:
            d = str(r.distance_m)
            if d not in dist_stats:
                dist_stats[d] = {"total": 0, "wins": 0}
            dist_stats[d]["total"] += 1
            if hr.finish_pos == 1:
                dist_stats[d]["wins"] += 1
    for d in dist_stats:
        t = dist_stats[d]["total"]
        dist_stats[d]["win_rate"] = round(dist_stats[d]["wins"] / t * 100, 1)

    # Form eğrisi — son 10 koşu pozisyonu
    form_curve = [
        {"date": r.race_date, "pos": hr.finish_pos, "city": r.city}
        for hr, r in recent[:10] if hr.finish_pos
    ]

    # Jokey uyumları
    jockey_stats = {}
    for hr, r in recent:
        if hr.jockey and hr.finish_pos:
            j = hr.jockey
            if j not in jockey_stats:
                jockey_stats[j] = {"total": 0, "wins": 0}
            jockey_stats[j]["total"] += 1
            if hr.finish_pos == 1:
                jockey_stats[j]["wins"] += 1
    best_jockeys = sorted(
        [{"jockey": j, **v, "win_rate": round(v["wins"]/v["total"]*100, 1)}
         for j, v in jockey_stats.items()],
        key=lambda x: x["win_rate"], reverse=True
    )[:5]

    return {
        **summary,
        "track_stats":   track_stats,
        "distance_stats": dist_stats,
        "form_curve":    form_curve,
        "best_jockeys":  best_jockeys,
        "recent_races": [
            {
                "date":       r.race_date,
                "city":       r.city,
                "race_name":  r.race_name,
                "distance_m": r.distance_m,
                "track":      r.track,
                "finish_pos": hr.finish_pos,
                "finish_time":hr.finish_time,
                "jockey":     hr.jockey,
                "weight_kg":  hr.weight_kg,
                "handicap_pts":hr.handicap_pts,
                "ganyan_odds":hr.ganyan_odds,
            }
            for hr, r in recent
        ]
    }
