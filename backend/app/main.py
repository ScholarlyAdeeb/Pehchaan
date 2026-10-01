"""
FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000
(from the `backend/` directory, with the virtualenv activated)
"""
from __future__ import annotations

import hmac
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_documents, routes_face, routes_health, routes_reference
from app.config import get_settings
from app.utils.logging_config import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI-Based Fake Identity & Document Screening System — OCR extraction, "
        "document validation, tampering detection, and face verification for "
        "border checkpoint screening. Prototype for SIH Problem Statement 26188."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security middleware: Engine API key required for all /api calls
@app.middleware("http")
async def require_engine_key(request: Request, call_next):
    # Only the web server (which authenticates officers) may call the engine.
    key = settings.ENGINE_API_KEY
    if key and request.url.path.startswith("/api"):
        sent = request.headers.get("x-engine-key", "")
        if not hmac.compare_digest(sent.encode(), key.encode()):
            return JSONResponse({"detail": "Missing or invalid engine key"}, status_code=401)
    return await call_next(request)

# Security middleware: Checkpoint access control
@app.middleware("http")
async def enforce_checkpoint_access(request: Request, call_next):
    # Enforce checkpoint scoping for engine instances that serve specific posts.
    allowed = settings.ENGINE_CHECKPOINT_IDS
    if allowed and request.url.path.startswith("/api/documents/scan"):
        # Checkpoint ID must be provided by the authenticated web server.
        checkpoint_id = request.headers.get("x-checkpoint-id", "")
        if not checkpoint_id or checkpoint_id not in allowed:
            return JSONResponse(
                {"detail": f"Checkpoint '{checkpoint_id}' not authorized for this engine instance"},
                status_code=403,
            )
    return await call_next(request)


app.include_router(routes_health.router)
app.include_router(routes_documents.router)
app.include_router(routes_face.router)
app.include_router(routes_reference.router)


@app.get("/")
async def root():
    return {
        "message": f"{settings.APP_NAME} API",
        "docs": "/docs",
        "health": "/api/health",
    }