from functools import lru_cache

from langchain_qdrant import QdrantVectorStore
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.document_compressors.flashrank_rerank import FlashrankRerank
from qdrant_client import QdrantClient

from app.config import settings
from app.rag.embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def search_knowledge(query: str, k: int | None = None) -> str:
    """
    Busca en la base de conocimiento de Qdrant, aplica Re-Ranking usando FlashRank,
    y retorna los chunks más relevantes formateados para el prompt.
    """
    effective_k = k if k is not None else settings.rag_top_k

    store = QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )

    try:
        # Recuperamos una muestra más grande para que el Re-Ranker tenga de donde elegir
        base_retriever = store.as_retriever(search_kwargs={"k": effective_k * 2})
        compressor = FlashrankRerank(top_n=effective_k)
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=base_retriever
        )
        compressed_docs = compression_retriever.invoke(query)
    except Exception:
        # Fallback si Qdrant falla, colección vacía, o Flashrank falla
        return "No se encontró información relevante en la base de conocimiento."

    if not compressed_docs:
        return "No se encontró información relevante en la base de conocimiento."

    parts = []
    for i, doc in enumerate(compressed_docs, 1):
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
