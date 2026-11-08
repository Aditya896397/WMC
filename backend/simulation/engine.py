"""Single shared simulation engine that synchronises all sub-simulators.

Patient, BLE, ambulance/GPS, cellular network and gateway are advanced
together in small sub-steps of simulated time.  The FastAPI backend owns
exactly one live instance; performance experiments create private
headless instances.
"""
from __future__ import annotations

import math
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional

import numpy as np

from .ambulance_simulator import ROUTE_PRESETS, AmbulanceSimulator, RouteProvider
from .ble_simulator import BLESimulator
from .config import SimulationConfig
from .gateway import AmbulanceGateway
from .network_simulator import NetworkSimulator
from .patient_simulator import SCENARIOS, PatientSimulator

SUBSTEP_S = 0.5
PATIENT_ID = "P001"
AMBULANCE_ID = "AMB001"


class SimulationEngine:
    def __init__(self, config: Optional[SimulationConfig] = None,
                 route_provider: Optional[RouteProvider] = None, headless: bool = False):
        self.lock = threading.RLock()
        self.config = config or SimulationConfig()
        self.route_provider = route_provider or RouteProvider()
        self.headless = headless
        self.outage_plan: Optional[dict] = None   # used by experiments
        self._build()

    # ================================================================== setup
    def _build(self) -> None:
        cfg = self.config
        self.run_id = datetime.now().strftime("RUN%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.rng = np.random.default_rng(cfg.seed)
        self.route = self.route_provider.get(cfg.route_preset)
        self.route_version = f"{cfg.route_preset}:{len(self.route['points'])}"
        self.start_wall = datetime.now(timezone.utc)
        self.status = "IDLE"
        self.sim_elapsed = 0.0
        self.next_packet_t = 0.0
        self._last_sample_t = -1.0

        self.patient = PatientSimulator(self.rng, cfg.scenario, PATIENT_ID)
        self.ble = BLESimulator(cfg, self.rng)
        self.ambulance = AmbulanceSimulator(self.route, self.rng, cfg.ambulance_speed_kmh, AMBULANCE_ID)
        self.network = NetworkSimulator(cfg, self.rng)
        self.gateway = AmbulanceGateway(cfg, self.ble, self.network, PATIENT_ID, AMBULANCE_ID, self.ts)

        self.vitals_history: Deque[dict] = deque(maxlen=600)
        self.location_history: Deque[dict] = deque(maxlen=600)
        self.signal_history: Deque[dict] = deque(maxlen=20000 if self.headless else 300)
        self.network_events: Deque[dict] = deque(maxlen=200)
        self.alerts: Deque[dict] = deque(maxlen=200)
        self.messages: Deque[dict] = deque(maxlen=200)
        self.pending_messages: List[dict] = []
        self._alert_last: Dict[str, float] = {}
        self._alert_seq = 0
        self._msg_seq = 0
        self.outage_records: List[dict] = []
        self._pending_outage: Optional[dict] = None
        self.outbox: Dict[str, List[dict]] = {k: [] for k in
                                              ("vitals", "locations", "network_events", "handovers",
                                               "alerts", "messages")}
        # initial cell attach at the start position
        lat, lon = self.ambulance.position()
        self._handle_network_events(self.network.update(lat, lon, 0.0, 0.0, 0.0))
        self._sample(0.0, force=True)

    def ts(self, t: float) -> str:
        return (self.start_wall + timedelta(seconds=t)).isoformat(timespec="milliseconds")

    # ================================================================== controls
    def start(self) -> str:
        with self.lock:
            if self.status == "ARRIVED":
                self.reset()
            self.status = "RUNNING"
            self.ambulance.moving = True
            self._log_event("SIMULATION_STARTED", "Simulation started")
            return self.status

    def pause(self) -> str:
        with self.lock:
            if self.status == "RUNNING":
                self.status = "PAUSED"
                self.ambulance.moving = False
                self._log_event("SIMULATION_PAUSED", "Simulation paused")
            return self.status

    def resume(self) -> str:
        with self.lock:
            if self.status in ("PAUSED", "IDLE"):
                self.status = "RUNNING"
                self.ambulance.moving = True
                self._log_event("SIMULATION_RESUMED", "Simulation resumed")
            return self.status

    def reset(self) -> str:
        with self.lock:
            self._build()
            self._log_event("SIMULATION_RESET", f"Simulation reset (new run {self.run_id})")
            return self.status

    def update_config(self, updates: dict) -> SimulationConfig:
        with self.lock:
            new = self.config.merged(updates)
            route_changed = new.route_preset != self.config.route_preset
            scenario_changed = new.scenario != self.config.scenario
            if route_changed and new.route_preset not in ROUTE_PRESETS:
                raise ValueError(f"Unknown route preset '{new.route_preset}'")
            self.config = new
            if route_changed:
                self._build()
                return self.config
            for sim in (self.ble, self.network, self.gateway):
                sim.update_config(new)
            self.ambulance.set_speed(new.ambulance_speed_kmh)
            if scenario_changed:
                self.patient.set_scenario(new.scenario)
                self._log_event("SCENARIO_CHANGED", f"Patient scenario → {new.scenario}: {SCENARIOS[new.scenario]}")
            changed = sorted(k for k, v in updates.items() if v is not None)
            if changed:
                self._log_event("CONFIG_UPDATED", "Configuration updated: " + ", ".join(changed))
            return self.config

    def network_control(self, action: str, degradation_db: Optional[float] = None) -> SimulationConfig:
        actions = {
            "degrade_5g": {"five_g_degradation_db": degradation_db if degradation_db is not None else 25.0},
            "restore_5g": {"five_g_degradation_db": 0.0},
            "force_4g": {"force_4g": True},
            "release_4g": {"force_4g": False},
            "fail": {"network_failure": True},
            "restore": {"network_failure": False},
            "restore_all": {"network_failure": False, "force_4g": False, "five_g_degradation_db": 0.0},
        }
        if action not in actions:
            raise ValueError(f"Unknown network action '{action}'. Options: {list(actions)}")
        with self.lock:
            cfg = self.update_config(actions[action])
            self._log_event("NETWORK_CONTROL", f"Network control applied: {action}")
            self._refresh_network()
            return cfg

    def update_base_station(self, bs_id: str, updates: dict) -> dict:
        with self.lock:
            bss = [b.model_dump() for b in self.config.base_stations]
            for b in bss:
                if b["id"] == bs_id:
                    b.update({k: v for k, v in updates.items() if v is not None})
                    break
            else:
                raise ValueError(f"Unknown base station '{bs_id}'")
            self.update_config({"base_stations": bss})
            self._refresh_network()
            return next(b for b in self.network.base_station_table() if b["id"] == bs_id)

    def trigger_handover(self, target: Optional[str] = None) -> List[dict]:
        with self.lock:
            evts = self.network.manual_handover(self.sim_elapsed, target)
            self._handle_network_events(evts)
            return evts

    def set_sensor_connection(self, device_id: str, connected: bool) -> None:
        with self.lock:
            self.ble.set_connection(device_id, connected)
            self._log_event("BLE_CONTROL", f"{device_id} {'connected' if connected else 'disconnected'}")

    def inject_vitals(self, vitals: dict) -> dict:
        """External reading (POST /api/patient/vitals) — processed by the gateway pipeline."""
        with self.lock:
            lat, lon = self.ambulance.position()
            t = self.sim_elapsed
            pkt = self.gateway.build_packet(vitals, lat, lon, t, source="EXTERNAL_API", ble=False)
            if pkt is None:
                raise ValueError("Packet rejected by gateway validation")
            status = self.gateway.forward(pkt, t)
            self._record_vitals(pkt, t)
            self._check_alerts(pkt, t)
            return {"packet_id": pkt["packet_id"], "status": status, "timestamp": pkt["timestamp"]}

    def set_location(self, lat: float, lon: float) -> dict:
        with self.lock:
            off = self.ambulance.snap_to(lat, lon)
            self._refresh_network()
            self._sample(self.sim_elapsed, force=True)
            self._log_event("LOCATION_SET", f"Ambulance relocated (snapped {off:.0f} m to route)")
            return {"snapped_offset_m": round(off, 1), **self.ambulance_state()}

    def send_message(self, sender: str, text: str) -> dict:
        with self.lock:
            self._msg_seq += 1
            msg = {"msg_id": f"MSG{self._msg_seq:04d}", "sender": sender, "text": text,
                   "sent_time_s": self.sim_elapsed, "sent_ts": self.ts(self.sim_elapsed),
                   "status": "QUEUED", "delivered_ts": None, "latency_ms": None,
                   "network_type": self.network.network_type()}
            self.messages.append(msg)
            self.pending_messages.append(msg)
            self._deliver_messages(self.sim_elapsed)
            return msg

    def _refresh_network(self) -> None:
        lat, lon = self.ambulance.position()
        evts = self.network.update(lat, lon, self.sim_elapsed, 0.0, self.ambulance.s)
        self._handle_network_events(evts)
        self._flush(self.sim_elapsed)

    # ================================================================== stepping
    def tick(self, real_dt: float) -> None:
        with self.lock:
            if self.status == "RUNNING":
                self.step(real_dt * self.config.time_scale)

    def step(self, dt_total: float) -> None:
        with self.lock:
            n = max(1, math.ceil(dt_total / SUBSTEP_S))
            dt = dt_total / n
            for _ in range(n):
                if self.status != "RUNNING":
                    break
                self._substep(dt)

    def _substep(self, dt: float) -> None:
        t = self.sim_elapsed + dt
        self.sim_elapsed = t
        self.ambulance.advance(dt)
        self.patient.step(dt)
        self._apply_outage_plan(t)
        lat, lon = self.ambulance.position()
        self._handle_network_events(self.network.update(lat, lon, t, dt, self.ambulance.s))
        self._flush(t)
        while self.next_packet_t <= t:
            tp = self.next_packet_t
            self.next_packet_t += self.config.packet_interval_s
            pkt = self.gateway.build_packet(self.patient.reading(), lat, lon, tp)
            if pkt is not None:
                self.gateway.forward(pkt, tp)
                self._record_vitals(pkt, tp)
                self._check_alerts(pkt, tp)
        self._deliver_messages(t)
        self._sample(t)
        if self.ambulance.arrived:
            self.status = "ARRIVED"
            self._log_event("AMBULANCE_ARRIVED", "Ambulance arrived at hospital")
            self._raise_alert("ARRIVAL", "INFO", "SYSTEM", "Ambulance arrived at the hospital", None, t)

    def _apply_outage_plan(self, t: float) -> None:
        plan = self.outage_plan
        if not plan:
            return
        progress = self.ambulance.s / self.ambulance.total_m if self.ambulance.total_m else 0
        if not plan.get("started") and progress >= plan["start_frac"]:
            plan["started"], plan["t0"] = True, t
            self.config = self.config.merged({"network_failure": True})
            self.network.update_config(self.config)
        elif plan.get("started") and not plan.get("ended") and t - plan["t0"] >= plan["duration_s"]:
            plan["ended"] = True
            self.config = self.config.merged({"network_failure": False})
            self.network.update_config(self.config)

    # ================================================================== bookkeeping
    def _handle_network_events(self, evts: List[dict]) -> None:
        for e in evts:
            e = {**e, "timestamp": self.ts(e["time"]), "network_type": self.network.network_type()}
            self.network_events.append(e)
            self.outbox["network_events"].append(e)
            et = e["event_type"]
            if et == "HANDOVER_INITIATED":
                self.outbox["handovers"].append({**e["details"], "timestamp": e["timestamp"]})
                if e["details"].get("to_type") == "4G" and e["details"].get("from_type") == "5G":
                    self._raise_alert("FALLBACK_4G", "WARNING", "NETWORK",
                                      f"5G unavailable — fallback to 4G LTE ({e['to_bs']})", None, e["time"])
            elif et == "OUTAGE_START":
                self.gateway.outage_buffered = 0
                self._raise_alert("NETWORK_OFFLINE", "CRITICAL", "NETWORK",
                                  "Network OFFLINE — patient data is being buffered at the gateway"
                                  if self.config.buffering_enabled else
                                  "Network OFFLINE — buffering disabled, packets are being lost", None, e["time"])
            elif et == "RECONNECTED":
                rec = dict(e["details"])
                rec["buffered_packets"] = self.gateway.outage_buffered
                rec["timestamp"] = e["timestamp"]
                self._pending_outage = rec   # finalised once the backlog is flushed

    def _flush(self, t: float) -> None:
        """Flush the gateway buffer and finalise any pending outage-recovery record."""
        fl = self.gateway.flush(t)
        rec = self._pending_outage
        if rec is None or not self.network.link_up(t):
            return
        self._pending_outage = None
        rec["flushed_packets"] = fl.get("flushed", 0)
        end = fl.get("end", rec["end"])
        rec["recovery_time_s"] = round(end - rec["start"], 3) if rec.get("start") is not None else None
        rec["drain_time_s"] = round(end - rec["end"], 4)
        self.outage_records.append(rec)
        msg = (f"Network restored via {rec['reconnect_bs']} after {rec['duration_s']:.1f}s — "
               f"{rec['flushed_packets']} buffered packets delivered")
        self._raise_alert("NETWORK_RESTORED", "INFO", "NETWORK", msg, None, t, cooldown=0)

    def _log_event(self, etype: str, message: str) -> None:
        e = {"time": self.sim_elapsed, "timestamp": self.ts(self.sim_elapsed), "event_type": etype,
             "from_bs": None, "to_bs": None, "message": message, "details": {},
             "network_type": self.network.network_type() if hasattr(self, "network") else "OFFLINE"}
        self.network_events.append(e)
        self.outbox["network_events"].append(e)

    def _record_vitals(self, pkt: dict, t: float) -> None:
        v = {"timestamp": pkt["timestamp"], "sim_time_s": round(t, 2), "heart_rate": pkt["heart_rate"],
             "spo2": pkt["spo2"], "temperature": pkt["temperature"], "packet_id": pkt["packet_id"],
             "source": pkt["source"], "patient_id": pkt["patient_id"]}
        self.vitals_history.append(v)
        self.outbox["vitals"].append(v)

    def _sample(self, t: float, force: bool = False) -> None:
        """Location + signal sampling once per simulated second."""
        if not force and t - self._last_sample_t < 1.0:
            return
        self._last_sample_t = t
        a = self.ambulance_state()
        loc = {"timestamp": self.ts(t), "sim_time_s": round(t, 2), "lat": a["lat"], "lon": a["lon"],
               "speed_kmh": a["speed_kmh"], "distance_to_hospital_km": a["distance_to_hospital_km"],
               "ambulance_id": AMBULANCE_ID}
        self.location_history.append(loc)
        self.outbox["locations"].append(loc)
        sig = {"t": round(t, 2), "timestamp": self.ts(t), "serving": self.network.serving or "OFFLINE",
               "network_type": self.network.network_type()}
        for b in self.network.bs.values():
            sig[b.cfg.id] = round(b.rsrp_dbm, 1)
        self.signal_history.append(sig)

    def _check_alerts(self, pkt: dict, t: float) -> None:
        th = self.config.thresholds
        hr, spo2, temp = pkt["heart_rate"], pkt["spo2"], pkt["temperature"]
        if hr >= th.hr_critical:
            self._raise_alert("HR_CRITICAL", "CRITICAL", "PATIENT", f"Heart rate critically high: {hr:.0f} BPM", hr, t)
        elif hr >= th.hr_high:
            self._raise_alert("HR_HIGH", "WARNING", "PATIENT", f"Heart rate high: {hr:.0f} BPM", hr, t)
        elif hr <= th.hr_low:
            self._raise_alert("HR_LOW", "WARNING", "PATIENT", f"Heart rate low: {hr:.0f} BPM", hr, t)
        if spo2 <= th.spo2_critical:
            self._raise_alert("SPO2_CRITICAL", "CRITICAL", "PATIENT", f"SpO2 critically low: {spo2:.1f}%", spo2, t)
        elif spo2 <= th.spo2_low:
            self._raise_alert("SPO2_LOW", "WARNING", "PATIENT", f"SpO2 low: {spo2:.1f}%", spo2, t)
        if temp >= th.temp_high:
            self._raise_alert("TEMP_HIGH", "WARNING", "PATIENT", f"Temperature high: {temp:.1f} °C", temp, t)
        elif temp <= th.temp_low:
            self._raise_alert("TEMP_LOW", "WARNING", "PATIENT", f"Temperature low: {temp:.1f} °C", temp, t)
        if pkt.get("stale_fields"):
            self._raise_alert("BLE_STALE", "WARNING", "BLE",
                              f"BLE readings missing for {', '.join(pkt['stale_fields'])} — last value reused", None, t)

    def _raise_alert(self, key: str, severity: str, category: str, message: str, value, t: float,
                     cooldown: float = 30.0) -> None:
        last = self._alert_last.get(key)
        if last is not None and t - last < cooldown:
            return
        self._alert_last[key] = t
        self._alert_seq += 1
        a = {"alert_id": f"ALT{self._alert_seq:04d}", "timestamp": self.ts(t), "sim_time_s": round(t, 2),
             "severity": severity, "category": category, "alert_type": key, "message": message,
             "value": value, "synthetic": True}
        self.alerts.append(a)
        self.outbox["alerts"].append(a)

    def _deliver_messages(self, t: float) -> None:
        if not self.pending_messages or not self.network.link_up(t):
            return
        for m in self.pending_messages:
            res = self.network.transmit(256)
            wait_ms = (t - m["sent_time_s"]) * 1000.0
            m["latency_ms"] = round(wait_ms + res.latency_ms, 1)
            m["delivered_ts"] = self.ts(t + res.latency_ms / 1000.0)
            m["status"] = "DELIVERED"
            m["network_type"] = self.network.network_type()
            self.outbox["messages"].append(dict(m))
        self.pending_messages = []

    def drain_outbox(self) -> Dict[str, List[dict]]:
        with self.lock:
            out = self.outbox
            self.outbox = {k: [] for k in out}
            out["packets"] = self.gateway.drain_outbox()
            return out

    # ================================================================== reporting
    def ambulance_state(self) -> dict:
        a = self.ambulance
        lat, lon = a.position()
        eta = a.eta_min()
        return {
            "ambulance_id": AMBULANCE_ID, "lat": round(lat, 6), "lon": round(lon, 6),
            "speed_kmh": round(a.current_speed_kmh, 1), "speed_setpoint_kmh": a.speed_setpoint_kmh,
            "heading_deg": round(a.heading(), 1),
            "distance_travelled_km": round(a.s / 1000, 3),
            "distance_to_hospital_km": round(a.remaining_m / 1000, 3),
            "route_length_km": round(a.total_m / 1000, 3),
            "progress_pct": round(100 * a.s / a.total_m, 2) if a.total_m else 100.0,
            "eta_min": round(eta, 2) if eta is not None else None,
            "arrived": a.arrived, "moving": a.moving,
        }

    def network_state(self) -> dict:
        from .performance import live_network_metrics
        net = self.network
        t = self.sim_elapsed
        serving = net.serving
        srv = net.bs.get(serving) if serving else None
        m = live_network_metrics(self)
        return {
            "network_type": net.network_type(),
            "serving_bs": serving,
            "rsrp_dbm": round(srv.rsrp_dbm, 1) if srv else None,
            "sinr_db": round(net.sinr_db(serving), 1) if srv else None,
            "throughput_mbps": round(net.throughput_bps(serving) / 1e6, 1) if srv else 0.0,
            "in_handover": bool(serving) and t < net.interrupt_until,
            "offline": serving is None,
            "available": serving is not None,
            "handover_count": net.handover_count,
            "last_interruption_ms": net.handovers[-1]["interruption_ms"] if net.handovers else None,
            "queued_packets": len(self.gateway.queue),
            "ttt_progress": {k: round(v, 2) for k, v in net.ttt_timer.items()},
            "controls": {
                "mode": self.config.mode, "five_g_degradation_db": self.config.five_g_degradation_db,
                "force_4g": self.config.force_4g, "network_failure": self.config.network_failure,
                "buffering_enabled": self.config.buffering_enabled,
            },
            **m,
            "base_stations": net.base_station_table(),
        }

    def patient_state(self) -> dict:
        r = self.vitals_history[-1] if self.vitals_history else {**self.patient.reading(), "timestamp": self.ts(0)}
        th = self.config.thresholds
        hr, spo2, temp = r["heart_rate"], r["spo2"], r["temperature"]
        if hr >= th.hr_critical or spo2 <= th.spo2_critical:
            status = "CRITICAL"
        elif hr >= th.hr_high or hr <= th.hr_low or spo2 <= th.spo2_low or temp >= th.temp_high or temp <= th.temp_low:
            status = "WARNING"
        else:
            status = "STABLE"
        return {
            "patient_id": PATIENT_ID, "name": "Synthetic Patient 001",
            "scenario": self.patient.scenario, "scenario_label": SCENARIOS[self.patient.scenario],
            "vitals": {"heart_rate": hr, "spo2": spo2, "temperature": temp, "timestamp": r["timestamp"]},
            "health_status": status, "synthetic": True,
            "ecg": self.patient.ecg_window(self.sim_elapsed),
        }

    def snapshot(self, history: int = 180) -> dict:
        with self.lock:
            g = self.gateway
            return {
                "run_id": self.run_id,
                "status": self.status,
                "sim_time": self.ts(self.sim_elapsed),
                "sim_elapsed_s": round(self.sim_elapsed, 2),
                "route_version": self.route_version,
                "route_source": self.route["source"],
                "route_label": self.route["label"],
                "hospital": {"name": self.route["hospital_name"], **self.route["hospital"]},
                "patient": self.patient_state(),
                "vitals_history": list(self.vitals_history)[-history:],
                "ambulance": self.ambulance_state(),
                "location_history": list(self.location_history)[-history:],
                "network": self.network_state(),
                "signal_history": list(self.signal_history)[-history:],
                "ble": self.ble.stats(),
                "gateway": {**g.counters, "queue_length": len(g.queue),
                            "last_packet": g.recent[-1] if g.recent else None},
                "recent_packets": list(g.recent)[-30:],
                "handover_events": self.network.handovers[-30:],
                "network_events": list(self.network_events)[-40:],
                "alerts": list(self.alerts)[-40:],
                "messages": list(self.messages)[-40:],
                "outages": self.outage_records[-20:],
                "config": self.config.model_dump(),
            }

    def route_info(self) -> dict:
        with self.lock:
            return {"route_version": self.route_version, **self.route, "cumulative_m": self.ambulance.cum,
                    "presets": {k: v["label"] for k, v in ROUTE_PRESETS.items()}}
