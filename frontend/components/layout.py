"""Shared page helpers."""
from __future__ import annotations

from typing import Optional

import streamlit as st

from components.theme import live_indicator, offline_message
from utils.live import get_state


def snapshot(show_indicator: bool = True, fresh: bool = False) -> Optional[dict]:
    snap, source = get_state(fresh=fresh)
    if show_indicator:
        live_indicator(source, snap)
    if snap is None:
        offline_message()
    return snap


def sim_buttons(snap: dict, key: str) -> None:
    """Start / Pause / Resume / Reset buttons wired to the backend."""
    from utils import api

    status = snap["status"] if snap else "IDLE"
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("▶ Start", key=f"{key}_start", width="stretch", type="primary",
                 disabled=status == "RUNNING"):
        api.action("POST", "/api/simulation/start")
        st.rerun()
    if c2.button("⏸ Pause", key=f"{key}_pause", width="stretch", disabled=status != "RUNNING"):
        api.action("POST", "/api/simulation/pause")
        st.rerun()
    if c3.button("⏯ Resume", key=f"{key}_resume", width="stretch", disabled=status != "PAUSED"):
        api.action("POST", "/api/simulation/resume")
        st.rerun()
    if c4.button("⟲ Reset", key=f"{key}_reset", width="stretch"):
        api.action("POST", "/api/simulation/reset")
        st.rerun()


def fmt(v, nd: int = 1, none: str = "—"):
    if v is None:
        return none
    try:
        return f"{v:,.{nd}f}"
    except (TypeError, ValueError):
        return str(v)
