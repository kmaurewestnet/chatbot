"""
Tools LangGraph para el agente de atención al cliente.

Cada tool es una función decorada con @tool. Los errores HTTP se capturan y se
retornan como dict con clave "error" para que el LLM pueda informar al cliente
de forma apropiada sin exponer detalles técnicos.
"""
import logging
from typing import Literal

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.crm import client as crm
from app.rag.retriever import search_knowledge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas para tipado fuerte
# ---------------------------------------------------------------------------

class ConsultarClienteDniSchema(BaseModel):
    dni: str = Field(description="El DNI del cliente a consultar, ej: 12345678, sin puntos ni separadores.")

class VerificarEstadoRedSchema(BaseModel):
    zona: str = Field(description="La zona, barrio o localidad del cliente.")

class DiagnosticarRouterClienteSchema(BaseModel):
    cliente_id: str = Field(description="El ID del cliente obtenido previamente con consultar_cliente_dni.")

class RegistrarReclamoSchema(BaseModel):
    cliente_id: str = Field(description="El ID del cliente obtenido de consultar_cliente_dni.")
    tipo: Literal['internet_caido', 'velocidad_lenta', 'router_falla', 'desconexion_intermitente', 'otro'] = Field(description="La categoría del reclamo.")
    descripcion: str = Field(description="Descripción clara y detallada del problema que reporta el cliente.")

class GenerarVisitaTecnicaSchema(BaseModel):
    cliente_id: str = Field(description="El ID del cliente obtenido de consultar_cliente_dni.")
    motivo: Literal['router_sin_señal', 'instalacion_nueva', 'cambio_equipo', 'revision_cableado', 'otro'] = Field(description="Motivo de la visita domiciliaria.")

class RegistrarSolicitudBajaSchema(BaseModel):
    cliente_id: str = Field(description="El ID del cliente obtenido de consultar_cliente_dni.")
    motivo: str = Field(description="El motivo por el cual el cliente desea cancelar el servicio.")

class BuscarEnBaseConocimientoSchema(BaseModel):
    query: str = Field(description="Texto o pregunta natural para buscar en la base de datos de conocimiento de la empresa.")

class MarcarEtapaConversacionSchema(BaseModel):
    etapa: Literal['recepcion', 'verificacion_dni', 'diagnostico_red', 'resolucion_reclamo', 'escala_humano', 'cierre'] = Field(description="La etapa actual de la conversación.")


# ---------------------------------------------------------------------------
# Helpers y Tools
# ---------------------------------------------------------------------------

def _handle_http_error(exc: Exception, context: str) -> dict:
    logger.error("%s: %s", context, exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return {"error": f"El sistema respondió con error {exc.response.status_code}. Intentar nuevamente en unos minutos."}
    return {"error": "No se pudo comunicar con los sistemas internos. Intentar nuevamente en unos minutos."}


@tool("marcar_etapa_conversacion", args_schema=MarcarEtapaConversacionSchema)
def marcar_etapa_conversacion(etapa: str) -> str:
    """
    Actualiza la etiqueta interna que marca la etapa de la conversación actual.
    USO OBLIGATORIO: Debes llamar a esta herramienta al inicio de enviar una respuesta
    si notas que la conversación ha avanzado a una de estas etapas.
    """
    # En runtime real de LangGraph esto no persiste globalmente, pero el frontend 
    # interceptará este tool_call para refrescar visualmente.
    # El runner la guardará al finalizar la iteración en Redis si es parte de las tools.
    return f"Etapa de conversación actualizada a: {etapa}"


@tool("consultar_cliente_dni", args_schema=ConsultarClienteDniSchema)
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


@tool("verificar_estado_red", args_schema=VerificarEstadoRedSchema)
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


@tool("diagnosticar_router_cliente", args_schema=DiagnosticarRouterClienteSchema)
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


@tool("registrar_reclamo", args_schema=RegistrarReclamoSchema)
def registrar_reclamo(cliente_id: str, tipo: str, descripcion: str) -> dict:
    """
    Registra un reclamo técnico en el CRM y genera un número de ticket.
    Retorna: ticket_id, estado del reclamo creado.
    """
    try:
        return crm.post_reclamo(cliente_id, tipo, descripcion)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "registrar_reclamo")


@tool("generar_visita_tecnica", args_schema=GenerarVisitaTecnicaSchema)
def generar_visita_tecnica(cliente_id: str, motivo: str) -> dict:
    """
    Genera una orden de visita técnica domiciliaria para el cliente.
    Retorna: visita_id, fecha_estimada, tecnico_asignado (si disponible).
    Usar cuando el diagnóstico remoto no resuelve el problema o se requiere intervención física.
    """
    try:
        return crm.post_visita_tecnica(cliente_id, motivo)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "generar_visita_tecnica")


@tool("registrar_solicitud_baja", args_schema=RegistrarSolicitudBajaSchema)
def registrar_solicitud_baja(cliente_id: str, motivo: str) -> dict:
    """
    Registra una solicitud de baja del servicio en el CRM.
    Retorna: solicitud_id, estado 'pendiente_confirmacion'.
    IMPORTANTE: Verificar deuda pendiente y condiciones de permanencia ANTES de registrar.
    """
    try:
        return crm.post_solicitud_baja(cliente_id, motivo)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return _handle_http_error(exc, "registrar_solicitud_baja")


@tool("buscar_en_base_conocimiento", args_schema=BuscarEnBaseConocimientoSchema)
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
    marcar_etapa_conversacion,
    consultar_cliente_dni,
    verificar_estado_red,
    diagnosticar_router_cliente,
    registrar_reclamo,
    generar_visita_tecnica,
    registrar_solicitud_baja,
    buscar_en_base_conocimiento,
]
