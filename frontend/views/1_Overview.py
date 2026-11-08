"""Overview dashboard — one-glance status of patient, ambulance and network."""
import pandas as pd
import streamlit as st

from components import charts
from components.layout import fmt, sim_buttons, snapshot
from components.map_view import render_map
from components.theme import COLORS, NET_COLORS, STATUS_COLORS, alert_html, banner, cards_row, header, synthetic_note
from utils import api

header("Overview Dashboard", "5G-Based Smart Ambulance Communication System — live simulation", "🚑")
synthetic_note()

snap0 = snapshot(show_indicator=False, fresh=True)
if snap0 is None:
    st.stop()
sim_buttons(snap0, "ov")


def pipeline(snap):
    net = snap["network"]
    ble = snap["ble"]
    g = snap["gateway"]
    nt = "HANDOVER" if net["in_handover"] else net["network_type"]
    nodes = [
        ("Virtual sensors", f"{ble['connected_devices']}/{ble['total_devices']} online",
         STATUS_COLORS["CONNECTED"] if ble["connected_devices"] == ble["total_devices"] else COLORS["amber"]),
        ("BLE link", ble["status"], STATUS_COLORS.get(ble["status"], COLORS["cyan"])),
        ("Ambulance gateway", f"{g['generated']} pkts · queue {g['queue_length']}",
         COLORS["amber"] if g["queue_length"] else COLORS["green"]),
        ("Cellular", f"{nt} · {net['serving_bs'] or '—'}", NET_COLORS.get(nt, COLORS["cyan"])),
        ("FastAPI backend", "online", COLORS["green"]),
        ("Hospital centre", f"PDR {fmt(net['pdr_pct'])}%", COLORS["green"] if (net["pdr_pct"] or 0) > 95 else COLORS["amber"]),
    ]
    parts = []
    for i, (t, s, c) in enumerate(nodes):
        parts.append(f'<div class="node" style="border-color:{c}55"><div class="t">{t}</div>'
                     f'<div class="s" style="color:{c}">{s}</div></div>')
        if i < len(nodes) - 1:
            parts.append('<div class="arrow">➜</div>')
    st.markdown('<div class="sa-pipe">' + "".join(parts) + "</div>", unsafe_allow_html=True)


@st.fragment(run_every=1)
def live():
    snap = snapshot()
    if snap is None:
        return
    p, a, net = snap["patient"], snap["ambulance"], snap["network"]
    v = p["vitals"]
    if net["offline"]:
        banner("NETWORK OFFLINE — gateway is buffering patient data", COLORS["red"], "📵", pulse=True)
    elif net["in_handover"]:
        banner("HANDOVER IN PROGRESS", COLORS["violet"], "🔁", pulse=True)
    if a["arrived"]:
        banner("Ambulance has arrived at the hospital", COLORS["blue"], "🏥")
    pipeline(snap)
    cards_row([
        dict(label="Ambulance", value=a["ambulance_id"], sub=f"{snap['status']} · {a['speed_kmh']} km/h",
             accent=COLORS["blue"]),
        dict(label="Patient", value=p["patient_id"], sub=f"Scenario {p['scenario']}: {p['scenario_label']}",
             accent=COLORS["blue"]),
        dict(label="Health status", value=p["health_status"], sub="demonstration rule (synthetic)",
             accent=STATUS_COLORS[p["health_status"]]),
        dict(label="Heart rate", value=fmt(v["heart_rate"], 0), unit="BPM", accent=COLORS["red"]),
        dict(label="SpO₂", value=fmt(v["spo2"], 1), unit="%", accent=COLORS["cyan"]),
        dict(label="Temperature", value=fmt(v["temperature"], 1), unit="°C", accent=COLORS["amber"]),
    ])
    st.write("")
    nt = "HANDOVER" if net["in_handover"] else net["network_type"]
    cards_row([
        dict(label="Current network", value=net["network_type"], sub="handover executing" if net["in_handover"] else
             f"mode {net['controls']['mode']}", accent=NET_COLORS.get(nt)),
        dict(label="Serving base station", value=net["serving_bs"] or "NONE",
             sub=f"{net['handover_count']} handovers so far", accent=NET_COLORS.get(nt)),
        dict(label="Signal strength", value=fmt(net["rsrp_dbm"]), unit="dBm",
             sub=f"SINR {fmt(net['sinr_db'])} dB", accent=COLORS["cyan"]),
        dict(label="Location", value=f"{a['lat']:.4f}, {a['lon']:.4f}", sub=f"heading {a['heading_deg']:.0f}°",
             accent=COLORS["blue"]),
        dict(label="Distance to hospital", value=fmt(a["distance_to_hospital_km"], 2), unit="km",
             sub=f"{a['progress_pct']:.0f}% of {a['route_length_km']:.1f} km", accent=COLORS["green"]),
        dict(label="Estimated arrival", value=fmt(a["eta_min"], 1), unit="min",
             sub="simulated minutes", accent=COLORS["green"]),
    ])
    st.write("")
    left, right = st.columns([1.25, 1])
    with left:
        st.plotly_chart(charts.vitals_overview(snap["vitals_history"][-120:], height=330),
                        width="stretch", key="ov_vitals")
        st.plotly_chart(charts.network_timeline(snap["signal_history"], height=130),
                        width="stretch", key="ov_nettl")
    with right:
        st.markdown("##### 🚨 Emergency alerts")
        alerts = list(reversed(snap["alerts"]))[:6]
        if alerts:
            st.markdown("".join(alert_html(x) for x in alerts), unsafe_allow_html=True)
        else:
            st.caption("No alerts yet.")
        st.markdown("##### 🔁 Recent handover events")
        ho = list(reversed(snap["handover_events"]))[:6]
        if ho:
            df = pd.DataFrame(ho)[["ho_id", "time", "from_bs", "to_bs", "from_type", "to_type", "reason",
                                   "interruption_ms"]]
            df["time"] = df["time"].round(1)
            st.dataframe(df, hide_index=True, width="stretch", height=240)
        else:
            st.caption("No handovers yet — start the simulation.")


live()


@st.fragment(run_every=3)
def map_section():
    snap = snapshot(show_indicator=False)
    if snap is None:
        return
    route = api.route(snap["route_version"])
    if route:
        st.markdown(f"##### 🗺️ Live position · {snap['route_label']}  "
                    f"<span style='color:#8aa0bd;font-size:.8rem'>route: {snap['route_source']}</span>",
                    unsafe_allow_html=True)
        render_map(route, snap, key="ov_map", height=420, zoom=13)


map_section()
