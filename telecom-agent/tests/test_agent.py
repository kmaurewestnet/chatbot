"""
Tests del agente de atención al cliente.

Categorías:
  - Unit: sin infraestructura externa (mocks)
  - Integration: con mocks de CRM y Qdrant
  - Smoke: requieren infraestructura real (marcados con @pytest.mark.e2e)
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Unit: tools registry
# ---------------------------------------------------------------------------

def test_tools_registered():
    """Verificar que los 7 tools están registrados con los nombres correctos."""
    from app.tools.tools import ALL_TOOLS

    tool_names = {t.name for t in ALL_TOOLS}
    assert "consultar_cliente_dni" in tool_names
    assert "verificar_estado_red" in tool_names
    assert "diagnosticar_router_cliente" in tool_names
    assert "registrar_reclamo" in tool_names
    assert "generar_visita_tecnica" in tool_names
    assert "registrar_solicitud_baja" in tool_names
    assert "buscar_en_base_conocimiento" in tool_names
    assert len(ALL_TOOLS) == 7


def test_tools_have_docstrings():
    """Cada tool debe tener descripción (usada por el LLM para decidir cuándo llamarla)."""
    from app.tools.tools import ALL_TOOLS

    for t in ALL_TOOLS:
        assert t.description, f"Tool '{t.name}' no tiene descripción"


# ---------------------------------------------------------------------------
# Unit: RAG retriever con colección vacía
# ---------------------------------------------------------------------------

def test_rag_retriever_empty_collection():
    """El retriever debe retornar mensaje de fallback si no hay resultados."""
    with patch("app.rag.retriever.QdrantVectorStore") as mock_store_cls:
        mock_store_cls.return_value.similarity_search.return_value = []

        from app.rag.retriever import search_knowledge

        result = search_knowledge("planes disponibles")
        assert "No se encontró" in result


def test_rag_retriever_formats_results():
    """El retriever debe formatear los chunks con número y fuente."""
    from langchain_core.documents import Document

    mock_docs = [
        Document(page_content="Plan básico 100 Mbps", metadata={"source": "knowledge/planes_y_precios.md"}),
        Document(page_content="Plan hogar 300 Mbps", metadata={"source": "knowledge/planes_y_precios.md"}),
    ]

    with patch("app.rag.retriever.QdrantVectorStore") as mock_store_cls:
        mock_store_cls.return_value.similarity_search.return_value = mock_docs

        from app.rag import retriever
        # Recargar para que el patch tenga efecto
        import importlib
        importlib.reload(retriever)

        with patch.object(retriever, "get_qdrant_client", return_value=MagicMock()), \
             patch.object(retriever, "get_embeddings", return_value=MagicMock()):
            result = retriever.search_knowledge("planes")

    assert "[1]" in result or "Plan" in result


# ---------------------------------------------------------------------------
# Unit: RAG tool
# ---------------------------------------------------------------------------

def test_buscar_en_base_conocimiento_tool():
    """El tool RAG debe pasar el query a search_knowledge y retornar el resultado."""
    with patch("app.tools.tools.search_knowledge") as mock_search:
        mock_search.return_value = "Plan básico: 100 Mbps por $X.XXX"

        from app.tools.tools import buscar_en_base_conocimiento

        result = buscar_en_base_conocimiento.invoke({"query": "cuánto cuesta el plan básico"})
        assert "100 Mbps" in result
        mock_search.assert_called_once_with("cuánto cuesta el plan básico")


# ---------------------------------------------------------------------------
# Unit: tools CRM con errores HTTP
# ---------------------------------------------------------------------------

def test_consultar_cliente_dni_http_error():
    """Si el CRM falla, el tool retorna dict con clave 'error'."""
    import httpx

    with patch("app.crm.client.httpx.Client") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = (
            httpx.HTTPStatusError("Service Unavailable", request=MagicMock(), response=mock_response)
        )

        from app.tools.tools import consultar_cliente_dni

        result = consultar_cliente_dni.invoke({"dni": "12345678"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Integration: session memory con fakeredis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_memory_persist_and_retrieve():
    """Guardar y recuperar historial de mensajes en Redis (fakeredis)."""
    import fakeredis.aioredis as fakeredis
    from langchain_core.messages import AIMessage, HumanMessage

    from app.memory.session import SessionMemory

    mem = SessionMemory()
    mem.redis = fakeredis.FakeRedis(decode_responses=True)

    messages = [
        HumanMessage(content="Hola, no tengo internet"),
        AIMessage(content="Entendido. ¿Me podés dar tu DNI para verificar tu cuenta?"),
    ]

    await mem.save_history("test-session-001", messages)
    recovered = await mem.get_history("test-session-001")

    assert len(recovered) == 2
    assert recovered[0].content == "Hola, no tengo internet"
    assert recovered[1].content == "Entendido. ¿Me podés dar tu DNI para verificar tu cuenta?"


@pytest.mark.asyncio
async def test_session_memory_customer_id():
    """Persistir y recuperar customer_id en Redis."""
    import fakeredis.aioredis as fakeredis

    from app.memory.session import SessionMemory

    mem = SessionMemory()
    mem.redis = fakeredis.FakeRedis(decode_responses=True)

    await mem.save_customer_id("test-session-002", "CLIENTE-001")
    cid = await mem.get_customer_id("test-session-002")
    assert cid == "CLIENTE-001"


@pytest.mark.asyncio
async def test_session_memory_empty_session():
    """Una sesión nueva debe retornar lista vacía e None."""
    import fakeredis.aioredis as fakeredis

    from app.memory.session import SessionMemory

    mem = SessionMemory()
    mem.redis = fakeredis.FakeRedis(decode_responses=True)

    history = await mem.get_history("nueva-sesion-xyz")
    cid = await mem.get_customer_id("nueva-sesion-xyz")

    assert history == []
    assert cid is None


# ---------------------------------------------------------------------------
# Integration: run_session con grafo mockeado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_session_returns_string():
    """run_session debe retornar un string con la respuesta del agente."""
    import fakeredis.aioredis as fakeredis
    from langchain_core.messages import AIMessage

    mock_result = {
        "messages": [
            AIMessage(content="Hola, soy el agente de atención al cliente. ¿En qué te puedo ayudar?")
        ],
        "customer_id": None,
    }

    with patch("app.agent.runner.compiled_graph") as mock_graph, \
         patch("app.agent.runner.session_memory") as mock_mem:

        mock_graph.ainvoke = AsyncMock(return_value=mock_result)
        mock_mem.get_history = AsyncMock(return_value=[])
        mock_mem.get_customer_id = AsyncMock(return_value=None)
        mock_mem.save_history = AsyncMock()
        mock_mem.save_customer_id = AsyncMock()

        from app.agent.runner import run_session

        response = await run_session("test-001", "Hola")
        assert isinstance(response, str)
        assert len(response) > 0


# ---------------------------------------------------------------------------
# Unit: config
# ---------------------------------------------------------------------------

def test_settings_defaults():
    """Los defaults de Settings deben ser válidos."""
    from app.config import Settings

    s = Settings(
        crm_api_key="test",
        net_diagnostics_key="test",
        langfuse_public_key="test",
        langfuse_secret_key="test",
        postgres_password="test",
        langfuse_nextauth_secret="test",
        _env_file=None,
    )
    assert s.llm_model == "qwen2.5:14b"
    assert s.embed_model == "nomic-embed-text"
    assert s.qdrant_collection == "telecom_knowledge"
    assert s.redis_ttl_seconds == 86400
