from functools import lru_cache

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.config import settings
from app.rag.embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def search_knowledge(query: str, k: int = 4) -> str:
    """
    Busca en la base de conocimiento de Qdrant y retorna los chunks más relevantes
    formateados como string para inyección directa en el contexto del LLM.

    Args:
        query: Texto de búsqueda semántica.
        k: Número de chunks a retornar (default 4).

    Returns:
        String con los chunks formateados, o mensaje de fallback si no hay resultados.
    """
    store = QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )

    try:
        docs = store.similarity_search(query, k=k)
    except Exception:
        # Colección vacía o no creada aún
        return "No se encontró información relevante en la base de conocimiento."

    if not docs:
        return "No se encontró información relevante en la base de conocimiento."

    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "desconocido")
        # Mostrar solo el nombre del archivo, no la ruta completa
        source_name = source.split("/")[-1].split("\\")[-1]
        parts.append(f"[{i}] Fuente: {source_name}\n{doc.page_content}")

    return "\n\n---\n\n".join(parts)
