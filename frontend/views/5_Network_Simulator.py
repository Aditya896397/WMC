"""5G NR / 4G LTE network simulator — signal, cell selection, handover, fallback, buffering."""
import pandas as pd
import streamlit as st

from components import charts
from components.layout import fmt, snapshot
from components.map_view import render_map
from components.theme import COLORS, NET_COLORS, banner, cards_row, header, synthetic_note
from utils import api

header("5G / 4G Network Simulator", "Path loss · signal strength · cell selection · handover · 5G→4G fallback · "
                                    "outage buffering", "📡")
synthetic_note("This is a SIMPLIFIED distance-based propagation and mobility model for teaching purposes. It is "
               "NOT a standards-compliant 3GPP channel/system simulation and the numbers are NOT real 5G measurements.")

snap0 = snapshot(show_indicator=False, fresh=True)
if snap0 is None:
    st.stop()
cfg = snap0["config"]

with st.expander("📘 How the network model works (assumptions)", expanded=False):
    st.markdown("**Received signal strength** (RSRP-like indicator) for each base station *i* at distance *d*:")
    st.latex(r"S_i = P_{tx,i} + G_{ant} - \Big[\underbrace{20\log_{10}\tfrac{4\pi f_i}{c}}_{\text{FSPL @ 1 m}} "
             r"+ 10\,n\,\log_{10} d\Big] + X_\sigma \;(-\,\Delta_{5G}\ \text{if degraded})")
    st.markdown("- *n* = path-loss exponent (5G mid-band 3.5 GHz, 4G 1.8 GHz), $X_\\sigma$ = log-normal shadowing, "
                "spatially correlated over the correlation distance (Gudmundson model).\n"
                "- **SINR** = S − noise floor (interference folded into the noise floor).")
    st.latex(r"\text{Throughput} = \eta\,B\,\min\big(\log_2(1+\text{SINR}),\ SE_{max}\big)\qquad "
             r"\text{BLER} = \frac{1}{1+e^{1.1(\text{SINR}-1)}}")
    st.markdown(
        "- A cell is **available** if enabled, the ambulance is within its coverage radius, S ≥ S_min for its "
        "technology, and policy allows it (mode, forced 4G, network failure).\n"
        "- **Selection score** = S + 5G preference offset (HYBRID mode) → 5G is preferred when suitable.\n"
        "- **Handover (A3-like):** neighbour score > serving score + hysteresis for the time-to-trigger, and the "
        "neighbour's S ≥ S_min + target margin. If the serving cell becomes unusable → immediate handover "
        "(radio-link-failure or policy fallback). If no cell is available → **OFFLINE**.\n"
        "- **Interruption time** (assumed): intra-NR ≈ 30 ms, NR→LTE ≈ 90 ms, LTE→NR ≈ 80 ms, intra-LTE ≈ 45 ms, "
        "+≈200 ms after radio-link failure; re-attach after outage ≈ 120 ms.\n"
        "- **Latency** = BLE + gateway (1 ms) + air interface (5G 4 ms / 4G 15 ms) + core (6 / 18 ms) + backhaul "
        "(8 ms) + serialisation × HARQ transmissions + HARQ RTT + jitter + buffering wait.\n"
        "- **Buffering:** while OFFLINE or during handover execution, the gateway queues packets and flushes them "
        "when the link is usable again.")


def toast_new_events(snap):
    seen = st.session_state.setdefault("seen_net_events", set())
    first = st.session_state.get("net_events_init") != snap["run_id"]
    for e in snap["network_events"]:
        key = (snap["run_id"], e["event_type"], round(e["time"], 3))
        if key in seen:
            continue
        seen.add(key)
        if first:
            continue
        if e["event_type"] in ("HANDOVER_INITIATED", "HANDOVER_COMPLETED"):
            st.toast(e["message"], icon="🔁")
        elif e["event_type"] == "OUTAGE_START":
            st.toast(e["message"], icon="📵")
        elif e["event_type"] == "RECONNECTED":
            st.toast(e["message"], icon="✅")
    st.session_state["net_events_init"] = snap["run_id"]


