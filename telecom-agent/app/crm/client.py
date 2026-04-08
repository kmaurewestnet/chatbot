"""
Cliente HTTP para el CRM interno.
Centraliza la autenticación y el base URL para todos los tools que necesitan el CRM.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Timeout para todas las llamadas al CRM
_TIMEOUT = 10.0


def _get_headers() -> dict:
    return {"X-API-Key": settings.crm_api_key, "Content-Type": "application/json"}


def get_cliente_by_dni(dni: str) -> dict:
    """GET /clientes?dni={dni}"""
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.get("/clientes", params={"dni": dni}, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()


def get_estado_red(zona: str) -> dict:
    """GET /estado/{zona} en la API de diagnósticos de red"""
    with httpx.Client(
        base_url=settings.net_diagnostics_url, timeout=_TIMEOUT, verify=False
    ) as client:
        resp = client.get(
            f"/estado/{zona}",
            headers={"X-API-Key": settings.net_diagnostics_key},
        )
        resp.raise_for_status()
        return resp.json()


def post_diagnostico_router(cliente_id: str) -> dict:
    """POST /diagnostico/{cliente_id} en la API de diagnósticos de red"""
    with httpx.Client(
        base_url=settings.net_diagnostics_url, timeout=_TIMEOUT, verify=False
    ) as client:
        resp = client.post(
            f"/diagnostico/{cliente_id}",
            headers={"X-API-Key": settings.net_diagnostics_key},
        )
        resp.raise_for_status()
        return resp.json()


def post_reclamo(cliente_id: str, tipo: str, descripcion: str) -> dict:
    """POST /reclamos"""
    payload = {"cliente_id": cliente_id, "tipo": tipo, "descripcion": descripcion}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.post("/reclamos", json=payload, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()


def post_visita_tecnica(cliente_id: str, motivo: str) -> dict:
    """POST /visitas"""
    payload = {"cliente_id": cliente_id, "motivo": motivo}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.post("/visitas", json=payload, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()


def post_solicitud_baja(cliente_id: str, motivo: str) -> dict:
    """POST /bajas"""
    payload = {"cliente_id": cliente_id, "motivo": motivo}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.post("/bajas", json=payload, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()
