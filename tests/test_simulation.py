"""Simulation-engine tests (run: python -m pytest tests -q  or  python tests/test_simulation.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("USE_OSRM", "false")  # deterministic, offline

from backend.simulation.ambulance_simulator import RouteProvider  # noqa: E402
from backend.simulation.engine import SimulationEngine  # noqa: E402
from backend.simulation.performance import run_comparison  # noqa: E402


def _run_full(**cfg_updates):
    e = SimulationEngine(route_provider=RouteProvider(use_osrm=False))
    if cfg_updates:
        e.update_config(cfg_updates)
    e.start()
    while e.status == "RUNNING":
        e.step(5)
    return e


def test_full_route_completes_and_hands_over():
    e = _run_full()
    assert e.status == "ARRIVED"
    assert e.network.handover_count >= 2
    types = {(h["from_type"], h["to_type"]) for h in e.network.handovers}
    assert ("5G", "4G") in types  # fallback happened
    m = e.snapshot()["network"]
    assert m["pdr_pct"] > 90


def test_network_failure_buffers_and_recovers():
    e = SimulationEngine(route_provider=RouteProvider(use_osrm=False))
    e.start()
    e.step(30)
    e.network_control("fail")
    e.step(20)
    assert e.network.serving is None
    assert len(e.gateway.queue) > 0
    e.network_control("restore")
    e.step(5)
    assert len(e.gateway.queue) == 0
    assert e.outage_records and e.outage_records[-1]["flushed_packets"] > 0


def test_force_4g_and_manual_handover():
    e = SimulationEngine(route_provider=RouteProvider(use_osrm=False))
    e.start()
    e.step(5)
    e.network_control("force_4g")
    assert e.network.network_type() == "4G"
    e.network_control("release_4g")
    e.step(5)
    assert e.network.network_type() == "5G"
    evts = e.trigger_handover()
    assert evts[0]["event_type"] == "HANDOVER_INITIATED"


def test_scenarios_raise_alerts():
    e = _run_full(scenario="B")
    assert any(a["alert_type"].startswith("HR_") for a in e.alerts)
    e = _run_full(scenario="C")
    assert any(a["alert_type"].startswith("SPO2") for a in e.alerts)


def test_comparison_configurations():
    base = SimulationEngine(route_provider=RouteProvider(use_osrm=False)).config
    res = run_comparison(base, RouteProvider(use_osrm=False), {"start_frac": 0.4, "duration_s": 30})
    by = {r["configuration"]: r["metrics"] for r in res}
    assert by["C_HYBRID"]["pdr_pct"] >= by["A_5G_ONLY"]["pdr_pct"]
    assert by["C_HYBRID"]["recovered_packets"] > 0
    assert by["A_5G_ONLY"]["buffered_packets"] == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