@st.fragment(run_every=1)
def live():
    snap = snapshot()
    if snap is None:
        return
    toast_new_events(snap)
    net = snap["network"]
    if net["offline"]:
        banner(f"OFFLINE — no network available · {net['queued_packets']} packets buffered at the gateway",
               COLORS["red"], "📵", pulse=True)
    elif net["in_handover"]:
        h = snap["handover_events"][-1]
        banner(f"HANDOVER INITIATED: {h['from_bs']} → {h['to_bs']}  ({h['from_type']}→{h['to_type']}, "
               f"{h['reason']}, {h['interruption_ms']:.0f} ms)", COLORS["violet"], "🔁", pulse=True)
    else:
        nt = net["network_type"]
        last = snap["handover_events"][-1] if snap["handover_events"] else None
        tail = f" · last: HANDOVER COMPLETED: {last['to_bs']} ({last['interruption_ms']:.0f} ms)" if last else ""
        banner(f"CONNECTED — {nt} via {net['serving_bs']}{tail}", NET_COLORS[nt], "📶")
    m = net
    cards_row([
        dict(label="Current network", value=net["network_type"], sub=f"mode {net['controls']['mode']}",
             accent=NET_COLORS.get(net["network_type"])),
        dict(label="Serving base station", value=net["serving_bs"] or "NONE",
             sub="TTT " + (", ".join(f"{k}:{v:.1f}s" for k, v in net["ttt_progress"].items()) or "idle"),
             accent=NET_COLORS.get(net["network_type"])),
        dict(label="Signal strength", value=fmt(net["rsrp_dbm"]), unit="dBm", sub=f"SINR {fmt(net['sinr_db'])} dB",
             accent=COLORS["cyan"]),
        dict(label="Network availability", value=fmt(m["availability_pct"], 2), unit="%",
             sub=f"offline {m['time_offline_s']:.0f}s of {m['sim_duration_s']:.0f}s", accent=COLORS["green"]),
        dict(label="Simulated latency", value=fmt(m["latency_ms"]), unit="ms",
             sub=f"real-time avg {fmt(m['avg_realtime_latency_ms'])} ms", accent=COLORS["violet"]),
        dict(label="Throughput", value=fmt(net["throughput_mbps"]), unit="Mbps", sub="link capacity (model)",
             accent=COLORS["blue"]),
    ])
    st.write("")
    cards_row([
        dict(label="Packet delivery ratio", value=fmt(m["pdr_pct"], 2), unit="%",
             sub=f"{m['packets_delivered']}/{m['packets_offered']} packets", accent=COLORS["green"]),
        dict(label="Packet loss", value=fmt(m["packet_loss_pct"], 2), unit="%", sub=f"{m['packets_lost']} lost",
             accent=COLORS["red"]),
        dict(label="Handover count", value=m["handover_count"], sub=f"total interruption {fmt(m['total_interruption_ms'], 0)} ms",
             accent=COLORS["violet"]),
        dict(label="Handover interruption", value=fmt(net["last_interruption_ms"], 0), unit="ms",
             sub=f"average {fmt(m['avg_interruption_ms'], 0)} ms", accent=COLORS["violet"]),
        dict(label="Buffered packets", value=net["queued_packets"], sub=f"{m['buffered_packets']} buffered in total · "
             f"{m['recovered_packets']} recovered", accent=COLORS["amber"]),
        dict(label="Outage recovery", value=fmt(m["avg_recovery_time_s"], 1), unit="s",
             sub=f"{m['outage_count']} outages", accent=COLORS["amber"]),
    ])
    c1, c2 = st.columns([2.3, 1])
    c1.plotly_chart(charts.signal_chart(snap["signal_history"], net["base_stations"], snap["config"]["min_rsrp_5g_dbm"],
                                        snap["config"]["min_rsrp_4g_dbm"]), width="stretch", key="ns_sig")
    with c2:
        st.plotly_chart(charts.gauge(net["rsrp_dbm"], f"Serving signal · {net['serving_bs'] or 'none'}"),
                        width="stretch", key="ns_gauge")
        st.plotly_chart(charts.network_timeline(snap["signal_history"], height=150), width="stretch",
                        key="ns_tl")
    st.markdown("##### Base stations (measured at the ambulance position)")
    bs = pd.DataFrame(net["base_stations"])
    bs["state"] = bs.apply(lambda r: "⭐ SERVING" if r["is_serving"] else ("✅ available" if r["available"] else
                           ("📶 weak/blocked" if r["in_coverage"] else "— out of range")), axis=1)
    st.dataframe(bs[["id", "network_type", "state", "distance_m", "rsrp_dbm", "sinr_db", "radius_m", "tx_power_dbm",
                     "frequency_ghz", "bandwidth_mhz", "enabled"]], hide_index=True, width="stretch")
    a, b = st.columns([1.2, 1])
    with a:
        st.markdown("##### 🔁 Handover log")
        ho = pd.DataFrame(list(reversed(snap["handover_events"])))
        if not ho.empty:
            ho["time"] = ho["time"].round(2)
            st.dataframe(ho[["ho_id", "time", "from_bs", "to_bs", "from_type", "to_type", "reason", "interruption_ms",
                             "rsrp_from_dbm", "rsrp_to_dbm"]], hide_index=True, width="stretch", height=280)
        else:
            st.caption("No handovers yet.")
    with b:
        st.markdown("##### 📜 Network event log")
        ev = pd.DataFrame(list(reversed(snap["network_events"])))
        if not ev.empty:
            ev["time"] = ev["time"].round(2)
            st.dataframe(ev[["time", "event_type", "message"]], hide_index=True, width="stretch", height=280)
    st.plotly_chart(charts.latency_chart(snap["recent_packets"], height=240,
                                         title="Recent packets — latency (◆ = delivered from buffer)"),
                    width="stretch", key="ns_lat")
    if snap["outages"]:
        st.markdown("##### Outage recovery records")
        st.dataframe(pd.DataFrame(snap["outages"]).drop(columns=["timestamp"], errors="ignore"),
                     hide_index=True, width="stretch")


