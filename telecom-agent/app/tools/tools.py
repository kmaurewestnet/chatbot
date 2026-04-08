"""
Tools LangGraph para el agente de atención al cliente.

Cada tool es una función decorada con @tool. Los errores HTTP se capturan y se
retornan como dict con clave "error" para que el LLM pueda informar al cliente
de forma apropiada sin exponer detalles técnicos.
"""
import logging

import httpx
from langchain_core.tools import tool

from app.crm import client as crm
from app.rag.retriever import search_knowledge

logger = logging.getLogger(__name__)


def _handle_http_error(exc: Exception, context: str) -> dict:
    logger.error("%s: %s", context, exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return {"error": f"El sistema respondió con error {exc.response.status_code}. Intentar nuevamente en unos minutos."}
    return {"error": "No se pudo comunicar con los sistemas internos. Intentar nuevamente en unos minutos."}


@tool
def consultar_cliente_dni(dni: str) -> dict:
    """
    Consulta los datos de un cliente en el CRM interno usando su DNI.
    Retorna: cliente_id, nombre, plan contratado, zona de servicio, estado de cuenta.
    Usar SIEMPRE como primer paso antes de cualquier gestión.
    """
    try:
        return crm.get_cliente_by_dni(dni)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "consultar_cliente_dni")


@tool
def verificar_estado_red(zona: str) -> dict:
    """
    Verifica si hay cortes o problemas masivos de red en una zona geográfica.
    Retorna: hay_corte (bool), descripcion del problema, eta_resolucion estimado.
    Usar ANTES de diagnosticar el router individual del cliente.
    """
    try:
        return crm.get_estado_red(zona)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "verificar_estado_red")


@tool
def diagnosticar_router_cliente(cliente_id: str) -> dict:
    """
    Ejecuta un diagnóstico remoto del router/ONT del cliente.
    Retorna: estado (ok | degradado | sin_señal), ultima_conexion, detalles técnicos.
    Usar solo si verificar_estado_red no indica corte masivo en la zona.
    """
    try:
        return crm.post_diagnostico_router(cliente_id)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "diagnosticar_router_cliente")


@tool
def registrar_reclamo(cliente_id: str, tipo: str, descripcion: str) -> dict:
    """
    Registra un reclamo técnico en el CRM y genera un número de ticket.
    Args:
        cliente_id: ID del cliente obtenido de consultar_cliente_dni.
        tipo: Categoría del reclamo (ej: 'internet_caido', 'velocidad_lenta', 'router_falla').
        descripcion: Descripción detallada del problema reportado por el cliente.
    Retorna: ticket_id, estado del reclamo creado.
    """
    try:
        return crm.post_reclamo(cliente_id, tipo, descripcion)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "registrar_reclamo")


@tool
def generar_visita_tecnica(cliente_id: str, motivo: str) -> dict:
    """
    Genera una orden de visita técnica domiciliaria para el cliente.
    Args:
        cliente_id: ID del cliente obtenido de consultar_cliente_dni.
        motivo: Motivo de la visita (ej: 'router_sin_señal', 'instalacion_nueva', 'cambio_equipo').
    Retorna: visita_id, fecha_estimada, tecnico_asignado (si disponible).
    Usar cuando el diagnóstico remoto no resuelve el problema o se requiere intervención física.
    """
    try:
        return crm.post_visita_tecnica(cliente_id, motivo)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "generar_visita_tecnica")


@tool
def registrar_solicitud_baja(cliente_id: str, motivo: str) -> dict:
    """
    Registra una solicitud de baja del servicio en el CRM.
    Args:
        cliente_id: ID del cliente obtenido de consultar_cliente_dni.
        motivo: Motivo de la baja declarado por el cliente.
    Retorna: solicitud_id, estado 'pendiente_confirmacion'.
    IMPORTANTE: Verificar deuda pendiente y condiciones de permanencia ANTES de registrar.
    """
    try:
        return crm.post_solicitud_baja(cliente_id, motivo)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "registrar_solicitud_baja")


@tool
def buscar_en_base_conocimiento(query: str) -> str:
    """
    Busca información en la base de conocimiento interna de la empresa.
    Usar para preguntas sobre: planes y precios, políticas de cancelación,
    condiciones contractuales, guías de configuración de equipos, preguntas frecuentes,
    procedimientos internos.
    NO usar para: estado actual de red (usar verificar_estado_red),
    datos del cliente (usar consultar_cliente_dni).
    """
    return search_knowledge(query)


# Registry de tools para usar en el grafo LangGraph
ALL_TOOLS = [
    consultar_cliente_dni,
    verificar_estado_red,
    diagnosticar_router_cliente,
    registrar_reclamo,
    generar_visita_tecnica,
    registrar_solicitud_baja,
    buscar_en_base_conocimiento,
]
