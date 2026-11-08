"""Network performance analysis — compare 5G-only, 4G-only and 5G+4G fallback with buffering."""
import pandas as pd
import streamlit as st

from components import charts
from components.layout import fmt, snapshot
from components.theme import header, synthetic_note
from utils import api

header("Network Performance Analysis", "Experiments computed from packet timestamps and simulation event logs", "📊")
synthetic_note("Results are produced by running the simulation model — they describe the MODEL under its stated "
               "assumptions, not measured 5G/4G network performance.")

METRIC_ROWS = [
    ("avg_realtime_latency_ms", "Avg real-time latency (ms) — packets sent immediately"),
    ("avg_latency_ms", "Avg end-to-end latency (ms) — all delivered incl. buffered"),
    ("p95_latency_ms", "95th percentile latency (ms)"),
    ("avg_throughput_mbps", "Avg link throughput while connected (Mbps)"),
    ("goodput_kbps", "Application goodput (kbit/s)"),
    ("pdr_pct", "Packet delivery ratio (%)"),
    ("packet_loss_pct", "Packet loss (%)"),
    ("availability_pct", "Network availability (%)"),
    ("handover_count", "Handover count"),
    ("avg_interruption_ms", "Avg handover interruption (ms)"),
    ("buffered_packets", "Total buffered packets"),
    ("recovered_packets", "Buffered packets recovered (delivered)"),
    ("outage_count", "Outages"),
    ("avg_recovery_time_s", "Avg outage recovery time (s, outage start → backlog drained)"),
    ("packets_offered", "Packets generated"),
    ("time_on_5g_s", "Time on 5G (s)"),
    ("time_on_4g_s", "Time on 4G (s)"),
    ("time_offline_s", "Time offline (s)"),
]


def metrics_table(results):
    data = {r["label"]: [r["metrics"].get(k) for k, _ in METRIC_ROWS] for r in results}
    return pd.DataFrame(data, index=[lbl for _, lbl in METRIC_ROWS])


tab_exp, tab_live, tab_hist, tab_assume = st.tabs(["🧪 Run comparison experiment", "📈 Current live run",
                                                   "🗄️ Saved experiments (SQLite)", "📘 Assumptions & limitations"])

snap = snapshot(show_indicator=False, fresh=True)
if snap is None:
    st.stop()
cfg = snap["config"]

