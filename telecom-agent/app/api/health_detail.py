"""
Router de health check detallado por dependencia.

GET /health/detail — verifica Redis, Qdrant y Ollama concurrentemente.
"""
import asyncio
import logging

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.memory.session import session_memory

logger = logging.getLogger(__name__)

router = APIRouter()

_PROBE_TIMEOUT = 3.0  # segundos por dependencia


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DependencyStatus(BaseModel):
    status: str   # "ok" | "error"
    detail: str


class HealthDetailResponse(BaseModel):
    redis: DependencyStatus
    qdrant: DependencyStatus
    ollama: DependencyStatus
    overall: str  # "ok" | "degraded" | "error"


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

async def _probe_redis() -> DependencyStatus:
    try:
        await asyncio.wait_for(session_memory.redis.ping(), timeout=_PROBE_TIMEOUT)
        return DependencyStatus(status="ok", detail="pong")
    except Exception as exc:
        return DependencyStatus(status="error", detail=str(exc))


async def _probe_qdrant() -> DependencyStatus:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(f"{settings.qdrant_url}/healthz")
            if resp.status_code == 200:
                return DependencyStatus(status="ok", detail="healthz ok")
            return DependencyStatus(status="error", detail=f"HTTP {resp.status_code}")
    except Exception as exc:
        return DependencyStatus(status="error", detail=str(exc))


async def _probe_ollama() -> DependencyStatus:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                loaded = settings.llm_model in " ".join(models)
                detail = f"modelos: {', '.join(models[:3]) or 'ninguno'}"
                if not loaded:
                    detail += f" (aviso: {settings.llm_model} no encontrado)"
                return DependencyStatus(status="ok", detail=detail)
            return DependencyStatus(status="error", detail=f"HTTP {resp.status_code}")
    except Exception as exc:
        return DependencyStatus(status="error", detail=str(exc))


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/detail", response_model=HealthDetailResponse)
async def health_detail():
    """Health check detallado: verifica cada dependencia en paralelo."""
    redis_status, qdrant_status, ollama_status = await asyncio.gather(
        _probe_redis(),
        _probe_qdrant(),
        _probe_ollama(),
        return_exceptions=False,
    )

    statuses = [redis_status.status, qdrant_status.status, ollama_status.status]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "degraded"
    else:
        overall = "error"

    return HealthDetailResponse(
        redis=redis_status,
        qdrant=qdrant_status,
        ollama=ollama_status,
        overall=overall,
    )
