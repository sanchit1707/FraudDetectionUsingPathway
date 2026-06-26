"""
idempotency.py
--------------

Dual-mode idempotency store for FlashGuard Agent 6.

Modes
-----
InMemoryIdempotencyStore  (default)
    Python dict.  Zero-dependency, used in unit tests and when REDIS_URL
    is not configured.

RedisIdempotencyStore
    Stores serialised ExecutionResult in Redis with a configurable TTL
    (default 24 h).  Uses redis.asyncio for non-blocking I/O.

Factory
-------
    build_idempotency_service()  reads REDIS_URL from env.

The module-level singletons (store / idempotency) remain so all existing
code that imports them continues to work unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_key(request) -> str:
    """SHA-256 of transaction_id + verdict → 64-char hex string."""
    raw = f"{request.transaction_id}:{request.verdict.value}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _result_to_json(result) -> str:
    """Serialise ExecutionResult to JSON string for Redis storage."""
    from models import ExecutionResult, ActionResult, ExecutionState, ActionStatus, ActionType

    def _convert(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "value"):          # Enum
            return obj.value
        if hasattr(obj, "__dataclass_fields__"):
            return {k: _convert(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [_convert(i) for i in obj]
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        return obj

    return json.dumps(_convert(result))


def _json_to_result(data: str):
    """Deserialise an ExecutionResult from its JSON string."""
    from models import (
        ExecutionResult, ActionResult,
        ExecutionState, ActionStatus, ActionType,
    )

    raw = json.loads(data)

    action_results = [
        ActionResult(
            action_type=ActionType(ar["action_type"]),
            status=ActionStatus(ar["status"]),
            latency_ms=ar["latency_ms"],
            message=ar["message"],
            retries=ar.get("retries", 0),
            response=ar.get("response"),
        )
        for ar in raw.get("action_results", [])
    ]

    def _dt(s):
        return datetime.fromisoformat(s) if s else None

    return ExecutionResult(
        execution_id=raw["execution_id"],
        transaction_id=raw["transaction_id"],
        state=ExecutionState(raw["state"]),
        started_at=_dt(raw["started_at"]),
        completed_at=_dt(raw.get("completed_at")),
        latency_ms=raw["latency_ms"],
        action_results=action_results,
        cached=True,                       # mark as cache hit on deserialise
        success=raw["success"],
        message=raw.get("message", ""),
    )


# ──────────────────────────────────────────────────────────────────────────────
# In-Memory store (original, kept intact)
# ──────────────────────────────────────────────────────────────────────────────

class IdempotencyStore:
    """Original in-memory dict store."""
    def __init__(self) -> None:
        self._cache: dict = {}


class IdempotencyService:
    """Original synchronous service – wraps IdempotencyStore."""

    def __init__(self, store: IdempotencyStore) -> None:
        self.store = store

    def check(self, request) -> Tuple[bool, Optional[object], str]:
        key = _make_key(request)
        if key in self.store._cache:
            return True, self.store._cache[key], key
        return False, None, key

    def store_result(self, key: str, result) -> None:
        self.store._cache[key] = result


# ──────────────────────────────────────────────────────────────────────────────
# Redis store
# ──────────────────────────────────────────────────────────────────────────────

class RedisIdempotencyStore:
    """
    Async idempotency store backed by Redis / Dragonfly.

    Keys are stored as JSON strings with a TTL so they automatically
    expire, preventing unbounded memory growth.
    """

    def __init__(self, redis_url: str, ttl: int = 86400) -> None:
        self._url = redis_url
        self._ttl = ttl
        self._client = None

    async def connect(self) -> None:
        try:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            logger.info("Redis idempotency store connected → %s", self._url)
        except Exception as exc:
            logger.warning(
                "Redis idempotency: connection failed (%s). "
                "Falling back to in-memory dict for this session.",
                exc,
            )
            self._client = None

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get(self, key: str) -> Optional[str]:
        if not self._client:
            return None
        try:
            return await self._client.get(f"idem:{key}")
        except Exception as exc:
            logger.error("Redis GET error: %s", exc)
            return None

    async def set(self, key: str, value: str) -> None:
        if not self._client:
            return
        try:
            await self._client.set(f"idem:{key}", value, ex=self._ttl)
        except Exception as exc:
            logger.error("Redis SET error: %s", exc)


class AsyncIdempotencyService:
    """
    Async-first idempotency service for use with FastAPI.

    Falls back to in-memory dict when Redis is unavailable so the
    application never fails hard due to a Redis outage.
    """

    def __init__(self, redis_store: RedisIdempotencyStore) -> None:
        self._redis = redis_store
        self._fallback: dict = {}          # in-process safety net

    async def check(self, request) -> Tuple[bool, Optional[object], str]:
        key = _make_key(request)

        # 1. Try Redis
        raw = await self._redis.get(key)
        if raw is not None:
            try:
                result = _json_to_result(raw)
                return True, result, key
            except Exception as exc:
                logger.error("Idempotency deserialise error: %s", exc)

        # 2. Try in-memory fallback
        if key in self._fallback:
            return True, self._fallback[key], key

        return False, None, key

    async def store_result(self, key: str, result) -> None:
        # Persist to Redis
        try:
            json_str = _result_to_json(result)
            await self._redis.set(key, json_str)
        except Exception as exc:
            logger.error("Idempotency Redis store error: %s", exc)

        # Always keep in-memory copy as fallback
        self._fallback[key] = result


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def build_idempotency_service():
    """
    Return an AsyncIdempotencyService backed by Redis (if REDIS_URL is set)
    or a plain IdempotencyService backed by in-memory dict.

    The returned object must be `await`-ed via its async methods when used
    from an async context (FastAPI).  The sync IdempotencyService is kept
    for the CLI path.
    """
    redis_url = os.getenv("REDIS_URL", "").strip()
    ttl = int(os.getenv("REDIS_TTL", "86400"))

    if redis_url:
        logger.info("Idempotency: Redis mode (url=%s, ttl=%ds)", redis_url, ttl)
        redis_store = RedisIdempotencyStore(redis_url=redis_url, ttl=ttl)
        return AsyncIdempotencyService(redis_store)

    logger.info("Idempotency: in-memory mode (REDIS_URL not set)")
    store = IdempotencyStore()
    return IdempotencyService(store)


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singletons (backward compatible)
# ──────────────────────────────────────────────────────────────────────────────
store = IdempotencyStore()
idempotency = IdempotencyService(store)
