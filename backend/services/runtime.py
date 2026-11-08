"""Process-wide runtime: the ONE shared simulation engine, the background
simulation loop and the WebSocket broadcaster."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Optional, Set

import numpy as np
from fastapi import WebSocket

from backend.simulation.ambulance_simulator import RouteProvider
from backend.simulation.config import SimulationConfig
from backend.simulation.engine import SimulationEngine

from .persistence import persist_outbox, register_run

log = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def dumps(obj) -> str:
    return json.dumps(obj, default=_json_default)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        if not self.active:
            return
        text = dumps(message)
        dead = []
        for ws in list(self.active):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=2.0)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class Runtime:
    def __init__(self) -> None:
        self.engine: Optional[SimulationEngine] = None
        self.route_provider = RouteProvider()
        self.manager = ConnectionManager()
        self._task: Optional[asyncio.Task] = None
        self._registered_run: Optional[str] = None
        self.ticks = 0

    def init_engine(self, config: SimulationConfig) -> SimulationEngine:
        self.engine = SimulationEngine(config, route_provider=self.route_provider)
        return self.engine

    def start_loop(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="simulation-loop")

    async def stop_loop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        last = time.perf_counter()
        while True:
            start = time.perf_counter()
            try:
                eng = self.engine
                eng.tick(min(start - last, 2.0))
                last = start
                if self._registered_run != eng.run_id:
                    self._registered_run = eng.run_id
                    await asyncio.to_thread(register_run, eng.run_id, eng.config.route_preset,
                                            eng.route["source"], eng.config.model_dump())
                run_id = eng.run_id
                outbox = eng.drain_outbox()
                if any(outbox.values()):
                    await asyncio.to_thread(persist_outbox, run_id, outbox)
                if self.manager.active:
                    snap = await asyncio.to_thread(eng.snapshot)
                    await self.manager.broadcast({"type": "snapshot", "data": snap})
                self.ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Simulation loop error")
            interval = self.engine.config.tick_interval_s if self.engine else 1.0
            await asyncio.sleep(max(0.05, interval - (time.perf_counter() - start)))


runtime = Runtime()


def get_engine() -> SimulationEngine:
    if runtime.engine is None:
        raise RuntimeError("Simulation engine not initialised")
    return runtime.engine
