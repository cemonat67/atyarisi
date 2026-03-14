"""
scrapers/tjk.py
---------------
TJK.org'dan veri çeken scraper — DB'ye doğrudan yazar.
"""

import requests
import re
import time
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.database import Race, Horse, HorseRace, ScrapeLog, SessionLocal

log = logging.getLogger(__name__)

BASE_URL = "https://www.tjk.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Referer": "https://www.tjk.org/",
}

CITIES = {
    1:  "İstanbul",
    2:  "İzmir",
    3:  "Ankara",
    4:  "Bursa",
    5:  "Adana",
    6:  "Diyarbakır",
    7:  "Elazığ",
    8:  "Kocaeli",
    9:  "Şanlıurfa",
    10: "Antalya",
}

DELAY = 1.5


# ── HTTP ─────────────────────────────────────────────────────

def get(url: str, retries: int = 3) -> str | None:
    for i in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.text
            log.warning(f"HTTP {r.status_code} {url}")
        except Exception as e:
            log.warning(f"İstek hatası [{i}/{retries}]: {e}")
        time.sleep(DELAY * i)
    return None


# ── PARSE ─────────────────────────────────────────────────────

def parse_int(v) -> int | None:
    try:   return int(re.sub(r"[^\d]", "", str(v)))
    except: return None

def parse_float(v) -> float | None:
    try:   return float(str(v).replace(",", ".").strip())
    except: return None

def clean(v) -> str:
    return str(v).strip() if v else ""


def fetch_city_races(city_id: int, city_name: str, date_str: str) -> list[dict]:
    """
    Bir şehrin belirli bir günkü tüm koşularını çeker.
    date_str: GG/AA/YYYY
    """
    # Yöntem 1: HTML sonuç sayfası
    url = (
        f"{BASE_URL}/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari"
        f"?SehirId={city_id}"
        f"&QueryParameter_Tarih={date_str}"
        f"&Era=past"
        f"&SehirAdi={requests.utils.quote(city_name)}"
    )
    html = get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    races = []

    # TJK sayfasındaki koşu bloklarını bul
    # Her koşu genellikle id="kos-N" veya class="race-block" altında
    race_sections = (
        soup.find_all("div", id=re.compile(r"kos[u]?[\-_]?\d+", re.I)) or
        soup.find_all("div", class_=re.compile(r"race|kosu|kos\b", re.I)) or
        soup.find_all("table", id=re.compile(r"\d+"))
    )

    if not race_sections:
        # Fallback: tüm tabloları tara
        race_sections = soup.find_all("table")

    for sec in race_sections:
        race = _parse_race_block(sec, city_id, city_name, date_str)
        if race:
            races.append(race)

    log.info(f"  {city_name} {date_str}: {len(races)} koşu bulundu")
    return races


def _parse_race_block(block, city_id, city_name, date_str) -> dict | None:
    text = block.get_text(" ", strip=True)

    # Koşu no
    m = re.search(r"(\d+)\.\s*[Kk]o[şs]u", text)
    if not m:
        return None
    race_no = int(m.group(1))

    # Mesafe
    dist = None
    dm = re.search(r"(\d{3,4})\s*[Mm]", text)
    if dm:
        dist = int(dm.group(1))

    # Pist
    track = None
    tm = re.search(r"(Çim|Kum|Sentetik|Dirt)", text, re.I)
    if tm:
        track = tm.group(1).capitalize()

    # Pist durumu
    cond = None
    cm = re.search(r"(İyi|Yumuşak|Ağır|Sert)", text, re.I)
    if cm:
        cond = cm.group(1)

    # Saat
    start_time = None
    stm = re.search(r"(\d{1,2}:\d{2})", text)
    if stm:
        start_time = stm.group(1)

    # Koşu adı
    race_name = None
    nm = re.search(r"Koşu\s*[:\-–]\s*(.+?)(?:\s*\d{3,4}[Mm]|\s*$)", text[:200])
    if nm:
        race_name = nm.group(1).strip()[:100]

    horses = _parse_horses(block)

    if not horses:
        return None

    return {
        "race_date":       date_str,
        "city":            city_name,
        "city_id":         city_id,
        "race_no":         race_no,
        "race_name":       race_name,
        "track":           track,
        "track_condition": cond,
        "distance_m":      dist,
        "start_time":      start_time,
        "horses":          horses,
    }


