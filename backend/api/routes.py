"""REST API + WebSocket endpoints."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from backend.database import models
from backend.database.init_db import reset_base_stations, save_base_stations
from backend.models.schemas import (ActionResponse, BaseStationUpdate, ConfigUpdate, ExperimentRequest,
                                    HandoverRequest, LocationIn, MessageIn, NetworkControlRequest, RouteRequest,
                                    ScenarioRequest, SensorControl, VitalsIn)
from backend.services import persistence
from backend.services.runtime import dumps, get_engine, runtime
from backend.simulation.performance import CONFIGURATIONS, live_network_metrics, run_comparison

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
ws_router = APIRouter()

HISTORY_TABLES = {
    "patient_vitals": models.PatientVital, "ambulance_locations": models.AmbulanceLocation,
    "network_events": models.NetworkEvent, "handover_logs": models.HandoverLog, "packet_logs": models.PacketLog,
    "emergency_alerts": models.EmergencyAlert, "doctor_messages": models.DoctorMessage,
}


def ok(message: str = "", data=None) -> ActionResponse:
    return ActionResponse(ok=True, message=message, data=data)


# ============================================================== health
@router.get("/health", tags=["system"])
def health():
    e = get_engine()
    return {"status": "ok", "simulation_status": e.status, "run_id": e.run_id,
            "websocket_clients": len(runtime.manager.active), "ticks": runtime.ticks}


# ============================================================== patient
@router.post("/patient/vitals", tags=["patient"], response_model=ActionResponse)
def post_vitals(v: VitalsIn):
    """Inject an external vitals reading. It is processed by the gateway (packet ID, timestamp,
    validation, forwarding/buffering) exactly like simulated readings."""
    e = get_engine()
    if v.patient_id != "P001":
        raise HTTPException(404, f"Unknown patient '{v.patient_id}'")
    res = e.inject_vitals(v.model_dump(exclude={"patient_id"}))
    return ok(f"Reading accepted as {res['packet_id']} ({res['status']})", res)


@router.get("/patient/vitals", tags=["patient"])
def get_vitals(limit: int = Query(120, ge=1, le=5000), source: Literal["memory", "db"] = "memory"):
    e = get_engine()
    with e.lock:
        p = e.patient_state()
        hist = list(e.vitals_history)[-limit:]
        run_id = e.run_id
    if source == "db":
        hist = list(reversed(persistence.query_table(models.PatientVital, run_id, limit)))
    p.pop("ecg", None)
    return {"patient": p, "latest": p["vitals"], "history": hist, "synthetic": True}


@router.get("/patient/ecg", tags=["patient"])
def get_ecg(seconds: float = Query(4.0, ge=1, le=10)):
    e = get_engine()
    with e.lock:
        return {"hr": e.patient.hr, **e.patient.ecg_window(e.sim_elapsed, seconds), "synthetic": True}


@router.post("/patient/scenario", tags=["patient"], response_model=ActionResponse)
def set_scenario(req: ScenarioRequest):
    get_engine().update_config({"scenario": req.scenario})
    return ok(f"Scenario set to {req.scenario}")


# ============================================================== ambulance
@router.post("/ambulance/location", tags=["ambulance"], response_model=ActionResponse)
def post_location(loc: LocationIn):
    """Relocate the ambulance (the position is snapped to the nearest point on the active route)."""
    if loc.ambulance_id != "AMB001":
        raise HTTPException(404, f"Unknown ambulance '{loc.ambulance_id}'")
    data = get_engine().set_location(loc.latitude, loc.longitude)
    return ok("Location updated", data)


@router.get("/ambulance/location", tags=["ambulance"])
def get_location(limit: int = Query(60, ge=1, le=600)):
    e = get_engine()
    with e.lock:
        return {**e.ambulance_state(), "timestamp": e.ts(e.sim_elapsed),
                "hospital": {"name": e.route["hospital_name"], **e.route["hospital"]},
                "history": list(e.location_history)[-limit:]}


@router.get("/route", tags=["ambulance"])
def get_route():
    return get_engine().route_info()


@router.post("/route", tags=["ambulance"], response_model=ActionResponse)
def set_route(req: RouteRequest):
    e = get_engine()
    e.update_config({"route_preset": req.preset})
    return ok(f"Route set to {req.preset} ({e.route['source']}); simulation reset")


# ============================================================== network
@router.get("/network/status", tags=["network"])
def network_status():
    e = get_engine()
    with e.lock:
        return {**e.network_state(), "timestamp": e.ts(e.sim_elapsed)}


@router.post("/network/handover", tags=["network"], response_model=ActionResponse)
def trigger_handover(req: HandoverRequest):
    evts = get_engine().trigger_handover(req.target_bs)
    return ok(evts[0]["message"], evts[0]["details"])


@router.get("/network/handovers", tags=["network"])
def handovers(limit: int = Query(100, ge=1, le=5000), source: Literal["memory", "db"] = "memory"):
    e = get_engine()
    if source == "db":
        return persistence.query_table(models.HandoverLog, e.run_id, limit)
    with e.lock:
        return e.network.handovers[-limit:]


@router.get("/network/events", tags=["network"])
def network_events(limit: int = Query(100, ge=1, le=200)):
    e = get_engine()
    with e.lock:
        return list(e.network_events)[-limit:]


@router.post("/network/control", tags=["network"], response_model=ActionResponse)
def network_control(req: NetworkControlRequest):
    e = get_engine()
    e.network_control(req.action, req.degradation_db)
    return ok(f"Applied '{req.action}' — network now {e.network.network_type()}",
              e.network_state()["controls"])


@router.get("/network/base_stations", tags=["network"])
def base_stations():
    e = get_engine()
    with e.lock:
        return e.network.base_station_table()


@router.put("/network/base_stations/{bs_id}", tags=["network"], response_model=ActionResponse)
def update_base_station(bs_id: str, upd: BaseStationUpdate):
    e = get_engine()
    row = e.update_base_station(bs_id, upd.model_dump(exclude_none=True))
    save_base_stations(e.config.base_stations)
    return ok(f"{bs_id} updated (saved to database)", row)


@router.post("/network/base_stations/reset", tags=["network"], response_model=ActionResponse)
def reset_bs():
    bss = reset_base_stations()
    get_engine().update_config({"base_stations": [b.model_dump() for b in bss]})
    return ok("Base stations reset to defaults")


# ============================================================== BLE & gateway
@router.get("/ble/status", tags=["ble"])
def ble_status():
    e = get_engine()
    with e.lock:
        return e.ble.stats()


@router.post("/ble/sensor", tags=["ble"], response_model=ActionResponse)
def ble_sensor(req: SensorControl):
    get_engine().set_sensor_connection(req.device_id, req.connected)
    return ok(f"{req.device_id} {'connected' if req.connected else 'disconnected'}")


@router.get("/gateway/packets", tags=["gateway"])
def gateway_packets(limit: int = Query(50, ge=1, le=5000), source: Literal["memory", "db"] = "memory"):
    e = get_engine()
    if source == "db":
        return persistence.query_table(models.PacketLog, e.run_id, limit)
    with e.lock:
        return e.gateway.records[-limit:]


@router.get("/gateway/status", tags=["gateway"])
def gateway_status():
    e = get_engine()
    with e.lock:
        g = e.gateway
        return {**g.counters, "queue_length": len(g.queue), "buffer_capacity": e.config.buffer_capacity,
                "buffering_enabled": e.config.buffering_enabled,
                "queued_packet_ids": [p["packet_id"] for p in list(g.queue)[:50]]}


# ============================================================== alerts & messages
@router.get("/alerts", tags=["alerts"])
def alerts(limit: int = Query(50, ge=1, le=1000), source: Literal["memory", "db"] = "memory"):
    e = get_engine()
    if source == "db":
        return persistence.query_table(models.EmergencyAlert, e.run_id, limit)
    with e.lock:
        return list(e.alerts)[-limit:]


@router.get("/messages", tags=["hospital"])
def get_messages(limit: int = Query(50, ge=1, le=200)):
    e = get_engine()
    with e.lock:
        return list(e.messages)[-limit:]


@router.post("/messages", tags=["hospital"], response_model=ActionResponse)
def post_message(m: MessageIn):
    msg = get_engine().send_message(m.sender, m.text)
    return ok(f"Message {msg['msg_id']} {msg['status'].lower()}", msg)


# ============================================================== simulation control
@router.get("/simulation/status", tags=["simulation"])
def simulation_status():
    """Full live snapshot (same payload as the WebSocket broadcast)."""
    return get_engine().snapshot()


@router.post("/simulation/start", tags=["simulation"], response_model=ActionResponse)
def sim_start():
    return ok(f"Simulation {get_engine().start()}")


@router.post("/simulation/pause", tags=["simulation"], response_model=ActionResponse)
def sim_pause():
    return ok(f"Simulation {get_engine().pause()}")


@router.post("/simulation/resume", tags=["simulation"], response_model=ActionResponse)
def sim_resume():
    return ok(f"Simulation {get_engine().resume()}")


@router.post("/simulation/reset", tags=["simulation"], response_model=ActionResponse)
def sim_reset():
    e = get_engine()
    e.reset()
    return ok(f"Simulation reset — new run {e.run_id}")


@router.get("/simulation/config", tags=["simulation"])
def get_config():
    return get_engine().config.model_dump()


@router.put("/simulation/config", tags=["simulation"], response_model=ActionResponse)
def put_config(upd: ConfigUpdate):  # type: ignore[valid-type]
    updates = upd.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No configuration fields supplied")
    cfg = get_engine().update_config(updates)
    return ok("Configuration updated: " + ", ".join(sorted(updates)), cfg.model_dump())


# ============================================================== analytics
@router.get("/analytics", tags=["analytics"])
def analytics():
    e = get_engine()
    with e.lock:
        live = live_network_metrics(e)
        live_handovers = e.network.handovers[-200:]
        outages = list(e.outage_records)
        run_id = e.run_id
    return {"run_id": run_id, "live_metrics": live, "handovers": live_handovers, "outages": outages,
            "configurations": CONFIGURATIONS, "experiments": persistence.list_experiments(30)}


@router.post("/analytics/experiment", tags=["analytics"])
def run_experiment(req: ExperimentRequest):
    """Run configurations A (5G-only), B (4G-only) and C (5G+4G fallback+buffering) on the same
    route, seed and parameters (headless, faster than real time) and store the results."""
    e = get_engine()
    overrides = req.model_dump(exclude={"name", "outage_start_frac", "outage_duration_s"}, exclude_none=True)
    base = e.config.merged(overrides)
    outage = {"start_frac": req.outage_start_frac, "duration_s": req.outage_duration_s}
    results = run_comparison(base, runtime.route_provider, outage)
    params = {**overrides, **outage, "route_preset": base.route_preset, "seed": base.seed,
              "speed_kmh": base.ambulance_speed_kmh, "packet_interval_s": base.packet_interval_s}
    exp_id = persistence.save_experiment(results, params, req.name)
    return {"experiment_id": exp_id, "params": params, "results": results}


@router.get("/analytics/experiments", tags=["analytics"])
def experiments(limit: int = Query(60, ge=1, le=500)):
    return persistence.list_experiments(limit)


# ============================================================== persisted history
@router.get("/history/runs", tags=["history"])
def history_runs(limit: int = Query(30, ge=1, le=200)):
    return persistence.list_runs(limit)


@router.get("/history/{table}", tags=["history"])
def history_table(table: str, run_id: Optional[str] = None, limit: int = Query(200, ge=1, le=10000)):
    if table not in HISTORY_TABLES:
        raise HTTPException(404, f"Unknown table. Options: {sorted(HISTORY_TABLES)}")
    return persistence.query_table(HISTORY_TABLES[table], run_id, limit)


# ============================================================== websocket
@ws_router.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    """Live stream. Messages: {"type": "snapshot", "data": {...}} once per engine tick, containing
    patient readings, GPS, network status, handover events, alerts and packet delivery info."""
    await runtime.manager.connect(ws)
    try:
        snap = await asyncio.to_thread(get_engine().snapshot)
        await ws.send_text(dumps({"type": "snapshot", "data": snap}))
        while True:
            msg = await ws.receive_text()   # keep-alive / ping from clients
            if msg == "ping":
                await ws.send_text(dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("websocket closed", exc_info=True)
    finally:
        runtime.manager.disconnect(ws)
