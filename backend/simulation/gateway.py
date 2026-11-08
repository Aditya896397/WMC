"""Ambulance gateway: BLE ingest -> packetise -> validate -> forward/buffer."""
from __future__ import annotations

from collections import deque
from typing import Callable, Deque, Dict, List, Optional

from .ble_simulator import BLESimulator
from .config import SimulationConfig
from .network_simulator import NetworkSimulator

VALID_RANGES = {
    "heart_rate": (20.0, 250.0),
    "spo2": (50.0, 100.0),
    "temperature": (30.0, 45.0),
    "latitude": (-90.0, 90.0),
    "longitude": (-180.0, 180.0),
}

SENSOR_FOR_FIELD = {"heart_rate": "SEN-PO2", "spo2": "SEN-PO2", "temperature": "SEN-TMP"}


class AmbulanceGateway:
    def __init__(self, cfg: SimulationConfig, ble: BLESimulator, network: NetworkSimulator,
                 patient_id: str, ambulance_id: str, timestamp_fn: Callable[[float], str]):
        self.cfg = cfg
        self.ble = ble
        self.network = network
        self.patient_id = patient_id
        self.ambulance_id = ambulance_id
        self.ts = timestamp_fn
        self.seq = 0
        self.queue: Deque[dict] = deque()
        self.last_values: Dict[str, float] = {}
        self.records: List[dict] = []          # finalised packet records (for analytics)
        self.outbox: List[dict] = []           # finalised packet records not yet persisted
        self.recent: Deque[dict] = deque(maxlen=60)
        self.outage_buffered = 0
        self.counters = {
            "generated": 0, "delivered": 0, "lost": 0, "rejected": 0, "buffered_total": 0,
            "recovered": 0, "dropped_buffer_full": 0, "ble_incomplete": 0,
        }

    def update_config(self, cfg: SimulationConfig) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------
    def build_packet(self, vitals: Dict[str, float], lat: float, lon: float, t: float,
                     source: str = "SIMULATED", ble: bool = True) -> Optional[dict]:
        """Receive sensor data over BLE, timestamp, assign ID and validate."""
        self.seq += 1
        pid = f"PKT{self.seq:06d}"
        stale: List[str] = []
        ble_latency = 0.0
        ble_retries = 0
        values = dict(vitals)
        if ble:
            results = {dev: self.ble.transmit(dev, t) for dev in ("SEN-PO2", "SEN-TMP", "SEN-ECG")}
            ble_latency = max((r.latency_ms for r in results.values() if r.success), default=0.0)
            ble_retries = sum(r.retries for r in results.values())
            for fld, dev in SENSOR_FOR_FIELD.items():
                if not results[dev].success:
                    if fld in self.last_values:
                        values[fld] = self.last_values[fld]
                        stale.append(fld)
                    else:
                        values[fld] = None
        packet = {
            "packet_id": pid,
            "patient_id": self.patient_id,
            "ambulance_id": self.ambulance_id,
            "heart_rate": values.get("heart_rate"),
            "spo2": values.get("spo2"),
            "temperature": values.get("temperature"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "network_type": self.network.network_type(),
            "base_station": self.network.serving or "NONE",
            "timestamp": self.ts(t),
            # simulation metadata
            "sim_time_s": round(t, 3),
            "source": source,
            "stale_fields": stale,
            "ble_latency_ms": round(ble_latency, 2),
            "ble_retries": ble_retries,
        }
        self.counters["generated"] += 1
        if stale:
            self.counters["ble_incomplete"] += 1
        err = self.validate(packet)
        if err:
            self.counters["rejected"] += 1
            self._finalise(packet, "REJECTED", None, None, reason=err)
            return None
        for fld in SENSOR_FOR_FIELD:
            if fld not in stale:
                self.last_values[fld] = packet[fld]
        return packet

    @staticmethod
    def validate(p: dict) -> Optional[str]:
        if not p.get("patient_id") or not p.get("ambulance_id"):
            return "MISSING_IDS"
        for fld, (lo, hi) in VALID_RANGES.items():
            v = p.get(fld)
            if v is None:
                return f"MISSING_{fld.upper()}"
            if not (lo <= float(v) <= hi):
                return f"OUT_OF_RANGE_{fld.upper()}"
        return None

    # ------------------------------------------------------------------
    def forward(self, packet: dict, t: float) -> str:
        net = self.network
        if net.link_up(t):
            if self.queue:
                self.flush(t)
            return self._send(packet, send_t=t, buffered=False)
        reason = "NO_NETWORK" if net.serving is None else "HANDOVER_INTERRUPTION"
        if self.cfg.buffering_enabled:
            if len(self.queue) >= self.cfg.buffer_capacity:
                self.counters["dropped_buffer_full"] += 1
                self.counters["lost"] += 1
                self._finalise(packet, "DROPPED_BUFFER_FULL", None, None, reason="BUFFER_FULL")
                return "DROPPED_BUFFER_FULL"
            packet["buffer_reason"] = reason
            self.queue.append(packet)
            self.counters["buffered_total"] += 1
            if net.serving is None:
                self.outage_buffered += 1
            return "BUFFERED"
        self.counters["lost"] += 1
        self._finalise(packet, "LOST", None, None, reason=reason)
        return "LOST"

    def flush(self, t: float) -> dict:
        """Transmit buffered packets once the link is usable again."""
        net = self.network
        if not self.queue or not net.link_up(t):
            return {"flushed": 0}
        start = net.link_up_time
        thr = net.throughput_bps(net.serving)
        ser_s = self.cfg.packet_size_bytes * 8 / thr
        n = 0
        cursor = start
        while self.queue:
            pkt = self.queue.popleft()
            send_t = max(cursor, pkt["sim_time_s"])
            self._send(pkt, send_t=send_t, buffered=True)
            cursor = send_t + ser_s
            n += 1
        return {"flushed": n, "start": start, "end": cursor}

    def _send(self, packet: dict, send_t: float, buffered: bool) -> str:
        net = self.network
        res = net.transmit(self.cfg.packet_size_bytes)
        wait_ms = (send_t - packet["sim_time_s"]) * 1000.0
        e2e = packet["ble_latency_ms"] + 1.0 + wait_ms + res.latency_ms  # +1 ms gateway processing
        packet["tx_network_type"] = net.network_type()
        packet["tx_base_station"] = net.serving
        packet["sinr_db"] = round(res.sinr_db, 2)
        packet["throughput_mbps"] = round(res.throughput_mbps, 2)
        packet["harq_tx"] = res.harq_tx
        if res.delivered:
            self.counters["delivered"] += 1
            if buffered:
                self.counters["recovered"] += 1
            self._finalise(packet, "DELIVERED", e2e, packet["sim_time_s"] + e2e / 1000.0,
                           buffered=buffered)
            return "DELIVERED"
        self.counters["lost"] += 1
        self._finalise(packet, "LOST", None, None, reason=res.reason, buffered=buffered)
        return "LOST"

    def _finalise(self, packet: dict, status: str, latency_ms, deliver_t, reason: str = "",
                  buffered: bool = False) -> None:
        rec = {
            **{k: v for k, v in packet.items() if k != "stale_fields"},
            "stale_fields": ",".join(packet.get("stale_fields", [])),
            "status": status,
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "deliver_time_s": round(deliver_t, 3) if deliver_t is not None else None,
            "buffered": buffered,
            "loss_reason": reason,
        }
        self.records.append(rec)
        if len(self.records) > 100_000:
            del self.records[:-100_000]
        self.outbox.append(rec)
        self.recent.append(rec)

    def drain_outbox(self) -> List[dict]:
        out, self.outbox = self.outbox, []
        return out