def _parse_horses(block) -> list[dict]:
    horses = []
    rows = block.find_all("tr")

    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        if not re.match(r"^\d{1,2}$", cells[0]):
            continue

        # TJK sütun sırası (tipik):
        # 0:No 1:At 2:Yaş 3:Kilo 4:Jokey 5:Antrenör 6:Sahip 7:HP 8:KGS 9:Son6 10:Derece 11:Ganyan
        h = {
            "start_no":     parse_int(cells[0]),
            "horse_name":   clean(cells[1]) if len(cells) > 1 else None,
            "age":          parse_int(cells[2]) if len(cells) > 2 else None,
            "weight_kg":    parse_float(cells[3]) if len(cells) > 3 else None,
            "jockey":       clean(cells[4]) if len(cells) > 4 else None,
            "trainer":      clean(cells[5]) if len(cells) > 5 else None,
            "owner":        clean(cells[6]) if len(cells) > 6 else None,
            "handicap_pts": parse_float(cells[7]) if len(cells) > 7 else None,
            "kgs":          parse_int(cells[8]) if len(cells) > 8 else None,
            "last_6_races": clean(cells[9]) if len(cells) > 9 else None,
            "finish_pos":   parse_int(cells[10]) if len(cells) > 10 else None,
            "ganyan_odds":  parse_float(cells[11]) if len(cells) > 11 else None,
        }

        if h["horse_name"] and len(h["horse_name"]) > 1:
            horses.append(h)

    return horses


# ── DB WRITER ─────────────────────────────────────────────────

def save_races_to_db(db: Session, races: list[dict]) -> int:
    saved = 0
    for r in races:
        # Mükerrer kontrol
        existing = db.query(Race).filter_by(
            race_date=r["race_date"],
            city_id=r["city_id"],
            race_no=r["race_no"]
        ).first()
        if existing:
            continue

        race_obj = Race(
            race_date       = r["race_date"],
            city            = r["city"],
            city_id         = r["city_id"],
            race_no         = r["race_no"],
            race_name       = r.get("race_name"),
            track           = r.get("track"),
            track_condition = r.get("track_condition"),
            distance_m      = r.get("distance_m"),
            start_time      = r.get("start_time"),
        )
        db.add(race_obj)
        db.flush()  # race_obj.id alabilmek için

        for h in r.get("horses", []):
            # At kaydını bul veya oluştur
            horse_obj = db.query(Horse).filter_by(name=h["horse_name"]).first()
            if not horse_obj:
                horse_obj = Horse(
                    name       = h["horse_name"],
                    birth_year = (2026 - h["age"]) if h.get("age") else None,
                )
                db.add(horse_obj)
                db.flush()

            hr = HorseRace(
                race_id       = race_obj.id,
                horse_id      = horse_obj.id,
                start_no      = h.get("start_no"),
                jockey        = h.get("jockey"),
                trainer       = h.get("trainer"),
                owner         = h.get("owner"),
                weight_kg     = h.get("weight_kg"),
                handicap_pts  = h.get("handicap_pts"),
                kgs           = h.get("kgs"),
                last_6_races  = h.get("last_6_races"),
                finish_pos    = h.get("finish_pos"),
                ganyan_odds   = h.get("ganyan_odds"),
            )
            db.add(hr)

        db.commit()
        saved += 1

    return saved


# ── BULK SCRAPER ──────────────────────────────────────────────

def scrape_date_range(
    from_date: str,   # GG/AA/YYYY
    to_date: str,
    city_ids: list[int] = None,
    delay: float = DELAY,
) -> dict:

    if city_ids is None:
        city_ids = list(CITIES.keys())

    fmt = "%d/%m/%Y"
    start   = datetime.strptime(from_date, fmt)
    end     = datetime.strptime(to_date,   fmt)
    current = start

    stats = {"days": 0, "races": 0, "horses": 0, "errors": 0}
    db    = SessionLocal()

    try:
        while current <= end:
            date_str = current.strftime(fmt)

            for city_id in city_ids:
                city_name = CITIES.get(city_id, f"Sehir_{city_id}")
                try:
                    races = fetch_city_races(city_id, city_name, date_str)
                    if races:
                        n = save_races_to_db(db, races)
                        stats["races"]  += n
                        stats["horses"] += sum(len(r.get("horses", [])) for r in races)
                        db.add(ScrapeLog(race_date=date_str, city_id=city_id,
                                         status="ok", races_found=n))
                    else:
                        db.add(ScrapeLog(race_date=date_str, city_id=city_id,
                                         status="no_data"))
                    db.commit()
                except Exception as e:
                    log.error(f"Hata {city_name} {date_str}: {e}")
                    stats["errors"] += 1
                    db.rollback()

                time.sleep(delay)

            stats["days"] += 1
            current += timedelta(days=1)
    finally:
        db.close()

    return stats
