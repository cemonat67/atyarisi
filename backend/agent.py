"""
agent.py — GALOP AI Ajanı
Anthropic Claude ile at yarışı analiz ve tahmin ajanı
"""

import os
import json
import anthropic
from datetime import date
from sqlalchemy import func, desc
from models.database import SessionLocal, Race, Horse, HorseRace

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ── TOOLS ────────────────────────────────────────────────────

tools = [
    {
        "name": "get_today_races",
        "description": "Bugünkü koşu programını getirir. Tüm hipodromlar ve koşu detayları.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Şehir filtresi (opsiyonel)"}
            }
        }
    },
    {
        "name": "get_horse_stats",
        "description": "Bir atın geçmiş performans istatistiklerini getirir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "horse_name": {"type": "string", "description": "At adı"},
                "track": {"type": "string", "description": "Pist tipi: Çim veya Kum (opsiyonel)"},
                "distance": {"type": "integer", "description": "Mesafe metre (opsiyonel)"}
            },
            "required": ["horse_name"]
        }
    },
    {
        "name": "get_race_horses",
        "description": "Belirli bir koşunun at listesini ve detaylarını getirir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {"type": "integer", "description": "Koşu ID"},
                "city": {"type": "string", "description": "Şehir adı"},
                "race_no": {"type": "integer", "description": "Koşu numarası"}
            }
        }
    },
    {
        "name": "get_jockey_stats",
        "description": "Bir jokeyin performans istatistiklerini getirir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "jockey_name": {"type": "string", "description": "Jokey adı"}
            },
            "required": ["jockey_name"]
        }
    },
    {
        "name": "find_surprise_horses",
        "description": "Yüksek ganyan oranına rağmen iyi form gösteren sürpriz adaylarını bulur.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_str": {"type": "string", "description": "Tarih GG/AA/YYYY formatında"},
                "min_odds": {"type": "number", "description": "Minimum ganyan oranı (varsayılan 10)"}
            }
        }
    }
]

# ── TOOL IMPLEMENTATIONS ──────────────────────────────────────

def get_today_races(city=None):
    db = SessionLocal()
    try:
        today = date.today().strftime("%d/%m/%Y")
        q = db.query(Race).filter(Race.race_date == today)
        if city:
            q = q.filter(Race.city.ilike(f"%{city}%"))
        races = q.order_by(Race.city, Race.race_no).all()
        result = []
        for r in races:
            horses = db.query(HorseRace).filter(HorseRace.race_id == r.id).count()
            result.append({
                "id": r.id, "city": r.city, "race_no": r.race_no,
                "race_name": r.race_name, "track": r.track,
                "distance_m": r.distance_m, "start_time": r.start_time,
                "horse_count": horses
            })
        return result
    finally:
        db.close()


def get_horse_stats(horse_name, track=None, distance=None):
    db = SessionLocal()
    try:
        horse = db.query(Horse).filter(Horse.name.ilike(f"%{horse_name}%")).first()
        if not horse:
            return {"error": f"{horse_name} bulunamadı"}

        q = db.query(HorseRace, Race).join(Race).filter(
            HorseRace.horse_id == horse.id,
            HorseRace.finish_pos.isnot(None)
        )
        if track:
            q = q.filter(Race.track == track)
        if distance:
            q = q.filter(Race.distance_m.between(distance-100, distance+100))

        results = q.order_by(desc(Race.race_date)).limit(20).all()
        if not results:
            return {"horse": horse.name, "total": 0, "message": "Sonuç kaydı yok"}

        positions = [hr.finish_pos for hr, r in results]
        wins  = sum(1 for p in positions if p == 1)
        top3  = sum(1 for p in positions if p <= 3)
        total = len(positions)

        recent = [
            {
                "date": r.race_date, "city": r.city,
                "track": r.track, "distance": r.distance_m,
                "pos": hr.finish_pos, "jockey": hr.jockey,
                "odds": hr.ganyan_odds, "time": hr.finish_time
            }
            for hr, r in results[:8]
        ]

        # Pist istatistikleri
        track_stats = {}
        for hr, r in results:
            t = r.track or "Bilinmiyor"
            if t not in track_stats:
                track_stats[t] = {"total": 0, "wins": 0, "top3": 0}
            track_stats[t]["total"] += 1
            if hr.finish_pos == 1: track_stats[t]["wins"] += 1
            if hr.finish_pos <= 3: track_stats[t]["top3"] += 1

        return {
            "horse": horse.name,
            "total_races": total,
            "wins": wins,
            "top3": top3,
            "win_rate": round(wins/total*100, 1),
            "top3_rate": round(top3/total*100, 1),
            "avg_position": round(sum(positions)/total, 1),
            "track_stats": track_stats,
            "recent_races": recent
        }
    finally:
        db.close()


