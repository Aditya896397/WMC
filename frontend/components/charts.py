"""Plotly figure builders (dark theme)."""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .theme import COLORS, NET_COLORS

BS_COLORS = {"BS1": "#22d3ee", "BS2": "#3b82f6", "BS3": "#f59e0b", "BS4": "#a78bfa"}
CONFIG_COLORS = {"A_5G_ONLY": "#22d3ee", "B_4G_ONLY": "#f59e0b", "C_HYBRID": "#10b981"}
SHORT_LABELS = {"A_5G_ONLY": "A · 5G-only", "B_4G_ONLY": "B · 4G-only", "C_HYBRID": "C · 5G+4G+buffer"}


def _layout(fig: go.Figure, height: int = 280, title: Optional[str] = None, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=36 if title else 10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,29,51,0.55)",
        font=dict(color=COLORS["text"], size=12), title=dict(text=title, font=dict(size=14), x=0.01) if title else None,
        showlegend=legend, legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1,
                                       bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified", uirevision="keep",
    )
    fig.update_xaxes(gridcolor="#1e3a5f", zerolinecolor="#1e3a5f")
    fig.update_yaxes(gridcolor="#1e3a5f", zerolinecolor="#1e3a5f")
    return fig


def vitals_line(history: List[dict], field: str, color: str, unit: str,
                thresholds: Optional[Dict[str, float]] = None, height: int = 220, title: Optional[str] = None):
    df = pd.DataFrame(history)
    fig = go.Figure()
    if not df.empty:
        fig.add_trace(go.Scatter(x=df["sim_time_s"], y=df[field], mode="lines", name=field,
                                 line=dict(color=color, width=2.2), fill="tozeroy",
                                 fillcolor=color + "18", hovertemplate=f"%{{y:.1f}} {unit}<extra></extra>"))
        lo, hi = df[field].min(), df[field].max()
        pad = max(2.0, (hi - lo) * 0.25)
        fig.update_yaxes(range=[lo - pad, hi + pad])
    for name, val in (thresholds or {}).items():
        fig.add_hline(y=val, line=dict(color=COLORS["red"] if "crit" in name else COLORS["amber"], dash="dot", width=1),
                      annotation_text=name, annotation_font_color=COLORS["muted"], annotation_position="top left")
    fig.update_xaxes(title_text="simulated time (s)")
    return _layout(fig, height, title, legend=False)


def vitals_overview(history: List[dict], height: int = 300):
    df = pd.DataFrame(history)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=("Heart rate (BPM)", "SpO₂ (%)", "Temperature (°C)"))
    if not df.empty:
        for i, (f, c) in enumerate([("heart_rate", "#ef4444"), ("spo2", "#22d3ee"), ("temperature", "#f59e0b")], 1):
            fig.add_trace(go.Scatter(x=df["sim_time_s"], y=df[f], mode="lines", line=dict(color=c, width=2),
                                     name=f), row=i, col=1)
    fig.update_annotations(font_size=11, font_color=COLORS["muted"])
    return _layout(fig, height, legend=False)


def ecg_chart(ecg: dict, height: int = 220, hr: Optional[float] = None):
    fig = go.Figure(go.Scatter(x=ecg.get("t", []), y=ecg.get("v", []), mode="lines",
                               line=dict(color="#10b981", width=1.8), hoverinfo="skip"))
    fig.update_xaxes(title_text="seconds (simulated)", dtick=0.2, showticklabels=True,
                     gridcolor="rgba(16,185,129,0.12)")
    fig.update_yaxes(title_text="mV", range=[-0.5, 1.3], dtick=0.5, gridcolor="rgba(16,185,129,0.12)")
    fig = _layout(fig, height, f"Synthetic ECG (Lead II-like){f' · {hr:.0f} BPM' if hr else ''}", legend=False)
    fig.update_layout(plot_bgcolor="#03140f", hovermode=False)
    return fig


def signal_chart(signal_history: List[dict], base_stations: List[dict], min_5g: float, min_4g: float,
                 height: int = 320):
    df = pd.DataFrame(signal_history)
    fig = go.Figure()
    if not df.empty:
        for bs in base_stations:
            bid = bs["id"]
            if bid not in df:
                continue
            fig.add_trace(go.Scatter(x=df["t"], y=df[bid], mode="lines", name=f"{bid} ({bs['network_type']})",
                                     line=dict(color=BS_COLORS.get(bid, "#94a3b8"), width=2,
                                               dash="solid" if bs["network_type"] == "5G" else "dash")))
        serving_vals = [row.get(row["serving"]) if row["serving"] != "OFFLINE" else None for row in signal_history]
        fig.add_trace(go.Scatter(x=df["t"], y=serving_vals, mode="markers", name="Serving cell",
                                 marker=dict(color="#ffffff", size=4, symbol="circle")))
    fig.add_hline(y=min_5g, line=dict(color=COLORS["cyan"], dash="dot", width=1), annotation_text="5G min",
                  annotation_font_color=COLORS["muted"])
    fig.add_hline(y=min_4g, line=dict(color=COLORS["amber"], dash="dot", width=1), annotation_text="4G min",
                  annotation_position="bottom left", annotation_font_color=COLORS["muted"])
    fig.update_yaxes(title_text="signal strength (dBm)", range=[-135, -55])
    fig.update_xaxes(title_text="simulated time (s)")
    return _layout(fig, height, "Received signal strength per base station")


