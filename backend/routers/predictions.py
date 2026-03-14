"""
routers/predictions.py
----------------------
Matematiksel tahmin motoru:
  - Bayesian skor (prior: tarihsel + posterior: son form)
  - ELO rating sistemi
  - Pist × Mesafe uyum matrisi
  - Form eğrisi ivmesi
  - Jokey - At sinerji skoru
  - Ağırlık / HP normalizasyonu
  - Sürpriz tespiti (istatistiksel outlier)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models.database import Race, HorseRace, Horse, get_db
import math

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# PUBLIC ENDPOINT
# ─────────────────────────────────────────────────────────────

@router.get("/{race_id}")
def predict_race(race_id: int, db: Session = Depends(get_db)):
    """Bir koşu için tam tahmin üret"""
    race = db.query(Race).filter(Race.id == race_id).first()
    if not race:
        return {"error": "Koşu bulunamadı"}

    horse_races = (
        db.query(HorseRace)
        .filter(HorseRace.race_id == race_id)
        .order_by(HorseRace.start_no)
        .all()
    )

    if not horse_races:
        return {"error": "Bu koşuda at kaydı yok"}

    scored = []
    for hr in horse_races:
        history = _get_history(hr.horse_id, race_id, db)
        score   = _compute_score(hr, race, history, db)
        scored.append({
            "start_no":     hr.start_no,
            "horse_name":   hr.horse.name,
            "jockey":       hr.jockey,
            "weight_kg":    hr.weight_kg,
            "handicap_pts": hr.handicap_pts,
            "last_6_races": hr.last_6_races,
            "ganyan_odds":  hr.ganyan_odds,
            "score":        score,
        })

    # Normalize → olasılık
    total = sum(s["score"]["total"] for s in scored) or 1
    for s in scored:
        s["win_probability"] = round(s["score"]["total"] / total * 100, 1)

    # Sırala
    ranked = sorted(scored, key=lambda x: x["win_probability"], reverse=True)
    for i, s in enumerate(ranked):
        s["predicted_rank"] = i + 1

    # Sürpriz tespiti
    surprise = _detect_surprise(ranked)

    return {
        "race": {
            "id":         race.id,
            "date":       race.race_date,
            "city":       race.city,
            "race_no":    race.race_no,
            "track":      race.track,
            "distance_m": race.distance_m,
        },
        "predictions":    ranked,
        "surprise":       surprise,
        "confidence_pct": _overall_confidence(ranked),
        "model_weights":  MODEL_WEIGHTS,
    }


# ─────────────────────────────────────────────────────────────
# MODEL WEIGHTS
# ─────────────────────────────────────────────────────────────

MODEL_WEIGHTS = {
    "form_curve":      0.25,   # Son form ivmesi
    "track_match":     0.20,   # Pist uyumu
    "distance_match":  0.18,   # Mesafe uyumu
    "bayesian":        0.15,   # Bayesian skor
    "jockey_synergy":  0.10,   # Jokey-at sinerji
    "hp_normalized":   0.07,   # Handikap puanı
    "elo":             0.05,   # ELO rating
}


# ─────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────

def _compute_score(hr: HorseRace, race: Race, history: list, db: Session) -> dict:
    scores = {}

    # 1. Form eğrisi ivmesi
    scores["form_curve"]     = _form_curve_score(history)

    # 2. Pist uyumu
    scores["track_match"]    = _track_match_score(hr.horse_id, race.track, db)

    # 3. Mesafe uyumu
    scores["distance_match"] = _distance_match_score(hr.horse_id, race.distance_m, db)

    # 4. Bayesian skor
    scores["bayesian"]       = _bayesian_score(history)

    # 5. Jokey sinerji
    scores["jockey_synergy"] = _jockey_synergy_score(hr.horse_id, hr.jockey, db)

    # 6. HP normalizasyon
    scores["hp_normalized"]  = _hp_score(hr.handicap_pts)

    # 7. ELO
    scores["elo"]            = _elo_score(history)

    # Ağırlıklı toplam
    total = sum(scores[k] * MODEL_WEIGHTS[k] for k in scores)

    # KGS cezası (çok uzun koşmama)
    if hr.kgs and hr.kgs > 60:
        total *= 0.85
    elif hr.kgs and hr.kgs > 30:
        total *= 0.95

    scores["total"] = max(0.01, total)
    return scores


def _get_history(horse_id: int, exclude_race_id: int, db: Session) -> list:
    rows = (
        db.query(HorseRace, Race)
        .join(Race)
        .filter(
            HorseRace.horse_id == horse_id,
            HorseRace.race_id  != exclude_race_id,
            HorseRace.finish_pos.isnot(None)
        )
        .order_by(desc(Race.race_date))
        .limit(30)
        .all()
    )
    return rows


# ─────────────────────────────────────────────────────────────
# INDIVIDUAL SCORING FUNCTIONS
# ─────────────────────────────────────────────────────────────

def _form_curve_score(history: list) -> float:
    """
    Son koşuların ağırlıklı ortalaması.
    Son koşular daha önemli (üstel ağırlık).
    """
    if not history:
        return 0.5   # nötr

    recent = history[:8]
    weights = [math.exp(-0.3 * i) for i in range(len(recent))]
    total_w = sum(weights)

    # Konum → skor: 1. = 1.0, 2. = 0.75, 3. = 0.55, daha aşağı → düşer
    def pos_to_score(pos):
        if pos == 1: return 1.0
        if pos == 2: return 0.75
        if pos == 3: return 0.55
        if pos == 4: return 0.35
        if pos == 5: return 0.20
        return max(0.05, 0.20 - (pos - 5) * 0.03)

    weighted_sum = sum(
        pos_to_score(hr.finish_pos) * weights[i]
        for i, (hr, r) in enumerate(recent)
    )
    return min(1.0, weighted_sum / total_w)


def _track_match_score(horse_id: int, track: str, db: Session) -> float:
    """O pisttte tarihsel kazanma oranı"""
    if not track:
        return 0.5

    all_on_track = db.query(HorseRace).join(Race).filter(
        HorseRace.horse_id == horse_id,
        Race.track == track,
        HorseRace.finish_pos.isnot(None)
    ).count()

    if all_on_track < 2:
        return 0.5   # Yetersiz veri

    wins = db.query(HorseRace).join(Race).filter(
        HorseRace.horse_id == horse_id,
        Race.track == track,
        HorseRace.finish_pos == 1
    ).count()

    top3 = db.query(HorseRace).join(Race).filter(
        HorseRace.horse_id == horse_id,
        Race.track == track,
        HorseRace.finish_pos <= 3
    ).count()

    # %60 kazanma + %40 ilk 3
    score = 0.6 * (wins / all_on_track) + 0.4 * (top3 / all_on_track)
    return min(1.0, score * 1.2)   # slight boost for matched data


def _distance_match_score(horse_id: int, distance_m: int, db: Session) -> float:
    """Mesafe uyumu — benzer mesafelerdeki başarı"""
    if not distance_m:
        return 0.5

    # ±100m tolerans
    low, high = distance_m - 100, distance_m + 100

    all_dist = db.query(HorseRace).join(Race).filter(
        HorseRace.horse_id == horse_id,
        Race.distance_m.between(low, high),
        HorseRace.finish_pos.isnot(None)
    ).count()

    if all_dist < 2:
        return 0.5

    wins = db.query(HorseRace).join(Race).filter(
        HorseRace.horse_id == horse_id,
        Race.distance_m.between(low, high),
        HorseRace.finish_pos == 1
    ).count()

    top3 = db.query(HorseRace).join(Race).filter(
        HorseRace.horse_id == horse_id,
        Race.distance_m.between(low, high),
        HorseRace.finish_pos <= 3
    ).count()

    return min(1.0, 0.6 * (wins / all_dist) + 0.4 * (top3 / all_dist) + 0.1)


def _bayesian_score(history: list) -> float:
    """
    Bayesian güncelleme:
    Prior = genel kazanma oranı (beta dağılımı)
    Posterior = son 6 koşuyla güncelle
    """
    if not history:
        return 0.2   # prior: zayıf

    all_pos = [hr.finish_pos for hr, r in history]
    total   = len(all_pos)
    wins    = sum(1 for p in all_pos if p == 1)
    top3    = sum(1 for p in all_pos if p <= 3)

    # Beta prior: alpha=wins+1, beta=losses+1
    alpha = wins + 1
    beta  = (total - wins) + 1
    prior_mean = alpha / (alpha + beta)

    # Son 6 koşuya extra ağırlık (likelihood update)
    recent6 = all_pos[:6]
    rec_wins = sum(1 for p in recent6 if p == 1)
    rec_top3 = sum(1 for p in recent6 if p <= 3)

    # Posterior (simplified)
    posterior = (prior_mean * 0.5 +
                 (rec_wins / len(recent6)) * 0.35 +
                 (rec_top3 / len(recent6)) * 0.15)

    return min(1.0, posterior)


def _jockey_synergy_score(horse_id: int, jockey: str, db: Session) -> float:
    """Bu jokey ile bu at'ın geçmiş sinerji skoru"""
    if not jockey:
        return 0.5

    together = db.query(HorseRace).filter(
        HorseRace.horse_id == horse_id,
        HorseRace.jockey == jockey,
        HorseRace.finish_pos.isnot(None)
    ).count()

    if together < 2:
        return 0.5

    wins = db.query(HorseRace).filter(
        HorseRace.horse_id == horse_id,
        HorseRace.jockey == jockey,
        HorseRace.finish_pos == 1
    ).count()

    return min(1.0, 0.4 + (wins / together) * 0.8)