def get_race_horses(race_id=None, city=None, race_no=None):
    db = SessionLocal()
    try:
        if race_id:
            race = db.query(Race).filter(Race.id == race_id).first()
        elif city and race_no:
            today = date.today().strftime("%d/%m/%Y")
            race = db.query(Race).filter(
                Race.race_date == today,
                Race.city.ilike(f"%{city}%"),
                Race.race_no == race_no
            ).first()
        else:
            return {"error": "race_id veya city+race_no gerekli"}

        if not race:
            return {"error": "Koşu bulunamadı"}

        hrs = db.query(HorseRace).filter(HorseRace.race_id == race.id).order_by(HorseRace.start_no).all()
        horses = []
        for hr in hrs:
            # Son 5 koşu
            hist = db.query(HorseRace, Race).join(Race).filter(
                HorseRace.horse_id == hr.horse_id,
                HorseRace.finish_pos.isnot(None)
            ).order_by(desc(Race.race_date)).limit(5).all()

            wins = sum(1 for h, r in hist if h.finish_pos == 1)
            horses.append({
                "start_no": hr.start_no,
                "name": hr.horse.name,
                "jockey": hr.jockey,
                "weight": hr.weight_kg,
                "hp": hr.handicap_pts,
                "kgs": hr.kgs,
                "last_5": [h.finish_pos for h, r in hist],
                "win_rate": round(wins/len(hist)*100) if hist else 0,
                "recent_track_wins": sum(1 for h, r in hist if r.track == race.track and h.finish_pos == 1)
            })

        return {
            "race": {
                "id": race.id, "city": race.city, "race_no": race.race_no,
                "name": race.race_name, "track": race.track,
                "distance": race.distance_m, "time": race.start_time
            },
            "horses": horses
        }
    finally:
        db.close()


def get_jockey_stats(jockey_name):
    db = SessionLocal()
    try:
        results = db.query(HorseRace, Race).join(Race).filter(
            HorseRace.jockey.ilike(f"%{jockey_name}%"),
            HorseRace.finish_pos.isnot(None)
        ).order_by(desc(Race.race_date)).limit(30).all()

        if not results:
            return {"error": f"{jockey_name} bulunamadı"}

        total = len(results)
        wins  = sum(1 for hr, r in results if hr.finish_pos == 1)
        top3  = sum(1 for hr, r in results if hr.finish_pos <= 3)

        return {
            "jockey": jockey_name,
            "total": total, "wins": wins, "top3": top3,
            "win_rate": round(wins/total*100, 1),
            "top3_rate": round(top3/total*100, 1),
            "recent": [
                {"date": r.race_date, "horse": hr.horse.name,
                 "pos": hr.finish_pos, "city": r.city, "track": r.track}
                for hr, r in results[:8]
            ]
        }
    finally:
        db.close()


