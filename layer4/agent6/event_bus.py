"""
event_bus.py
------------

Dual-mode event bus for FlashGuard Agent 6.

Modes
-----
InMemoryEventBus  (default)
    Topic-keyed dict of handler lists.  Zero-dependency, used in unit tests
    and when KAFKA_BOOTSTRAP_SERVERS is not set.

KafkaEventBus
    Publishes every EventMessage as a JSON record to a Kafka topic via
    aiokafka.AIOKafkaProducer.  Falls back to InMemoryEventBus on any
    connection error.

Factory
-------
    build_event_bus()   reads KAFKA_BOOTSTRAP_SERVERS from env;
                        returns KafkaEventBus or InMemoryEventBus.

The module-level singleton `event_bus` is an InMemoryEventBus so all
existing code that imports it continues to work unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List

from models import EventMessage, EventType

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# In-Memory implementation (original, kept intact)
# ──────────────────────────────────────────────────────────────────────────────

class InMemoryEventBus:
    """Simple synchronous pub/sub bus.  No external dependencies."""

    def __init__(self) -> None:
        self.s: Dict[Any, List[Callable]] = defaultdict(list)

    def subscribe(self, topic: EventType, handler: Callable) -> None:
        self.s[topic].append(handler)

    def publish(self, event: EventMessage) -> None:
        for h in self.s[event.topic]:
            try:
                h(event)
            except Exception as exc:
                logger.error("EventBus handler error: %s", exc)

    def publish_simple(
        self,
        topic: EventType,
        key: str,
        payload: Dict[str, Any],
    ) -> None:
        self.publish(
            EventMessage(
                topic=topic,
                key=key,
                payload=payload,
                timestamp=datetime.utcnow(),
            )
        )

    # Async stubs so callers can await either bus type uniformly
    async def async_publish_simple(
        self,
        topic: EventType,
        key: str,
        payload: Dict[str, Any],
    ) -> None:
        self.publish_simple(topic, key, payload)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Kafka implementation
# ──────────────────────────────────────────────────────────────────────────────

class KafkaEventBus(InMemoryEventBus):
    """
    Extends InMemoryEventBus with async Kafka publishing.

    Local subscribers still work (useful for in-process side-effects).
    Every publish also sends the event to Kafka so downstream consumers
    (other services) receive it.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str = "flashguard.executions",
    ) -> None:
        super().__init__()
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer = None
        self._ready = False

    async def start(self) -> None:
        """Create and start the Kafka producer.  Called at app startup."""
        try:
            from aiokafka import AIOKafkaProducer  # lazy import
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode(),
                key_serializer=lambda k: k.encode() if k else None,
                acks="all",
                enable_idempotence=True,
            )
            await self._producer.start()
            self._ready = True
            logger.info(
                "KafkaEventBus: producer connected → %s (topic: %s)",
                self._bootstrap_servers,
                self._topic,
            )
        except Exception as exc:
            logger.warning(
                "KafkaEventBus: failed to connect (%s). "
                "Publishing will be in-memory only.",
                exc,
            )
            self._ready = False

    async def stop(self) -> None:
        """Flush and close the Kafka producer."""
        if self._producer and self._ready:
            try:
                await self._producer.stop()
                logger.info("KafkaEventBus: producer stopped")
            except Exception as exc:
                logger.warning("KafkaEventBus: stop error: %s", exc)
        self._ready = False

    async def async_publish_simple(
        self,
        topic: EventType,
        key: str,
        payload: Dict[str, Any],
    ) -> None:
        """Publish to Kafka + notify in-memory subscribers."""
        # Always notify synchronous in-memory subscribers
        self.publish_simple(topic, key, payload)

        if not self._ready or self._producer is None:
            return

        record: Dict[str, Any] = {
            "topic": topic.value,
            "key": key,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            await self._producer.send_and_wait(
                self._topic,
                key=key,
                value=record,
            )
            logger.debug(
                "KafkaEventBus: sent key=%s to topic=%s",
                key,
                self._topic,
            )
        except Exception as exc:
            logger.error(
                "KafkaEventBus: failed to publish to Kafka (%s). "
                "Event was already delivered to in-memory subscribers.",
                exc,
            )

    # Override sync publish_simple to also schedule async send
    def publish_simple(
        self,
        topic: EventType,
        key: str,
        payload: Dict[str, Any],
    ) -> None:
        """Sync publish – notifies in-memory subscribers immediately."""
        super().publish_simple(topic, key, payload)


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def build_event_bus() -> InMemoryEventBus:
    """
    Return a KafkaEventBus if KAFKA_BOOTSTRAP_SERVERS is set,
    otherwise an InMemoryEventBus.

    Call `await bus.start()` after construction when using KafkaEventBus.
    """
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    topic = os.getenv("KAFKA_TOPIC", "flashguard.executions")

    if servers:
        logger.info("EventBus: Kafka mode (servers=%s)", servers)
        return KafkaEventBus(bootstrap_servers=servers, topic=topic)

    logger.info("EventBus: in-memory mode (KAFKA_BOOTSTRAP_SERVERS not set)")
    return InMemoryEventBus()


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singleton (backward compatible)
# ──────────────────────────────────────────────────────────────────────────────
event_bus: InMemoryEventBus = InMemoryEventBus()
