"""Writes simulation output (engine outbox) to the database in batches."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Dict, List, Optional

from sqlalchemy import desc, insert, select

from backend.database import models
from backend.database.db import SessionLocal

log = logging.getLogger(__name__)


def _vitals(run_id, rows):
    return [{"run_id": run_id, "patient_id": r["patient_id"], "packet_id": r["packet_id"],
             "timestamp": r["timestamp"], "sim_time_s": r["sim_time_s"], "heart_rate": r["heart_rate"],
             "spo2": r["spo2"], "temperature": r["temperature"], "source": r["source"]} for r in rows]


def _locations(run_id, rows):
    return [{"run_id": run_id, "ambulance_id": r["ambulance_id"], "timestamp": r["timestamp"],
             "sim_time_s": r["sim_time_s"], "lat": r["lat"], "lon": r["lon"], "speed_kmh": r["speed_kmh"],
             "distance_to_hospital_km": r["distance_to_hospital_km"]} for r in rows]


def _events(run_id, rows):
    return [{"run_id": run_id, "timestamp": r["timestamp"], "sim_time_s": r["time"], "event_type": r["event_type"],
             "network_type": r.get("network_type"), "from_bs": r.get("from_bs"), "to_bs": r.get("to_bs"),
             "message": r["message"], "details_json": json.dumps(r.get("details") or {}, default=str)} for r in rows]


def _handovers(run_id, rows):
    return [{"run_id": run_id, "ho_id": r["ho_id"], "timestamp": r["timestamp"], "sim_time_s": r["time"],
             "from_bs": r["from_bs"], "to_bs": r["to_bs"], "from_type": r["from_type"], "to_type": r["to_type"],
             "reason": r["reason"], "interruption_ms": r["interruption_ms"], "rsrp_from_dbm": r["rsrp_from_dbm"],
             "rsrp_to_dbm": r["rsrp_to_dbm"]} for r in rows]


def _packets(run_id, rows):
    return [{"run_id": run_id, "packet_id": r["packet_id"], "patient_id": r["patient_id"],
             "ambulance_id": r["ambulance_id"], "timestamp": r["timestamp"], "sim_time_s": r["sim_time_s"],
             "status": r["status"], "latency_ms": r.get("latency_ms"),
             "network_type": r.get("tx_network_type") or r.get("network_type"),
             "base_station": r.get("tx_base_station") or r.get("base_station"),
             "buffered": bool(r.get("buffered")), "harq_tx": r.get("harq_tx"),
             "ble_latency_ms": r.get("ble_latency_ms"), "loss_reason": r.get("loss_reason") or None,
             "heart_rate": r.get("heart_rate"), "spo2": r.get("spo2"), "temperature": r.get("temperature"),
             "latitude": r.get("latitude"), "longitude": r.get("longitude"), "source": r.get("source")}
            for r in rows]


def _alerts(run_id, rows):
    return [{"run_id": run_id, "alert_id": r["alert_id"], "timestamp": r["timestamp"], "sim_time_s": r["sim_time_s"],
             "severity": r["severity"], "category": r["category"], "alert_type": r["alert_type"],
             "message": r["message"], "value": r["value"]} for r in rows]


def _messages(run_id, rows):
    return [{"run_id": run_id, "msg_id": r["msg_id"], "sender": r["sender"], "text": r["text"],
             "sent_ts": r["sent_ts"], "delivered_ts": r.get("delivered_ts"), "latency_ms": r.get("latency_ms"),
             "network_type": r.get("network_type")} for r in rows]


_MAP = {
    "vitals": (models.PatientVital, _vitals),
    "locations": (models.AmbulanceLocation, _locations),
    "network_events": (models.NetworkEvent, _events),
    "handovers": (models.HandoverLog, _handovers),
    "packets": (models.PacketLog, _packets),
    "alerts": (models.EmergencyAlert, _alerts),
    "messages": (models.DoctorMessage, _messages),
}


def persist_outbox(run_id: str, outbox: Dict[str, List[dict]]) -> int:
    n = 0
    try:
        with SessionLocal.begin() as s:
            for key, rows in outbox.items():
                if not rows or key not in _MAP:
                    continue
                model, conv = _MAP[key]
                s.execute(insert(model), conv(run_id, rows))
                n += len(rows)
    except Exception:  # never crash the simulation loop because of the DB
        log.exception("Failed to persist simulation outbox")
    return n


def register_run(run_id: str, route_preset: str, route_source: str, config: dict) -> None:
    try:
        with SessionLocal.begin() as s:
            if s.get(models.SimulationRun, run_id) is None:
                s.add(models.SimulationRun(run_id=run_id, route_preset=route_preset, route_source=route_source,
                                           config_json=json.dumps(config, default=str)))
    except Exception:
        log.exception("Failed to register run")


# --------------------------------------------------------------------------- experiments
EXP_FIELDS = ["avg_latency_ms", "avg_realtime_latency_ms", "p95_latency_ms", "avg_throughput_mbps", "goodput_kbps",
              "pdr_pct", "packet_loss_pct", "availability_pct", "handover_count", "avg_interruption_ms",
              "buffered_packets", "recovered_packets", "avg_recovery_time_s", "packets_offered"]


def save_experiment(results: List[dict], params: dict, name: Optional[str]) -> str:
    exp_id = "EXP-" + uuid.uuid4().hex[:8]
    with SessionLocal.begin() as s:
        for r in results:
            m = r["metrics"]
            s.add(models.SimulationExperiment(
                experiment_id=exp_id, name=name, configuration=r["configuration"], label=r["label"],
                params_json=json.dumps(params, default=str), metrics_json=json.dumps(m, default=str),
                **{f: m.get(f) for f in EXP_FIELDS}))
    return exp_id


def list_experiments(limit: int = 60) -> List[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(models.SimulationExperiment)
                         .order_by(desc(models.SimulationExperiment.id)).limit(limit)).all()
        return [{"experiment_id": r.experiment_id, "name": r.name, "created_at": r.created_at.isoformat(),
                 "configuration": r.configuration, "label": r.label,
                 "params": json.loads(r.params_json or "{}"),
                 **{f: getattr(r, f) for f in EXP_FIELDS}} for r in rows]


def query_table(model, run_id: Optional[str], limit: int) -> List[dict]:
    with SessionLocal() as s:
        q = select(model)
        if run_id and hasattr(model, "run_id"):
            q = q.where(model.run_id == run_id)
        q = q.order_by(desc(model.id)).limit(limit)
        rows = s.scalars(q).all()
        return [{c.name: getattr(r, c.name) for c in model.__table__.columns} for r in rows]


def list_runs(limit: int = 30) -> List[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(models.SimulationRun).order_by(desc(models.SimulationRun.started_at))
                         .limit(limit)).all()
        return [{"run_id": r.run_id, "started_at": r.started_at.isoformat(), "route_preset": r.route_preset,
                 "route_source": r.route_source} for r in rows]
