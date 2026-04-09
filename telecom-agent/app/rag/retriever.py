from functools import lru_cache

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.config import settings
from app.rag.embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def search_knowledge(query: str, k: int | None = None) -> str:
    """
    Busca en la base de conocimiento de Qdrant y retorna los chunks más relevantes
    formateados como string para inyección directa en el contexto del LLM.

    Solo retorna chunks con score de similitud coseno >= rag_score_threshold.
    Si ningún chunk supera el umbral, retorna el mensaje de fallback para que
    el LLM responda que no tiene información (sin inventar).

    Args:
        query: Texto de búsqueda semántica.
        k: Número de chunks a recuperar. Si es None, usa settings.rag_top_k.

    Returns:
        String con los chunks formateados, o mensaje de fallback si no hay resultados relevantes.
    """
    effective_k = k if k is not None else settings.rag_top_k
    threshold = settings.rag_score_threshold

    store = QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )

    try:
        results = store.similarity_search_with_score(query, k=effective_k)
    except Exception:
        # Colección vacía o no creada aún
        return "No se encontró información relevante en la base de conocimiento."

    # Filtrar por umbral de similitud coseno (langchain-qdrant retorna [0,1], mayor=mejor)
    filtered = [(doc, score) for doc, score in results if score >= threshold]

    if not filtered:
        return "No se encontró información relevante en la base de conocimiento."

    parts = []
    for i, (doc, score) in enumerate(filtered, 1):
        doc_name = doc.metadata.get(
            "doc_name",
            doc.metadata.get("source", "desconocido").split("/")[-1].split("\\")[-1],
        )
        headers = [
            doc.metadata[h]
            for h in ("Header1", "Header2", "Header3")
            if doc.metadata.get(h)
        ]
        section = " > ".join(headers)
        source_label = doc_name + (f" — {section}" if section else "")
        parts.append(f"[{i}] Fuente: {source_label}\n{doc.page_content}")

    return "\n\n---\n\n".join(parts)
