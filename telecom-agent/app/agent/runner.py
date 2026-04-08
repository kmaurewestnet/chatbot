"""
Coordinador de sesión: conecta FastAPI con el grafo LangGraph e inyecta memoria Redis.
"""
import logging

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langfuse import Langfuse
from langfuse.callback import CallbackHandler

from app.agent.graph import AgentState, compiled_graph
from app.config import settings
from app.memory.session import session_memory

logger = logging.getLogger(__name__)

# Cliente Langfuse (singleton). Si las keys no están configuradas, los traces se omiten.
_langfuse = None
if settings.langfuse_public_key not in ("change_me", "") and settings.langfuse_secret_key not in ("change_me", ""):
    try:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:
        logger.warning("Langfuse no configurado — trazabilidad deshabilitada.")


def _build_invoke_config(session_id: str) -> dict:
    """Construye el config de callbacks para Langfuse si está disponible."""
    if _langfuse is None:
        return {}
    langfuse_handler = CallbackHandler(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
        session_id=session_id,
        metadata={"model": settings.llm_model},
    )
    return {"callbacks": [langfuse_handler]}


def _extract_tool_events(messages: list) -> list[dict]:
    """
    Extrae los tool calls y sus resultados de la lista de mensajes LangGraph.
    Retorna una lista de dicts con {tool_name, args, result}.
    """
    tool_events = []
    pending: dict[str, dict] = {}  # tool_call_id → {tool_name, args}

    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                pending[tc["id"]] = {"tool_name": tc["name"], "args": tc["args"]}
        elif isinstance(msg, ToolMessage):
            call_id = msg.tool_call_id
            if call_id in pending:
                event = {**pending.pop(call_id), "result": msg.content}
            else:
                event = {"tool_name": "desconocido", "args": {}, "result": msg.content}
            tool_events.append(event)

    return tool_events


async def run_session(session_id: str, user_message: str) -> str:
    """
    Procesa un mensaje del usuario dentro de una sesión.

    1. Carga historial de Redis
    2. Construye el estado inicial con el nuevo mensaje
    3. Invoca el grafo LangGraph (con tracing Langfuse si está configurado)
    4. Persiste el historial actualizado en Redis
    5. Retorna la respuesta del asistente como string
    """
    history = await session_memory.get_history(session_id)
    customer_id = await session_memory.get_customer_id(session_id)

    initial_state = AgentState(
        messages=history + [HumanMessage(content=user_message)],
        customer_id=customer_id,
        session_metadata={"session_id": session_id},
    )

    result = await compiled_graph.ainvoke(initial_state, config=_build_invoke_config(session_id))

    last_message = result["messages"][-1]
    response_text: str = last_message.content if hasattr(last_message, "content") else str(last_message)

    await session_memory.save_history(session_id, result["messages"])

    new_customer_id = result.get("customer_id")
    if new_customer_id and new_customer_id != customer_id:
        await session_memory.save_customer_id(session_id, new_customer_id)

    return response_text


async def run_session_dev(session_id: str, user_message: str) -> dict:
    """
    Igual que run_session pero retorna también los tool calls para el modo desarrollador.

    Returns:
        {
            "response": str,
            "tool_events": [{tool_name, args, result}, ...],
            "message_count": int,
        }
    """
    history = await session_memory.get_history(session_id)
    customer_id = await session_memory.get_customer_id(session_id)

    initial_state = AgentState(
        messages=history + [HumanMessage(content=user_message)],
        customer_id=customer_id,
        session_metadata={"session_id": session_id},
    )

    result = await compiled_graph.ainvoke(initial_state, config=_build_invoke_config(session_id))

    last_message = result["messages"][-1]
    response_text: str = last_message.content if hasattr(last_message, "content") else str(last_message)

    await session_memory.save_history(session_id, result["messages"])

    new_customer_id = result.get("customer_id")
    if new_customer_id and new_customer_id != customer_id:
        await session_memory.save_customer_id(session_id, new_customer_id)

    return {
        "response": response_text,
        "tool_events": _extract_tool_events(result["messages"]),
        "message_count": len(result["messages"]),
    }
