"""Pydantic request/response schemas for the REST API."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, create_model

from backend.simulation.config import SimulationConfig, Thresholds


class VitalsIn(BaseModel):
    patient_id: str = Field("P001", min_length=1, max_length=16)
    heart_rate: float = Field(..., ge=20, le=250, description="BPM")
    spo2: float = Field(..., ge=50, le=100, description="%")
    temperature: float = Field(..., ge=30, le=45, description="°C")

    model_config = {"json_schema_extra": {"example": {"patient_id": "P001", "heart_rate": 95,
                                                       "spo2": 97, "temperature": 37.2}}}


class LocationIn(BaseModel):
    ambulance_id: str = Field("AMB001", min_length=1, max_length=16)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    model_config = {"json_schema_extra": {"example": {"ambulance_id": "AMB001",
                                                       "latitude": 13.0474, "longitude": 80.2332}}}


class HandoverRequest(BaseModel):
    target_bs: Optional[str] = Field(None, description="Target base station ID; best neighbour if omitted")


class ScenarioRequest(BaseModel):
    scenario: Literal["A", "B", "C"]


class NetworkControlRequest(BaseModel):
    action: Literal["degrade_5g", "restore_5g", "force_4g", "release_4g", "fail", "restore", "restore_all"]
    degradation_db: Optional[float] = Field(None, ge=0, le=60)


class BaseStationUpdate(BaseModel):
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: Optional[float] = Field(None, gt=50, le=20000)
    tx_power_dbm: Optional[float] = Field(None, ge=10, le=60)
    enabled: Optional[bool] = None


class SensorControl(BaseModel):
    device_id: str
    connected: bool


class MessageIn(BaseModel):
    sender: Literal["HOSPITAL", "AMBULANCE"]
    text: str = Field(..., min_length=1, max_length=500)


class ExperimentRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    ambulance_speed_kmh: Optional[float] = Field(None, ge=5, le=120)
    packet_interval_s: Optional[float] = Field(None, ge=0.2, le=10)
    outage_start_frac: float = Field(0.4, ge=0, le=1, description="Route progress at which an outage is injected")
    outage_duration_s: float = Field(30, ge=0, le=600, description="Injected outage length (0 = none)")
    five_g_degradation_db: Optional[float] = Field(None, ge=0, le=60)
    extra_packet_loss: Optional[float] = Field(None, ge=0, le=0.9)
    shadowing_sigma_db: Optional[float] = Field(None, ge=0, le=12)
    hysteresis_db: Optional[float] = Field(None, ge=0, le=15)
    time_to_trigger_s: Optional[float] = Field(None, ge=0, le=10)
    seed: Optional[int] = None


class RouteRequest(BaseModel):
    preset: str


class ActionResponse(BaseModel):
    ok: bool = True
    message: str = ""
    data: Optional[Any] = None


# Partial config update model generated from SimulationConfig (all fields optional).
_EXCLUDE = {"base_stations", "thresholds"}
ThresholdsUpdate = create_model(
    "ThresholdsUpdate", **{k: (Optional[f.annotation], None) for k, f in Thresholds.model_fields.items()}
)
ConfigUpdate = create_model(
    "ConfigUpdate",
    thresholds=(Optional[ThresholdsUpdate], None),
    **{k: (Optional[f.annotation], None) for k, f in SimulationConfig.model_fields.items() if k not in _EXCLUDE},
)
