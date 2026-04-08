"""
Memoria de sesión respaldada en Redis.

Keys por sesión:
  session:{session_id}:messages     → historial serializado (JSON)
  session:{session_id}:customer_id  → ID del cliente identificado (string)

TTL: 24 horas desde la última escritura (configurado en settings).
"""
import json
import logging
from typing import Optional

import redis.asyncio as aioredis
from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

from app.config import settings

logger = logging.getLogger(__name__)


class SessionMemory:
    def __init__(self) -> None:
        self.redis: aioredis.Redis = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
        self.ttl = settings.redis_ttl_seconds

    def _msg_key(self, session_id: str) -> str:
        return f"session:{session_id}:messages"

    def _cid_key(self, session_id: str) -> str:
        return f"session:{session_id}:customer_id"

    async def get_history(self, session_id: str) -> list[BaseMessage]:
        raw = await self.redis.get(self._msg_key(session_id))
        if not raw:
            return []
        try:
            return messages_from_dict(json.loads(raw))
        except Exception:
            logger.warning("No se pudo deserializar historial para sesión %s", session_id)
            return []

    async def save_history(self, session_id: str, messages: list[BaseMessage]) -> None:
        serialized = json.dumps(messages_to_dict(messages))
        await self.redis.setex(self._msg_key(session_id), self.ttl, serialized)

    async def get_customer_id(self, session_id: str) -> Optional[str]:
        return await self.redis.get(self._cid_key(session_id))

    async def save_customer_id(self, session_id: str, customer_id: str) -> None:
        await self.redis.setex(self._cid_key(session_id), self.ttl, customer_id)

    async def clear_session(self, session_id: str) -> None:
        await self.redis.delete(self._msg_key(session_id), self._cid_key(session_id))

    async def close(self) -> None:
        await self.redis.aclose()


# Singleton
session_memory = SessionMemory()
