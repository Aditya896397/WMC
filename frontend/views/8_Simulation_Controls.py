"""Simulation control panel — every control changes the backend simulation state."""
import pandas as pd
import streamlit as st

from components.layout import sim_buttons, snapshot
from components.theme import badge, header, synthetic_note
from utils import api

header("Simulation Controls", "Every control below modifies the shared backend simulation state via the REST API", "🎛️")
synthetic_note("Controls change a software simulation; they do not affect any real network or device.")

snap = snapshot(fresh=True)
if snap is None:
    st.stop()
cfg = snap["config"]
ctl = snap["network"]["controls"]

st.markdown(f"Status {badge(snap['status'])} · run `{snap['run_id']}` · network {badge(snap['network']['network_type'])}",
            unsafe_allow_html=True)
sim_buttons(snap, "ctl")


def put(updates: dict, msg: str):
    api.action("PUT", "/api/simulation/config", updates, success=msg)
    st.rerun()


t1, t2, t3, t4, t5 = st.tabs(["⏱️ Simulation & patient", "📡 Network events", "📶 Radio propagation",
                              "🗼 Base stations", "📦 Traffic, loss & latency"])

with t1:
    with st.form("sim_form"):
        c1, c2, c3 = st.columns(3)
        labels = {"A": "A — Stable patient", "B": "B — Increasing heart rate", "C": "C — Decreasing SpO₂"}
        scenario = c1.selectbox("Patient scenario", list(labels), format_func=labels.get,
                                index=list(labels).index(cfg["scenario"]))
        speed = c2.slider("Ambulance speed (km/h)", 5, 120, int(cfg["ambulance_speed_kmh"]))
        ts = c3.slider("Time acceleration (sim s per real s)", 0.5, 30.0, float(cfg["time_scale"]), 0.5)
        tick = c1.slider("Engine tick / UI broadcast interval (s)", 0.2, 5.0, float(cfg["tick_interval_s"]), 0.1)
        seed = c2.number_input("Random seed (applies on reset)", 0, 10_000_000, int(cfg["seed"] or 42))
        if st.form_submit_button("Apply", type="primary"):
            put({"scenario": scenario, "ambulance_speed_kmh": speed, "time_scale": ts, "tick_interval_s": tick,
                 "seed": int(seed)}, "Simulation settings applied")

with t2:
    st.markdown("Fault injection & manual mobility events")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("**5G degradation**")
        deg = st.slider("dB attenuation", 0, 60, int(ctl["five_g_degradation_db"]) or 25, key="c_deg")
        if st.button("Simulate 5G degradation", width="stretch"):
            api.action("POST", "/api/network/control", {"action": "degrade_5g", "degradation_db": deg})
            st.rerun()
        if st.button("Restore 5G signal", width="stretch"):
            api.action("POST", "/api/network/control", {"action": "restore_5g"})
            st.rerun()
    with c2:
        st.markdown("**Fallback**")
        st.caption(f"Forced 4G: **{ctl['force_4g']}**")
        if st.button("Force 4G fallback", width="stretch", disabled=ctl["force_4g"]):
            api.action("POST", "/api/network/control", {"action": "force_4g"})
            st.rerun()
        if st.button("Release 4G (allow 5G)", width="stretch", disabled=not ctl["force_4g"]):
            api.action("POST", "/api/network/control", {"action": "release_4g"})
            st.rerun()
    with c3:
        st.markdown("**Outage**")
        st.caption(f"Network failure: **{ctl['network_failure']}**")
        if st.button("Simulate network failure", width="stretch", type="primary",
                     disabled=ctl["network_failure"]):
            api.action("POST", "/api/network/control", {"action": "fail"})
            st.rerun()
        if st.button("Restore network connectivity", width="stretch", disabled=not ctl["network_failure"]):
            api.action("POST", "/api/network/control", {"action": "restore"})
            st.rerun()
    with c4:
        st.markdown("**Handover**")
        tgt = st.selectbox("Target cell", ["Best neighbour"] + [b["id"] for b in snap["network"]["base_stations"]])
        if st.button("Trigger handover", width="stretch"):
            api.action("POST", "/api/network/handover", {"target_bs": None if tgt == "Best neighbour" else tgt})
            st.rerun()
        if st.button("Restore all network faults", width="stretch"):
            api.action("POST", "/api/network/control", {"action": "restore_all"})
            st.rerun()
    st.divider()
    with st.form("policy"):
        p1, p2, p3, p4 = st.columns(4)
        modes = ["HYBRID", "5G_ONLY", "4G_ONLY"]
        mode = p1.selectbox("Network mode", modes, index=modes.index(cfg["mode"]))
        buf = p2.toggle("Gateway buffering", value=cfg["buffering_enabled"])
        cap = p3.number_input("Buffer capacity (packets)", 10, 100000, int(cfg["buffer_capacity"]))
        pref = p4.slider("5G preference offset (dB)", 0.0, 30.0, float(cfg["prefer_5g_offset_db"]), 0.5)
        h1, h2, h3 = st.columns(3)
        hyst = h1.slider("Handover hysteresis (dB)", 0.0, 15.0, float(cfg["hysteresis_db"]), 0.5)
        ttt = h2.slider("Time-to-trigger (s)", 0.0, 10.0, float(cfg["time_to_trigger_s"]), 0.25)
        marg = h3.slider("Target entry margin (dB)", 0.0, 20.0, float(cfg["ho_target_margin_db"]), 0.5)
        if st.form_submit_button("Apply mobility policy", type="primary"):
            put({"mode": mode, "buffering_enabled": buf, "buffer_capacity": int(cap), "prefer_5g_offset_db": pref,
                 "hysteresis_db": hyst, "time_to_trigger_s": ttt, "ho_target_margin_db": marg}, "Policy applied")

