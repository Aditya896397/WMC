"""Hospital monitoring centre — what the receiving hospital sees in real time."""
import html

import pandas as pd
import streamlit as st

from components import charts
from components.layout import fmt, snapshot
from components.map_view import render_map
from components.theme import COLORS, NET_COLORS, STATUS_COLORS, alert_html, badge, cards_row, header, synthetic_note
from utils import api

header("Hospital Monitoring Centre", "Incoming patient telemetry, ambulance tracking and network status "
                                     "(live via WebSocket from the FastAPI backend)", "🏥")
synthetic_note()


@st.fragment(run_every=1)
def live():
    snap = snapshot()
    if snap is None:
        return
    p, a, net, g = snap["patient"], snap["ambulance"], snap["network"], snap["gateway"]
    v = p["vitals"]
    st.markdown(
        f"**Incoming:** {a['ambulance_id']} with patient {p['patient_id']} {badge(p['health_status'])} · "
        f"ETA **{fmt(a['eta_min'], 1)} min** · link {badge('HANDOVER' if net['in_handover'] else net['network_type'])}",
        unsafe_allow_html=True)
    left, right = st.columns([1.6, 1])
    with left:
        st.markdown("#### 🫀 Patient")
        cards_row([
            dict(label="Patient ID", value=p["patient_id"], sub=p["scenario_label"], accent=COLORS["blue"]),
            dict(label="Heart rate", value=fmt(v["heart_rate"], 0), unit="BPM", accent=COLORS["red"]),
            dict(label="SpO₂", value=fmt(v["spo2"], 1), unit="%", accent=COLORS["cyan"]),
            dict(label="Temperature", value=fmt(v["temperature"], 1), unit="°C", accent=COLORS["amber"]),
        ])
        st.plotly_chart(charts.ecg_chart(p["ecg"], height=200, hr=v["heart_rate"]), width="stretch",
                        key="h_ecg")
        st.plotly_chart(charts.vitals_overview(snap["vitals_history"][-150:], height=300), width="stretch",
                        key="h_vit")
    with right:
        st.markdown("#### 🚑 Ambulance")
        cards_row([dict(label="Speed", value=fmt(a["speed_kmh"]), unit="km/h", accent=COLORS["cyan"]),
                   dict(label="Distance", value=fmt(a["distance_to_hospital_km"], 2), unit="km", accent=COLORS["green"]),
                   dict(label="ETA", value=fmt(a["eta_min"], 1), unit="min", accent=COLORS["green"])])
        st.caption(f"📍 {a['lat']:.5f}, {a['lon']:.5f} · {a['progress_pct']:.0f}% of route")
        st.markdown("#### 📡 Network")
        nt = "HANDOVER" if net["in_handover"] else net["network_type"]
        cards_row([dict(label="Network", value=net["network_type"], accent=NET_COLORS.get(nt)),
                   dict(label="Serving BS", value=net["serving_bs"] or "NONE", accent=NET_COLORS.get(nt)),
                   dict(label="Signal", value=fmt(net["rsrp_dbm"]), unit="dBm", accent=COLORS["cyan"])])
        st.write("")
        ho_state = ("IN PROGRESS" if net["in_handover"] else
                    (f"last {snap['handover_events'][-1]['from_bs']}→{snap['handover_events'][-1]['to_bs']}"
                     if snap["handover_events"] else "none yet"))
        cards_row([dict(label="Handover status", value=ho_state, sub=f"{net['handover_count']} total",
                        accent=COLORS["violet"]),
                   dict(label="Packets", value=f"{g['delivered']}/{g['generated']}",
                        sub=f"PDR {fmt(net['pdr_pct'], 1)}% · queue {g['queue_length']}", accent=COLORS["green"])])
        st.markdown("#### 🚨 Alerts")
        alerts = list(reversed(snap["alerts"]))[:5]
        st.markdown("".join(alert_html(x) for x in alerts) if alerts else "<i>No alerts.</i>", unsafe_allow_html=True)

    st.markdown("#### 📦 Packet transmission status (latest received)")
    df = pd.DataFrame(list(reversed(snap["recent_packets"])))
    if not df.empty:
        cols = [c for c in ["packet_id", "timestamp", "status", "latency_ms", "tx_network_type", "tx_base_station",
                            "buffered", "heart_rate", "spo2", "temperature", "loss_reason"] if c in df]
        st.dataframe(df[cols].head(15), hide_index=True, width="stretch", height=250)


live()

st.divider()
c_chat, c_map = st.columns([1, 1.2])
with c_chat:
    st.markdown("#### 💬 Doctor ↔ Ambulance communication (simulated)")
    st.caption("Messages travel over the simulated cellular link: they are delivered with the current network latency, "
               "or queued while the ambulance is OFFLINE.")

    @st.fragment(run_every=2)
    def chat_log():
        snap = snapshot(show_indicator=False)
        if snap is None:
            return
        msgs = snap["messages"][-14:]
        if not msgs:
            st.caption("No messages yet.")
        parts = []
        for m in msgs:
            cls = "h" if m["sender"] == "HOSPITAL" else "a"
            who = "🩺 Hospital" if m["sender"] == "HOSPITAL" else "🚑 Ambulance crew"
            status = (f"✓ delivered in {m['latency_ms']:.0f} ms via {m['network_type']}" if m["status"] == "DELIVERED"
                      else "⏳ queued (no network)")
            parts.append(f'<div class="sa-chat {cls}"><b>{who}</b><br>{html.escape(m["text"])}'
                         f'<div class="meta">{m["sent_ts"][11:19]} · {status}</div></div>')
        st.markdown("".join(parts), unsafe_allow_html=True)

    chat_log()
    with st.form("chat", clear_on_submit=True):
        sender = st.radio("Send as", ["HOSPITAL", "AMBULANCE"], horizontal=True,
                          format_func={"HOSPITAL": "🩺 Hospital doctor", "AMBULANCE": "🚑 Ambulance crew"}.get)
        text = st.text_input("Message", placeholder="e.g. Prepare trauma bay 2; administer oxygen")
        quick = st.selectbox("…or quick message", ["", "Increase oxygen flow", "Share 12-lead ECG",
                                                   "ETA confirmed, trauma team ready", "Patient stable, en route"])
        if st.form_submit_button("Send", type="primary"):
            msg = text or quick
            if msg:
                api.action("POST", "/api/messages", {"sender": sender, "text": msg})
            else:
                st.warning("Type a message first.")

with c_map:
    @st.fragment(run_every=3)
    def hmap():
        snap = snapshot(show_indicator=False)
        if snap is None:
            return
        route = api.route(snap["route_version"])
        if route:
            st.markdown("#### 🗺️ Ambulance location")
            render_map(route, snap, key="h_map", height=470, show_coverage=False, zoom=13)

    hmap()
