"""
models/database.py — SQLite + SQLAlchemy ORM
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Text, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "galop.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── TABLES ───────────────────────────────────────────────────

class Race(Base):
    __tablename__ = "races"

    id              = Column(Integer, primary_key=True, index=True)
    race_date       = Column(String(10), nullable=False, index=True)
    city            = Column(String(50), nullable=False, index=True)
    city_id         = Column(Integer)
    race_no         = Column(Integer)
    race_name       = Column(String(200))
    track           = Column(String(20))          # Çim / Kum / Sentetik
    track_condition = Column(String(20))          # İyi / Yumuşak / Ağır
    distance_m      = Column(Integer)
    start_time      = Column(String(10))
    race_class      = Column(String(50))          # Handikap / Grup / Maiden
    prize_tl        = Column(Float)
    created_at      = Column(DateTime, server_default=func.now())

    horses = relationship("HorseRace", back_populates="race")

    __table_args__ = (
        Index("idx_race_date_city", "race_date", "city"),
    )


class Horse(Base):
    __tablename__ = "horses"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False, unique=True, index=True)
    birth_year  = Column(Integer)
    gender      = Column(String(10))              # Erkek / Dişi / İğdiş
    sire        = Column(String(100))             # Baba
    dam         = Column(String(100))             # Anne
    color       = Column(String(30))
    breeder     = Column(String(100))
    origin      = Column(String(50))              # TR / GB / FR / ...
    active      = Column(Integer, default=1)      # 1=aktif 0=emekli
    created_at  = Column(DateTime, server_default=func.now())
    updated_at  = Column(DateTime, onupdate=func.now())

    races = relationship("HorseRace", back_populates="horse")


class HorseRace(Base):
    """At + Koşu ilişkisi — her satır bir at'ın bir koşudaki performansı"""
    __tablename__ = "horse_races"

    id              = Column(Integer, primary_key=True, index=True)
    race_id         = Column(Integer, ForeignKey("races.id"), nullable=False)
    horse_id        = Column(Integer, ForeignKey("horses.id"), nullable=False)

    # Program bilgisi
    start_no        = Column(Integer)
    jockey          = Column(String(100))
    trainer         = Column(String(100))
    owner           = Column(String(100))
    weight_kg       = Column(Float)
    handicap_pts    = Column(Float)               # HP
    kgs             = Column(Integer)             # Koşmama gün sayısı
    last_6_races    = Column(String(20))          # "1-2-1-3-1-2"
    s20             = Column(String(50))          # Son 20 performans özeti
    eid             = Column(String(20))          # En iyi derece
    agf             = Column(Float)               # Ağırlıklı Galibiyet Faktörü
    gny_score       = Column(Float)               # Günlük Nispi Yarış puanı

    # Sonuç
    finish_pos      = Column(Integer)             # NULL = henüz koşmadı
    finish_time     = Column(String(20))
    margin          = Column(String(20))          # Fark (boy, baş, boyun...)
    ganyan_odds     = Column(Float)
    place_odds      = Column(Float)

    # İlişkiler
    race  = relationship("Race",  back_populates="horses")
    horse = relationship("Horse", back_populates="races")

    __table_args__ = (
        Index("idx_hr_race",  "race_id"),
        Index("idx_hr_horse", "horse_id"),
    )


class ScrapeLog(Base):
    __tablename__ = "scrape_log"

    id          = Column(Integer, primary_key=True)
    race_date   = Column(String(10))
    city_id     = Column(Integer)
    status      = Column(String(20))              # ok / no_data / error
    races_found = Column(Integer, default=0)
    scraped_at  = Column(DateTime, server_default=func.now())


# ── DB INIT ──────────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)
    print(f"✅ DB hazır: {DB_PATH}")


def get_db():
    """FastAPI dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