live()

st.divider()
st.markdown("### Network controls")
ctl = snap0["network"]["controls"]
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown("**5G signal degradation**")
    deg = st.slider("Attenuation on all 5G cells (dB)", 0, 60, int(ctl["five_g_degradation_db"]) or 25, key="deg")
    d1, d2 = st.columns(2)
    if d1.button("Degrade 5G", width="stretch"):
        api.action("POST", "/api/network/control", {"action": "degrade_5g", "degradation_db": deg})
    if d2.button("Restore 5G", width="stretch"):
        api.action("POST", "/api/network/control", {"action": "restore_5g"})
with k2:
    st.markdown("**4G fallback / failure**")
    if st.button("Release forced 4G" if ctl["force_4g"] else "Force 4G fallback", width="stretch"):
        api.action("POST", "/api/network/control", {"action": "release_4g" if ctl["force_4g"] else "force_4g"})
        st.rerun()
    if st.button("Restore connectivity" if ctl["network_failure"] else "Simulate network failure",
                 width="stretch", type="primary" if not ctl["network_failure"] else "secondary"):
        api.action("POST", "/api/network/control", {"action": "restore" if ctl["network_failure"] else "fail"})
        st.rerun()
with k3:
    st.markdown("**Manual handover**")
    opts = ["Best neighbour"] + [b["id"] for b in snap0["network"]["base_stations"]]
    tgt = st.selectbox("Target", opts, label_visibility="collapsed")
    if st.button("Trigger handover", width="stretch"):
        api.action("POST", "/api/network/handover", {"target_bs": None if tgt == "Best neighbour" else tgt})
with k4:
    st.markdown("**Policy**")
    modes = ["HYBRID", "5G_ONLY", "4G_ONLY"]
    mode = st.selectbox("Mode", modes, index=modes.index(ctl["mode"]))
    buf = st.toggle("Gateway buffering", value=ctl["buffering_enabled"])
    if st.button("Apply policy", width="stretch"):
        api.action("PUT", "/api/simulation/config", {"mode": mode, "buffering_enabled": buf})
        st.rerun()
st.caption(f"Active: mode **{ctl['mode']}** · 5G degradation **{ctl['five_g_degradation_db']:.0f} dB** · "
           f"forced 4G **{ctl['force_4g']}** · network failure **{ctl['network_failure']}** · "
           f"buffering **{ctl['buffering_enabled']}**. More parameters on the Simulation Controls page.")


@st.fragment(run_every=3)
def coverage_map():
    snap = snapshot(show_indicator=False)
    if snap is None:
        return
    route = api.route(snap["route_version"])
    if route:
        st.markdown("##### Coverage map")
        render_map(route, snap, key="ns_map", height=420, zoom=13)


coverage_map()
