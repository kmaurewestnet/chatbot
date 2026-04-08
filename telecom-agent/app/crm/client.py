"""
Cliente HTTP para el CRM interno.
Centraliza la autenticación y el base URL para todos los tools que necesitan el CRM.

Modo demo: si CRM_API_KEY es "change_me" (valor por defecto), todas las funciones
retornan datos ficticios sin conectarse a ningún servicio externo.
"""
import logging
import random
import string
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Timeout para todas las llamadas al CRM
_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# Datos demo
# ---------------------------------------------------------------------------

_DEMO_CLIENTES = {
    "32456789": {
        "cliente_id": "CLI-001",
        "nombre": "Juan Pérez",
        "plan": "Fibra 300 Mbps",
        "zona": "norte",
        "estado_cuenta": "al_dia",
        "email": "juan.perez@email.com",
        "telefono": "011-4567-8901",
    },
    "28901234": {
        "cliente_id": "CLI-002",
        "nombre": "María González",
        "plan": "Fibra 100 Mbps",
        "zona": "sur",
        "estado_cuenta": "deuda_pendiente",
        "email": "maria.gonzalez@email.com",
        "telefono": "011-5678-9012",
    },
    "40123456": {
        "cliente_id": "CLI-003",
        "nombre": "Carlos Rodríguez",
        "plan": "Fibra 500 Mbps",
        "zona": "centro",
        "estado_cuenta": "al_dia",
        "email": "carlos.rodriguez@email.com",
        "telefono": "011-6789-0123",
    },
}


def _is_demo() -> bool:
    return settings.crm_api_key == "change_me"


def _random_id(prefix: str) -> str:
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{prefix}-{suffix}"


# ---------------------------------------------------------------------------
# Funciones del cliente
# ---------------------------------------------------------------------------


def _get_headers() -> dict:
    return {"X-API-Key": settings.crm_api_key, "Content-Type": "application/json"}


def get_cliente_by_dni(dni: str) -> dict:
    """GET /clientes?dni={dni}"""
    if _is_demo():
        cliente = _DEMO_CLIENTES.get(dni)
        if cliente:
            return cliente
        return {"error": f"No se encontró ningún cliente con DNI {dni}."}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.get("/clientes", params={"dni": dni}, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()


def get_estado_red(zona: str) -> dict:
    """GET /estado/{zona} en la API de diagnósticos de red"""
    if _is_demo():
        return {"hay_corte": False, "descripcion": "Sin incidentes en la zona.", "eta_resolucion": None}
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
    if _is_demo():
        return {
            "estado": "degradado",
            "ultima_conexion": (datetime.now() - timedelta(hours=2)).isoformat(),
            "detalles": "Señal óptica baja (-28 dBm). Posible suciedad en conector ONT.",
        }
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
    if _is_demo():
        return {"ticket_id": _random_id("TKT"), "estado": "abierto", "cliente_id": cliente_id}
    payload = {"cliente_id": cliente_id, "tipo": tipo, "descripcion": descripcion}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.post("/reclamos", json=payload, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()


def post_visita_tecnica(cliente_id: str, motivo: str) -> dict:
    """POST /visitas"""
    if _is_demo():
        fecha = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        return {"visita_id": _random_id("VIS"), "fecha_estimada": fecha, "tecnico_asignado": "Técnico Demo"}
    payload = {"cliente_id": cliente_id, "motivo": motivo}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.post("/visitas", json=payload, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()


def post_solicitud_baja(cliente_id: str, motivo: str) -> dict:
    """POST /bajas"""
    if _is_demo():
        return {"solicitud_id": _random_id("BAJ"), "estado": "pendiente_confirmacion", "cliente_id": cliente_id}
    payload = {"cliente_id": cliente_id, "motivo": motivo}
    with httpx.Client(base_url=settings.crm_base_url, timeout=_TIMEOUT, verify=False) as client:
        resp = client.post("/bajas", json=payload, headers=_get_headers())
        resp.raise_for_status()
        return resp.json()
