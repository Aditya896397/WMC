"""Ambulance movement & GPS tracking on OpenStreetMap."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.charts import _layout
from components.layout import fmt, sim_buttons, snapshot
from components.map_view import render_map
from components.theme import COLORS, cards_row, header, synthetic_note
from utils import api

header("Ambulance Tracking", "Virtual GPS movement along a road route (OSRM, with offline fallback)", "🗺️")
synthetic_note("GPS positions are simulated by moving a virtual ambulance along the route; they are not real "
               "vehicle positions.")

snap0 = snapshot(show_indicator=False, fresh=True)
if snap0 is None:
    st.stop()
sim_buttons(snap0, "trk")

with st.expander("Route & speed settings", expanded=False):
    route0 = api.route(snap0["route_version"]) or {}
    presets = route0.get("presets", {})
    c1, c2 = st.columns([2, 1])
    with c1:
        keys = list(presets) or [snap0["config"]["route_preset"]]
        sel = st.selectbox("Demonstration route (Chennai)", keys, format_func=lambda k: presets.get(k, k),
                           index=keys.index(snap0["config"]["route_preset"]) if snap0["config"]["route_preset"] in keys else 0)
        if st.button("Apply route (resets simulation)", disabled=sel == snap0["config"]["route_preset"]):
            api.action("POST", "/api/route", {"preset": sel})
            st.cache_data.clear()
            st.rerun()
    with c2:
        speed = st.slider("Ambulance speed set-point (km/h)", 5, 120, int(snap0["config"]["ambulance_speed_kmh"]))
        if st.button("Apply speed"):
            api.action("PUT", "/api/simulation/config", {"ambulance_speed_kmh": speed},
                       success=f"Speed set to {speed} km/h")
    st.caption("The actual speed varies around the set-point with a simulated traffic factor (0.5–1.0).")

c_map, c_side = st.columns([2.2, 1])
with c_side:
    follow = st.toggle("Follow ambulance", value=False)
    coverage = st.toggle("Show cell coverage", value=True)


@st.fragment(run_every=2)
def live_map():
    snap = snapshot()
    if snap is None:
        return
    route = api.route(snap["route_version"])
    if route:
        render_map(route, snap, key="trk_map", height=560, show_coverage=coverage, follow=follow,
                   zoom=15 if follow else 13)
        st.caption(f"Route: {snap['route_label']} · source **{route['source']}** · "
                   f"{len(route['points'])} points · © OpenStreetMap contributors")


@st.fragment(run_every=1)
def live_side():
    snap = snapshot(show_indicator=False)
    if snap is None:
        return
    a = snap["ambulance"]
    st.markdown("##### Vehicle telemetry")
    cards_row([dict(label="Speed", value=fmt(a["speed_kmh"]), unit="km/h", sub=f"set-point {a['speed_setpoint_kmh']:.0f}",
                    accent=COLORS["cyan"]),
               dict(label="Heading", value=f"{a['heading_deg']:.0f}°", accent=COLORS["blue"])])
    st.write("")
    cards_row([dict(label="Distance to hospital", value=fmt(a["distance_to_hospital_km"], 2), unit="km",
                    accent=COLORS["green"]),
               dict(label="ETA", value=fmt(a["eta_min"], 1), unit="min", sub="simulated", accent=COLORS["green"])])
    st.write("")
    st.progress(min(1.0, a["progress_pct"] / 100), text=f"Route progress {a['progress_pct']:.1f}% "
                                                         f"({a['distance_travelled_km']:.2f} / {a['route_length_km']:.2f} km)")
    st.markdown(f"**GPS** `{a['lat']:.6f}, {a['lon']:.6f}`  \n**Status** `{snap['status']}` · "
                f"**Network** `{snap['network']['network_type']}` via `{snap['network']['serving_bs'] or '—'}`")
    hist = pd.DataFrame(snap["location_history"])
    if not hist.empty:
        fig = go.Figure(go.Scatter(x=hist["sim_time_s"], y=hist["speed_kmh"], mode="lines",
                                   line=dict(color=COLORS["cyan"], width=2), fill="tozeroy",
                                   fillcolor="rgba(34,211,238,.12)"))
        fig.update_xaxes(title_text="sim time (s)")
        fig.update_yaxes(title_text="km/h")
        st.plotly_chart(_layout(fig, 200, "Speed history", legend=False), width="stretch", key="trk_speed")


with c_map:
    live_map()
with c_side:
    live_side()


@st.fragment(run_every=3)
def gps_log():
    snap = snapshot(show_indicator=False)
    if snap is None:
        return
    hist = pd.DataFrame(snap["location_history"])
    if not hist.empty:
        st.markdown("##### GPS log (latest first)")
        st.dataframe(hist.iloc[::-1].head(40), hide_index=True, width="stretch", height=260)


gps_log()
