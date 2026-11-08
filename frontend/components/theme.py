"""Dark-navy healthcare-tech theme + reusable HTML widgets."""
from __future__ import annotations

import html
from typing import Optional

import streamlit as st

COLORS = {
    "bg": "#07111f", "card": "#0f1d33", "card2": "#13253f", "border": "#1e3a5f",
    "text": "#e2e8f0", "muted": "#8aa0bd", "cyan": "#22d3ee", "blue": "#3b82f6",
    "green": "#10b981", "amber": "#f59e0b", "red": "#ef4444", "violet": "#a78bfa",
}
NET_COLORS = {"5G": "#22d3ee", "4G": "#f59e0b", "OFFLINE": "#ef4444", "HANDOVER": "#a78bfa"}
STATUS_COLORS = {"STABLE": "#10b981", "WARNING": "#f59e0b", "CRITICAL": "#ef4444",
                 "RUNNING": "#10b981", "PAUSED": "#f59e0b", "IDLE": "#8aa0bd", "ARRIVED": "#3b82f6",
                 "CONNECTED": "#10b981", "DEGRADED": "#f59e0b", "DISCONNECTED": "#ef4444",
                 "INFO": "#3b82f6"}

_CSS = """
<style>
:root { --cyan:#22d3ee; --blue:#3b82f6; --card:#0f1d33; --border:#1e3a5f; --muted:#8aa0bd; }
.stApp { background: radial-gradient(1200px 600px at 10% -10%, #0e2a4a 0%, #07111f 55%) fixed; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0b1a2e 0%, #07111f 100%);
  border-right: 1px solid var(--border); }
.block-container { padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px; }
h1, h2, h3 { letter-spacing: -0.01em; }
div[data-testid="stMetric"] { background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 10px 14px; }
div[data-testid="stMetricLabel"] p { color: var(--muted) !important; font-size: .78rem; }
.sa-header { display:flex; align-items:center; gap:14px; margin-bottom: .3rem; }
.sa-header .icon { font-size: 2rem; width: 54px; height: 54px; display:flex; align-items:center;
  justify-content:center; border-radius: 14px; background: linear-gradient(135deg,#0e7490,#1d4ed8);
  box-shadow: 0 0 24px rgba(34,211,238,.25); }
.sa-header h1 { margin: 0; font-size: 1.65rem; line-height: 1.2; }
.sa-header p { margin: 2px 0 0; color: var(--muted); font-size: .9rem; }
.sa-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 12px 16px; height: 100%; position: relative; overflow: hidden; }
.sa-card::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background: var(--accent, #22d3ee); }
.sa-card .lbl { color: var(--muted); font-size: .74rem; text-transform: uppercase; letter-spacing: .06em; }
.sa-card .val { font-size: clamp(.95rem, 1.45vw, 1.55rem); font-weight: 700; color: #f1f5f9; line-height: 1.25; margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sa-card .val small { font-size: .85rem; color: var(--muted); font-weight: 500; margin-left: 3px; }
.sa-card .sub { color: var(--muted); font-size: .76rem; margin-top: 2px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.sa-badge { display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .75rem; font-weight: 600;
  border: 1px solid currentColor; background: rgba(255,255,255,.03); }
.sa-banner { border-radius: 12px; padding: 10px 16px; margin: 6px 0 10px; font-weight: 600;
  border: 1px solid; display:flex; align-items:center; gap:10px; }
.sa-note { color: var(--muted); font-size: .78rem; border-left: 3px solid #f59e0b; padding: 4px 10px;
  background: rgba(245,158,11,.06); border-radius: 0 8px 8px 0; margin: 4px 0 12px; }
.sa-pipe { display:flex; align-items:stretch; gap:6px; flex-wrap: wrap; margin: 4px 0 8px; }
.sa-pipe .node { flex:1; min-width: 110px; background: var(--card); border:1px solid var(--border);
  border-radius: 10px; padding: 8px 10px; text-align:center; }
.sa-pipe .node .t { font-size:.72rem; color: var(--muted); text-transform: uppercase; letter-spacing:.05em; }
.sa-pipe .node .s { font-size:.86rem; font-weight:700; margin-top:2px; }
.sa-pipe .arrow { align-self:center; color: var(--muted); font-size: 1.1rem; }
.sa-alert { border-radius: 10px; padding: 7px 12px; margin-bottom: 6px; font-size: .84rem;
  border-left: 4px solid; background: rgba(255,255,255,.03); }
.sa-alert .ts { color: var(--muted); font-size: .72rem; }
.sa-live { display:inline-flex; align-items:center; gap:6px; font-size:.75rem; color: var(--muted); }
.sa-live .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.sa-chat { border-radius: 12px; padding: 8px 12px; margin: 6px 0; max-width: 85%; font-size: .88rem; }
.sa-chat.h { background: #12345a; margin-right: auto; border: 1px solid #1f4f86; }
.sa-chat.a { background: #0f3b3a; margin-left: auto; border: 1px solid #136160; }
.sa-chat .meta { color: var(--muted); font-size: .7rem; margin-top: 3px; }
@keyframes pulse { 0% { opacity: 1 } 50% { opacity: .35 } 100% { opacity: 1 } }
.pulse { animation: pulse 1.4s infinite; }
</style>
"""


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "", icon: str = "🚑") -> None:
    st.markdown(
        f'<div class="sa-header"><div class="icon">{icon}</div><div><h1>{html.escape(title)}</h1>'
        f'<p>{html.escape(subtitle)}</p></div></div>', unsafe_allow_html=True)


