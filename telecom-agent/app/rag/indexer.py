"""
Indexador de documentos internos en Qdrant.

Uso:
    from app.rag.indexer import index_knowledge_base
    count = index_knowledge_base()

O desde línea de comandos:
    python scripts/index_knowledge.py
"""
import logging
from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import settings
from app.rag.embeddings import EMBED_DIM, get_embeddings

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge"

# Chunk size optimizado para documentos técnicos de telecom:
# - 512 tokens captura un procedimiento completo o una entrada de FAQ
# - 64 tokens de overlap evita partir pasos de un procedimiento
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


def _create_collection(client: QdrantClient, force: bool = False) -> None:
    """Crea la colección en Qdrant. Con force=True, la recrea desde cero."""
    existing = [c.name for c in client.get_collections().collections]

    if settings.qdrant_collection in existing:
        if not force:
            logger.info(
                "Colección '%s' ya existe. Usar force=True para recrear.",
                settings.qdrant_collection,
            )
            return
        logger.info("Eliminando colección existente '%s'...", settings.qdrant_collection)
        client.delete_collection(settings.qdrant_collection)

    logger.info(
        "Creando colección '%s' (dim=%d, distance=COSINE)...",
        settings.qdrant_collection,
        EMBED_DIM,
    )
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )


def index_knowledge_base(force: bool = True) -> int:
    """
    Carga documentos de knowledge/, los divide en chunks y los indexa en Qdrant.

    Args:
        force: Si True, recrea la colección desde cero. Default True para Phase 1.

    Returns:
        Número de chunks indexados.
    """
    if not KNOWLEDGE_DIR.exists():
        raise FileNotFoundError(f"Directorio knowledge/ no encontrado en {KNOWLEDGE_DIR}")

    # Cargar documentos .md y .txt
    loader = DirectoryLoader(
        str(KNOWLEDGE_DIR),
        glob="**/*.md",
        loader_cls=UnstructuredMarkdownLoader,
        show_progress=True,
        silent_errors=True,
    )
    docs = loader.load()

    # También cargar .txt si los hay
    txt_loader = DirectoryLoader(
        str(KNOWLEDGE_DIR),
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
        silent_errors=True,
    )
    docs += txt_loader.load()

    if not docs:
        logger.warning("No se encontraron documentos en %s", KNOWLEDGE_DIR)
        return 0

    logger.info("Documentos cargados: %d", len(docs))

    # Dividir en chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    logger.info("Chunks generados: %d", len(chunks))

    # Crear/recrear colección
    client = QdrantClient(url=settings.qdrant_url)
    _create_collection(client, force=force)

    # Indexar en Qdrant
    QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
    )

    logger.info(
        "Indexados %d chunks en colección '%s'.", len(chunks), settings.qdrant_collection
    )
    return len(chunks)
