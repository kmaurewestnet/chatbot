"""
API FastAPI del agente de atención al cliente.

Endpoints:
  POST /chat                 — REST: mensaje + session_id → respuesta
  POST /chat/dev             — REST modo dev: incluye tool calls en la respuesta
  WS   /ws/{session_id}      — WebSocket: streaming de mensajes
  POST /webhook/whatsapp     — Webhook Twilio para WhatsApp
  POST /audio                — Transcripción Whisper + chat
  GET  /health               — Health check básico
  GET  /health/detail        — Health check detallado por dependencia
  *    /knowledge/...        — CRUD de la base de conocimiento
  GET  /ui                   — Interfaz de desarrollador (StaticFiles)
"""
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import whisper
from fastapi import FastAPI, File, Form, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.runner import run_session, run_session_dev, run_session_stream
from app.api.health_detail import router as health_detail_router
from app.api.knowledge import router as knowledge_router
from app.api.openai_compat import router as openai_compat_router
from app.config import settings
from app.memory.session import session_memory

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"

# ---------------------------------------------------------------------------
# Whisper (cargado una vez en startup)
# ---------------------------------------------------------------------------
_whisper_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _whisper_model

    logger.info("Iniciando Telecom Agent API...")

    logger.info("Cargando modelo Whisper 'base'...")
    _whisper_model = whisper.load_model("base")
    logger.info("Whisper listo.")

    try:
        await session_memory.redis.ping()
        logger.info("Redis OK: %s", settings.redis_url)
    except Exception as exc:
        logger.error("Redis no disponible: %s", exc)

    logger.info(
        "Ollama configurado en %s | LLM: %s | Embed: %s",
        settings.ollama_base_url,
        settings.llm_model,
        settings.embed_model,
    )

    yield

    await session_memory.close()
    logger.info("API detenida.")


app = FastAPI(
    title="Telecom Agent API",
    version="1.0.0",
    description="Agente de atención al cliente — Fibra óptica (on-premise)",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
app.include_router(health_detail_router, prefix="/health", tags=["health"])
app.include_router(openai_compat_router)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response: str


class DevChatResponse(BaseModel):
    session_id: str
    response: str
    tool_events: list[dict]
    message_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health():
    return {
        "status": "ok",
        "model": settings.llm_model,
        "embed_model": settings.embed_model,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Endpoint REST principal. Recibe un mensaje y retorna la respuesta del agente."""
    response = await run_session(request.session_id, request.message)
    return ChatResponse(session_id=request.session_id, response=response)


@app.post("/chat/dev", response_model=DevChatResponse, tags=["dev"])
async def chat_dev(request: ChatRequest):
    """
    Endpoint REST modo desarrollador.
    Retorna la respuesta del agente + tool calls ejecutados durante la sesión.
    """
    result = await run_session_dev(request.session_id, request.message)
    return DevChatResponse(
        session_id=request.session_id,
        response=result["response"],
        tool_events=result["tool_events"],
        message_count=result["message_count"],
    )




@app.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket para chat en tiempo real (web/app móvil)."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            async for chunk in run_session_stream(session_id, data):
                await websocket.send_text(chunk)
    except WebSocketDisconnect:
        logger.info("WebSocket desconectado: sesión %s", session_id)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Webhook Twilio para WhatsApp.
    Twilio envía los mensajes como form data y espera una respuesta TwiML.

    TODO (producción): agregar validación de firma Twilio con
    twilio.request_validator.RequestValidator para prevenir spoofing.
    """
    form_data = await request.form()
    from_number: str = form_data.get("From", "")
    body: str = form_data.get("Body", "").strip()

    if not body:
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    session_id = "wa_" + from_number.replace("whatsapp:", "").replace("+", "").replace(" ", "")

    response_text = await run_session(session_id, body)

    safe_response = (
        response_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{safe_response}</Message></Response>"""

    return Response(content=twiml, media_type="application/xml")


@app.post("/audio")
async def transcribe_and_chat(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
):
    """
    Recibe un archivo de audio, lo transcribe con Whisper local y procesa
    el texto resultante como mensaje del chat.
    """
    if _whisper_model is None:
        return {"error": "Modelo Whisper no inicializado."}

    suffix = "." + (audio.filename.rsplit(".", 1)[-1] if audio.filename and "." in audio.filename else "wav")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(await audio.read())
        tmp.flush()
        result = _whisper_model.transcribe(tmp.name, language="es")

    transcript: str = result.get("text", "").strip()
    if not transcript:
        return {"transcript": "", "response": "No pude entender el audio. ¿Podés repetir?"}

    response = await run_session(session_id, transcript)
    return {"transcript": transcript, "response": response}


# ---------------------------------------------------------------------------
# Static files — UI de desarrollador (montar al final para no shadear rutas API)
# ---------------------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
else:
    logger.warning("Directorio app/static/ no encontrado — UI de desarrollador no disponible.")
