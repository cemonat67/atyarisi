"""
scrapers/tjk_playwright.py
--------------------------
TJK.org JavaScript render'lı sayfalarını Playwright ile çeker.
Requests ile veri gelmediğinde bu scraper devreye girer.
"""

import re
import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.database import Race, Horse, HorseRace, ScrapeLog, SessionLocal

log = logging.getLogger(__name__)

BASE_URL = "https://www.tjk.org"

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


# ── HELPERS ──────────────────────────────────────────────────

def parse_int(v):
    try:   return int(re.sub(r"[^\d]", "", str(v)))
    except: return None

def parse_float(v):
    try:   return float(str(v).replace(",", ".").strip())
    except: return None

def clean(v):
    return str(v).strip() if v else ""


# ── PLAYWRIGHT SCRAPER ────────────────────────────────────────

async def fetch_city_races_pw(city_id: int, city_name: str, date_str: str) -> list[dict]:
    """
    Playwright ile TJK şehir yarış sayfasını çeker.
    date_str: GG/AA/YYYY
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("Playwright yüklü değil: pip install playwright && playwright install chromium")
        return []

    url = (
        f"{BASE_URL}/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari"
        f"?SehirId={city_id}"
        f"&QueryParameter_Tarih={date_str}"
        f"&Era=past"
        f"&SehirAdi={city_name}"
    )

    races = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Sayfanın yüklenmesini bekle
            await page.wait_for_timeout(2000)

            # Tüm koşu bloklarını bul
            # TJK sayfasında koşular genellikle accordion veya tab içinde
            race_tabs = await page.query_selector_all("[id*='kos'], [class*='race'], [class*='kosu']")

            if not race_tabs:
                # Fallback: tüm tabloları al
                race_tabs = await page.query_selector_all("table")

            for tab in race_tabs:
                html = await tab.inner_html()
                text = await tab.inner_text()

                race = _parse_race_text(text, html, city_id, city_name, date_str)
                if race:
                    races.append(race)

            # Eğer hâlâ boşsa tüm sayfayı parse et
            if not races:
                full_text = await page.inner_text("body")
                full_html = await page.inner_html("body")
                races = _parse_full_page(full_text, full_html, city_id, city_name, date_str)

        except Exception as e:
            log.error(f"Playwright hata {city_name} {date_str}: {e}")
        finally:
            await browser.close()

    log.info(f"  [PW] {city_name} {date_str}: {len(races)} koşu")
    return races


async def fetch_today_program_pw(city_id: int, city_name: str) -> list[dict]:
    """
    Bugünün PROGRAM sayfasını çeker (sonuçlar değil — yarış öncesi).
    """
    from datetime import date
    today = date.today().strftime("%d/%m/%Y")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    url = (
        f"{BASE_URL}/TR/YarisSever/Info/Sehir/GunlukYarisProgrami"
        f"?SehirId={city_id}"
        f"&QueryParameter_Tarih={today}"
        f"&SehirAdi={city_name}"
    )

    races = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # Koşu bloklarını tara
            content = await page.content()
            races = _parse_program_html(content, city_id, city_name, today)

        except Exception as e:
            log.error(f"Program fetch hatası: {e}")
        finally:
            await browser.close()

    return races


# ── PARSE FONKSİYONLARI ───────────────────────────────────────

def _parse_race_text(text: str, html: str, city_id, city_name, date_str) -> dict | None:
    """Metin bloğundan tek koşu parse et"""
    m = re.search(r"(\d+)\.\s*[Kk]o[şs]u", text)
    if not m:
        return None

    race_no = int(m.group(1))

    dist_m = re.search(r"(\d{3,4})\s*[Mm]", text)
    track_m = re.search(r"(Çim|Kum|Sentetik|Dirt)", text, re.I)
    time_m = re.search(r"(\d{1,2}:\d{2})", text)
    cond_m = re.search(r"(İyi|Yumuşak|Ağır|Sert)", text, re.I)

    horses = _parse_horse_rows(text)
    if not horses:
        return None

    return {
        "race_date":       date_str,
        "city":            city_name,
        "city_id":         city_id,
        "race_no":         race_no,
        "race_name":       None,
        "track":           track_m.group(1).capitalize() if track_m else None,
        "track_condition": cond_m.group(1) if cond_m else None,
        "distance_m":      int(dist_m.group(1)) if dist_m else None,
        "start_time":      time_m.group(1) if time_m else None,
        "horses":          horses,
    }


def _parse_horse_rows(text: str) -> list[dict]:
    """
    Satır bazlı at parse.
    TJK formatı: No  AtAdı  Yaş  Kilo  Jokey  HP  KGS  Son6  Derece  Ganyan
    """
    horses = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        parts = re.split(r"\s{2,}|\t", line)
        if len(parts) < 3:
            continue
        if not re.match(r"^\d{1,2}$", parts[0]):
            continue

        h = {
            "start_no":     parse_int(parts[0]),
            "horse_name":   clean(parts[1]) if len(parts) > 1 else None,
            "age":          parse_int(parts[2]) if len(parts) > 2 else None,
            "weight_kg":    parse_float(parts[3]) if len(parts) > 3 else None,
            "jockey":       clean(parts[4]) if len(parts) > 4 else None,
            "trainer":      clean(parts[5]) if len(parts) > 5 else None,
            "handicap_pts": parse_float(parts[6]) if len(parts) > 6 else None,
            "kgs":          parse_int(parts[7]) if len(parts) > 7 else None,
            "last_6_races": clean(parts[8]) if len(parts) > 8 else None,
            "finish_pos":   parse_int(parts[9]) if len(parts) > 9 else None,
            "ganyan_odds":  parse_float(parts[10]) if len(parts) > 10 else None,
        }

        if h["horse_name"] and len(h["horse_name"]) > 1:
            horses.append(h)

    return horses


def _parse_full_page(text: str, html: str, city_id, city_name, date_str) -> list[dict]:
    """Tüm sayfa metnini koşu bloklarına böler"""
    races = []
    # Koşu sınırları: "1. Koşu", "2. Koşu" ...
    blocks = re.split(r"(?=\d+\.\s*[Kk]o[şs]u)", text)
    for block in blocks:
        if not block.strip():
            continue
        race = _parse_race_text(block, "", city_id, city_name, date_str)
        if race:
            races.append(race)
    return races


def _parse_program_html(html: str, city_id, city_name, date_str) -> list[dict]:
    """Program HTML'ini parse et (BeautifulSoup ile)"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    races = []

    tables = soup.find_all("table")
    for table in tables:
        text = table.get_text("\t", strip=True)
        race = _parse_race_text(text, str(table), city_id, city_name, date_str)
        if race:
            races.append(race)

    return races


