"""FastAPI backend for the 5G-Based Smart Ambulance Communication System (simulation).

Run:  uvicorn backend.main:app --reload --port 8000
Docs: http://localhost:8000/docs   (Swagger)   |   http://localhost:8000/redoc
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import router, ws_router
from backend.database.init_db import init_db, load_base_stations
from backend.services.runtime import runtime
from backend.simulation.config import SimulationConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smart_ambulance")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bss = load_base_stations()
    config = SimulationConfig(base_stations=bss) if bss else SimulationConfig()
    eng = runtime.init_engine(config)
    log.info("Simulation engine ready (run %s, route source: %s)", eng.run_id, eng.route["source"])
    runtime.start_loop()
    yield
    await runtime.stop_loop()


app = FastAPI(
    title="5G Smart Ambulance — Simulation API",
    version="1.0.0",
    description=(
        "Backend for a **software simulation** of a 5G-based smart ambulance: synthetic patient vitals, "
        "BLE sensor links, GPS movement, a simplified 5G NR / 4G LTE network with handover, fallback and "
        "buffering, and hospital coordination.\n\n"
        "All data is **synthetic**. Network figures come from a simplified model and are **not** real-world "
        "5G measurements. Vital signs are not clinically validated.\n\n"
        "Live stream: `ws://<host>:8000/ws/live`"
    ),
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"ok": False, "detail": str(exc)})


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_: Request, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})


@app.get("/", tags=["system"])
def root():
    return {"service": "5G Smart Ambulance Simulation API", "docs": "/docs", "websocket": "/ws/live"}


app.include_router(router)
app.include_router(ws_router)
