"""
tjk_real.py — TJK Gerçek Veri Scraper
Playwright ile TJK'nın gerçek HTML yapısını parse eder.
"""

import asyncio
import re
import time
import logging
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from models.database import SessionLocal, Race, Horse, HorseRace, ScrapeLog

log = logging.getLogger(__name__)

BASE = "https://www.tjk.org"
UA   = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

def p_int(v):
    try: return int(re.sub(r"[^\d]","",str(v)))
    except: return None

def p_float(v):
    try: return float(str(v).replace(",",".").strip())
    except: return None

def clean(v):
    return str(v).strip() if v else ""

async def get_city_links(date_str: str) -> list[dict]:
    """Günlük ana sayfadan şehir linklerini çek"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=UA)
        page    = await context.new_page()
        url = f"{BASE}/TR/YarisSever/Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih={date_str}&Era=past"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        links = await page.query_selector_all("a[href*=SehirId]")
        cities = []
        seen = set()
        for l in links:
            href = await l.get_attribute("href") or ""
            text = await l.inner_text()
            # Sadece Türkiye hipodromları — yabancı olanları atla
            if any(x in text for x in ["ABD","Afrika","Arjantin","Avustralya","Krallık","Fransa","İrlanda","Japonya","İtalya","Almanya","Belçika","BAE","Kanada","Hong"]):
                continue
            m = re.search(r"SehirId=(\d+)", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                cities.append({
                    "city_id":   int(m.group(1)),
                    "city_name": text.split("(")[0].strip(),
                    "url":       BASE + href if href.startswith("/") else href,
                })
        await browser.close()
    return cities

async def scrape_city(url: str, city_id: int, city_name: str, date_str: str) -> list[dict]:
    """Bir şehrin yarış sayfasını parse et"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=UA)
        page    = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        text = await page.inner_text("body")
        await browser.close()

    return parse_races(text, city_id, city_name, date_str)

def parse_races(text: str, city_id: int, city_name: str, date_str: str) -> list[dict]:
    """Sayfa metninden koşuları parse et"""
    races = []
    # Koşuları böl
    blocks = re.split(r"(\d+)\.\s*Koşu\s*[:：]?\s*(\d{1,2}[:.]\d{2})", text)

    i = 1
    while i < len(blocks) - 2:
        race_no  = p_int(blocks[i])
        time_str = clean(blocks[i+1])
        body     = blocks[i+2] if i+2 < len(blocks) else ""
        i += 3

        if not race_no:
            continue

        # Mesafe
        dist_m = re.search(r"(\d{3,4})\s*(?:Kum|Çim|Sentetik|m\b)", body)
        dist   = p_int(dist_m.group(1)) if dist_m else None

        # Pist
        track_m = re.search(r"(Kum|Çim|Sentetik)", body)
        track   = track_m.group(1) if track_m else None

        # Koşu adı
        name_m = re.search(r"^(.+?),\s*\d", body.strip())
        race_name = clean(name_m.group(1))[:100] if name_m else None

        horses = parse_horses(body)
        if not horses:
            continue

        races.append({
            "race_date":  date_str,
            "city":       city_name,
            "city_id":    city_id,
            "race_no":    race_no,
            "race_name":  race_name,
            "track":      track,
            "distance_m": dist,
            "start_time": time_str,
            "horses":     horses,
        })

    return races

