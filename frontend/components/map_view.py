"""Folium / OpenStreetMap map of the route, ambulance, hospital and base stations.

The static layer (tiles, route, hospital) is rendered once; the moving
parts (ambulance, travelled path, cell coverage, serving link) are sent
as a dynamic FeatureGroup so the map updates without a full reload.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Optional

import folium
from streamlit_folium import st_folium

from .theme import NET_COLORS

AMBULANCE_ICON = """
<div style="font-size:26px;filter:drop-shadow(0 0 6px #22d3ee);transform:translate(-4px,-6px)">🚑</div>
"""
HOSPITAL_ICON = """
<div style="font-size:26px;filter:drop-shadow(0 0 6px #ef4444);transform:translate(-4px,-8px)">🏥</div>
"""


def _travelled(route: dict, travelled_km: float, current: tuple) -> list:
    cum = route.get("cumulative_m") or []
    pts = route["points"]
    if not cum:
        return [pts[0], current]
    i = bisect_right(cum, travelled_km * 1000.0)
    return [tuple(p) for p in pts[:max(i, 1)]] + [current]


def build_base_map(route: dict, snap: dict, zoom: int = 14) -> folium.Map:
    pts = route["points"]
    mid = pts[len(pts) // 2]
    m = folium.Map(location=mid, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True,
                   attribution_control=True)
    folium.PolyLine(pts, color="#3b82f6", weight=5, opacity=0.55, tooltip="Planned route").add_to(m)
    folium.CircleMarker(pts[0], radius=6, color="#10b981", fill=True, fill_opacity=1,
                        tooltip=route.get("start_name", "Start")).add_to(m)
    h = snap["hospital"]
    folium.Marker([h["lat"], h["lon"]], tooltip=h["name"],
                  icon=folium.DivIcon(html=HOSPITAL_ICON)).add_to(m)
    return m


def dynamic_layer(route: dict, snap: dict, show_coverage: bool = True) -> folium.FeatureGroup:
    fg = folium.FeatureGroup(name="live")
    a = snap["ambulance"]
    pos = (a["lat"], a["lon"])
    net = snap["network"]
    if show_coverage:
        for bs in net["base_stations"]:
            col = NET_COLORS[bs["network_type"]]
            serving = bs["is_serving"]
            folium.Circle([bs["lat"], bs["lon"]], radius=bs["radius_m"], color=col,
                          weight=3 if serving else 1, dash_array=None if bs["enabled"] else "6",
                          fill=True, fill_opacity=0.16 if serving else 0.05,
                          tooltip=f"{bs['id']} · {bs['network_type']} · r={bs['radius_m']:.0f} m").add_to(fg)
            folium.Marker([bs["lat"], bs["lon"]], icon=folium.DivIcon(icon_size=(70, 24), icon_anchor=(14, 12), html=(
                f'<div style="display:inline-block;background:{col if bs["enabled"] else "#475569"};'
                f'color:#07111f;font-weight:800;font-size:11px;border-radius:6px;padding:2px 5px;'
                f'border:2px solid {"#fff" if serving else "#07111f"};white-space:nowrap">📡 {bs["id"]}</div>')),
                tooltip=(f"{bs['id']} ({bs['network_type']}) — {bs['rsrp_dbm']} dBm at "
                         f"{bs['distance_m']:.0f} m{' · SERVING' if serving else ''}")).add_to(fg)
            if serving:
                folium.PolyLine([pos, (bs["lat"], bs["lon"])], color=col, weight=2, dash_array="4 6",
                                opacity=0.9).add_to(fg)
    folium.PolyLine(_travelled(route, a["distance_travelled_km"], pos), color="#22d3ee", weight=6,
                    opacity=0.95, tooltip="Travelled").add_to(fg)
    folium.Marker(pos, icon=folium.DivIcon(html=AMBULANCE_ICON),
                  tooltip=(f"{a['ambulance_id']} · {a['speed_kmh']} km/h · {net['network_type']} via "
                           f"{net['serving_bs'] or '—'}")).add_to(fg)
    return fg


def render_map(route: dict, snap: dict, key: str, height: int = 480, show_coverage: bool = True,
               follow: bool = False, zoom: int = 14) -> None:
    m = build_base_map(route, snap, zoom)
    fg = dynamic_layer(route, snap, show_coverage)
    a = snap["ambulance"]
    st_folium(m, feature_group_to_add=fg, key=key, height=height, use_container_width=True,
              center=(a["lat"], a["lon"]) if follow else None, zoom=zoom if follow else None,
              returned_objects=[])
