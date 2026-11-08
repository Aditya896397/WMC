"""Ambulance movement + GPS simulation along a road route.

Routes come from the public OSRM routing API when reachable; otherwise a
predefined waypoint route (approximate, hand-digitised) is used.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from bisect import bisect_right
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

from .geo import bearing_deg, haversine_m

log = logging.getLogger(__name__)

OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")

LatLon = Tuple[float, float]

ROUTE_PRESETS: Dict[str, dict] = {
    "saidapet_ggh": {
        "label": "Saidapet → Govt. General Hospital (Park Town), Chennai",
        "start": (13.0213, 80.2231),
        "start_name": "Saidapet (pickup point)",
        "dest": (13.0810, 80.2775),
        "hospital_name": "Govt. General Hospital (demo destination)",
        # Approximate road path (digitised from an OSRM route), used when OSRM is unavailable.
        "fallback": [
            (13.0213, 80.2231), (13.0245, 80.2286), (13.0292, 80.2308), (13.0354, 80.2304),
            (13.0415, 80.2322), (13.0474, 80.2332), (13.0462, 80.2395), (13.0477, 80.2448),
            (13.0516, 80.2499), (13.0554, 80.2550), (13.0596, 80.2598), (13.0636, 80.2648),
            (13.0680, 80.2692), (13.0711, 80.2741), (13.0757, 80.2785), (13.0801, 80.2810),
            (13.0810, 80.2775),
        ],
    },
    "tnagar_ggh": {
        "label": "T. Nagar → Govt. General Hospital (Park Town), Chennai",
        "start": (13.0418, 80.2341),
        "start_name": "T. Nagar (pickup point)",
        "dest": (13.0810, 80.2775),
        "hospital_name": "Govt. General Hospital (demo destination)",
        "fallback": [
            (13.0418, 80.2341), (13.0448, 80.2397), (13.0480, 80.2453), (13.0519, 80.2504),
            (13.0557, 80.2555), (13.0599, 80.2603), (13.0640, 80.2652), (13.0683, 80.2696),
            (13.0716, 80.2743), (13.0761, 80.2788), (13.0806, 80.2807), (13.0810, 80.2775),
        ],
    },
}


def fetch_osrm_route(start: LatLon, dest: LatLon, timeout: float = 6.0) -> Optional[List[LatLon]]:
    url = (
        f"{OSRM_URL}/route/v1/driving/{start[1]},{start[0]};{dest[1]},{dest[0]}"
        "?overview=full&geometries=geojson"
    )
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "smart-ambulance-sim/1.0"})
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        coords = data["routes"][0]["geometry"]["coordinates"]
        pts = [(float(lat), float(lon)) for lon, lat in coords]
        return pts if len(pts) >= 2 else None
    except Exception as exc:  # network errors, JSON errors, timeouts
        log.warning("OSRM route request failed (%s); using fallback route", exc)
        return None


class RouteProvider:
    """Caches routes per preset so OSRM is called at most once per preset."""

    def __init__(self, use_osrm: Optional[bool] = None):
        if use_osrm is None:
            use_osrm = os.getenv("USE_OSRM", "true").lower() in ("1", "true", "yes")
        self.use_osrm = use_osrm
        self._cache: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, preset: str) -> dict:
        if preset not in ROUTE_PRESETS:
            raise ValueError(f"Unknown route preset '{preset}'. Options: {list(ROUTE_PRESETS)}")
        with self._lock:
            if preset in self._cache:
                return self._cache[preset]
            p = ROUTE_PRESETS[preset]
            points = fetch_osrm_route(p["start"], p["dest"]) if self.use_osrm else None
            source = "OSRM"
            if not points:
                points, source = list(p["fallback"]), "FALLBACK (predefined waypoints)"
            route = {
                "preset": preset,
                "label": p["label"],
                "start_name": p["start_name"],
                "hospital_name": p["hospital_name"],
                "hospital": {"lat": p["dest"][0], "lon": p["dest"][1]},
                "points": points,
                "source": source,
            }
            self._cache[preset] = route
            return route


class AmbulanceSimulator:
    def __init__(self, route: dict, rng: np.random.Generator, speed_kmh: float, ambulance_id: str = "AMB001"):
        self.ambulance_id = ambulance_id
        self.rng = rng
        self.route = route
        self.points: List[LatLon] = route["points"]
        self.cum: List[float] = [0.0]
        for a, b in zip(self.points[:-1], self.points[1:]):
            self.cum.append(self.cum[-1] + haversine_m(a[0], a[1], b[0], b[1]))
        self.total_m = self.cum[-1]
        self.s = 0.0                       # distance travelled along route (m)
        self.speed_setpoint_kmh = speed_kmh
        self.traffic = 0.9                 # traffic factor (OU process in [0.5, 1])
        self.current_speed_kmh = 0.0
        self.moving = False
        self.arrived = False

    # ------------------------------------------------------------------
    def set_speed(self, kmh: float) -> None:
        self.speed_setpoint_kmh = kmh

    def advance(self, dt: float) -> None:
        if not self.moving or self.arrived:
            self.current_speed_kmh = 0.0
            return
        self.traffic += 0.1 * (0.9 - self.traffic) * dt + 0.05 * math.sqrt(dt) * float(self.rng.standard_normal())
        self.traffic = float(np.clip(self.traffic, 0.5, 1.0))
        self.current_speed_kmh = self.speed_setpoint_kmh * self.traffic
        self.s += self.current_speed_kmh / 3.6 * dt
        if self.s >= self.total_m:
            self.s = self.total_m
            self.arrived = True
            self.moving = False
            self.current_speed_kmh = 0.0

    def position(self) -> LatLon:
        if self.s <= 0:
            return self.points[0]
        if self.s >= self.total_m:
            return self.points[-1]
        i = bisect_right(self.cum, self.s) - 1
        i = min(max(i, 0), len(self.points) - 2)
        seg = self.cum[i + 1] - self.cum[i]
        f = 0.0 if seg <= 0 else (self.s - self.cum[i]) / seg
        a, b = self.points[i], self.points[i + 1]
        return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))

    def heading(self) -> float:
        i = min(max(bisect_right(self.cum, self.s) - 1, 0), len(self.points) - 2)
        a, b = self.points[i], self.points[i + 1]
        return bearing_deg(a[0], a[1], b[0], b[1])

    def snap_to(self, lat: float, lon: float) -> float:
        """Move the ambulance to the route point nearest to (lat, lon)."""
        best_i, best_d = 0, float("inf")
        for i, (plat, plon) in enumerate(self.points):
            d = haversine_m(lat, lon, plat, plon)
            if d < best_d:
                best_i, best_d = i, d
        self.s = self.cum[best_i]
        self.arrived = self.s >= self.total_m
        return best_d

    @property
    def remaining_m(self) -> float:
        return max(0.0, self.total_m - self.s)

    def eta_min(self) -> Optional[float]:
        if self.arrived:
            return 0.0
        v = self.current_speed_kmh if self.current_speed_kmh > 1 else self.speed_setpoint_kmh * 0.9
        return (self.remaining_m / 1000.0) / v * 60.0 if v > 0 else None
