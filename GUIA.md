# Guía de instalación y uso — Telecom Agent

Chatbot de atención al cliente para ISP de fibra óptica.  
Corre 100% on-premise: sin APIs de nube, sin datos que salgan del servidor.

---

## Requisitos previos

Antes de empezar, instalá estas herramientas en el servidor host:

| Herramienta | Versión mínima | Para qué se usa |
|---|---|---|
| [Docker](https://docs.docker.com/get-docker/) | 24+ | Corre todos los servicios |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.20+ | Orquesta los contenedores |
| [Ollama](https://ollama.com/download) | 0.3+ | Corre el LLM y embeddings localmente |
| Python | 3.11+ | Solo si querés desarrollar/testear sin Docker |

**Verificar que estén instalados:**
```bash
docker --version
docker compose version
ollama --version
python3 --version
```

---

## Paso 1 — Clonar el repositorio

```bash
git clone https://github.com/kmaurewestnet/chatbot.git
cd chatbot/telecom-agent
```

---

## Paso 2 — Descargar los modelos de IA

Esto se hace **en el host** (no dentro de Docker), porque Ollama usa la GPU del host.

```bash
# Modelo de lenguaje principal (~9 GB)
ollama pull qwen2.5:14b

# Modelo de embeddings para RAG (~270 MB)
ollama pull nomic-embed-text
```

> Los modelos se descargan una sola vez. El proceso puede tardar varios minutos según la velocidad de descarga.

---

## Paso 3 — Configurar las variables de entorno

```bash
cp .env.example .env
```

Abrí `.env` con cualquier editor y completá los valores:

```env
# --- Obligatorios para producción ---
CRM_BASE_URL=https://tu-crm-interno.local/api/v1
CRM_API_KEY=tu_api_key_real

NET_DIAGNOSTICS_URL=https://tu-api-red.local/api
NET_DIAGNOSTICS_KEY=tu_api_key_real

# --- Seguridad de Langfuse (podés poner cualquier string largo) ---
POSTGRES_PASSWORD=una_contraseña_segura
LANGFUSE_NEXTAUTH_SECRET=un_string_secreto_largo

# --- El resto puede quedarse con los valores por defecto ---
```

> Para pruebas locales podés dejar `CRM_API_KEY=change_me` y `NET_DIAGNOSTICS_KEY=change_me`.  
> El agente funcionará pero las herramientas CRM devolverán errores simulados.

---

## Paso 4 — Levantar todos los servicios

```bash
docker compose up -d --build
```

Este comando construye la imagen de la API e inicia los 5 servicios:

| Servicio | Puerto | Descripción |
|---|---|---|
| `api` | **8000** | FastAPI — el agente y todos los endpoints |
| `redis` | 6379 | Memoria de sesión (historial de chat) |
| `qdrant` | 6333 | Base de datos vectorial (RAG) |
| `postgres` | — | Base de datos de Langfuse |
| `langfuse` | 3000 | Observabilidad del LLM (opcional) |

**Verificar que todo levantó:**
```bash
docker compose ps
```
Todos los servicios deben aparecer como `running`.

**Ver logs de la API en tiempo real:**
```bash
docker compose logs -f api
```

---

## Paso 5 — Indexar la base de conocimiento

Antes de chatear, los documentos de `knowledge/` deben cargarse en Qdrant:

```bash
docker compose exec api python scripts/index_knowledge.py
```

Deberías ver algo como:
```
Documentos cargados: 4
Chunks generados: 47
Indexados 47 chunks en colección 'telecom_knowledge'.
```

> Repetí este comando cada vez que modifiques archivos en `knowledge/`.

---

## Usar el sistema

### Interfaz de desarrollador (recomendado para pruebas)

Abrí en el navegador:
```
http://localhost:8000/ui
```

Desde ahí podés:
- Chatear directamente con el agente
- Ver los tool calls que ejecutó el agente (toggle "Tool calls")
- Gestionar los archivos de la knowledge base (ver, editar, subir, borrar)
- Re-indexar la knowledge base con un clic
- Ver el estado de Redis, Qdrant y Ollama en tiempo real

---

### Chat por API (REST)

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "prueba-001", "message": "Hola, no tengo internet"}'
```

Respuesta:
```json
{
  "session_id": "prueba-001",
  "response": "Hola, lamentamos el inconveniente. Para ayudarte necesito verificar tu cuenta. ¿Me podés dar tu DNI?"
}
```

---

### Chat modo desarrollador (con tool calls visibles)

```bash
curl -X POST http://localhost:8000/chat/dev \
  -H "Content-Type: application/json" \
  -d '{"session_id": "prueba-002", "message": "Mi DNI es 30000001"}'
```

Respuesta incluye los tools que ejecutó el agente:
```json
{
  "session_id": "prueba-002",
  "response": "Encontré tu cuenta, Juan...",
  "tool_events": [
    {
      "tool_name": "consultar_cliente_dni",
      "args": {"dni": "30000001"},
      "result": "{\"cliente_id\": \"CLI-001\", \"nombre\": \"Juan...\"}"
    }
  ],
  "message_count": 4
}
```

---

### WebSocket (streaming)

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/mi-sesion-123");
ws.onmessage = (e) => console.log(e.data);
ws.send("Quiero dar de baja el servicio");
```

---

### Health check

```bash
# Estado básico
curl http://localhost:8000/health

# Estado detallado por dependencia
curl http://localhost:8000/health/detail
```

---

## Gestión de la knowledge base

Los documentos están en `telecom-agent/knowledge/`. Son archivos `.md` o `.txt` que el agente consulta cuando necesita información sobre planes, precios, políticas, etc.

### Agregar o editar documentos

**Opción A — Desde la UI:**
1. Abrí `http://localhost:8000/ui`
2. En el panel derecho, hacé clic en "Subir" o seleccioná un archivo para editar
3. Guardá y hacé clic en "Re-indexar"

**Opción B — Manualmente:**
```bash
# Editar un archivo existente
nano telecom-agent/knowledge/planes_y_precios.md

# Re-indexar para que los cambios tomen efecto
docker compose exec api python scripts/index_knowledge.py
```

---

## Comandos de mantenimiento

```bash
# Ver logs de todos los servicios
docker compose logs

# Ver logs solo de la API
docker compose logs -f api

# Reiniciar solo la API (sin rebuilding)
docker compose restart api

# Rebuilding completo (después de cambiar código)
docker compose up -d --build api

# Detener todo
docker compose down

# Detener y borrar volúmenes (BORRA datos de Redis y Qdrant)
docker compose down -v

# Ver uso de recursos
docker stats
```

---

## Correr los tests

```bash
# Instalar dependencias de testing (una sola vez)
pip install -r telecom-agent/requirements.txt

# Correr todos los tests
cd telecom-agent
pytest tests/ -v

# Solo tests unitarios (sin infraestructura)
pytest tests/ -k "unit" -v

# Tests async con reporte detallado
pytest tests/ -v --asyncio-mode=auto
```

---

## Solución de problemas frecuentes

**La API no responde:**
```bash
docker compose logs api | tail -30
# Si dice "Ollama no disponible", verificar:
curl http://localhost:11434/api/tags
# Si no responde, iniciar Ollama: ollama serve
```

**El agente no encuentra información en la knowledge base:**
```bash
# Re-indexar
docker compose exec api python scripts/index_knowledge.py
# Verificar colección en Qdrant
curl http://localhost:6333/collections/telecom_knowledge
```

**Redis no conecta:**
```bash
docker compose restart redis
docker compose logs redis
```

**Qdrant no conecta:**
```bash
docker compose restart qdrant
# Verificar dashboard: http://localhost:6333/dashboard
```

**Cambié el código y no se actualizó:**
```bash
docker compose up -d --build api
```

---

## Servicios web disponibles

| URL | Descripción |
|---|---|
| `http://localhost:8000/ui` | Interfaz de desarrollador |
| `http://localhost:8000/docs` | Documentación interactiva de la API (Swagger) |
| `http://localhost:6333/dashboard` | Dashboard de Qdrant (ver colecciones y vectores) |
| `http://localhost:3000` | Langfuse (trazabilidad del LLM) |