with t3:
    with st.form("radio"):
        st.caption("Simplified log-distance model parameters (signal strength = Ptx + G − PL + shadowing).")
        r1, r2, r3 = st.columns(3)
        n5 = r1.slider("Path-loss exponent 5G", 2.0, 6.0, float(cfg["path_loss_exponent_5g"]), 0.1)
        n4 = r2.slider("Path-loss exponent 4G", 2.0, 6.0, float(cfg["path_loss_exponent_4g"]), 0.1)
        sig = r3.slider("Shadowing σ (dB)", 0.0, 12.0, float(cfg["shadowing_sigma_db"]), 0.5)
        corr = r1.slider("Shadowing correlation distance (m)", 5, 500, int(cfg["shadowing_corr_m"]))
        gain = r2.slider("Antenna gain (dB)", 0.0, 30.0, float(cfg["antenna_gain_db"]), 0.5)
        noise = r3.slider("Noise + interference floor (dBm)", -130.0, -90.0, float(cfg["noise_floor_dbm"]), 1.0)
        m5 = r1.slider("Min usable signal 5G (dBm)", -130.0, -80.0, float(cfg["min_rsrp_5g_dbm"]), 1.0)
        m4 = r2.slider("Min usable signal 4G (dBm)", -130.0, -80.0, float(cfg["min_rsrp_4g_dbm"]), 1.0)
        if st.form_submit_button("Apply propagation parameters", type="primary"):
            put({"path_loss_exponent_5g": n5, "path_loss_exponent_4g": n4, "shadowing_sigma_db": sig,
                 "shadowing_corr_m": corr, "antenna_gain_db": gain, "noise_floor_dbm": noise,
                 "min_rsrp_5g_dbm": m5, "min_rsrp_4g_dbm": m4}, "Propagation parameters applied")

with t4:
    st.caption("Changes are applied immediately and saved to the `base_stations` table (persist across restarts).")
    for b in snap["network"]["base_stations"]:
        with st.form(f"bs_{b['id']}"):
            st.markdown(f"**{b['id']}** · {b['network_type']} · {b['frequency_ghz']} GHz · {b['bandwidth_mhz']:.0f} MHz"
                        f" · now {b['rsrp_dbm']} dBm at {b['distance_m']:.0f} m"
                        + (" · ⭐ serving" if b["is_serving"] else ""))
            c1, c2, c3, c4, c5 = st.columns([1.2, 1.2, 1, 1, .8])
            rad = c1.slider("Coverage radius (m)", 100, 8000, int(b["radius_m"]), 50, key=f"r_{b['id']}")
            txp = c2.slider("Tx power (dBm)", 20.0, 55.0, float(b["tx_power_dbm"]), 0.5, key=f"p_{b['id']}")
            lat = c3.number_input("Latitude", value=float(b["lat"]), format="%.5f", key=f"la_{b['id']}")
            lon = c4.number_input("Longitude", value=float(b["lon"]), format="%.5f", key=f"lo_{b['id']}")
            en = c5.toggle("Enabled", value=b["enabled"], key=f"e_{b['id']}")
            if st.form_submit_button(f"Update {b['id']}"):
                api.action("PUT", f"/api/network/base_stations/{b['id']}",
                           {"radius_m": rad, "tx_power_dbm": txp, "lat": lat, "lon": lon, "enabled": en})
                st.rerun()
    if st.button("Reset all base stations to defaults"):
        api.action("POST", "/api/network/base_stations/reset")
        st.rerun()

with t5:
    with st.form("traffic"):
        a1, a2, a3 = st.columns(3)
        pint = a1.slider("Packet generation interval (s)", 0.2, 10.0, float(cfg["packet_interval_s"]), 0.1)
        psize = a2.slider("Packet size (bytes)", 64, 8000, int(cfg["packet_size_bytes"]), 64)
        loss = a3.slider("Configured extra network packet loss", 0.0, 0.5, float(cfg["extra_packet_loss"]), 0.01)
        lat = a1.slider("Configured extra network latency (ms)", 0.0, 1000.0, float(cfg["extra_latency_ms"]), 5.0)
        bl = a2.slider("BLE base latency (ms)", 0.0, 100.0, float(cfg["ble_base_latency_ms"]), 0.5)
        bloss = a3.slider("BLE per-attempt packet loss", 0.0, 0.9, float(cfg["ble_packet_loss"]), 0.01)
        if st.form_submit_button("Apply traffic settings", type="primary"):
            put({"packet_interval_s": pint, "packet_size_bytes": psize, "extra_packet_loss": loss,
                 "extra_latency_ms": lat, "ble_base_latency_ms": bl, "ble_packet_loss": bloss},
                "Traffic/loss/latency settings applied")

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.markdown("##### Active configuration (from the backend)")
    st.json(cfg, expanded=False)
with c2:
    st.markdown("##### Control & system event log")
    ev = pd.DataFrame(list(reversed(snap["network_events"])))
    if not ev.empty:
        st.dataframe(ev[["time", "event_type", "message"]].round({"time": 1}), hide_index=True,
                     width="stretch", height=300)
