"""Performance metrics computed from packet records & simulation event logs.

Nothing here is hard-coded: every number is derived from the packet log
(generation/delivery timestamps, status) and the network event log
(handovers, outages, connected time) of a simulation run.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import numpy as np

from .config import SimulationConfig

CONFIGURATIONS = {
    "A_5G_ONLY": {"label": "A. 5G-only", "mode": "5G_ONLY", "buffering_enabled": False},
    "B_4G_ONLY": {"label": "B. 4G LTE-only", "mode": "4G_ONLY", "buffering_enabled": False},
    "C_HYBRID": {"label": "C. 5G + 4G fallback + buffering", "mode": "HYBRID", "buffering_enabled": True},
}


def _metrics_from(records: List[dict], net, queue_len: int, sim_elapsed: float,
                  packet_size_bytes: int, outages: List[dict]) -> Dict[str, Optional[float]]:
    recs = [r for r in records if r["status"] != "REJECTED"]
    delivered = [r for r in recs if r["status"] == "DELIVERED"]
    lost = [r for r in recs if r["status"] in ("LOST", "DROPPED_BUFFER_FULL")]
    offered = len(recs) + queue_len
    lat = np.array([r["latency_ms"] for r in delivered], dtype=float) if delivered else np.array([])
    rt = np.array([r["latency_ms"] for r in delivered if not r.get("buffered")], dtype=float)
    thr = [r["throughput_mbps"] for r in delivered if r.get("throughput_mbps") is not None]
    ho = net.handovers
    buffered = [r for r in recs if r.get("buffered")]
    recovered = [r for r in buffered if r["status"] == "DELIVERED"]
    recov_times = [o["recovery_time_s"] for o in outages if o.get("recovery_time_s") is not None]
    goodput_kbps = (len(delivered) * packet_size_bytes * 8 / 1000.0 / sim_elapsed) if sim_elapsed > 0 else 0.0
    return {
        "packets_offered": offered,
        "packets_delivered": len(delivered),
        "packets_lost": len(lost),
        "packets_pending": queue_len,
        "avg_latency_ms": round(float(lat.mean()), 2) if lat.size else None,
        "avg_realtime_latency_ms": round(float(rt.mean()), 2) if rt.size else None,
        "p95_latency_ms": round(float(np.percentile(lat, 95)), 2) if lat.size else None,
        "max_latency_ms": round(float(lat.max()), 2) if lat.size else None,
        "avg_throughput_mbps": round(float(np.mean(thr)), 2) if thr else 0.0,
        "goodput_kbps": round(goodput_kbps, 3),
        "pdr_pct": round(100.0 * len(delivered) / offered, 2) if offered else None,
        "packet_loss_pct": round(100.0 * len(lost) / offered, 2) if offered else None,
        "availability_pct": round(100.0 * net.connected_time / net.total_time, 2) if net.total_time else None,
        "handover_count": net.handover_count,
        "avg_interruption_ms": round(float(np.mean([h["interruption_ms"] for h in ho])), 2) if ho else 0.0,
        "total_interruption_ms": round(float(np.sum([h["interruption_ms"] for h in ho])), 2) if ho else 0.0,
        "buffered_packets": len(buffered) + queue_len,
        "recovered_packets": len(recovered),
        "outage_count": len(outages),
        "avg_recovery_time_s": round(float(np.mean(recov_times)), 3) if recov_times else None,
        "time_on_5g_s": round(net.time_on["5G"], 1),
        "time_on_4g_s": round(net.time_on["4G"], 1),
        "time_offline_s": round(net.time_on["OFFLINE"], 1),
        "sim_duration_s": round(sim_elapsed, 1),
    }


def live_network_metrics(engine) -> dict:
    """Metrics for the live run (called while holding the engine lock)."""
    g, net = engine.gateway, engine.network
    m = _metrics_from(g.records, net, len(g.queue), engine.sim_elapsed,
                      engine.config.packet_size_bytes, engine.outage_records)
    recent = [r["latency_ms"] for r in list(g.records)[-20:] if r["status"] == "DELIVERED"]
    m["latency_ms"] = round(float(np.mean(recent)), 2) if recent else None
    return m


def latency_series(records: List[dict], max_points: int = 600) -> List[dict]:
    rows = [{"t": r["sim_time_s"], "latency_ms": r["latency_ms"], "status": r["status"],
             "network_type": r.get("tx_network_type") or r["network_type"], "buffered": r.get("buffered", False)}
            for r in records if r["status"] != "REJECTED"]
    step = max(1, len(rows) // max_points)
    return rows[::step]


def run_single(base: SimulationConfig, key: str, route_provider, outage: Optional[dict],
               max_sim_s: float = 3600.0) -> dict:
    from .engine import SimulationEngine

    spec = CONFIGURATIONS[key]
    cfg = base.merged({"mode": spec["mode"], "buffering_enabled": spec["buffering_enabled"],
                       "network_failure": False, "force_4g": False})
    eng = SimulationEngine(cfg, route_provider=route_provider, headless=True)
    if outage and outage.get("duration_s", 0) > 0:
        eng.outage_plan = {"start_frac": outage["start_frac"], "duration_s": outage["duration_s"]}
    eng.start()
    t0 = time.perf_counter()
    while eng.status == "RUNNING" and eng.sim_elapsed < max_sim_s:
        eng.step(10.0)
    # let any final backlog drain (ambulance parked at hospital)
    eng._flush(eng.sim_elapsed)
    m = _metrics_from(eng.gateway.records, eng.network, len(eng.gateway.queue), eng.sim_elapsed,
                      cfg.packet_size_bytes, eng.outage_records)
    return {
        "configuration": key,
        "label": spec["label"],
        "metrics": m,
        "handovers": eng.network.handovers,
        "outages": eng.outage_records,
        "latency_series": latency_series(eng.gateway.records),
        "network_timeline": [{"t": s["t"], "network_type": s["network_type"], "serving": s["serving"]}
                             for s in list(eng.signal_history)[:: max(1, len(eng.signal_history) // 600)]],
        "compute_time_s": round(time.perf_counter() - t0, 3),
    }


def run_comparison(base: SimulationConfig, route_provider, outage: Optional[dict] = None) -> List[dict]:
    """Run configurations A, B, C with identical seed/route/parameters."""
    return [run_single(base, key, route_provider, outage) for key in CONFIGURATIONS]
