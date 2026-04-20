#!/bin/bash
# Setup inicial del proyecto Telecom Agent.
# Ejecutar desde la raíz del proyecto: bash scripts/setup.sh

set -e

echo "=== Telecom Agent — Setup inicial ==="

# 1. Verificar que Ollama esté corriendo
if ! curl -s http://localhost:11434 > /dev/null; then
  echo "ERROR: Ollama no está corriendo en http://localhost:11434"
  echo "Iniciarlo con: ollama serve"
  exit 1
fi

# 2. Descargar modelos Ollama
echo ""
echo "[1/5] Descargando modelo LLM: qwen3.5:9b"
ollama pull qwen3.5:9b

echo ""
echo "[2/5] Descargando modelo de embeddings: qwen3-embedding:8b"
ollama pull qwen3-embedding:8b

# 3. Crear modelo customizado con Modelfile
echo ""
echo "[3/5] Creando modelo telecom-agent con configuración personalizada..."
ollama create telecom-agent -f scripts/Modelfile

# 4. Copiar .env.example a .env si no existe
if [ ! -f .env ]; then
  echo ""
  echo "[4/5] Creando .env desde .env.example..."
  cp .env.example .env
  echo "IMPORTANTE: Editá .env con tus valores reales antes de continuar."
else
  echo ""
  echo "[4/5] .env ya existe — no se sobreescribe."
fi

# 5. Levantar infraestructura (sin la API por ahora)
echo ""
echo "[5/5] Iniciando infraestructura (Redis, Qdrant, Langfuse, Postgres)..."
docker compose up -d redis qdrant postgres langfuse

echo ""
echo "Esperando 10 segundos para que los servicios estén listos..."
sleep 10

# 6. Indexar base de conocimiento
echo ""
echo "[6/6] Indexando documentos en Qdrant..."
python scripts/index_knowledge.py

# 7. Levantar API
echo ""
echo "Iniciando API..."
docker compose up -d api

echo ""
echo "=== Setup completo ==="
echo ""
echo "Servicios disponibles:"
echo "  API:      http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo "  Qdrant:   http://localhost:6333/dashboard"
echo "  Langfuse: http://localhost:3000"
echo ""
echo "Smoke test:"
echo "  curl -X POST http://localhost:8000/chat \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"session_id\": \"test-001\", \"message\": \"Hola, no tengo internet\"}'"
