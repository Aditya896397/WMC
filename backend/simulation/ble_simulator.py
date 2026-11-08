"""Bluetooth Low Energy link simulator (sensor -> ambulance gateway).

No real Bluetooth hardware is used.  Each virtual sensor has an
in-vehicle distance to the gateway; RSSI follows a log-distance model,
each transmission attempt can be lost (configurable probability, worse at
weak RSSI) and the link layer retries up to `ble_max_retries` times on
subsequent connection events.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from .config import SimulationConfig


@dataclass
class BLESensor:
    device_id: str
    name: str
    measures: List[str]
    distance_m: float
    mac: str
    connected: bool = True
    battery_pct: float = 100.0
    packets_sent: int = 0
    packets_lost: int = 0
    retries: int = 0
    last_rssi_dbm: float = -60.0
    last_latency_ms: float = 0.0
    latency_sum_ms: float = 0.0
    delivered: int = 0


@dataclass
class BLEResult:
    device_id: str
    success: bool
    latency_ms: float
    retries: int
    rssi_dbm: float
    reason: str = ""


class BLESimulator:
    TX_REF_RSSI_1M = -59.0   # RSSI at 1 m (dBm)
    PATH_LOSS_N = 2.2        # in-vehicle path-loss exponent

    def __init__(self, cfg: SimulationConfig, rng: np.random.Generator):
        self.cfg = cfg
        self.rng = rng
        self.sensors: Dict[str, BLESensor] = {
            s.device_id: s
            for s in [
                BLESensor("SEN-PO2", "Pulse Oximeter (HR + SpO2)", ["heart_rate", "spo2"], 1.2, "C4:7F:51:0A:21:01"),
                BLESensor("SEN-TMP", "Temperature Patch", ["temperature"], 0.9, "C4:7F:51:0A:21:02"),
                BLESensor("SEN-ECG", "ECG Chest Patch", ["ecg"], 1.6, "C4:7F:51:0A:21:03"),
            ]
        }
        self.latency_history: List[dict] = []

    def update_config(self, cfg: SimulationConfig) -> None:
        self.cfg = cfg

    def set_connection(self, device_id: str, connected: bool) -> None:
        if device_id not in self.sensors:
            raise ValueError(f"Unknown BLE device '{device_id}'")
        self.sensors[device_id].connected = connected

    def transmit(self, device_id: str, t: float) -> BLEResult:
        s = self.sensors[device_id]
        if not s.connected:
            s.packets_lost += 1
            return BLEResult(device_id, False, 0.0, 0, s.last_rssi_dbm, "DISCONNECTED")

        cfg = self.cfg
        rssi = self.TX_REF_RSSI_1M - 10 * self.PATH_LOSS_N * math.log10(max(s.distance_m, 0.1))
        rssi += float(self.rng.normal(0, 2.0))
        s.last_rssi_dbm = rssi
        # Attempt loss probability grows when RSSI is weak.
        p_loss = min(0.95, cfg.ble_packet_loss + max(0.0, (-85.0 - rssi) / 40.0))

        attempts = 0
        success = False
        while attempts <= cfg.ble_max_retries:
            attempts += 1
            if self.rng.random() >= p_loss:
                success = True
                break
        retries = attempts - 1
        ci = cfg.ble_connection_interval_ms
        jitter = float(self.rng.gamma(2.0, cfg.ble_jitter_ms / 2.0)) if cfg.ble_jitter_ms > 0 else 0.0
        latency = float(self.rng.uniform(0, ci)) + cfg.ble_base_latency_ms + jitter + retries * ci

        s.packets_sent += 1
        s.retries += retries
        s.battery_pct = max(0.0, s.battery_pct - 0.002)
        if success:
            s.delivered += 1
            s.last_latency_ms = latency
            s.latency_sum_ms += latency
            self.latency_history.append({"t": round(t, 2), "device_id": device_id, "latency_ms": round(latency, 2)})
            if len(self.latency_history) > 300:
                del self.latency_history[:-300]
            return BLEResult(device_id, True, latency, retries, rssi)
        s.packets_lost += 1
        return BLEResult(device_id, False, latency, retries, rssi, "BLE_LOSS_AFTER_RETRIES")

    def stats(self) -> dict:
        sent = sum(s.packets_sent for s in self.sensors.values())
        lost = sum(s.packets_lost for s in self.sensors.values())
        delivered = sum(s.delivered for s in self.sensors.values())
        lat_sum = sum(s.latency_sum_ms for s in self.sensors.values())
        n_conn = sum(1 for s in self.sensors.values() if s.connected)
        status = "CONNECTED" if n_conn == len(self.sensors) else ("DEGRADED" if n_conn else "DISCONNECTED")
        return {
            "status": status,
            "connected_devices": n_conn,
            "total_devices": len(self.sensors),
            "packets_transmitted": sent,
            "packets_delivered": delivered,
            "packets_lost": lost,
            "packet_loss_pct": round(100.0 * lost / sent, 2) if sent else 0.0,
            "avg_latency_ms": round(lat_sum / delivered, 2) if delivered else 0.0,
            "config": {
                "base_latency_ms": self.cfg.ble_base_latency_ms,
                "jitter_ms": self.cfg.ble_jitter_ms,
                "packet_loss": self.cfg.ble_packet_loss,
                "max_retries": self.cfg.ble_max_retries,
                "connection_interval_ms": self.cfg.ble_connection_interval_ms,
            },
            "devices": [
                {
                    "device_id": s.device_id,
                    "name": s.name,
                    "mac": s.mac,
                    "measures": s.measures,
                    "connected": s.connected,
                    "distance_m": s.distance_m,
                    "rssi_dbm": round(s.last_rssi_dbm, 1),
                    "battery_pct": round(s.battery_pct, 2),
                    "packets_sent": s.packets_sent,
                    "packets_lost": s.packets_lost,
                    "retries": s.retries,
                    "loss_pct": round(100.0 * s.packets_lost / s.packets_sent, 2) if s.packets_sent else 0.0,
                    "last_latency_ms": round(s.last_latency_ms, 2),
                    "avg_latency_ms": round(s.latency_sum_ms / s.delivered, 2) if s.delivered else 0.0,
                }
                for s in self.sensors.values()
            ],
            "latency_history": self.latency_history[-150:],
        }
