"""End-to-end smoke test of every REST endpoint + the WebSocket against a RUNNING backend.

Usage:  python tests/smoke_api.py [http://localhost:8000]
"""
import json
import sys
import time

import requests
from websockets.sync.client import connect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
WS = BASE.replace("http", "ws", 1) + "/ws/live"
results = []


def check(name, method, path, expect=200, **kw):
    r = requests.request(method, BASE + path, timeout=60, **kw)
    passed = r.status_code == expect
    results.append(passed)
    print(f"{'PASS' if passed else 'FAIL'} {method:6} {path:45} -> {r.status_code}"
          + ("" if passed else f"  {r.text[:200]}"))
    try:
        return r.json()
    except ValueError:
        return None


check("health", "GET", "/api/health")
check("reset", "POST", "/api/simulation/reset")
check("config", "PUT", "/api/simulation/config", json={"time_scale": 10})
check("start", "POST", "/api/simulation/start")
time.sleep(3)
st = check("status", "GET", "/api/simulation/status")
assert st["status"] == "RUNNING" and st["sim_elapsed_s"] > 0, st["status"]
check("vitals get", "GET", "/api/patient/vitals?limit=5")
check("vitals db", "GET", "/api/patient/vitals?limit=5&source=db")
check("vitals post", "POST", "/api/patient/vitals", json={"patient_id": "P001", "heart_rate": 95, "spo2": 97,
                                                           "temperature": 37.2})
check("vitals invalid", "POST", "/api/patient/vitals", expect=422, json={"heart_rate": 400, "spo2": 97,
                                                                          "temperature": 37})
check("ecg", "GET", "/api/patient/ecg")
check("scenario", "POST", "/api/patient/scenario", json={"scenario": "B"})
check("location get", "GET", "/api/ambulance/location")
check("location post", "POST", "/api/ambulance/location", json={"latitude": 13.0474, "longitude": 80.2332})
check("route", "GET", "/api/route")
check("network", "GET", "/api/network/status")
check("bs list", "GET", "/api/network/base_stations")
check("bs update", "PUT", "/api/network/base_stations/BS2", json={"radius_m": 1450})
check("bs bad", "PUT", "/api/network/base_stations/BS9", expect=400, json={"radius_m": 1450})
check("handover", "POST", "/api/network/handover", json={})
check("handover bad", "POST", "/api/network/handover", expect=400, json={"target_bs": "BS9"})
check("handovers", "GET", "/api/network/handovers")
check("handovers db", "GET", "/api/network/handovers?source=db")
check("events", "GET", "/api/network/events")
check("degrade", "POST", "/api/network/control", json={"action": "degrade_5g", "degradation_db": 30})
check("force4g", "POST", "/api/network/control", json={"action": "force_4g"})
n = check("network", "GET", "/api/network/status")
assert n["network_type"] in ("4G", "OFFLINE"), n["network_type"]
check("fail", "POST", "/api/network/control", json={"action": "fail"})
time.sleep(3)
n = check("network", "GET", "/api/network/status")
assert n["network_type"] == "OFFLINE" and n["queued_packets"] > 0, n
check("restore", "POST", "/api/network/control", json={"action": "restore_all"})
time.sleep(2)
n = check("network", "GET", "/api/network/status")
assert n["network_type"] != "OFFLINE" and n["queued_packets"] == 0, n
check("ble", "GET", "/api/ble/status")
check("ble sensor", "POST", "/api/ble/sensor", json={"device_id": "SEN-TMP", "connected": False})
check("ble sensor on", "POST", "/api/ble/sensor", json={"device_id": "SEN-TMP", "connected": True})
check("gateway", "GET", "/api/gateway/status")
check("packets", "GET", "/api/gateway/packets?limit=5")
check("packets db", "GET", "/api/gateway/packets?limit=5&source=db")
check("alerts", "GET", "/api/alerts")
check("message", "POST", "/api/messages", json={"sender": "HOSPITAL", "text": "Prepare for arrival"})
check("messages", "GET", "/api/messages")
check("pause", "POST", "/api/simulation/pause")
check("resume", "POST", "/api/simulation/resume")
check("config get", "GET", "/api/simulation/config")
check("config bad", "PUT", "/api/simulation/config", expect=400, json={"route_preset": "nowhere"})
check("analytics", "GET", "/api/analytics")
exp = check("experiment", "POST", "/api/analytics/experiment",
            json={"name": "smoke", "outage_start_frac": 0.5, "outage_duration_s": 20})
print("   experiment:", {r["configuration"]: r["metrics"]["pdr_pct"] for r in exp["results"]})
check("experiments", "GET", "/api/analytics/experiments")
check("runs", "GET", "/api/history/runs")
check("history", "GET", "/api/history/packet_logs?limit=3")
check("history bad", "GET", "/api/history/nope", expect=404)
check("bs reset", "POST", "/api/network/base_stations/reset")
check("reset", "POST", "/api/simulation/reset")
check("start", "POST", "/api/simulation/start")

with connect(WS, open_timeout=5, max_size=16 * 2**20) as ws:
    msgs = [json.loads(ws.recv(timeout=5)) for _ in range(3)]
    ok_ws = all(m["type"] == "snapshot" for m in msgs) and msgs[-1]["data"]["sim_elapsed_s"] > msgs[0]["data"]["sim_elapsed_s"]
    keys = sorted(msgs[-1]["data"].keys())
    results.append(ok_ws)
    print(f"{'PASS' if ok_ws else 'FAIL'} WS     /ws/live  ({len(msgs)} snapshots; keys: {', '.join(keys)})")

check("reset", "POST", "/api/simulation/reset")
check("config", "PUT", "/api/simulation/config", json={"time_scale": 3, "scenario": "A"})
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
