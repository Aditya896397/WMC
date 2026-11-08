"""Create tables and seed reference data.

Run directly:  python -m backend.database.init_db
(It also runs automatically when the FastAPI backend starts.)
"""
from __future__ import annotations

from typing import List

from sqlalchemy import select

from backend.simulation.config import DEFAULT_BASE_STATIONS, BaseStationConfig

from . import models  # noqa: F401  (registers tables)
from .db import DATABASE_URL, Base, SessionLocal, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    seed()


def seed() -> None:
    with SessionLocal.begin() as s:
        if s.get(models.Patient, "P001") is None:
            s.add(models.Patient(id="P001", name="Synthetic Patient 001", age=54, gender="M",
                                 note="Synthetic demo patient — not a real person"))
        if s.get(models.Ambulance, "AMB001") is None:
            s.add(models.Ambulance(id="AMB001", registration="TN-01-AMB-0001 (demo)",
                                   crew="Driver + Paramedic (simulated)", base_location="Saidapet, Chennai"))
        for bs in DEFAULT_BASE_STATIONS:
            if s.get(models.BaseStation, bs.id) is None:
                s.add(models.BaseStation(**bs.model_dump()))


def load_base_stations() -> List[BaseStationConfig]:
    """Base-station config persisted in the DB (edits survive restarts)."""
    with SessionLocal() as s:
        rows = s.scalars(select(models.BaseStation).order_by(models.BaseStation.id)).all()
        return [BaseStationConfig(id=r.id, network_type=r.network_type, lat=r.lat, lon=r.lon,
                                  radius_m=r.radius_m, tx_power_dbm=r.tx_power_dbm,
                                  frequency_ghz=r.frequency_ghz, bandwidth_mhz=r.bandwidth_mhz,
                                  enabled=r.enabled) for r in rows]


def save_base_stations(bss: List[BaseStationConfig]) -> None:
    with SessionLocal.begin() as s:
        for bs in bss:
            row = s.get(models.BaseStation, bs.id)
            if row is None:
                s.add(models.BaseStation(**bs.model_dump()))
            else:
                for k, v in bs.model_dump().items():
                    setattr(row, k, v)


def reset_base_stations() -> List[BaseStationConfig]:
    save_base_stations(DEFAULT_BASE_STATIONS)
    return load_base_stations()


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DATABASE_URL}")
    print("Tables:", ", ".join(sorted(Base.metadata.tables)))
