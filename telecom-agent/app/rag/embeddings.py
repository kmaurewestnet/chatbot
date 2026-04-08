from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from app.config import settings

# nomic-embed-text produce vectores de 768 dimensiones
EMBED_DIM = 768


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    """
    Retorna instancia cacheada de OllamaEmbeddings con nomic-embed-text.
    Usar esta función en indexer y retriever para garantizar consistencia de dimensión.
    """
    return OllamaEmbeddings(
        model=settings.embed_model,
        base_url=settings.ollama_base_url,
    )


def verify_embeddings_connectivity() -> None:
    """Verifica que Ollama responde con el modelo de embeddings. Llamar en startup."""
    try:
        emb = get_embeddings()
        result = emb.embed_query("test de conectividad")
        if len(result) != EMBED_DIM:
            raise RuntimeError(
                f"Dimensión inesperada: {len(result)} (esperado {EMBED_DIM}). "
                f"Verificar que el modelo '{settings.embed_model}' esté instalado en Ollama."
            )
    except Exception as exc:
        raise RuntimeError(
            f"No se puede conectar a Ollama en {settings.ollama_base_url} "
            f"con modelo '{settings.embed_model}': {exc}"
        ) from exc
