"""Basic mobile-communication concepts, each shown with its formula and a LIVE value from the simulation."""
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.charts import BS_COLORS, _layout
from components.layout import fmt, snapshot
from components.theme import COLORS, NET_COLORS, cards_row, header, synthetic_note

header("Mobile Communication Concepts", "Key wireless & mobile concepts explained with live values from the "
                                        "running simulation", "📚")
synthetic_note("Values come from the simplified simulation model (educational), not from real network measurements.")

C = 3e8


def fspl_1m(f_ghz: float) -> float:
    return 20 * math.log10(4 * math.pi * f_ghz * 1e9 / C)


def ping_pongs(hos: list, window_s: float = 10.0) -> int:
    """A → B → A within `window_s` seconds counts as one ping-pong handover."""
    return sum(1 for a, b in zip(hos, hos[1:])
               if b["to_bs"] == a["from_bs"] and b["time"] - a["time"] <= window_s)


@st.fragment(run_every=1)
def live():
    snap = snapshot()
    if snap is None:
        return
    cfg, net, amb = snap["config"], snap["network"], snap["ambulance"]
    bss = {b["id"]: b for b in net["base_stations"]}
    srv = bss.get(net["serving_bs"])

    # ------------------------------------------------------------------ 1. link budget
    st.markdown("### 1 · Link budget of the serving cell")
    if srv:
        f = srv["frequency_ghz"]
        v = amb["speed_kmh"] / 3.6
        doppler = v / C * f * 1e9
        pl = srv["tx_power_dbm"] + cfg["antenna_gain_db"] - srv["rsrp_dbm"]
        if srv["network_type"] == "5G":
            pl -= cfg["five_g_degradation_db"]
        shannon = srv["bandwidth_mhz"] * math.log2(1 + 10 ** (srv["sinr_db"] / 10))
        cards_row([
            dict(label="Serving cell", value=f"{srv['id']} · {srv['network_type']}",
                 sub=f"{f} GHz · {srv['bandwidth_mhz']:.0f} MHz", accent=NET_COLORS[srv["network_type"]]),
            dict(label="Distance to cell", value=fmt(srv["distance_m"], 0), unit="m",
                 sub=f"coverage radius {srv['radius_m']:.0f} m", accent=COLORS["blue"]),
            dict(label="Path loss", value=fmt(pl), unit="dB", sub="incl. shadowing", accent=COLORS["amber"]),
            dict(label="Received signal", value=fmt(srv["rsrp_dbm"]), unit="dBm", sub="RSRP-like", accent=COLORS["cyan"]),
            dict(label="SINR", value=fmt(srv["sinr_db"]), unit="dB", sub=f"noise floor {cfg['noise_floor_dbm']:.0f} dBm",
                 accent=COLORS["green"]),
            dict(label="Doppler shift", value=fmt(doppler, 0), unit="Hz", sub=f"at {amb['speed_kmh']:.0f} km/h",
                 accent=COLORS["violet"]),
        ])
        with st.expander("Formulas used", expanded=False):
            st.latex(r"P_r\,[\text{dBm}] = P_t + G - PL(d), \qquad PL(d) = 20\log_{10}\frac{4\pi f}{c} + 10\,n\log_{10}d")
            st.latex(r"\text{SINR} = P_r - N_{floor}, \qquad C_{Shannon} = B\log_2(1+\text{SINR})"
                     rf" = {shannon:,.0f}\ \text{{Mbit/s (ideal)}}")
            st.latex(r"f_D = \frac{v}{c}\,f_c = \frac{%.1f\ \text{m/s}}{3\times10^8}\times %.1f\ \text{GHz} = %.0f\ \text{Hz}"
                     % (v, f, doppler))
            st.caption("Doppler shift grows with speed and carrier frequency, so a fast ambulance on 3.5 GHz 5G sees "
                       "roughly twice the shift it would on 1.8 GHz LTE.")
    else:
        st.warning("OFFLINE — no serving cell, so there is no link budget to show.")

    # ------------------------------------------------------------------ 2. signal vs distance
    st.markdown("### 2 · Path loss: signal strength vs distance")
    st.caption("Higher frequency (5G, 3.5 GHz) loses signal faster than 4G (1.8 GHz), so 5G cells are smaller. "
               "Dots show each base station's measured signal at the ambulance's current distance.")
    d = np.linspace(10, 6000, 300)
    fig = go.Figure()
    for typ, f_ghz, n, ptx in (("5G", 3.5, cfg["path_loss_exponent_5g"], 46),
                               ("4G", 1.8, cfg["path_loss_exponent_4g"], 46)):
        s = ptx + cfg["antenna_gain_db"] - (fspl_1m(f_ghz) + 10 * n * np.log10(d))
        fig.add_trace(go.Scatter(x=d, y=s, mode="lines", name=f"{typ} model ({f_ghz} GHz, n={n})",
                                 line=dict(color=NET_COLORS[typ], width=2.5)))
    for b in bss.values():
        fig.add_trace(go.Scatter(x=[b["distance_m"]], y=[b["rsrp_dbm"]], mode="markers+text", name=b["id"],
                                 text=[b["id"] + (" ⭐" if b["is_serving"] else "")], textposition="top center",
                                 marker=dict(size=13, color=BS_COLORS.get(b["id"]), line=dict(color="white", width=1.5))))
    fig.add_hline(y=cfg["min_rsrp_5g_dbm"], line=dict(color=COLORS["cyan"], dash="dot"), annotation_text="5G min usable")
    fig.add_hline(y=cfg["min_rsrp_4g_dbm"], line=dict(color=COLORS["amber"], dash="dot"),
                  annotation_text="4G min usable", annotation_position="bottom right")
    fig.update_xaxes(title_text="distance from base station (m)")
    fig.update_yaxes(title_text="received signal (dBm)", range=[-140, -40])
    fig = _layout(fig, 340)
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, width="stretch", key="mc_pl")

    # ------------------------------------------------------------------ 3. handover decision
    st.markdown("### 3 · Handover decision (A3 event: hysteresis + time-to-trigger)")
    c1, c2 = st.columns([1.3, 1])
    with c1:
        avail = [b for b in bss.values() if b["available"]]
        bonus = cfg["prefer_5g_offset_db"] if cfg["mode"] == "HYBRID" else 0.0
        score = lambda b: b["rsrp_dbm"] + (bonus if b["network_type"] == "5G" else 0.0)  # noqa: E731
        neigh = [b for b in avail if not b["is_serving"]]
        if srv and neigh:
            best = max(neigh, key=score)
            s_srv, s_nb = score(srv), score(best)
            thr = s_srv + cfg["hysteresis_db"]
            met = s_nb > thr
            lo = math.floor((min(s_srv, s_nb, thr) - 10) / 10) * 10   # bars grow up from the axis floor
            fig = go.Figure(go.Bar(x=[f"Serving {srv['id']}", f"Best neighbour {best['id']}"],
                                   y=[s_srv - lo, s_nb - lo], base=lo,
                                   marker_color=[NET_COLORS[srv["network_type"]], NET_COLORS[best["network_type"]]],
                                   text=[f"{s_srv:.1f} dB", f"{s_nb:.1f} dB"], textposition="outside",
                                   hoverinfo="skip"))
            fig.add_hline(y=thr, line=dict(color=COLORS["red"], dash="dash"),
                          annotation_text=f"serving + hysteresis ({cfg['hysteresis_db']:.0f} dB)")
            fig.update_yaxes(title_text="selection score (dB)", range=[lo, max(s_srv, s_nb, thr) + 8])
            st.plotly_chart(_layout(fig, 280, legend=False), width="stretch", key="mc_a3")
            ttt = net["ttt_progress"].get(best["id"], 0.0)
            st.progress(min(1.0, ttt / cfg["time_to_trigger_s"]) if cfg["time_to_trigger_s"] else float(met),
                        text=f"Time-to-trigger {ttt:.1f} / {cfg['time_to_trigger_s']:.1f} s  →  "
                             + ("condition MET, counting…" if met else "condition not met, staying on serving cell"))
        elif srv:
            st.info(f"Only {srv['id']} is available here, so there is no handover candidate.")
        else:
            st.error("OFFLINE — waiting for any cell to become available.")
    with c2:
        st.markdown(
            f"- **Score** = signal + **{bonus:.0f} dB bonus for 5G** (prefer 5G when it is usable)\n"
            f"- **A3 condition:** neighbour score > serving score + **hysteresis**\n"
            f"- It must hold for the **time-to-trigger**, which prevents ping-pong from short signal dips\n"
            f"- If the serving cell drops below its minimum usable level → **immediate handover** "
            f"(radio-link failure) or **fallback to 4G**\n"
            f"- If no cell is usable → **OFFLINE**, and the gateway **buffers** packets until it reconnects")

    # ------------------------------------------------------------------ 4. handover statistics
    st.markdown("### 4 · Handover types & mobility statistics")
    hos = snap["handover_events"]
    horiz = sum(1 for h in hos if h["from_type"] == h["to_type"])
    vert = len(hos) - horiz
    pp = ping_pongs(hos)
    avg_int = np.mean([h["interruption_ms"] for h in hos]) if hos else None
    cards_row([
        dict(label="Total handovers", value=net["handover_count"], accent=COLORS["violet"]),
        dict(label="Horizontal (intra-RAT)", value=horiz, sub="5G↔5G or 4G↔4G", accent=COLORS["cyan"]),
        dict(label="Vertical (inter-RAT)", value=vert, sub="5G↔4G fallback / return", accent=COLORS["amber"]),
        dict(label="Ping-pong handovers", value=pp, sub="A→B→A within 10 s", accent=COLORS["red"]),
        dict(label="Avg interruption", value=fmt(avg_int, 0), unit="ms", sub="hard handover: break-before-make",
             accent=COLORS["blue"]),
    ])
    st.caption("This model uses hard handover (the old link is released before the new one carries data), which is "
               "how 4G and 5G NR hand over in practice. The short gap is the handover interruption time.")

    # ------------------------------------------------------------------ 5. 5G vs 4G
    st.markdown("### 5 · 5G NR vs 4G LTE in this simulation")
    rows = []
    for typ in ("5G", "4G"):
        cells = [b for b in bss.values() if b["network_type"] == typ]
        if not cells:
            continue
        rows.append({
            "Technology": "5G NR" if typ == "5G" else "4G LTE",
            "Cells": ", ".join(b["id"] for b in cells),
            "Carrier frequency (GHz)": cells[0]["frequency_ghz"],
            "Bandwidth (MHz)": cells[0]["bandwidth_mhz"],
            "Coverage radius (m)": ", ".join(f"{b['radius_m']:.0f}" for b in cells),
            "Path-loss exponent n": cfg["path_loss_exponent_5g" if typ == "5G" else "path_loss_exponent_4g"],
            "Time connected (s)": net["time_on_5g_s" if typ == "5G" else "time_on_4g_s"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("5G: wider bandwidth → higher throughput and lower latency, but higher frequency → smaller cells. "
               "4G: lower frequency → large umbrella coverage, so it serves as the fallback layer.")


live()
