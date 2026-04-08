# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`telecom-agent/` is a fully on-premise customer support chatbot for a fiber-optic ISP (Argentina). It uses a LangGraph agent backed by a local Ollama LLM (`qwen2.5:14b`), with RAG over internal knowledge docs, Redis session memory, and CRM/network-diagnostics API integrations. All Spanish-language responses use Argentine Rioplatense register.

## Commands

### Run (Docker)
```bash
cd telecom-agent
docker compose up -d                          # Start all services
docker compose up -d --build                  # Rebuild API image
docker compose logs -f api                    # Follow API logs
```

### Run locally (development)
```bash
cd telecom-agent
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.api.main:app --reload --port 8000
```

### Tests
```bash
cd telecom-agent
pytest tests/                                 # All tests
pytest tests/test_agent.py -k "unit"          # Filter by name
pytest tests/ -v --asyncio-mode=auto          # Verbose with async
```

### Index knowledge base
```bash
cd telecom-agent
python scripts/index_knowledge.py             # Recreate collection
python scripts/index_knowledge.py --no-force  # Append without recreating
```

### Pull Ollama models (host, not container)
```bash
ollama pull qwen2.5:14b
ollama pull nomic-embed-text
```

## Architecture

```
FastAPI (app/api/main.py)
  └─ run_session() ─── app/agent/runner.py
       ├─ Redis history ─── app/memory/session.py
       └─ LangGraph graph ─ app/agent/graph.py
            ├─ agent_node: ChatOllama + bind_tools(ALL_TOOLS)
            └─ ToolNode ──── app/tools/tools.py
                 ├─ CRM tools ─── app/crm/client.py  (httpx, sync)
                 └─ RAG tool  ─── app/rag/retriever.py → Qdrant
```

**LangGraph loop:** `agent → should_continue → tools → agent → … → END`. The graph is stateless; full message history is injected per invocation from Redis.

**RAG pipeline:** `knowledge/*.md` files are chunked (512 tokens, 64 overlap) by `app/rag/indexer.py` and stored in Qdrant collection `telecom_knowledge`. `nomic-embed-text` via Ollama provides embeddings (`app/rag/embeddings.py`).

**Session memory:** Redis keys `session:{id}:messages` and `session:{id}:customer_id` with 24h TTL. Messages serialized via LangChain `messages_to_dict`.

**Config:** All settings in `app/config.py` via `pydantic-settings`. Override via `.env` file or environment variables.

## Services (docker-compose)

| Service | Port | Purpose |
|---------|------|---------|
| api | 8000 | FastAPI + Whisper |
| redis | 6379 | Session memory |
| qdrant | 6333/6334 | Vector store (REST/gRPC) |
| postgres | — | Langfuse backend DB |
| langfuse | 3000 | LLM observability UI |

Ollama runs on the **host** (GPU access). Docker containers reach it via `host.docker.internal:11434`.

## API Endpoints

- `POST /chat` — REST: `{session_id, message}` → `{session_id, response}`
- `WS /ws/{session_id}` — WebSocket streaming
- `POST /webhook/whatsapp` — Twilio TwiML webhook (form data)
- `POST /audio` — Whisper transcription + chat (`multipart/form-data`)
- `GET /health` — Health check

## Agent Tools (ALL_TOOLS)

Seven LangChain `@tool` functions in `app/tools/tools.py`:
1. `consultar_cliente_dni` — CRM lookup by DNI (always first step)
2. `verificar_estado_red` — Check mass network outage by zone
3. `diagnosticar_router_cliente` — Remote router/ONT diagnostics
4. `registrar_reclamo` — Create support ticket
5. `generar_visita_tecnica` — Schedule technician visit
6. `registrar_solicitud_baja` — Register service cancellation
7. `buscar_en_base_conocimiento` — Semantic search over knowledge docs

## Knowledge Base

Markdown files in `knowledge/` are the only editable knowledge source. After editing any `.md` file, re-run `python scripts/index_knowledge.py` to update Qdrant.

## Testing Patterns

- Unit tests mock external dependencies (CRM, Qdrant, Redis)
- Integration tests use `fakeredis` for `SessionMemory`
- Tests marked `@pytest.mark.e2e` require live infrastructure
- `pytest-asyncio` handles async tests; use `@pytest.mark.asyncio`

## Key Configuration

Required `.env` values (see `app/config.py` for full list):
- `CRM_BASE_URL`, `CRM_API_KEY` — internal CRM
- `NET_DIAGNOSTICS_URL`, `NET_DIAGNOSTICS_KEY` — network diagnostics API
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — observability (optional)
- `POSTGRES_PASSWORD`, `LANGFUSE_NEXTAUTH_SECRET` — Langfuse DB
