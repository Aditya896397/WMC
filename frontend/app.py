"""Streamlit entry point — 5G-Based Smart Ambulance Communication System (simulation).

Run from the project root:  streamlit run frontend/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parent
for _p in (FRONTEND_DIR, FRONTEND_DIR.parent):  # frontend/ for pages, project root for the embedded backend
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from components.theme import COLORS, STATUS_COLORS, apply_theme, badge  # noqa: E402
from utils import api  # noqa: E402
from utils.embedded import ensure_backend  # noqa: E402
from utils.live import get_feed, get_state  # noqa: E402

st.set_page_config(page_title="5G Smart Ambulance", page_icon="🚑", layout="wide",
                   initial_sidebar_state="expanded")
apply_theme()
BACKEND_MODE = ensure_backend()  # starts FastAPI in-process if none is running (Streamlit Cloud)
get_feed()  # start the shared WebSocket client thread

P = FRONTEND_DIR / "views"  # not "pages/": avoids Streamlit legacy auto-discovery bypassing st.navigation
pages = {
    "Monitoring": [
        st.Page(P / "1_Overview.py", title="Overview Dashboard", icon="🏠", default=True),
        st.Page(P / "2_Ambulance_Tracking.py", title="Ambulance Tracking", icon="🗺️"),
        st.Page(P / "3_Patient_Monitoring.py", title="Patient Monitoring", icon="❤️"),
    ],
    "Communication": [
        st.Page(P / "4_BLE_Communication.py", title="BLE Communication", icon="📶"),
        st.Page(P / "5_Network_Simulator.py", title="5G/4G Network Simulator", icon="📡"),
        st.Page(P / "9_Mobile_Concepts.py", title="Mobile Comm Concepts", icon="📚"),
        st.Page(P / "6_Hospital_Dashboard.py", title="Hospital Monitoring", icon="🏥"),
    ],
    "Analysis & Control": [
        st.Page(P / "7_Performance_Analysis.py", title="Network Performance Analysis", icon="📊"),
        st.Page(P / "8_Simulation_Controls.py", title="Simulation Controls", icon="🎛️"),
    ],
}
nav = st.navigation(pages)

@st.fragment(run_every=2)
def sidebar_status() -> None:
    snap, source = get_state()
    if snap:
        net = snap["network"]["network_type"]
        st.markdown(
            f"**Simulation** {badge(snap['status'])} &nbsp; **Network** {badge(net)}<br>"
            f"<span style='color:#8aa0bd;font-size:.78rem'>Run {snap['run_id']}<br>"
            f"Sim time {snap['sim_elapsed_s']:.0f}s · ×{snap['config']['time_scale']:g} speed<br>"
            f"Data link: {'WebSocket ✅' if source == 'websocket' else 'REST fallback ⚠️'}</span>",
            unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if snap["status"] == "RUNNING":
            if c1.button("⏸ Pause", width="stretch", key="sb_pause"):
                api.action("POST", "/api/simulation/pause")
                st.rerun()
        else:
            label = "⏯ Resume" if snap["status"] == "PAUSED" else "▶ Start"
            path = "/api/simulation/resume" if snap["status"] == "PAUSED" else "/api/simulation/start"
            if c1.button(label, width="stretch", type="primary", key="sb_start"):
                api.action("POST", path)
                st.rerun()
        if c2.button("⟲ Reset", width="stretch", key="sb_reset"):
            api.action("POST", "/api/simulation/reset")
            st.rerun()
    else:
        st.error("Backend offline")
        st.caption(f"Expected at {api.BACKEND_URL}")


with st.sidebar:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin:-8px 0 6px">'
        '<div style="font-size:30px">🚑</div><div><div style="font-weight:800;font-size:1.05rem">'
        'Smart Ambulance</div><div style="color:#8aa0bd;font-size:.75rem">5G · BLE · Hospital link — '
        'simulation</div></div></div>', unsafe_allow_html=True)
    sidebar_status()
    st.divider()
    if BACKEND_MODE == "embedded":
        st.caption("Backend: embedded in this Streamlit process")
    else:
        st.caption(f"API docs: [{api.BACKEND_URL}/docs]({api.BACKEND_URL}/docs)")
    st.caption("All data is synthetic. Not a medical device. Not real 5G measurements.")

nav.run()