def find_surprise_horses(date_str=None, min_odds=10):
    db = SessionLocal()
    try:
        if not date_str:
            date_str = date.today().strftime("%d/%m/%Y")

        hrs = db.query(HorseRace, Race).join(Race).filter(
            Race.race_date == date_str,
            HorseRace.ganyan_odds >= min_odds
        ).all()

        surprises = []
        for hr, r in hrs:
            hist = db.query(HorseRace, Race).join(Race).filter(
                HorseRace.horse_id == hr.horse_id,
                HorseRace.finish_pos.isnot(None)
            ).order_by(desc(Race.race_date)).limit(10).all()

            if len(hist) < 3:
                continue

            positions = [h.finish_pos for h, r2 in hist]
            wins = sum(1 for p in positions if p == 1)
            top3 = sum(1 for p in positions if p <= 3)

            # Sürpriz kriteri: yüksek oran + iyi tarihsel form
            if top3 >= 3 and wins >= 1:
                track_wins = sum(1 for h, r2 in hist if r2.track == r.track and h.finish_pos <= 3)
                ev = (hr.ganyan_odds or 0) * (wins/len(positions)) - 1
                surprises.append({
                    "horse": hr.horse.name,
                    "race": f"{r.city} {r.race_no}. Koşu",
                    "odds": hr.ganyan_odds,
                    "win_rate": round(wins/len(positions)*100, 1),
                    "top3_rate": round(top3/len(positions)*100, 1),
                    "track_top3": track_wins,
                    "expected_value": round(ev, 2)
                })

        surprises.sort(key=lambda x: x["expected_value"], reverse=True)
        return {"date": date_str, "surprises": surprises[:5]}
    finally:
        db.close()


# ── TOOL ROUTER ───────────────────────────────────────────────

def run_tool(name, inputs):
    if name == "get_today_races":
        return get_today_races(**inputs)
    elif name == "get_horse_stats":
        return get_horse_stats(**inputs)
    elif name == "get_race_horses":
        return get_race_horses(**inputs)
    elif name == "get_jockey_stats":
        return get_jockey_stats(**inputs)
    elif name == "find_surprise_horses":
        return find_surprise_horses(**inputs)
    return {"error": "Bilinmeyen tool"}


# ── AGENT ─────────────────────────────────────────────────────

SYSTEM = """Sen GALOP — Türkiye'nin en gelişmiş at yarışı analiz ajanısın.
TJK veritabanına erişimin var: gerçek koşu sonuçları, at performans istatistikleri, jokey verileri.

Görevlerin:
1. Koşu tahminleri: Hangi at kazanır? Pist uyumu, form, jokey sinerji.
2. At analizi: Geçmiş performans, güçlü/zayıf yönler.
3. Sürpriz tespiti: Yüksek oran ama iyi potansiyel olan atlar.
4. Günlük brifing: Bugünkü en önemli koşular ve öneriler.

Yanıtlarını Türkçe ver. Verilere dayalı, özgüvenli ama dürüst ol.
Matematiksel analiz yap: kazanma oranı, beklenen değer, form eğrisi.
Uzman bir at yarışçısı gibi konuş — teknik ama anlaşılır."""


def chat(user_message: str, history: list = None) -> tuple[str, list]:
    """Agent ile konuş"""
    if history is None:
        history = []

    history.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM,
            tools=tools,
            messages=history
        )

        if response.stop_reason == "tool_use":
            # Tool çağrıları işle
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False)
                    })

            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": tool_results})

        else:
            # Final yanıt
            final = "".join(b.text for b in response.content if hasattr(b, "text"))
            history.append({"role": "assistant", "content": final})
            return final, history


def daily_briefing() -> str:
    """Günlük otomatik brifing üret"""
    msg = "Bugünkü tüm koşuları analiz et. Her hipodrom için en güçlü tahminleri ve en ilginç sürpriz adayları söyle. Günlük brifing formatında yaz."
    response, _ = chat(msg)
    return response


if __name__ == "__main__":
    # Test
    print("🏇 GALOP Agent Test\n")
    print(daily_briefing())
