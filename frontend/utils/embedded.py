"""Embedded backend for single-process hosting (e.g. Streamlit Community Cloud).

Streamlit Cloud runs only `streamlit run frontend/app.py`, so there is no separate
Uvicorn process. If no backend answers at BACKEND_URL (and it points to this
machine), the FastAPI app is started once, in a background thread of the
Streamlit server process. The dashboard then talks to it over localhost
exactly as it does with a separately started backend.

Disable with EMBED_BACKEND=false.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st

from . import api

ROOT = Path(__file__).resolve().parents[2]


def _healthy(timeout: float = 1.5) -> bool:
    try:
        return requests.get(api.BACKEND_URL + "/api/health", timeout=timeout).ok
    except requests.RequestException:
        return False


@st.cache_resource(show_spinner="Starting simulation backend…")
def ensure_backend() -> str:
    """Return 'external' (already running), 'embedded' (started here) or 'unavailable'."""
    if _healthy():
        return "external"
    url = urlparse(api.BACKEND_URL)
    local = url.hostname in ("localhost", "127.0.0.1", "0.0.0.0")
    if not local or os.getenv("EMBED_BACKEND", "true").lower() in ("0", "false", "no"):
        return "unavailable"

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import uvicorn  # imported lazily: only needed in embedded mode

    config = uvicorn.Config("backend.main:app", host="127.0.0.1", port=url.port or 8000,
                            log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="embedded-fastapi", daemon=True).start()
    deadline = time.time() + 45
    while time.time() < deadline:
        if _healthy(timeout=1.0):
            return "embedded"
        time.sleep(0.5)
    return "unavailable"
