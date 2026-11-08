"""Patient monitoring — synthetic vital signs, ECG, scenarios and demonstration alerts."""
import pandas as pd
import streamlit as st

from components import charts
from components.layout import fmt, snapshot
from components.theme import COLORS, STATUS_COLORS, alert_html, cards_row, header, synthetic_note
from utils import api

header("Patient Monitoring", "Virtual patient sensors — heart rate, SpO₂, temperature and ECG", "❤️")
synthetic_note("SYNTHETIC readings generated with stochastic (Ornstein–Uhlenbeck) processes. Alerts are "
               "demonstration alerts based on configurable thresholds — NOT clinically validated diagnoses.")

snap0 = snapshot(show_indicator=False, fresh=True)
if snap0 is None:
    st.stop()
cfg = snap0["config"]

c1, c2 = st.columns([1.4, 1])
with c1:
    labels = {"A": "A — Stable patient", "B": "B — Increasing heart rate", "C": "C — Decreasing SpO₂"}
    sc = st.radio("Patient scenario", list(labels), format_func=labels.get, horizontal=True,
                  index=list(labels).index(snap0["patient"]["scenario"]))
    if sc != snap0["patient"]["scenario"]:
        api.action("POST", "/api/patient/scenario", {"scenario": sc}, success=f"Scenario {sc} active")
        st.rerun()
with c2:
    with st.expander("Demonstration alert thresholds"):
        th = cfg["thresholds"]
        with st.form("thr"):
            a1, a2 = st.columns(2)
            hr_high = a1.number_input("HR high (BPM)", 60.0, 220.0, float(th["hr_high"]))
            hr_crit = a2.number_input("HR critical (BPM)", 60.0, 250.0, float(th["hr_critical"]))
            hr_low = a1.number_input("HR low (BPM)", 20.0, 100.0, float(th["hr_low"]))
            spo2_low = a2.number_input("SpO₂ low (%)", 70.0, 100.0, float(th["spo2_low"]))
            spo2_crit = a1.number_input("SpO₂ critical (%)", 60.0, 100.0, float(th["spo2_critical"]))
            temp_high = a2.number_input("Temp high (°C)", 36.0, 43.0, float(th["temp_high"]))
            if st.form_submit_button("Apply thresholds", type="primary"):
                api.action("PUT", "/api/simulation/config", {"thresholds": {
                    "hr_high": hr_high, "hr_critical": hr_crit, "hr_low": hr_low, "spo2_low": spo2_low,
                    "spo2_critical": spo2_crit, "temp_high": temp_high}}, success="Thresholds updated")


@st.fragment(run_every=1)
def live():
    snap = snapshot()
    if snap is None:
        return
    p = snap["patient"]
    v = p["vitals"]
    th = snap["config"]["thresholds"]
    cards_row([
        dict(label="Patient", value=p["patient_id"], sub=p["name"], accent=COLORS["blue"]),
        dict(label="Status", value=p["health_status"], sub=f"Scenario {p['scenario']}", accent=STATUS_COLORS[p["health_status"]]),
        dict(label="Heart rate", value=fmt(v["heart_rate"], 0), unit="BPM", accent=COLORS["red"],
             sub=f"limits {th['hr_low']:.0f}–{th['hr_high']:.0f}"),
        dict(label="SpO₂", value=fmt(v["spo2"], 1), unit="%", accent=COLORS["cyan"], sub=f"low < {th['spo2_low']:.0f}"),
        dict(label="Temperature", value=fmt(v["temperature"], 2), unit="°C", accent=COLORS["amber"],
             sub=f"high > {th['temp_high']:.1f}"),
        dict(label="Last reading", value=v["timestamp"][11:19], unit="UTC", sub="sim clock", accent=COLORS["violet"]),
    ])
    st.plotly_chart(charts.ecg_chart(p["ecg"], height=230, hr=v["heart_rate"]), width="stretch", key="pm_ecg")
    hist = snap["vitals_history"]
    g1, g2, g3 = st.columns(3)
    g1.plotly_chart(charts.vitals_line(hist, "heart_rate", "#ef4444", "BPM",
                                       {"high": th["hr_high"], "critical": th["hr_critical"]}, title="Heart rate (BPM)"),
                    width="stretch", key="pm_hr")
    g2.plotly_chart(charts.vitals_line(hist, "spo2", "#22d3ee", "%",
                                       {"low": th["spo2_low"], "critical": th["spo2_critical"]}, title="SpO₂ (%)"),
                    width="stretch", key="pm_spo2")
    g3.plotly_chart(charts.vitals_line(hist, "temperature", "#f59e0b", "°C", {"high": th["temp_high"]},
                                       title="Temperature (°C)"), width="stretch", key="pm_temp")
    a, b = st.columns([1, 1.4])
    with a:
        st.markdown("##### 🚨 Patient alerts (demonstration)")
        alerts = [x for x in reversed(snap["alerts"]) if x["category"] in ("PATIENT", "BLE")][:8]
        st.markdown("".join(alert_html(x) for x in alerts) if alerts else "<i>No patient alerts.</i>",
                    unsafe_allow_html=True)
    with b:
        st.markdown("##### Timestamped reading history")
        df = pd.DataFrame(hist)
        if not df.empty:
            st.dataframe(df.iloc[::-1][["timestamp", "sim_time_s", "packet_id", "heart_rate", "spo2", "temperature",
                                        "source"]].head(60), hide_index=True, width="stretch", height=300)


live()

st.divider()
with st.expander("Inject an external reading (POST /api/patient/vitals)"):
    st.caption("Sends a manual reading through the gateway pipeline (packet ID, timestamp, validation, forwarding).")
    with st.form("inject"):
        i1, i2, i3 = st.columns(3)
        hr = i1.number_input("Heart rate", 20.0, 250.0, 95.0)
        sp = i2.number_input("SpO₂", 50.0, 100.0, 97.0)
        tp = i3.number_input("Temperature", 30.0, 45.0, 37.2)
        if st.form_submit_button("Send reading"):
            api.action("POST", "/api/patient/vitals", {"patient_id": "P001", "heart_rate": hr, "spo2": sp,
                                                       "temperature": tp})
with st.expander("Download persisted vitals (SQLite)"):
    if st.button("Load from database"):
        rows = api.get("/api/patient/vitals", limit=5000, source="db")
        if rows:
            df = pd.DataFrame(rows["history"])
            st.dataframe(df.tail(200), width="stretch", hide_index=True)
            st.download_button("Download CSV", df.to_csv(index=False), "patient_vitals.csv", "text/csv")