def _hp_score(hp: float | None) -> float:
    """HP puanını 0-1 skalasına normalize et"""
    if hp is None:
        return 0.5
    # TJK HP genellikle 50-120 arasında
    normalized = min(1.0, max(0.0, (hp - 50) / 70))
    return 0.3 + normalized * 0.7   # 0.3 - 1.0 aralığı


def _elo_score(history: list) -> float:
    """
    Basit ELO simülasyonu — her 1. = +32, her derece dışı = -16
    Başlangıç: 1500
    """
    elo = 1500.0
    for hr, r in reversed(history):   # eskiden yeniye
        if hr.finish_pos == 1:
            elo += 32
        elif hr.finish_pos == 2:
            elo += 16
        elif hr.finish_pos == 3:
            elo += 8
        elif hr.finish_pos and hr.finish_pos > 5:
            elo -= 16

    # 1200-1900 arasını 0-1'e map et
    return min(1.0, max(0.0, (elo - 1200) / 700))


# ─────────────────────────────────────────────────────────────
# SURPRISE DETECTION
# ─────────────────────────────────────────────────────────────

def _detect_surprise(ranked: list) -> dict | None:
    """
    Düşük tahmin skoru ama yüksek beklenen değer olan at.
    Uzun oran × tarihsel hidden pattern = sürpriz.
    """
    # Son sıradakilerin ganyan oranlarına bak
    candidates = [h for h in ranked if h["predicted_rank"] >= 4]
    if not candidates:
        return None

    # Yüksek ganyan odası ama geçmişte bu koşulda iyi koşmuş
    best = None
    best_ev = 0

    for h in candidates:
        odds = h.get("ganyan_odds") or 15.0
        prob = h["win_probability"] / 100
        # Beklenen değer (Expected Value)
        ev = odds * prob - 1

        track_score = h["score"].get("track_match", 0)
        dist_score  = h["score"].get("distance_match", 0)

        # Sürpriz kriteri: EV > 0 VE pist/mesafe uyumu iyi
        if ev > 0.3 and (track_score + dist_score) > 0.9 and ev > best_ev:
            best_ev = ev
            best    = h

    if not best:
        # Fallback: en yüksek ganyanı olan
        best = max(candidates, key=lambda x: x.get("ganyan_odds") or 0)
        if not best or (best.get("ganyan_odds") or 0) < 10:
            return None

    return {
        "horse_name":    best["horse_name"],
        "start_no":      best["start_no"],
        "ganyan_odds":   best.get("ganyan_odds"),
        "win_probability":best["win_probability"],
        "expected_value": round(best_ev, 2),
        "reason": _surprise_reason(best),
    }


def _surprise_reason(h: dict) -> str:
    reasons = []
    sc = h.get("score", {})

    if sc.get("track_match", 0) > 0.6:
        reasons.append("bu pistte tarihi başarı yüksek")
    if sc.get("distance_match", 0) > 0.6:
        reasons.append("mesafe uyumu güçlü")
    if sc.get("jockey_synergy", 0) > 0.6:
        reasons.append("jokey sinerji pozitif")
    if sc.get("elo", 0) > 0.6:
        reasons.append("ELO rating yükseliyor")

    odds = h.get("ganyan_odds") or 15
    if odds > 10:
        reasons.append(f"düşük favori — yüksek ödeme ({odds:.1f}×)")

    return "; ".join(reasons) if reasons else "istatistiksel sapma tespit edildi"


def _overall_confidence(ranked: list) -> int:
    """Tahmin güven skoru %"""
    if not ranked:
        return 0
    top_prob = ranked[0]["win_probability"] if ranked else 0
    gap      = (ranked[0]["win_probability"] - ranked[1]["win_probability"]) if len(ranked) > 1 else 0

    # Güven = lider ne kadar net öne çıkıyor
    confidence = min(95, int(40 + top_prob * 0.6 + gap * 0.8))
    return confidence