def latency_chart(packets: List[dict], height: int = 260, title: str = "End-to-end packet latency"):
    df = pd.DataFrame(packets)
    fig = go.Figure()
    if not df.empty and "latency_ms" in df:
        d = df[df["status"] == "DELIVERED"]
        net_col = "tx_network_type" if "tx_network_type" in d else "network_type"
        for net in ("5G", "4G"):
            sub = d[d[net_col] == net]
            if not sub.empty:
                fig.add_trace(go.Scatter(x=sub["sim_time_s"], y=sub["latency_ms"], mode="markers", name=net,
                                         marker=dict(color=NET_COLORS[net], size=6,
                                                     symbol=["diamond" if b else "circle" for b in sub["buffered"]])))
        lost = df[df["status"].isin(["LOST", "DROPPED_BUFFER_FULL"])]
        if not lost.empty:
            fig.add_trace(go.Scatter(x=lost["sim_time_s"], y=[1] * len(lost), mode="markers", name="lost (plotted at 1 ms)",
                                     marker=dict(color=COLORS["red"], size=8, symbol="x")))
    fig.update_yaxes(title_text="latency (ms)", type="log")
    fig.update_xaxes(title_text="simulated time (s)")
    return _layout(fig, height, title)


def gauge(value: Optional[float], title: str, rng=(-130, -60), unit: str = "dBm", height: int = 200):
    v = value if value is not None else rng[0]
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v, number=dict(suffix=f" {unit}", font=dict(size=26)),
        title=dict(text=title, font=dict(size=13, color=COLORS["muted"])),
        gauge=dict(axis=dict(range=list(rng), tickcolor=COLORS["muted"]), bar=dict(color=COLORS["cyan"]),
                   bgcolor="rgba(0,0,0,0)", borderwidth=0,
                   steps=[dict(range=[rng[0], rng[0] + (rng[1] - rng[0]) * .35], color="rgba(239,68,68,.25)"),
                          dict(range=[rng[0] + (rng[1] - rng[0]) * .35, rng[0] + (rng[1] - rng[0]) * .65],
                               color="rgba(245,158,11,.22)"),
                          dict(range=[rng[0] + (rng[1] - rng[0]) * .65, rng[1]], color="rgba(16,185,129,.22)")])))
    fig = _layout(fig, height, legend=False)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=10))
    if value is None:
        fig.update_traces(number=dict(font=dict(size=1, color="rgba(0,0,0,0)")))
        fig.add_annotation(text="NO SIGNAL", x=0.5, y=0.15, showarrow=False, font=dict(size=22, color=COLORS["red"]))
    return fig


def network_timeline(signal_history: List[dict], height: int = 120):
    df = pd.DataFrame(signal_history)
    fig = go.Figure()
    if not df.empty:
        w = float(df["t"].diff().median()) if len(df) > 1 else 1.0
        w = w if w > 0 else 1.0
        for net in ("5G", "4G", "OFFLINE"):
            sub = df[df["network_type"] == net]
            fig.add_trace(go.Bar(x=sub["t"], y=[1] * len(sub), name=net, marker_color=NET_COLORS[net],
                                 marker_line_width=0, hovertext=sub["serving"], width=w * 1.02))
    fig.update_layout(barmode="stack", bargap=0)
    fig.update_yaxes(visible=False)
    fig.update_xaxes(title_text="simulated time (s)")
    return _layout(fig, height, "Serving network over time")


def comparison_bars(results: List[dict], metric: str, title: str, unit: str = "", height: int = 260):
    labels = [SHORT_LABELS.get(r["configuration"], r["label"]) for r in results]
    vals = [r["metrics"].get(metric) for r in results]
    colors = [CONFIG_COLORS.get(r["configuration"], COLORS["blue"]) for r in results]
    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=colors,
                           text=[("—" if v is None else f"{v:,.2f}{unit}") for v in vals], textposition="outside"))
    fig.update_yaxes(title_text=unit.strip() or None)
    top = max([v for v in vals if v is not None] or [1])
    fig.update_yaxes(range=[0, top * 1.25 if top > 0 else 1])
    fig.update_xaxes(tickangle=0)
    fig = _layout(fig, height, title, legend=False)
    fig.update_layout(hovermode="closest")
    return fig


def comparison_latency(results: List[dict], height: int = 300):
    fig = go.Figure()
    for r in results:
        df = pd.DataFrame(r["latency_series"])
        if df.empty:
            continue
        d = df[df["status"] == "DELIVERED"]
        fig.add_trace(go.Scatter(x=d["t"], y=d["latency_ms"], mode="markers", name=r["label"],
                                 marker=dict(size=4, color=CONFIG_COLORS.get(r["configuration"]))))
    fig.update_yaxes(title_text="latency (ms, log)", type="log")
    fig.update_xaxes(title_text="simulated time (s)")
    return _layout(fig, height, "Per-packet end-to-end latency (delivered packets)")


def comparison_network_timeline(results: List[dict], height: int = 220):
    fig = go.Figure()
    for i, r in enumerate(results):
        df = pd.DataFrame(r["network_timeline"])
        if df.empty:
            continue
        for net in ("5G", "4G", "OFFLINE"):
            sub = df[df["network_type"] == net]
            fig.add_trace(go.Scatter(x=sub["t"], y=[r["label"]] * len(sub), mode="markers", name=net,
                                     marker=dict(color=NET_COLORS[net], size=7, symbol="square"),
                                     showlegend=(i == 0)))
    fig.update_xaxes(title_text="simulated time (s)")
    return _layout(fig, height, "Serving network along the route (per configuration)")
