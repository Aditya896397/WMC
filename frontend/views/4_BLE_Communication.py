"""BLE communication between virtual patient sensors and the ambulance gateway."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.charts import _layout
from components.layout import fmt, snapshot
from components.theme import COLORS, STATUS_COLORS, badge, cards_row, header, synthetic_note
from utils import api

header("BLE Communication", "Patient sensors → Bluetooth Low Energy → Ambulance gateway (simulated)", "📶")
st.info("**Bluetooth Low Energy (BLE)** is used for **low-power, short-range** links between body-worn patient "
        "sensors and the ambulance gateway (a few metres inside the vehicle). Sensors exchange data during periodic "
        "*connection events*; a lost packet is retransmitted at the next connection event. This page simulates that "
        "behaviour in software — no Bluetooth hardware is used.", icon="ℹ️")
synthetic_note("BLE RSSI, latency and packet loss are produced by a simplified model "
               "(log-distance RSSI, per-attempt loss probability, link-layer retries).")

snap0 = snapshot(show_indicator=False, fresh=True)
if snap0 is None:
    st.stop()
cfg = snap0["config"]


def architecture(snap):
    ble = snap["ble"]
    sensors = "".join(
        f'<div class="node" style="border-color:{(COLORS["green"] if d["connected"] else COLORS["red"])}66">'
        f'<div class="t">{d["device_id"]}</div><div class="s" style="color:'
        f'{COLORS["green"] if d["connected"] else COLORS["red"]}">{d["name"].split(" (")[0]}</div>'
        f'<div class="t">{d["rssi_dbm"]} dBm · 🔋{d["battery_pct"]:.1f}%</div></div>' for d in ble["devices"])
    col = STATUS_COLORS.get(ble["status"], COLORS["cyan"])
    st.markdown(
        f'<div class="sa-pipe"><div style="display:flex;flex-direction:column;gap:6px;flex:1.3">{sensors}</div>'
        f'<div class="arrow">⇢ BLE ⇢</div>'
        f'<div class="node" style="border-color:{col}88;align-self:center"><div class="t">BLE link</div>'
        f'<div class="s" style="color:{col}">{ble["status"]}</div><div class="t">CI {ble["config"]["connection_interval_ms"]:.1f} ms · '
        f'{ble["config"]["max_retries"]} retries</div></div><div class="arrow">➜</div>'
        f'<div class="node" style="align-self:center;border-color:#22d3ee88"><div class="t">Ambulance gateway</div>'
        f'<div class="s" style="color:#22d3ee">{snap["gateway"]["generated"]} packets</div>'
        f'<div class="t">timestamp · packet ID · validate</div></div></div>', unsafe_allow_html=True)


@st.fragment(run_every=1)
def live():
    snap = snapshot()
    if snap is None:
        return
    ble = snap["ble"]
    architecture(snap)
    cards_row([
        dict(label="BLE connection", value=ble["status"], sub=f"{ble['connected_devices']}/{ble['total_devices']} sensors",
             accent=STATUS_COLORS.get(ble["status"])),
        dict(label="Packets transmitted", value=f"{ble['packets_transmitted']:,}", accent=COLORS["cyan"]),
        dict(label="Packets delivered", value=f"{ble['packets_delivered']:,}", accent=COLORS["green"]),
        dict(label="Packet loss", value=fmt(ble["packet_loss_pct"], 2), unit="%", sub=f"{ble['packets_lost']} lost after retries",
             accent=COLORS["red"]),
        dict(label="Avg BLE latency", value=fmt(ble["avg_latency_ms"], 1), unit="ms", accent=COLORS["violet"]),
        dict(label="Gateway status", value="RECEIVING" if snap["status"] == "RUNNING" else snap["status"],
             sub=f"{snap['gateway']['ble_incomplete']} packets with stale fields", accent=COLORS["blue"]),
    ])
    st.write("")
    a, b = st.columns([1.3, 1])
    with a:
        st.markdown("##### Connected sensor devices")
        df = pd.DataFrame(ble["devices"])
        df["connected"] = df["connected"].map({True: "🟢 connected", False: "🔴 disconnected"})
        df["measures"] = df["measures"].apply(", ".join)
        st.dataframe(df[["device_id", "name", "mac", "connected", "measures", "distance_m", "rssi_dbm", "battery_pct",
                         "packets_sent", "packets_lost", "retries", "loss_pct", "avg_latency_ms"]],
                     hide_index=True, width="stretch")
    with b:
        lh = pd.DataFrame(ble["latency_history"])
        fig = go.Figure()
        if not lh.empty:
            for dev, color in zip(["SEN-PO2", "SEN-TMP", "SEN-ECG"], ["#22d3ee", "#f59e0b", "#10b981"]):
                sub = lh[lh["device_id"] == dev]
                fig.add_trace(go.Scatter(x=sub["t"], y=sub["latency_ms"], mode="lines+markers", name=dev,
                                         line=dict(color=color, width=1.5), marker=dict(size=4)))
        fig.update_yaxes(title_text="ms")
        fig.update_xaxes(title_text="sim time (s)")
        st.plotly_chart(_layout(fig, 280, "Sensor → gateway latency"), width="stretch", key="ble_lat")
    last = snap["gateway"]["last_packet"]
    if last:
        st.markdown("##### Latest packet assembled by the gateway")
        keys = ["packet_id", "patient_id", "ambulance_id", "heart_rate", "spo2", "temperature", "latitude",
                "longitude", "network_type", "base_station", "timestamp"]
        st.json({k: last.get(k) for k in keys} | {"status": last.get("status"),
                                                   "ble_latency_ms": last.get("ble_latency_ms"),
                                                   "stale_fields": last.get("stale_fields")}, expanded=False)


live()

st.divider()
st.markdown("### BLE controls")
c1, c2 = st.columns([1.4, 1])
with c1:
    with st.form("ble_cfg"):
        f1, f2 = st.columns(2)
        lat = f1.slider("Base latency (ms)", 0.0, 100.0, float(cfg["ble_base_latency_ms"]), 0.5)
        jit = f2.slider("Jitter (ms)", 0.0, 50.0, float(cfg["ble_jitter_ms"]), 0.5)
        loss = f1.slider("Per-attempt packet loss", 0.0, 0.9, float(cfg["ble_packet_loss"]), 0.01)
        retries = f2.slider("Max link-layer retries", 0, 10, int(cfg["ble_max_retries"]))
        ci = f1.slider("Connection interval (ms)", 7.5, 200.0, float(cfg["ble_connection_interval_ms"]), 2.5)
        if st.form_submit_button("Apply BLE parameters", type="primary"):
            api.action("PUT", "/api/simulation/config", {"ble_base_latency_ms": lat, "ble_jitter_ms": jit,
                                                         "ble_packet_loss": loss, "ble_max_retries": retries,
                                                         "ble_connection_interval_ms": ci},
                       success="BLE parameters updated")
with c2:
    st.markdown("**Sensor connection (simulate a detached sensor)**")
    for d in snap0["ble"]["devices"]:
        new = st.toggle(f"{d['device_id']} — {d['name']}", value=d["connected"], key=f"tog_{d['device_id']}")
        if new != d["connected"]:
            api.action("POST", "/api/ble/sensor", {"device_id": d["device_id"], "connected": new})
            st.rerun()
    st.caption("When a sensor is disconnected or a reading is lost after all retries, the gateway re-uses the last "
               "valid value and flags it as stale.")
