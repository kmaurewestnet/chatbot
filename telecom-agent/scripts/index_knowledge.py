#!/usr/bin/env python3
"""
Indexa los documentos de knowledge/ en Qdrant.

Uso desde la raíz del proyecto:
    python scripts/index_knowledge.py           # recrea colección
    python scripts/index_knowledge.py --no-force  # agrega sin borrar colección existente

Requiere:
    - .env con QDRANT_URL, EMBED_MODEL, OLLAMA_BASE_URL configurados
    - Qdrant corriendo (docker compose up -d qdrant)
    - Ollama corriendo con nomic-embed-text instalado
"""
import argparse
import logging
import sys
from pathlib import Path

# Agregar raíz del proyecto al path para importar app.*
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.config import settings
from app.rag.indexer import index_knowledge_base


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa documentos en Qdrant")
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="No recrear la colección si ya existe (solo agrega nuevos docs)",
    )
    args = parser.parse_args()

    force = not args.no_force

    print(f"Qdrant URL:   {settings.qdrant_url}")
    print(f"Colección:    {settings.qdrant_collection}")
    print(f"Embed model:  {settings.embed_model}")
    print(f"Ollama URL:   {settings.ollama_base_url}")
    print(f"Forzar recreación: {force}")
    print()

    count = index_knowledge_base(force=force)
    print(f"\nIndexación completa: {count} chunks en '{settings.qdrant_collection}'")


if __name__ == "__main__":
    main()
