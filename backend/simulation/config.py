"""Simulation configuration (validated with Pydantic).

Every tunable parameter of the simulation lives here so the API, the
Streamlit control panel and the performance experiments all modify the
same, validated configuration object.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

NetworkType = Literal["5G", "4G"]
Mode = Literal["HYBRID", "5G_ONLY", "4G_ONLY"]
Scenario = Literal["A", "B", "C"]


class Thresholds(BaseModel):
    """Demonstration alert thresholds (NOT clinical thresholds)."""

    hr_high: float = Field(120, ge=60, le=220)
    hr_critical: float = Field(140, ge=60, le=250)
    hr_low: float = Field(50, ge=20, le=100)
    spo2_low: float = Field(92, ge=70, le=100)
    spo2_critical: float = Field(88, ge=60, le=100)
    temp_high: float = Field(38.5, ge=36, le=43)
    temp_low: float = Field(35.0, ge=30, le=37)


class BaseStationConfig(BaseModel):
    id: str
    network_type: NetworkType
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=50, le=20000)
    tx_power_dbm: float = Field(ge=10, le=60)
    frequency_ghz: float = Field(gt=0.3, le=60)
    bandwidth_mhz: float = Field(gt=1, le=400)
    enabled: bool = True


# Base stations are positioned around the default Chennai demo route so
# that the ambulance experiences 5G -> 5G handovers, a 5G coverage gap
# served only by 4G LTE (fallback), and a return to 5G near the hospital.
DEFAULT_BASE_STATIONS: List[BaseStationConfig] = [
    BaseStationConfig(id="BS1", network_type="5G", lat=13.0265, lon=80.2290, radius_m=1500,
                      tx_power_dbm=46, frequency_ghz=3.5, bandwidth_mhz=100),
    BaseStationConfig(id="BS2", network_type="5G", lat=13.0470, lon=80.2400, radius_m=1400,
                      tx_power_dbm=46, frequency_ghz=3.5, bandwidth_mhz=100),
    BaseStationConfig(id="BS3", network_type="4G", lat=13.0560, lon=80.2560, radius_m=6000,
                      tx_power_dbm=46, frequency_ghz=1.8, bandwidth_mhz=20),
    BaseStationConfig(id="BS4", network_type="5G", lat=13.0740, lon=80.2760, radius_m=1400,
                      tx_power_dbm=46, frequency_ghz=3.5, bandwidth_mhz=100),
]


class SimulationConfig(BaseModel):
    # ---- timing -------------------------------------------------------
    tick_interval_s: float = Field(1.0, ge=0.2, le=5, description="Real seconds between engine ticks")
    time_scale: float = Field(3.0, ge=0.5, le=30, description="Simulated seconds per real second")
    packet_interval_s: float = Field(1.0, ge=0.2, le=10, description="Gateway packet period (sim s)")
    seed: Optional[int] = Field(42, description="RNG seed (None = non-deterministic)")

    # ---- patient ------------------------------------------------------
    scenario: Scenario = "A"
    thresholds: Thresholds = Field(default_factory=Thresholds)

    # ---- ambulance ----------------------------------------------------
    ambulance_speed_kmh: float = Field(45, ge=5, le=120)
    route_preset: str = "saidapet_ggh"

    # ---- BLE ----------------------------------------------------------
    ble_base_latency_ms: float = Field(8, ge=0, le=500)
    ble_jitter_ms: float = Field(3, ge=0, le=200)
    ble_packet_loss: float = Field(0.02, ge=0, le=0.9, description="Per-attempt BLE loss probability")
    ble_max_retries: int = Field(2, ge=0, le=10)
    ble_connection_interval_ms: float = Field(30, ge=7.5, le=4000)

    # ---- radio propagation (simplified, NOT 3GPP-compliant) ------------
    path_loss_exponent_5g: float = Field(3.8, ge=2, le=6)
    path_loss_exponent_4g: float = Field(3.4, ge=2, le=6)
    shadowing_sigma_db: float = Field(4.0, ge=0, le=12)
    shadowing_corr_m: float = Field(50, ge=1, le=1000)
    antenna_gain_db: float = Field(15, ge=0, le=40)
    noise_floor_dbm: float = Field(-110, ge=-140, le=-80)
    min_rsrp_5g_dbm: float = Field(-105, ge=-140, le=-60)
    min_rsrp_4g_dbm: float = Field(-112, ge=-140, le=-60)

    # ---- mobility management -----------------------------------------
    hysteresis_db: float = Field(3, ge=0, le=15)
    time_to_trigger_s: float = Field(1.5, ge=0, le=10)
    ho_target_margin_db: float = Field(4, ge=0, le=20, description="Target must exceed S_min by this margin (A5-like)")
    prefer_5g_offset_db: float = Field(6, ge=0, le=30)

    # ---- network policy & fault injection -----------------------------
    mode: Mode = "HYBRID"
    buffering_enabled: bool = True
    five_g_degradation_db: float = Field(0, ge=0, le=60)
    force_4g: bool = False
    network_failure: bool = False
    extra_packet_loss: float = Field(0.0, ge=0, le=0.9)
    extra_latency_ms: float = Field(0.0, ge=0, le=2000)
    buffer_capacity: int = Field(5000, ge=10, le=100000)
    packet_size_bytes: int = Field(1200, ge=64, le=65000)

    base_stations: List[BaseStationConfig] = Field(
        default_factory=lambda: [bs.model_copy() for bs in DEFAULT_BASE_STATIONS]
    )

    def merged(self, updates: dict) -> "SimulationConfig":
        """Return a new validated config with `updates` applied."""
        data = self.model_dump()
        for key, value in updates.items():
            if value is None:
                continue
            if key == "thresholds" and isinstance(value, dict):
                data["thresholds"] = {**data["thresholds"], **{k: v for k, v in value.items() if v is not None}}
            else:
                data[key] = value
        return SimulationConfig.model_validate(data)
