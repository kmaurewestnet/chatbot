"""
Capa de compatibilidad OpenAI para OpenWebUI.

Implementa el subconjunto mínimo del API de OpenAI que OpenWebUI necesita:
  GET  /v1/models               — lista de modelos disponibles
  POST /v1/chat/completions     — chat completions (con y sin streaming SSE)

El session_id se deriva del campo `chat_id` que OpenWebUI incluye en el body
(extensión no estándar). Si no está presente, se usa el campo `user` o un hash
del primer mensaje del usuario, garantizando continuidad de sesión por conversación.
"""
import hashlib
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Optional, Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.runner import run_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["openai-compat"])

MODEL_ID = "telecom-agent"

# ---------------------------------------------------------------------------
# Schemas — subconjunto del API de OpenAI
# ---------------------------------------------------------------------------


class MessageContent(BaseModel):
    role: str
    content: Union[str, list]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[MessageContent]
    stream: bool = False
    # Campos extra que envía OpenWebUI (no forman parte del estándar OpenAI)
    chat_id: Optional[str] = None
    user: Optional[str] = None
    # Parámetros estándar que aceptamos pero ignoramos (el agente no los usa)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stop: Optional[Union[str, list]] = None

    model_config = {"extra": "allow"}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageInfo


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "local"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelObject]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_session_id(req: ChatCompletionRequest) -> str:
    """
    Deriva un session_id estable a partir de los campos del request de OpenWebUI.

    Prioridad:
    1. chat_id (campo propio de OpenWebUI — estable durante toda la conversación)
    2. user    (ID del usuario OpenWebUI — sesión por usuario)
    3. hash del primer mensaje del usuario (determinista para anónimos)
    4. UUID aleatorio (último recurso)
    """
    if req.chat_id:
        return "owui_" + req.chat_id
    if req.user:
        return "owui_user_" + req.user
    first_user = next(
        (m.content if isinstance(m.content, str) else "" for m in req.messages if m.role == "user"),
        "",
    )
    if first_user:
        return "owui_hash_" + hashlib.md5(first_user.encode()).hexdigest()[:12]
    return "owui_" + str(uuid.uuid4())


def _extract_last_user_message(messages: list[MessageContent]) -> str:
    """Extrae el contenido del último mensaje del usuario."""
    for msg in reversed(messages):
        if msg.role == "user":
            if isinstance(msg.content, str):
                return msg.content
            # Contenido multimodal: extraer solo partes de texto
            return " ".join(
                part.get("text", "") for part in msg.content if isinstance(part, dict) and part.get("type") == "text"
            )
    return ""


async def _stream_response(completion_id: str, model: str, text: str) -> AsyncGenerator[str, None]:
    """
    Genera un stream SSE falso: envía la respuesta completa en un único chunk de contenido.
    Suficiente para que OpenWebUI renderice la respuesta de forma progresiva.
    """
    ts = int(time.time())
    base = {"id": completion_id, "object": "chat.completion.chunk", "created": ts, "model": model}

    # Chunk 1: anuncio del rol
    yield "data: " + json.dumps({
        **base,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }) + "\n\n"

    # Chunk 2: contenido completo
    yield "data: " + json.dumps({
        **base,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }) + "\n\n"

    # Chunk 3: señal de fin
    yield "data: " + json.dumps({
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }) + "\n\n"

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/models", response_model=ModelList)
async def list_models():
    """Lista los modelos disponibles. OpenWebUI llama este endpoint al conectarse."""
    return ModelList(
        data=[ModelObject(id=MODEL_ID, created=int(time.time()))]
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    Endpoint de chat completions compatible con OpenAI.
    Soporta streaming (SSE) y respuesta simple.
    """
    last_user_msg = _extract_last_user_message(request.messages)
    if not last_user_msg:
        raise HTTPException(status_code=422, detail="No se encontró un mensaje de usuario en el array messages.")

    session_id = _derive_session_id(request)
    logger.debug("OpenWebUI → session_id=%s | stream=%s", session_id, request.stream)

    response_text = await run_session(session_id, last_user_msg)
    completion_id = "chatcmpl-" + str(uuid.uuid4())

    if request.stream:
        return StreamingResponse(
            _stream_response(completion_id, request.model, response_text),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",   # evita buffering si hay nginx adelante
            },
        )

    return ChatCompletionResponse(
        id=completion_id,
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(role="assistant", content=response_text)
            )
        ],
        usage=UsageInfo(),
    )
