
from typing import Optional
from .response import LLMResponse

_store: dict[str, LLMResponse] = {}


async def lookup(cache_key: str) -> Optional[LLMResponse]:
    return _store.get(cache_key)


async def store(cache_key: str, response: LLMResponse) -> None:
    _store[cache_key] = response