# ── SYNC WRAPPER ──────────────────────────────────────────────

def fetch_city_races_sync(city_id: int, city_name: str, date_str: str) -> list[dict]:
    """Async scraper'ı sync olarak çağır"""
    return asyncio.run(fetch_city_races_pw(city_id, city_name, date_str))


def fetch_today_sync(city_id: int, city_name: str) -> list[dict]:
    return asyncio.run(fetch_today_program_pw(city_id, city_name))


# ── BULK SCRAPER (Playwright + fallback) ─────────────────────

def scrape_with_playwright(
    from_date: str,
    to_date:   str,
    city_ids:  list[int] = None,
) -> dict:
    """
    Playwright ile tam veri çekimi.
    Önce requests dener, başarısız olursa Playwright devreye girer.
    """
    import time
    from scrapers.tjk import fetch_city_races as fetch_requests, save_races_to_db

    if city_ids is None:
        city_ids = list(CITIES.keys())

    fmt = "%d/%m/%Y"
    start   = datetime.strptime(from_date, fmt)
    end     = datetime.strptime(to_date,   fmt)
    current = start

    stats = {"days": 0, "races": 0, "horses": 0, "pw_used": 0, "errors": 0}
    db    = SessionLocal()

    try:
        while current <= end:
            date_str = current.strftime(fmt)

            for city_id in city_ids:
                city_name = CITIES.get(city_id, f"Sehir_{city_id}")

                try:
                    # 1. Önce hızlı requests ile dene
                    races = fetch_requests(city_id, city_name, date_str)

                    # 2. Boş geldiyse Playwright dene
                    if not races:
                        log.info(f"  Requests boş — Playwright devreye giriyor: {city_name}")
                        races = fetch_city_races_sync(city_id, city_name, date_str)
                        if races:
                            stats["pw_used"] += 1

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

                time.sleep(1.5)

            stats["days"] += 1
            current += timedelta(days=1)

    finally:
        db.close()

    return stats
