"""SQLAlchemy ORM models (tables)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[Optional[int]] = mapped_column(Integer)
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Ambulance(Base):
    __tablename__ = "ambulances"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    registration: Mapped[str] = mapped_column(String(32))
    crew: Mapped[Optional[str]] = mapped_column(String(200))
    base_location: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    route_preset: Mapped[Optional[str]] = mapped_column(String(40))
    route_source: Mapped[Optional[str]] = mapped_column(String(60))
    config_json: Mapped[Optional[str]] = mapped_column(Text)


class PatientVital(Base):
    __tablename__ = "patient_vitals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    patient_id: Mapped[str] = mapped_column(String(16), ForeignKey("patients.id"))
    packet_id: Mapped[Optional[str]] = mapped_column(String(16))
    timestamp: Mapped[str] = mapped_column(String(40), index=True)
    sim_time_s: Mapped[float] = mapped_column(Float)
    heart_rate: Mapped[float] = mapped_column(Float)
    spo2: Mapped[float] = mapped_column(Float)
    temperature: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="SIMULATED")


class AmbulanceLocation(Base):
    __tablename__ = "ambulance_locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    ambulance_id: Mapped[str] = mapped_column(String(16), ForeignKey("ambulances.id"))
    timestamp: Mapped[str] = mapped_column(String(40))
    sim_time_s: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float] = mapped_column(Float)
    distance_to_hospital_km: Mapped[float] = mapped_column(Float)


class BaseStation(Base):
    __tablename__ = "base_stations"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    network_type: Mapped[str] = mapped_column(String(4))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    tx_power_dbm: Mapped[float] = mapped_column(Float)
    frequency_ghz: Mapped[float] = mapped_column(Float)
    bandwidth_mhz: Mapped[float] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class NetworkEvent(Base):
    __tablename__ = "network_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    timestamp: Mapped[str] = mapped_column(String(40))
    sim_time_s: Mapped[float] = mapped_column(Float)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    network_type: Mapped[Optional[str]] = mapped_column(String(8))
    from_bs: Mapped[Optional[str]] = mapped_column(String(16))
    to_bs: Mapped[Optional[str]] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[Optional[str]] = mapped_column(Text)


class HandoverLog(Base):
    __tablename__ = "handover_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    ho_id: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[str] = mapped_column(String(40))
    sim_time_s: Mapped[float] = mapped_column(Float)
    from_bs: Mapped[str] = mapped_column(String(16))
    to_bs: Mapped[str] = mapped_column(String(16))
    from_type: Mapped[str] = mapped_column(String(4))
    to_type: Mapped[str] = mapped_column(String(4))
    reason: Mapped[str] = mapped_column(String(40))
    interruption_ms: Mapped[float] = mapped_column(Float)
    rsrp_from_dbm: Mapped[Optional[float]] = mapped_column(Float)
    rsrp_to_dbm: Mapped[Optional[float]] = mapped_column(Float)


class PacketLog(Base):
    __tablename__ = "packet_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    packet_id: Mapped[str] = mapped_column(String(16))
    patient_id: Mapped[str] = mapped_column(String(16))
    ambulance_id: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[str] = mapped_column(String(40))
    sim_time_s: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), index=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    network_type: Mapped[Optional[str]] = mapped_column(String(8))
    base_station: Mapped[Optional[str]] = mapped_column(String(16))
    buffered: Mapped[bool] = mapped_column(Boolean, default=False)
    harq_tx: Mapped[Optional[int]] = mapped_column(Integer)
    ble_latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    loss_reason: Mapped[Optional[str]] = mapped_column(String(40))
    heart_rate: Mapped[Optional[float]] = mapped_column(Float)
    spo2: Mapped[Optional[float]] = mapped_column(Float)
    temperature: Mapped[Optional[float]] = mapped_column(Float)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[Optional[str]] = mapped_column(String(20))


class EmergencyAlert(Base):
    __tablename__ = "emergency_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    alert_id: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[str] = mapped_column(String(40))
    sim_time_s: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(12))
    category: Mapped[str] = mapped_column(String(12))
    alert_type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[Optional[float]] = mapped_column(Float)


class DoctorMessage(Base):
    __tablename__ = "doctor_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    msg_id: Mapped[str] = mapped_column(String(16))
    sender: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text)
    sent_ts: Mapped[str] = mapped_column(String(40))
    delivered_ts: Mapped[Optional[str]] = mapped_column(String(40))
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    network_type: Mapped[Optional[str]] = mapped_column(String(8))


class SimulationExperiment(Base):
    __tablename__ = "simulation_experiments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    configuration: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(60))
    avg_latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    avg_realtime_latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    p95_latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    avg_throughput_mbps: Mapped[Optional[float]] = mapped_column(Float)
    goodput_kbps: Mapped[Optional[float]] = mapped_column(Float)
    pdr_pct: Mapped[Optional[float]] = mapped_column(Float)
    packet_loss_pct: Mapped[Optional[float]] = mapped_column(Float)
    availability_pct: Mapped[Optional[float]] = mapped_column(Float)
    handover_count: Mapped[Optional[int]] = mapped_column(Integer)
    avg_interruption_ms: Mapped[Optional[float]] = mapped_column(Float)
    buffered_packets: Mapped[Optional[int]] = mapped_column(Integer)
    recovered_packets: Mapped[Optional[int]] = mapped_column(Integer)
    avg_recovery_time_s: Mapped[Optional[float]] = mapped_column(Float)
    packets_offered: Mapped[Optional[int]] = mapped_column(Integer)
    params_json: Mapped[Optional[str]] = mapped_column(Text)
    metrics_json: Mapped[Optional[str]] = mapped_column(Text)
