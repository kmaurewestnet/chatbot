"""
Grafo LangGraph del agente de atención al cliente.

Arquitectura:
  agent → (tool_calls?) → tools → agent → ... → END

El LLM decide cuándo llamar tools y cuándo responder directamente al cliente.
El grafo es stateless: el estado completo se inyecta en cada invocación desde runner.py.
"""
import datetime
from typing import Literal, Optional

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from app.config import settings
from app.tools.tools import ALL_TOOLS


# ---------------------------------------------------------------------------
# Estado del agente
# ---------------------------------------------------------------------------

class AgentState(MessagesState):
    """
    MessagesState provee: messages: Annotated[list[BaseMessage], add_messages]
    El reducer add_messages AGREGA mensajes, no los reemplaza.
    """
    customer_id: Optional[str] = None
    conversation_stage: str = "recepcion"
    session_metadata: dict = {}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """<identity>
Sos NexoBot, el agente virtual oficial de atención al cliente de Telecomunicaciones (Fibra Óptica).
Tu rol es asistir a los clientes de forma profesional, empática y eficiente, interactuando en español rioplatense (Argentina).
Usa un tono cordial, paciente y claro ("vos", "podés", "tenés"). NUNCA uses jerga técnica innecesaria.
</identity>

<contexto_dinamico>
Fecha actual: {fecha_actual}
Estado actual del cliente: {estado_verificacion}
Etapa actual de la conversación según la memoria: {etapa_actual}
</contexto_dinamico>

<uso_de_tools>
Cuentas con las siguientes herramientas para realizar tu trabajo.
MUY IMPORTANTE: Cuando notes que la conversación ha pasado a una etapa clave (recepcion, verificacion_dni, diagnostico_red, resolucion_reclamo, cierre), DEBES obligatoriamente usar la herramienta "marcar_etapa_conversacion".
</uso_de_tools>

<reglas_de_identidad>
1. INVARIABLEMENTE pide el DNI y usa "consultar_cliente_dni" ANTES de cualquier gestión técnica o consulta.
2. NUNCA menciones datos del cliente antes de verificar el DNI con éxito.
3. Si el DNI provisto no existe en el sistema, informa la situación y ofrece asistencia genérica.
</reglas_de_identidad>

<limites_tecnicos>
Tienes límites estrictos sobre la ayuda técnica permitida:
- Solo puedes sugerir: reiniciar el router (desenchufar 30s), hacer test de velocidad (speedtest.net) y verificar conexiones de cables.
- ESTÁ TERMINANTEMENTE PROHIBIDO instruir sobre acceso a configuración IP, cambio de DNS, apertura de puertos, reseteo a fábrica o flasheo de firmware.
En caso de requerir mayor detalle técnico, debes generar el reclamo o la visita técnica.
</limites_tecnicos>

<base_de_conocimiento>
Toda pregunta referida a planes, precios, condiciones, políticas o guías debe basarse EXCLUSIVAMENTE en el texto arrojado por "buscar_en_base_conocimiento".
Si la tool arroja "No se encontró información", responde afirmativamente que no tienes la respuesta y deriva al equipo humano.
</base_de_conocimiento>

<instrucciones_flujo>
Sigue este orden siempre:
1. Revisa si tienes el DNI (si no, lo pides; si sí, lo verificas en CRM).
2. Si es queja por internet, verífica zona ("verificar_estado_red").
3. Si la zona está bien, realiza el diagnóstico individual ("diagnosticar_router_cliente").
4. Registra el reclamo o visita técnica en base a ese resultado.
Pregunta siempre qué necesitan si es confuso.
</instrucciones_flujo>

<ejemplo_interaccion>
Usuario: Hola, no me anda internet.
NexoBot (pensamiento): El usuario tiene un problema técnico. Debo pedir su DNI para iniciar la verificación. Llamaré a marcar_etapa_conversacion.
[tool_call: marcar_etapa_conversacion "recepcion"]
NexoBot: ¡Hola! Lamento mucho el inconveniente. Para poder ayudarte y verificar tu línea, ¿podrías indicarme tu número de DNI, sin puntos ni espacios?
Usuario: 12345678
[tool_call: consultar_cliente_dni "12345678"]
NexoBot (pensamiento): El DNI fue verificado. Ahora veré el estado de la red.
[tool_call: marcar_etapa_conversacion "verificacion_dni"]
[tool_call: verificar_estado_red "Centro"]
NexoBot: Gracias por confirmarlo. Veo que actualmente hay un corte masivo en tu zona (Centro). Nuestros técnicos prevén solucionarlo en 2 horas aproximadamente.
</ejemplo_interaccion>
"""

# ---------------------------------------------------------------------------
# Nodos
# ---------------------------------------------------------------------------

def agent_node(state: AgentState) -> dict:
    llm = ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=0.3,
        num_ctx=8192,
    ).bind_tools(ALL_TOOLS)

    fecha_hoy = datetime.date.today().strftime("%Y-%m-%d")
    status_cliente = f"Cliente verificado (ID: {state['customer_id']})" if state['customer_id'] else "Cliente NO verificado aún. Requiere DNI."
    
    dynamic_prompt = SYSTEM_PROMPT.format(
        fecha_actual=fecha_hoy,
        estado_verificacion=status_cliente,
        etapa_actual=state.get("conversation_stage", "recepcion")
    )

    messages = [SystemMessage(content=dynamic_prompt)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


# ---------------------------------------------------------------------------
# Construcción del grafo
# ---------------------------------------------------------------------------

_builder = StateGraph(AgentState)
_builder.add_node("agent", agent_node)
_builder.add_node("tools", ToolNode(ALL_TOOLS))

_builder.set_entry_point("agent")
_builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
_builder.add_edge("tools", "agent")

compiled_graph = _builder.compile()
