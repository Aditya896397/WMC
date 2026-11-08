"""Start backend (FastAPI/Uvicorn) and frontend (Streamlit) with one command.

    python run.py            # backend :8000, frontend :8501
    python run.py --reload   # backend with auto-reload
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def wait_for(url: str, timeout: float = 40) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.7)
    return False


def main() -> int:
    backend_port = os.getenv("BACKEND_PORT", "8000")
    frontend_port = os.getenv("FRONTEND_PORT", "8501")
    env = {**os.environ, "BACKEND_URL": os.getenv("BACKEND_URL", f"http://localhost:{backend_port}")}
    b_cmd = [PY, "-m", "uvicorn", "backend.main:app", "--port", backend_port]
    if "--reload" in sys.argv:
        b_cmd.append("--reload")
    print(f"> Backend : {' '.join(b_cmd)}")
    backend = subprocess.Popen(b_cmd, cwd=ROOT, env=env)
    if not wait_for(f"http://localhost:{backend_port}/api/health"):
        print("ERROR Backend did not start - see the log above.")
        backend.terminate()
        return 1
    print(f"OK Backend ready  -> http://localhost:{backend_port}/docs")
    f_cmd = [PY, "-m", "streamlit", "run", "frontend/app.py", "--server.port", frontend_port]
    print(f"> Frontend: {' '.join(f_cmd)}")
    frontend = subprocess.Popen(f_cmd, cwd=ROOT, env=env)
    print(f"OK Dashboard     -> http://localhost:{frontend_port}\n  (Ctrl+C to stop both)")
    try:
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (frontend, backend):
            if p.poll() is None:
                p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
