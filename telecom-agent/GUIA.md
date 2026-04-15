# 📘 Guía del Proyecto — Telecom Agent (NexoBot)

Agente virtual de atención al cliente para una empresa de fibra óptica, construido con **LangGraph**, **FastAPI**, **Qdrant**, **Redis** y modelos locales de **Ollama**.

---

## Índice

1. [Arquitectura General](#arquitectura-general)
2. [Stack Tecnológico](#stack-tecnológico)
3. [Estructura de Archivos](#estructura-de-archivos)
4. [Configuración y Variables de Entorno](#configuración-y-variables-de-entorno)
5. [Modelos de IA](#modelos-de-ia)
6. [Herramientas del Agente (Tools)](#herramientas-del-agente-tools)
7. [Sistema RAG](#sistema-rag)
8. [Memoria de Sesión](#memoria-de-sesión)
9. [Streaming y Frontend](#streaming-y-frontend)
10. [Despliegue](#despliegue)
11. [Testing](#testing)

---

## Arquitectura General

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend   │◄───►│  FastAPI      │◄───►│  LangGraph  │
│  (Dev UI)   │ WS  │  /chat /ws   │     │  Agent Loop │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                     │
              ┌────────────┼─────────────────────┤
              ▼            ▼                     ▼
         ┌────────┐  ┌──────────┐  ┌───────────────────┐
         │ Redis  │  │  Qdrant  │  │  Ollama (GPU)     │
         │ Sesión │  │  RAG KB  │  │  qwen3.5:9b       │
         └────────┘  └──────────┘  │  Qwen3-Embed-8B   │
                                   └───────────────────┘
```

El flujo principal es:

1. El usuario envía un mensaje vía **WebSocket** (`/ws/{session_id}`) o REST (`/chat`).
2. **runner.py** carga el historial y el `conversation_stage` desde **Redis**.
3. Se construye el estado inicial (`AgentState`) y se invoca el grafo **LangGraph**.
4. El nodo **agent** inyecta dinámicamente fecha, estado del cliente y etapa en el **System Prompt** dé NexoBot.
5. El LLM decide si responder directamente o llamar herramientas (tools).
6. Los resultados se emiten como **NDJSON** por WebSocket (tokens + eventos de tools).
7. Al finalizar, se persiste historial, `customer_id` y `conversation_stage` en Redis.

---

## Stack Tecnológico

| Componente | Tecnología | Propósito |
|---|---|---|
| LLM | `qwen3.5:9b` vía Ollama | Generación de respuestas |
| Embeddings | `qwen3-embedding:8b` vía Ollama | Vectorización de documentos |
| Orquestador | LangGraph | Flujo reactivo agente ↔ tools |
| API | FastAPI + WebSockets | Endpoints REST y streaming |
| Vector DB | Qdrant | Base de conocimiento semántica |
| Sesión | Redis | Historial, customer_id, stage |
| Re-Ranker | FlashRank | Re-ranking post-retrieval RAG |
| Observabilidad | Langfuse | Trazabilidad de LLM y tools |
| Audio | Whisper (local) | Transcripción de voz a texto |
| Frontend | Alpine.js + Vanilla CSS | UI de desarrollo con vista dual |

---

## Estructura de Archivos

```
telecom-agent/
├── app/
│   ├── agent/
│   │   ├── graph.py          # Grafo LangGraph, AgentState, System Prompt dinámico
│   │   └── runner.py         # Coordinador de sesión (run_session, run_session_stream)
│   ├── api/
│   │   ├── main.py           # FastAPI app, endpoints REST/WS/Twilio/Audio
│   │   ├── health_detail.py  # Health check detallado por dependencia
│   │   └── knowledge.py      # CRUD de archivos de conocimiento
│   ├── crm/
│   │   └── client.py         # Cliente HTTP al CRM (modo demo incluido)
│   ├── memory/
│   │   └── session.py        # SessionMemory: historial, customer_id, stage en Redis
│   ├── rag/
│   │   ├── embeddings.py     # OllamaEmbeddings + dimensión dinámica
│   │   ├── indexer.py        # Indexador de documentos → Qdrant
│   │   └── retriever.py      # Búsqueda semántica + FlashRank Re-Ranker
│   ├── tools/
│   │   └── tools.py          # 8 herramientas con Pydantic schemas
│   ├── static/
│   │   ├── index.html        # UI de desarrollo (vista dual)
│   │   ├── app.js            # Lógica Alpine.js + WebSocket streaming
│   │   └── style.css         # Estilos dark mode
│   └── config.py             # Pydantic Settings (carga .env)
├── knowledge/                 # Documentos de la base de conocimiento (.md, .txt)
├── tests/
│   └── test_agent.py         # Tests unitarios e integración
├── scripts/
│   ├── setup.sh              # Script de setup (pull modelos Ollama)
│   └── Modelfile             # Definición de modelo custom Ollama
├── docker-compose.yml        # Stack completo: API + Redis + Qdrant + Langfuse
├── Dockerfile                # Imagen Docker de la API
├── Modelfile                 # Modelo custom base Ollama
├── requirements.txt          # Dependencias Python
└── .env.example              # Variables de entorno de ejemplo
```

---

## Configuración y Variables de Entorno

Copiar `.env.example` → `.env` y configurar:

```env
# Modelos Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=qwen3.5:9b
EMBED_MODEL=qwen3-embedding:8b

# Infraestructura
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379

# CRM (dejar "change_me" para modo demo con datos ficticios)
CRM_API_KEY=change_me

# Langfuse (observabilidad, opcional)
LANGFUSE_PUBLIC_KEY=change_me
LANGFUSE_SECRET_KEY=change_me
```

> **Modo Demo**: Si `CRM_API_KEY=change_me`, el CRM retorna datos ficticios sin conexión externa. Ideal para desarrollo.

---

## Modelos de IA

### LLM: `qwen3.5:9b`
- Modelo de lenguaje principal para generación de respuestas.
- Se ejecuta en Ollama local (GPU recomendada).
- `temperature=0.3`, `num_ctx=8192`.

### Embeddings: `qwen3-embedding:8b`
- Modelo de embeddings para vectorización de documentos RAG.
- La dimensión se detecta **dinámicamente** al arrancar (no está hardcodeada).

### Whisper: `base`
- Modelo local de transcripción de audio (OpenAI Whisper).
- Se carga en el startup de la API.

---

## Herramientas del Agente (Tools)

Todas las herramientas tienen **Pydantic schemas** con `args_schema` para tipado fuerte y validación estricta de parámetros, evitando alucinaciones del LLM.

| Tool | Schema | Propósito |
|---|---|---|
| `marcar_etapa_conversacion` | `Literal['recepcion', 'verificacion_dni', ...]` | Etiqueta la etapa actual de la conversación |
| `consultar_cliente_dni` | `dni: str` | Consulta datos del cliente en el CRM |
| `verificar_estado_red` | `zona: str` | Verifica cortes masivos en una zona |
| `diagnosticar_router_cliente` | `cliente_id: str` | Diagnóstico remoto del router/ONT |
| `registrar_reclamo` | `cliente_id, tipo (Literal), descripcion` | Crea ticket de reclamo en el CRM |
| `generar_visita_tecnica` | `cliente_id, motivo (Literal)` | Genera orden de visita domiciliaria |
| `registrar_solicitud_baja` | `cliente_id, motivo` | Registra solicitud de cancelación |
| `buscar_en_base_conocimiento` | `query: str` | Búsqueda semántica RAG + Re-Ranking |

---

## Sistema RAG

### Pipeline de Indexación (`indexer.py`)

```
knowledge/*.md → MarkdownHeaderSplitter → RecursiveCharSplitter → Qdrant
```

1. Carga archivos `.md` y `.txt` del directorio `knowledge/`.
2. Divide por headers Markdown (preserva contexto de sección).
3. Subdivide secciones largas con `RecursiveCharacterTextSplitter`.
4. Enriquece metadata con nombre de archivo y headers de sección.
5. Indexa en Qdrant con embeddings dinámicos.

### Pipeline de Retrieval (`retriever.py`)

```
Query → Qdrant (top k*2) → FlashRank Re-Ranker (top k) → Formato texto
```

1. Recupera `k*2` documentos iniciales de Qdrant (búsqueda semántica).
2. Aplica **FlashRank** como re-ranker (modelo liviano, sin PyTorch pesado).
3. Selecciona los `top_k` mejores documentos por relevancia.
4. Formatea los chunks con número, fuente y sección para inyectar en el prompt.

---

## Memoria de Sesión

Redis almacena 3 claves por sesión (TTL: 24 horas):

```
session:{session_id}:messages     → Historial serializado (JSON)
session:{session_id}:customer_id  → ID del cliente verificado
session:{session_id}:stage        → Etapa actual de la conversación
```

La etapa (`stage`) permite:
- Que el prompt dinámico del agente sepa en qué punto está la conversación al retomarla.
- Que el frontend muestre el estado actual en el panel de "Cerebro de NexoBot".

---

## Streaming y Frontend

### Backend (NDJSON por WebSocket)

El endpoint `/ws/{session_id}` emite eventos JSON-Lines en tiempo real:

```json
{"type": "chunk", "content": "Hola, "}
{"type": "chunk", "content": "¿en qué "}
{"type": "tool_start", "tool_name": "consultar_cliente_dni"}
{"type": "tool_end", "tool_name": "consultar_cliente_dni", "result": "..."}
{"type": "chunk", "content": "te puedo ayudar?"}
```

### Frontend (Vista Dual)

La UI de desarrollo (`/ui`) tiene dos paneles:

- **Panel izquierdo**: Chat clásico usuario ↔ NexoBot (texto en tiempo real).
- **Panel derecho**: "Cerebro de NexoBot" — muestra en vivo:
  - Estado de la conversación (`recepcion`, `verificacion_dni`, etc.)
  - Cada tool ejecutada con su resultado
  - Spinner cuando una tool está en ejecución.

### System Prompt Dinámico

El prompt de NexoBot usa:
- **Etiquetas XML** (`<identity>`, `<limites_tecnicos>`, etc.) para segmentación cognitiva.
- **Inyección de estado**: fecha actual, verificación de cliente, etapa de la conversación.
- **Few-Shot**: un ejemplo completo de interacción ideal incluido en el prompt.

---

## Despliegue

### Con Docker Compose (recomendado)

```bash
# 1. Copiar y configurar .env
cp .env.example .env

# 2. Asegurar que Ollama está corriendo en el host con los modelos
ollama pull qwen3.5:9b
ollama pull qwen3-embedding:8b

# 3. Levantar todo el stack
docker compose up --build -d

# 4. Acceder
#    API:       http://localhost:8000
#    Dev UI:    http://localhost:8000/ui
#    Qdrant:    http://localhost:6333/dashboard
#    Langfuse:  http://localhost:3000
```

### Primera indexación

Tras subir archivos al directorio `knowledge/`, re-indexar desde la UI de desarrollo (botón "Re-indexar") o bien vía API:

```bash
curl -X POST http://localhost:8000/knowledge/reindex
```

> **IMPORTANTE**: Si cambias el modelo de embeddings, debes recrear la colección en Qdrant (la re-indexación con `force=True` lo hace automáticamente).

---

## Testing

```bash
# Instalar dependencias de test
pip install pytest pytest-asyncio fakeredis[aioredis]

# Ejecutar tests
pytest tests/test_agent.py -v
```

Los tests cubren:
- **Registry de tools**: verifica que las 8 herramientas están registradas con nombres correctos.
- **RAG retriever**: verifica fallback, formateo de resultados y headers de sección.
- **CRM errors**: verifica manejo graceful de errores HTTP.
- **Session memory**: persistencia y recuperación con fakeredis.
- **Config**: validación de defaults de Settings.

---

## Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Health check básico |
| `GET` | `/health/detail` | Estado detallado de Redis, Qdrant, Ollama |
| `POST` | `/chat` | Chat REST (mensaje → respuesta) |
| `POST` | `/chat/dev` | Chat REST modo dev (incluye tool events) |
| `WS` | `/ws/{session_id}` | Chat WebSocket con streaming NDJSON |
| `POST` | `/webhook/whatsapp` | Webhook Twilio para WhatsApp |
| `POST` | `/audio` | Transcripción Whisper + chat |
| `GET` | `/knowledge` | Listar archivos de conocimiento |
| `POST` | `/knowledge` | Subir archivo de conocimiento |
| `GET` | `/knowledge/{name}` | Ver contenido de un archivo |
| `PUT` | `/knowledge/{name}` | Editar archivo de conocimiento |
| `DELETE` | `/knowledge/{name}` | Borrar archivo |
| `POST` | `/knowledge/reindex` | Iniciar re-indexación |
| `GET` | `/knowledge/reindex/{id}` | Estado de re-indexación |
| `GET` | `/ui` | Interfaz de desarrollador |
