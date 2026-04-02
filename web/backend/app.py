"""FastAPI app — CORS, WebSocket routes, static file serving."""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Add src/ to PYTHONPATH so agent.py imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# Add project root so web.backend imports work
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env
from utils import load_env  # noqa: E402

load_env(os.path.join(PROJECT_ROOT, ".env"))
# Clear any stale Anthropic env that would override the base URL
os.environ.pop("ANTHROPIC_BASE_URL", None)
os.environ.pop("ANTHROPIC_HOST", None)

from web.backend.permissions import router as permissions_router  # noqa: E402
from web.backend.ws import router as ws_router  # noqa: E402

app = FastAPI(title="Agent Authorization Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(permissions_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve frontend static files in production
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