def parse_horses(body: str) -> list[dict]:
    """At satırlarını parse et"""
    horses = []
    # TJK formatı: S\tAt İsmi\tYaş\tOrijin\tSıklet\tJokey\tSahip\tAntrenör\tDerece\tGny\tAGF\tSt\tFark\tG.Çık\tHP
    rows = re.findall(
        r"^(\d{1,2})\s+([A-ZÇĞİÖŞÜa-zçğışöüÇĞİÖŞÜ\(\)\s\d]+?)\s+(\d+y\s*[dka]\s*[ak]?)\s+(.+?)\s+([\d,]+)\s+(.+?)\s+(.+?)\s+(.+?)\s+([\d:.]+|0)\s+([\d,.]+)",
        body, re.MULTILINE
    )

    for row in rows:
        horses.append({
            "start_no":    p_int(row[0]),
            "horse_name":  clean(row[1]),
            "age":         p_int(re.search(r"(\d+)", row[2]).group(1)) if re.search(r"(\d+)", row[2]) else None,
            "jockey":      clean(row[5]),
            "owner":       clean(row[6]),
            "trainer":     clean(row[7]),
            "finish_time": clean(row[8]),
            "ganyan_odds": p_float(row[9]),
        })

    # Fallback: basit satır parse
    if not horses:
        lines = body.split("\n")
        for line in lines:
            parts = line.strip().split()
            if not parts or not re.match(r"^\d{1,2}$", parts[0]):
                continue
            if len(parts) < 4:
                continue
            horses.append({
                "start_no":   p_int(parts[0]),
                "horse_name": clean(parts[1]) if len(parts)>1 else None,
                "jockey":     clean(parts[5]) if len(parts)>5 else None,
                "ganyan_odds":p_float(parts[-1]),
            })

    return [h for h in horses if h.get("horse_name") and len(h["horse_name"]) > 1]

def save(db, races):
    saved = 0
    for r in races:
        ex = db.query(Race).filter_by(race_date=r["race_date"], city_id=r["city_id"], race_no=r["race_no"]).first()
        if ex:
            continue
        ro = Race(
            race_date=r["race_date"], city=r["city"], city_id=r["city_id"],
            race_no=r["race_no"], race_name=r.get("race_name"),
            track=r.get("track"), distance_m=r.get("distance_m"),
            start_time=r.get("start_time"),
        )
        db.add(ro); db.flush()
        for h in r.get("horses", []):
            ho = db.query(Horse).filter_by(name=h["horse_name"]).first()
            if not ho:
                ho = Horse(name=h["horse_name"], birth_year=(2026-h["age"]) if h.get("age") else None)
                db.add(ho); db.flush()
            db.add(HorseRace(
                race_id=ro.id, horse_id=ho.id,
                start_no=h.get("start_no"), jockey=h.get("jockey"),
                owner=h.get("owner"), trainer=h.get("trainer"),
                finish_time=h.get("finish_time"), ganyan_odds=h.get("ganyan_odds"),
            ))
        db.commit()
        saved += 1
    return saved

async def scrape_date(date_str: str) -> dict:
    """Tek bir günü tara"""
    cities = await get_city_links(date_str)
    log.info(f"{date_str}: {len(cities)} Türkiye hipodromu")
    db = SessionLocal()
    total_races = 0
    total_horses = 0
    try:
        for c in cities:
            races = await scrape_city(c["url"], c["city_id"], c["city_name"], date_str)
            if races:
                n = save(db, races)
                total_races += n
                total_horses += sum(len(r.get("horses",[])) for r in races)
                log.info(f"  {c['city_name']}: {n} koşu kaydedildi")
            await asyncio.sleep(1)
    finally:
        db.close()
    return {"date": date_str, "races": total_races, "horses": total_horses}

def scrape_range(from_date: str, to_date: str):
    """Tarih aralığını tara"""
    fmt = "%d/%m/%Y"
    start = datetime.strptime(from_date, fmt)
    end   = datetime.strptime(to_date, fmt)
    cur   = start
    stats = {"days":0, "races":0, "horses":0}
    while cur <= end:
        ds = cur.strftime(fmt)
        result = asyncio.run(scrape_date(ds))
        stats["days"]   += 1
        stats["races"]  += result["races"]
        stats["horses"] += result["horses"]
        print(f"✅ {ds}: {result['races']} koşu, {result['horses']} at")
        cur += timedelta(days=1)
        time.sleep(2)
    return stats

if __name__ == "__main__":
    import sys
    from_d = sys.argv[1] if len(sys.argv)>1 else "18/03/2026"
    to_d   = sys.argv[2] if len(sys.argv)>2 else "18/03/2026"
    print(scrape_range(from_d, to_d))
