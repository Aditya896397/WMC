"""Simplified 5G NR / 4G LTE cellular network simulator.

Model (educational, NOT a standards-compliant 3GPP channel model):

* Path loss  : log-distance  PL(d) = FSPL(1 m, f) + 10·n·log10(d / 1 m)
* Shadowing  : log-normal, spatially correlated per base station
               (Gudmundson AR(1), correlation distance `shadowing_corr_m`)
* Signal     : S = P_tx + G_ant − PL + X_σ  (− 5G degradation when injected)
               reported as an RSRP-like "signal strength" in dBm
* SINR       : S − noise_floor  (interference folded into the noise floor)
* Throughput : η · B · min(log2(1 + SINR), SE_max)   (Shannon, capped)
* Errors     : block error rate BLER = 1 / (1 + e^{1.1·(SINR − 1 dB)})
               with up to 4 HARQ transmissions per packet
* Cell choice: available = enabled ∧ d ≤ radius ∧ S ≥ S_min(type) ∧ allowed by policy
               score = S + 5G preference offset (HYBRID mode)
* Handover   : A3-like — neighbour score > serving score + hysteresis for
               time-to-trigger, and neighbour S ≥ S_min + target margin (A5-like); immediate (RLF / policy) handover when the
               serving cell becomes unavailable; OFFLINE when nothing is.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import BaseStationConfig, SimulationConfig
from .geo import haversine_m

C_LIGHT = 299_792_458.0
MAX_HARQ_TX = 4
INTERNET_BACKHAUL_MS = 8.0   # operator core → hospital server

# Per-technology latency/throughput assumptions (documented in README).
RAN_PARAMS = {
    "5G": {"air_ms": 4.0, "core_ms": 6.0, "harq_rtt_ms": 1.0, "se_max": 7.4, "eff": 0.6, "jitter_ms": 1.5},
    "4G": {"air_ms": 15.0, "core_ms": 18.0, "harq_rtt_ms": 8.0, "se_max": 5.5, "eff": 0.6, "jitter_ms": 4.0},
}

# Handover interruption time assumptions: (mean ms, std ms)
HO_INTERRUPTION_MS: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("5G", "5G"): (30.0, 8.0),    # intra-NR
    ("5G", "4G"): (90.0, 20.0),   # inter-RAT NR -> LTE
    ("4G", "5G"): (80.0, 20.0),   # inter-RAT LTE -> NR
    ("4G", "4G"): (45.0, 10.0),   # intra-LTE
}
RLF_PENALTY_MS = (200.0, 50.0)       # radio-link-failure re-establishment
REESTABLISH_MS = (120.0, 30.0)       # re-attach after an outage


def fspl_1m_db(freq_ghz: float) -> float:
    return 20 * math.log10(4 * math.pi * freq_ghz * 1e9 / C_LIGHT)


@dataclass
class BSState:
    cfg: BaseStationConfig
    shadow_db: float = 0.0
    distance_m: float = 0.0
    rsrp_dbm: float = -140.0
    in_coverage: bool = False
    available: bool = False


@dataclass
class LinkResult:
    delivered: bool
    latency_ms: float
    harq_tx: int
    reason: str
    sinr_db: float
    throughput_mbps: float


class NetworkSimulator:
    def __init__(self, cfg: SimulationConfig, rng: np.random.Generator):
        self.cfg = cfg
        self.rng = rng
        self.bs: Dict[str, BSState] = {}
        self.serving: Optional[str] = None
        self.sync_base_stations()
        self.interrupt_until: float = 0.0       # link unusable until this sim time
        self.link_up_time: float = 0.0          # when the current link became usable
        self.ttt_timer: Dict[str, float] = {}
        self.handover_count = 0
        self.handovers: List[dict] = []
        self.outage_start: Optional[float] = 0.0  # start OFFLINE until first attach
        self.first_attach = True
        self.outages: List[dict] = []
        self.connected_time = 0.0
        self.total_time = 0.0
        self.time_on: Dict[str, float] = {"5G": 0.0, "4G": 0.0, "OFFLINE": 0.0}
        self._last_travel_m = 0.0
        self._ho_seq = 0

    # ------------------------------------------------------------------ config
    def update_config(self, cfg: SimulationConfig) -> None:
        self.cfg = cfg
        self.sync_base_stations()

    def sync_base_stations(self) -> None:
        new: Dict[str, BSState] = {}
        for bcfg in self.cfg.base_stations:
            old = self.bs.get(bcfg.id)
            new[bcfg.id] = BSState(cfg=bcfg, shadow_db=old.shadow_db if old else 0.0)
        self.bs = new
        if self.serving and self.serving not in self.bs:
            self.serving = None

    def _allowed(self, net_type: str) -> bool:
        c = self.cfg
        if c.network_failure:
            return False
        if c.mode == "5G_ONLY":
            return net_type == "5G" and not c.force_4g
        if c.mode == "4G_ONLY":
            return net_type == "4G"
        if c.force_4g and net_type == "5G":
            return False
        return True

    def _score(self, b: BSState) -> float:
        bonus = self.cfg.prefer_5g_offset_db if (b.cfg.network_type == "5G" and self.cfg.mode == "HYBRID") else 0.0
        return b.rsrp_dbm + bonus

    def _min_rsrp(self, net_type: str) -> float:
        return self.cfg.min_rsrp_5g_dbm if net_type == "5G" else self.cfg.min_rsrp_4g_dbm

    # ------------------------------------------------------------------ radio
    def measure(self, lat: float, lon: float, travelled_m: float) -> None:
        c = self.cfg
        moved = abs(travelled_m - self._last_travel_m)
        self._last_travel_m = travelled_m
        rho = math.exp(-moved / c.shadowing_corr_m) if moved > 0 else 1.0
        for b in self.bs.values():
            bc = b.cfg
            d = max(haversine_m(lat, lon, bc.lat, bc.lon), 10.0)
            n = c.path_loss_exponent_5g if bc.network_type == "5G" else c.path_loss_exponent_4g
            pl = fspl_1m_db(bc.frequency_ghz) + 10 * n * math.log10(d)
            if rho < 1.0 or b.shadow_db == 0.0:
                innov = float(self.rng.normal(0.0, c.shadowing_sigma_db)) if c.shadowing_sigma_db > 0 else 0.0
                b.shadow_db = rho * b.shadow_db + math.sqrt(max(0.0, 1 - rho * rho)) * innov if b.shadow_db else innov
            s = bc.tx_power_dbm + c.antenna_gain_db - pl + b.shadow_db
            if bc.network_type == "5G":
                s -= c.five_g_degradation_db
            b.distance_m = d
            b.rsrp_dbm = s
            b.in_coverage = bc.enabled and d <= bc.radius_m
            b.available = (
                b.in_coverage and s >= self._min_rsrp(bc.network_type) and self._allowed(bc.network_type)
            )

    def sinr_db(self, bs_id: str) -> float:
        return self.bs[bs_id].rsrp_dbm - self.cfg.noise_floor_dbm

    def throughput_bps(self, bs_id: str) -> float:
        b = self.bs[bs_id]
        p = RAN_PARAMS[b.cfg.network_type]
        sinr_lin = 10 ** (self.sinr_db(bs_id) / 10)
        se = min(math.log2(1 + sinr_lin), p["se_max"])
        return max(p["eff"] * b.cfg.bandwidth_mhz * 1e6 * se, 1e5)

    # ------------------------------------------------------------------ mobility management
    def update(self, lat: float, lon: float, t: float, dt: float, travelled_m: float) -> List[dict]:
        """Measure all cells, run cell selection / handover. Returns new events."""
        events: List[dict] = []
        self.measure(lat, lon, travelled_m)
        candidates = [b for b in self.bs.values() if b.available]

        # Availability accounting for the interval (t - dt, t]
        self.total_time += dt
        if self.serving:
            up = max(0.0, t - max(t - dt, self.interrupt_until))
            self.connected_time += min(dt, up)
            self.time_on[self.bs[self.serving].cfg.network_type] += dt
        else:
            self.time_on["OFFLINE"] += dt

        if self.serving is None:
            if candidates:
                best = max(candidates, key=self._score)
                delay = 0.0 if self.first_attach else max(20.0, float(self.rng.normal(*REESTABLISH_MS)))
                self.serving = best.cfg.id
                self.interrupt_until = t + delay / 1000.0
                self.link_up_time = self.interrupt_until
                self.ttt_timer.clear()
                if self.first_attach:
                    events.append(self._event(t, "ATTACHED", None, best.cfg.id,
                                              f"Initial attach to {best.cfg.id} ({best.cfg.network_type})"))
                    self.outage_start = None
                    self.first_attach = False
                else:
                    outage = {
                        "start": self.outage_start, "end": self.link_up_time,
                        "duration_s": round(self.link_up_time - (self.outage_start or t), 3),
                        "reconnect_bs": best.cfg.id, "reestablish_ms": round(delay, 1),
                    }
                    self.outages.append(outage)
                    self.outage_start = None
                    events.append(self._event(t, "RECONNECTED", None, best.cfg.id,
                                              f"Connectivity restored via {best.cfg.id} ({best.cfg.network_type}) "
                                              f"after {outage['duration_s']:.1f}s outage", extra=outage))
            return events

        srv = self.bs[self.serving]
        if not srv.available:
            if candidates:
                best = max(candidates, key=self._score)
                policy = srv.in_coverage and srv.rsrp_dbm >= self._min_rsrp(srv.cfg.network_type)
                reason = "POLICY_FALLBACK" if policy else "RADIO_LINK_FAILURE"
                events += self._handover(best.cfg.id, t, reason)
            else:
                why = ("Network failure injected" if self.cfg.network_failure
                       else "No suitable cell in coverage")
                events.append(self._event(t, "OUTAGE_START", self.serving, None,
                                          f"OFFLINE: lost {self.serving} — {why}"))
                self.serving = None
                self.outage_start = t
                self.ttt_timer.clear()
            return events

        # A3-like event evaluation with hysteresis and time-to-trigger
        margin = self.cfg.ho_target_margin_db
        ho_cands = [b for b in candidates
                    if b.cfg.id == self.serving or b.rsrp_dbm >= self._min_rsrp(b.cfg.network_type) + margin]
        best = max(ho_cands, key=self._score)
        if best.cfg.id != self.serving and self._score(best) > self._score(srv) + self.cfg.hysteresis_db:
            self.ttt_timer = {best.cfg.id: self.ttt_timer.get(best.cfg.id, 0.0) + dt}
            if self.ttt_timer[best.cfg.id] >= self.cfg.time_to_trigger_s:
                events += self._handover(best.cfg.id, t, "A3_BETTER_NEIGHBOUR")
        else:
            self.ttt_timer.clear()
        return events

    def _handover(self, target: str, t: float, reason: str) -> List[dict]:
        src = self.serving
        sb, tb = self.bs[src], self.bs[target]
        pair = (sb.cfg.network_type, tb.cfg.network_type)
        mean, sd = HO_INTERRUPTION_MS[pair]
        interruption = max(5.0, float(self.rng.normal(mean, sd)))
        if reason == "RADIO_LINK_FAILURE":
            interruption += max(50.0, float(self.rng.normal(*RLF_PENALTY_MS)))
        self._ho_seq += 1
        ho = {
            "ho_id": f"HO{self._ho_seq:04d}",
            "time": t,
            "completed_time": t + interruption / 1000.0,
            "from_bs": src, "to_bs": target,
            "from_type": pair[0], "to_type": pair[1],
            "reason": reason,
            "interruption_ms": round(interruption, 2),
            "rsrp_from_dbm": round(sb.rsrp_dbm, 1),
            "rsrp_to_dbm": round(tb.rsrp_dbm, 1),
        }
        self.handovers.append(ho)
        self.handover_count += 1
        self.serving = target
        self.interrupt_until = ho["completed_time"]
        self.link_up_time = self.interrupt_until
        self.ttt_timer.clear()
        kind = "INTER-RAT" if pair[0] != pair[1] else "INTRA-RAT"
        return [
            self._event(t, "HANDOVER_INITIATED", src, target,
                        f"HANDOVER INITIATED: {src} → {target} ({pair[0]}→{pair[1]}, {kind}, {reason})", extra=ho),
            self._event(ho["completed_time"], "HANDOVER_COMPLETED", src, target,
                        f"HANDOVER COMPLETED: {target} (interruption {interruption:.0f} ms)", extra=ho),
        ]

    def manual_handover(self, t: float, target: Optional[str] = None) -> List[dict]:
        if self.serving is None:
            raise ValueError("Cannot hand over while OFFLINE")
        if target:
            if target not in self.bs:
                raise ValueError(f"Unknown base station '{target}'")
            if target == self.serving:
                raise ValueError(f"{target} is already the serving base station")
            if not self.bs[target].available:
                raise ValueError(f"{target} is not available at the ambulance position")
        else:
            cands = [b for b in self.bs.values() if b.available and b.cfg.id != self.serving]
            if not cands:
                raise ValueError("No alternative base station available for handover")
            target = max(cands, key=self._score).cfg.id
        return self._handover(target, t, "MANUAL")

    # ------------------------------------------------------------------ data plane
    def link_up(self, t: float) -> bool:
        return self.serving is not None and t >= self.interrupt_until

    def transmit(self, size_bytes: int) -> LinkResult:
        """Send one packet over the current serving link (assumed up)."""
        bs_id = self.serving
        b = self.bs[bs_id]
        p = RAN_PARAMS[b.cfg.network_type]
        sinr = self.sinr_db(bs_id)
        bler = 1.0 / (1.0 + math.exp(1.1 * (sinr - 1.0)))
        thr = self.throughput_bps(bs_id)
        tx = 0
        ok = False
        while tx < MAX_HARQ_TX:
            tx += 1
            if self.rng.random() >= bler:
                ok = True
                break
        ser_ms = size_bytes * 8 / thr * 1000.0
        jitter = float(self.rng.exponential(p["jitter_ms"]))
        latency = (p["air_ms"] + p["core_ms"] + INTERNET_BACKHAUL_MS + ser_ms * tx
                   + (tx - 1) * p["harq_rtt_ms"] + jitter + self.cfg.extra_latency_ms)
        reason = "" if ok else "RADIO_BLER"
        if ok and self.cfg.extra_packet_loss > 0 and self.rng.random() < self.cfg.extra_packet_loss:
            ok, reason = False, "CONFIGURED_LOSS"
        return LinkResult(ok, latency, tx, reason, sinr, thr / 1e6)

    # ------------------------------------------------------------------ reporting
    def network_type(self) -> str:
        return self.bs[self.serving].cfg.network_type if self.serving else "OFFLINE"

    def base_station_table(self) -> List[dict]:
        return [
            {
                "id": b.cfg.id,
                "network_type": b.cfg.network_type,
                "lat": b.cfg.lat, "lon": b.cfg.lon,
                "radius_m": b.cfg.radius_m,
                "tx_power_dbm": b.cfg.tx_power_dbm,
                "frequency_ghz": b.cfg.frequency_ghz,
                "bandwidth_mhz": b.cfg.bandwidth_mhz,
                "enabled": b.cfg.enabled,
                "distance_m": round(b.distance_m, 1),
                "rsrp_dbm": round(b.rsrp_dbm, 1),
                "sinr_db": round(b.rsrp_dbm - self.cfg.noise_floor_dbm, 1),
                "in_coverage": b.in_coverage,
                "available": b.available,
                "is_serving": b.cfg.id == self.serving,
            }
            for b in self.bs.values()
        ]

    @staticmethod
    def _event(t: float, etype: str, from_bs, to_bs, message: str, extra: Optional[dict] = None) -> dict:
        return {"time": t, "event_type": etype, "from_bs": from_bs, "to_bs": to_bs,
                "message": message, "details": extra or {}}