with tab_exp:
    st.markdown("Each experiment drives the ambulance over the **whole route** three times with the **same seed, route "
                "and parameters**, changing only the network configuration:")
    st.markdown("- **A. 5G-only** — only NR cells, no gateway buffering\n- **B. 4G LTE-only** — only LTE cells, no "
                "buffering\n- **C. 5G + 4G fallback + buffering** — prefers 5G, falls back to LTE, buffers during "
                "outages/handovers")
    with st.form("exp"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("Experiment name", value="Baseline with 30 s outage")
        seed = c1.number_input("Random seed", 0, 10_000_000, int(cfg["seed"] or 42))
        speed = c2.slider("Ambulance speed (km/h)", 10, 120, int(cfg["ambulance_speed_kmh"]))
        pint = c2.select_slider("Packet interval (s)", [0.25, 0.5, 1.0, 2.0, 5.0], value=float(cfg["packet_interval_s"])
                                if float(cfg["packet_interval_s"]) in [0.25, 0.5, 1.0, 2.0, 5.0] else 1.0)
        o_start = c3.slider("Inject outage at route progress (%)", 0, 100, 40)
        o_dur = c3.slider("Outage duration (s, 0 = none)", 0, 300, 30)
        deg = c4.slider("5G degradation (dB)", 0, 40, int(cfg["five_g_degradation_db"]))
        loss = c4.slider("Extra packet loss", 0.0, 0.3, float(cfg["extra_packet_loss"]), 0.01)
        e1, e2, e3 = st.columns(3)
        shadow = e1.slider("Shadowing σ (dB)", 0.0, 10.0, float(cfg["shadowing_sigma_db"]), 0.5)
        hyst = e2.slider("Handover hysteresis (dB)", 0.0, 10.0, float(cfg["hysteresis_db"]), 0.5)
        ttt = e3.slider("Time-to-trigger (s)", 0.0, 5.0, float(cfg["time_to_trigger_s"]), 0.25)
        go = st.form_submit_button("Run experiment (A, B, C)", type="primary")
    if go:
        with st.spinner("Running three full-route simulations…"):
            ok, res = api.call("POST", "/api/analytics/experiment", {
                "name": name, "seed": int(seed), "ambulance_speed_kmh": speed, "packet_interval_s": pint,
                "outage_start_frac": o_start / 100, "outage_duration_s": o_dur, "five_g_degradation_db": deg,
                "extra_packet_loss": loss, "shadowing_sigma_db": shadow, "hysteresis_db": hyst,
                "time_to_trigger_s": ttt}, timeout=180)
        if ok:
            st.session_state["exp_result"] = res
            st.toast(f"Experiment {res['experiment_id']} saved to SQLite", icon="✅")
        else:
            st.error(res)
    res = st.session_state.get("exp_result")
    if res:
        results = res["results"]
        st.success(f"**{res['experiment_id']}** — route {res['params']['route_preset']}, seed {res['params']['seed']}, "
                   f"outage {res['params']['duration_s']:.0f}s at {res['params']['start_frac'] * 100:.0f}% of route. "
                   f"Saved to the `simulation_experiments` table.")
        st.dataframe(metrics_table(results), width="stretch", height=660)
        grid = [("avg_realtime_latency_ms", "Real-time latency", " ms"), ("avg_latency_ms", "End-to-end latency (incl. buffered)", " ms"),
                ("avg_throughput_mbps", "Throughput", " Mbps"), ("pdr_pct", "Packet delivery ratio", " %"),
                ("packet_loss_pct", "Packet loss", " %"), ("availability_pct", "Network availability", " %"),
                ("handover_count", "Handover count", ""), ("avg_interruption_ms", "Avg handover interruption", " ms"),
                ("buffered_packets", "Buffered packets", ""), ("recovered_packets", "Recovered after outage", ""),
                ("avg_recovery_time_s", "Avg recovery time", " s"), ("goodput_kbps", "Application goodput", " kbps")]
        for i in range(0, len(grid), 3):
            cols = st.columns(3)
            for col, (k, t, u) in zip(cols, grid[i:i + 3]):
                col.plotly_chart(charts.comparison_bars(results, k, t, u), width="stretch", key=f"cmp_{k}")
        st.plotly_chart(charts.comparison_latency(results), width="stretch", key="cmp_lat")
        st.plotly_chart(charts.comparison_network_timeline(results), width="stretch", key="cmp_tl")
        with st.expander("Handover & outage logs per configuration"):
            for r in results:
                st.markdown(f"**{r['label']}** — {len(r['handovers'])} handovers, {len(r['outages'])} outages, "
                            f"computed in {r['compute_time_s']}s")
                if r["handovers"]:
                    st.dataframe(pd.DataFrame(r["handovers"]), hide_index=True, width="stretch", height=180)
                if r["outages"]:
                    st.dataframe(pd.DataFrame(r["outages"]), hide_index=True, width="stretch")

with tab_live:
    a = api.get("/api/analytics")
    if a:
        lm = a["live_metrics"]
        st.markdown(f"Metrics of the **live run `{a['run_id']}`** so far (configuration: mode "
                    f"**{cfg['mode']}**, buffering **{cfg['buffering_enabled']}**). Refresh the page to update.")
        st.dataframe(pd.DataFrame({"value": [lm.get(k) for k, _ in METRIC_ROWS]},
                                  index=[lbl for _, lbl in METRIC_ROWS]), width="stretch", height=640)
        if a["handovers"]:
            ho = pd.DataFrame(a["handovers"])
            st.markdown("##### Handover interruption per event")
            import plotly.express as px
            fig = px.bar(ho, x="ho_id", y="interruption_ms", color="reason",
                         hover_data=["from_bs", "to_bs", "from_type", "to_type"])
            st.plotly_chart(charts._layout(fig, 280), width="stretch")
        pk = api.get("/api/gateway/packets", limit=2000)
        if pk:
            st.plotly_chart(charts.latency_chart(pk, height=280, title="Live run — all packets"),
                            width="stretch")

with tab_hist:
    exps = api.get("/api/analytics/experiments", limit=300) or []
    if not exps:
        st.caption("No experiments saved yet.")
    else:
        df = pd.DataFrame(exps)
        ids = list(dict.fromkeys(df["experiment_id"]))
        sel = st.selectbox("Experiment", ids, format_func=lambda i: f"{i} — {df[df.experiment_id == i].iloc[0]['name']} "
                                                                     f"({df[df.experiment_id == i].iloc[0]['created_at'][:19]})")
        sub = df[df["experiment_id"] == sel]
        st.json(sub.iloc[0]["params"], expanded=False)
        results = [{"configuration": r["configuration"], "label": r["label"],
                    "metrics": {k: r[k] for k in df.columns}} for _, r in sub.iterrows()]
        results.sort(key=lambda r: r["configuration"])
        cols = st.columns(3)
        for col, (k, t, u) in zip(cols * 2, [("pdr_pct", "PDR", " %"), ("avg_realtime_latency_ms", "Real-time latency", " ms"),
                                             ("availability_pct", "Availability", " %"), ("handover_count", "Handovers", ""),
                                             ("buffered_packets", "Buffered", ""), ("avg_throughput_mbps", "Throughput", " Mbps")]):
            col.plotly_chart(charts.comparison_bars(results, k, t, u, height=230), width="stretch",
                             key=f"hist_{k}")
        st.markdown("##### All saved experiment rows")
        st.dataframe(df.drop(columns=["params"]), hide_index=True, width="stretch")
        st.download_button("Download CSV", df.drop(columns=["params"]).to_csv(index=False), "experiments.csv", "text/csv")

with tab_assume:
    st.markdown("""
#### How metrics are computed
| Metric | Definition (from the packet log / event log) |
|---|---|
| End-to-end latency | `deliver_time − generation_time` of each delivered packet: BLE + gateway + buffering wait + radio access + core + backhaul + serialisation × HARQ transmissions + jitter |
| Real-time latency | Same, only packets not held in the gateway buffer |
| Throughput | Shannon-based link capacity of the serving cell, averaged over delivered packets |
| Goodput | delivered packets × packet size ÷ simulated duration |
| PDR / loss | delivered (or lost) ÷ (generated − rejected + still queued) |
| Availability | time a usable link existed (excluding outages and handover interruptions) ÷ simulated time |
| Handover interruption | sampled per handover from type-dependent assumptions (+ penalty after radio-link failure) |
| Recovery time | outage start → time the last buffered packet was flushed |

#### Assumptions
- Simplified log-distance path loss + correlated log-normal shadowing; no fast fading, no inter-cell interference
  modelling (folded into the noise floor), no load / scheduling, no beamforming.
- Interruption, air-interface, core and backhaul delays are fixed assumptions with random jitter (see the network page).
- Configurations A/B have **no** gateway buffering: packets generated while OFFLINE or during a handover are lost.
- Experiments use identical seeds, so differences come from the network configuration (common random numbers).
- Base-station positions, power and radii are illustrative and chosen to create handovers and a 5G coverage gap.

#### Limitations
- Not a 3GPP-compliant system-level simulator (e.g. no 38.901 channel model, no RRC state machine, no measurement gaps).
- No real radio hardware, no real 5G connectivity and no real patient data.
- The synthetic vital signs and demonstration alerts are not clinically validated.
""")
