"""Thin REST client for the FastAPI backend (all state lives in the backend)."""
from __future__ import annotations

import os
from typing import Any, Optional, Tuple

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
WS_URL = os.getenv("BACKEND_WS_URL", BACKEND_URL.replace("http", "ws", 1) + "/ws/live")

_session = requests.Session()


def get(path: str, timeout: float = 5, **params) -> Optional[Any]:
    try:
        r = _session.get(BACKEND_URL + path, params=params or None, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def call(method: str, path: str, payload: Optional[dict] = None, timeout: float = 10) -> Tuple[bool, Any]:
    """POST/PUT helper returning (ok, message_or_data)."""
    try:
        r = _session.request(method, BACKEND_URL + path, json=payload, timeout=timeout)
        data = r.json() if r.content else {}
        if r.ok:
            return True, data
        detail = data.get("detail") if isinstance(data, dict) else data
        if isinstance(detail, list):  # pydantic validation errors
            detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])))}: {d.get('msg')}" for d in detail)
        return False, detail or f"HTTP {r.status_code}"
    except requests.RequestException as exc:
        return False, f"Backend unreachable ({exc.__class__.__name__}). Is it running at {BACKEND_URL}?"


def action(method: str, path: str, payload: Optional[dict] = None, success: Optional[str] = None,
           timeout: float = 10) -> bool:
    """Call the backend and show a toast with the outcome."""
    ok, data = call(method, path, payload, timeout)
    if ok:
        msg = success or (data.get("message") if isinstance(data, dict) else None) or "Done"
        st.toast(msg, icon="✅")
    else:
        st.toast(f"Error: {data}", icon="⚠️")
    return ok


@st.cache_data(ttl=600, show_spinner=False)
def route(version: str) -> Optional[dict]:
    """Route geometry (cached per route version)."""
    return get("/api/route", timeout=15)
