"""
Grafo LangGraph del agente de atención al cliente.

Arquitectura:
  agent → (tool_calls?) → tools → agent → ... → END

El LLM decide cuándo llamar tools y cuándo responder directamente al cliente.
El grafo es stateless: el estado completo se inyecta en cada invocación desde runner.py.
"""
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
    session_metadata: dict = {}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un agente de atención al cliente de una empresa de fibra óptica.
Tu objetivo es resolver los problemas del cliente de manera profesional, empática y eficiente.

## Reglas obligatorias

1. **Identificación**: Siempre pedí el DNI del cliente y usá `consultar_cliente_dni` antes de realizar cualquier gestión. No inventes datos del cliente.

2. **Sin internet**: Antes de diagnosticar el router individual, usá `verificar_estado_red` con la zona del cliente para descartar un corte masivo.

3. **Solicitud de baja**: Antes de registrar la baja, consultá el estado de cuenta, informá las condiciones de permanencia y cargos por cancelación anticipada usando `buscar_en_base_conocimiento`.

4. **Información de planes y precios**: Usá `buscar_en_base_conocimiento` para responder preguntas sobre planes, precios, condiciones contractuales o procedimientos.

5. **Veracidad**: Nunca inventes información. Si no sabés algo, usá las herramientas disponibles o informá que derivarás el caso.

6. **Tono**: Respondé siempre en español rioplatense (Argentina), de manera cordial y concisa. Usá "vos" en lugar de "tú".

## Flujo para "no tengo internet"
1. Identificar cliente con DNI
2. Verificar estado de red en la zona del cliente
3. Si hay corte masivo: informar y dar ETA de resolución
4. Si no hay corte: diagnosticar router del cliente
5. Si router sin señal/degradado: registrar reclamo + generar visita técnica
6. Informar número de ticket al cliente

## Flujo para "quiero dar de baja"
1. Identificar cliente con DNI
2. Buscar condiciones de cancelación en la base de conocimiento
3. Informar cargos por permanencia y deuda pendiente
4. Si el cliente confirma: registrar solicitud de baja
5. Dar número de gestión y pasos siguientes
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

    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
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