def card(label: str, value, unit: str = "", sub: str = "", accent: Optional[str] = None) -> str:
    v = "—" if value is None else html.escape(str(value))
    u = f"<small>{html.escape(unit)}</small>" if unit and value is not None else ""
    s = f'<div class="sub">{html.escape(sub)}</div>' if sub else '<div class="sub">&nbsp;</div>'
    return (f'<div class="sa-card" style="--accent:{accent or COLORS["cyan"]}">'
            f'<div class="lbl">{html.escape(label)}</div><div class="val">{v}{u}</div>{s}</div>')


def cards_row(items: list) -> None:
    cols = st.columns(len(items))
    for col, it in zip(cols, items):
        col.markdown(card(**it), unsafe_allow_html=True)


def badge(text: str, color: Optional[str] = None) -> str:
    c = color or STATUS_COLORS.get(text, NET_COLORS.get(text, COLORS["cyan"]))
    return f'<span class="sa-badge" style="color:{c}">{html.escape(str(text))}</span>'


def banner(text: str, color: str, icon: str = "", pulse: bool = False) -> None:
    st.markdown(f'<div class="sa-banner {"pulse" if pulse else ""}" style="color:{color};border-color:{color};'
                f'background:{color}14">{icon} {html.escape(text)}</div>', unsafe_allow_html=True)


def synthetic_note(text: Optional[str] = None) -> None:
    st.markdown('<div class="sa-note">⚠️ ' + html.escape(
        text or "All data shown is SYNTHETIC, generated by a software simulation. Vital signs are not real "
                "medical measurements and alerts are demonstration alerts, not clinical diagnoses. "
                "Network figures come from a simplified model, not real-world 5G measurements.")
                + '</div>', unsafe_allow_html=True)


def live_indicator(source: str, snap: Optional[dict]) -> None:
    color = {"websocket": COLORS["green"], "rest": COLORS["amber"]}.get(source, COLORS["red"])
    label = {"websocket": "Live · WebSocket", "rest": "Live · REST fallback"}.get(source, "Backend offline")
    extra = ""
    if snap:
        extra = f" · sim t = {snap['sim_elapsed_s']:.0f}s · {snap['status']}"
    st.markdown(f'<span class="sa-live"><span class="dot pulse" style="background:{color}"></span>'
                f'{label}{html.escape(extra)}</span>', unsafe_allow_html=True)


def alert_html(a: dict) -> str:
    c = STATUS_COLORS.get(a["severity"], COLORS["blue"])
    icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(a["severity"], "•")
    return (f'<div class="sa-alert" style="border-color:{c}">{icon} <b style="color:{c}">{a["severity"]}</b> '
            f'· {html.escape(a["category"])} — {html.escape(a["message"])}'
            f'<div class="ts">{a["timestamp"][11:19]} UTC · sim t={a["sim_time_s"]:.0f}s · {a["alert_id"]}</div></div>')


def offline_message() -> None:
    from utils.api import BACKEND_URL
    st.error(f"Cannot reach the FastAPI backend at **{BACKEND_URL}**.\n\n"
             "Start it from the project root with:\n\n```\nuvicorn backend.main:app --reload --port 8000\n```")
