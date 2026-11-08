"""Virtual patient monitor producing SYNTHETIC vital signs.

The readings are generated with mean-reverting stochastic processes
(Ornstein-Uhlenbeck) whose targets depend on the selected scenario.
They are for communication-system demonstration only and have no
clinical validity.
"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

SCENARIOS: Dict[str, str] = {
    "A": "Stable patient",
    "B": "Increasing heart rate",
    "C": "Decreasing SpO2",
}

# Synthetic ECG template: (phase centre, amplitude mV, width) for P, Q, R, S, T
_ECG_WAVES = [
    (0.20, 0.12, 0.025),
    (0.355, -0.12, 0.008),
    (0.38, 1.00, 0.010),
    (0.405, -0.25, 0.010),
    (0.62, 0.30, 0.045),
]


class PatientSimulator:
    def __init__(self, rng: np.random.Generator, scenario: str = "A", patient_id: str = "P001"):
        self.rng = rng
        self.patient_id = patient_id
        self.hr = 78.0
        self.spo2 = 98.0
        self.temp = 36.9
        self.ecg_phase = 0.0
        self.scenario = "A"
        self.scenario_elapsed = 0.0
        self.set_scenario(scenario)

    # ------------------------------------------------------------------
    def set_scenario(self, scenario: str) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'")
        self.scenario = scenario
        self.scenario_elapsed = 0.0

    def _targets(self):
        e = self.scenario_elapsed
        if self.scenario == "B":
            hr = min(165.0, 84.0 + 0.30 * e)          # +18 bpm per simulated minute
            return hr, 96.5, min(37.9, 37.0 + 0.002 * e)
        if self.scenario == "C":
            spo2 = max(82.0, 97.5 - 0.045 * e)        # -2.7 % per simulated minute
            hr = 82.0 + (97.5 - spo2) * 1.2           # compensatory tachycardia
            return hr, spo2, 37.1
        return 78.0, 98.0, 36.9

    def step(self, dt: float) -> None:
        """Advance the patient state by `dt` simulated seconds."""
        self.scenario_elapsed += dt
        t_hr, t_spo2, t_temp = self._targets()
        sq = math.sqrt(max(dt, 1e-6))
        n = self.rng.standard_normal(3)
        self.hr += 0.25 * (t_hr - self.hr) * dt + 1.2 * sq * n[0]
        self.spo2 += 0.30 * (t_spo2 - self.spo2) * dt + 0.25 * sq * n[1]
        self.temp += 0.05 * (t_temp - self.temp) * dt + 0.01 * sq * n[2]
        self.hr = float(np.clip(self.hr, 30, 220))
        self.spo2 = float(np.clip(self.spo2, 70, 100))
        self.temp = float(np.clip(self.temp, 34, 42))
        self.ecg_phase = (self.ecg_phase + self.hr / 60.0 * dt) % 1.0

    def reading(self) -> Dict[str, float]:
        return {
            "heart_rate": round(self.hr, 1),
            "spo2": round(self.spo2, 1),
            "temperature": round(self.temp, 2),
        }

    # ------------------------------------------------------------------
    def ecg_window(self, sim_time: float, seconds: float = 4.0, fs: int = 125) -> Dict[str, List[float]]:
        """Synthetic ECG lead trace ending at the current simulated time."""
        t = np.arange(-seconds, 0.0, 1.0 / fs)
        phase = (self.ecg_phase + t * self.hr / 60.0) % 1.0
        v = np.zeros_like(t)
        for centre, amp, width in _ECG_WAVES:
            d = np.abs(phase - centre)
            d = np.minimum(d, 1.0 - d)  # circular distance
            v += amp * np.exp(-0.5 * (d / width) ** 2)
        v += 0.05 * np.sin(2 * np.pi * 0.3 * (sim_time + t))  # baseline wander
        v += 0.015 * self.rng.standard_normal(t.size)       # measurement noise
        return {"t": np.round(t, 3).tolist(), "v": np.round(v, 3).tolist()}
