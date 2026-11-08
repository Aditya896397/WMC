"""Live data feed: a background WebSocket client shared by all Streamlit sessions.

A daemon thread keeps a connection to the backend's /ws/live endpoint and
stores the latest snapshot.  Pages read that snapshot without blocking;
if the WebSocket is down they fall back to a REST call.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional, Tuple

import streamlit as st
from websockets.sync.client import connect

from . import api


class LiveFeed:
    def __init__(self, url: str):
        self.url = url
        self.latest: Optional[dict] = None
        self.updated = 0.0
        self.connected = False
        self.messages = 0
        self.error: Optional[str] = None
        self._thread = threading.Thread(target=self._run, name="ws-live-feed", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                with connect(self.url, open_timeout=4, max_size=32 * 2**20, ping_interval=20) as ws:
                    self.connected, self.error = True, None
                    for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "snapshot":
                            self.latest = msg["data"]
                            self.updated = time.time()
                            self.messages += 1
            except Exception as exc:
                self.error = f"{exc.__class__.__name__}: {exc}"
            self.connected = False
            time.sleep(2)


@st.cache_resource(show_spinner=False)
def get_feed() -> LiveFeed:
    return LiveFeed(api.WS_URL)


def get_state(max_age: float = 3.0, fresh: bool = False) -> Tuple[Optional[dict], str]:
    """Return (snapshot, source) where source is 'websocket', 'rest' or 'offline'.

    fresh=True bypasses the WebSocket cache (used where controls must reflect a change just made)."""
    feed = get_feed()
    if not fresh and feed.latest is not None and time.time() - feed.updated < max_age:
        return feed.latest, "websocket"
    snap = api.get("/api/simulation/status")
    if snap is not None:
        return snap, "rest"
    return None, "offline"
