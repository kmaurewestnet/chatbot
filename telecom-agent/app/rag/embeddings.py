from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from app.config import settings

@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    """
    Retorna instancia cacheada de OllamaEmbeddings.
    Usar esta función en indexer y retriever para garantizar consistencia.
    """
    return OllamaEmbeddings(
        model=settings.embed_model,
        base_url=settings.ollama_base_url,
    )


@lru_cache(maxsize=1)
def get_embedding_dimension() -> int:
    """
    Obtiene dinámicamente la dimensión del modelo de embeddings configurado.
    """
    emb = get_embeddings()
    result = emb.embed_query("test de dimensión")
    return len(result)


def verify_embeddings_connectivity() -> None:
    """Verifica que Ollama responde con el modelo de embeddings. Llamar en startup."""
    try:
        dim = get_embedding_dimension()
        if dim <= 0:
            raise RuntimeError(f"Dimensión inválida devuelta: {dim}")
    except Exception as exc:
        raise RuntimeError(
            f"No se puede conectar a Ollama en {settings.ollama_base_url} "
            f"con modelo '{settings.embed_model}': {exc}"
        ) from exc
