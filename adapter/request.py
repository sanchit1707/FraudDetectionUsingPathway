
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class LLMRequest:
    prompt: str
    cust_token: str  # required — BDH depends on every request carrying this.
                      # Never forwarded to litellm/the provider; internal only.
    tools: List[Dict[str, Any]] = field(default_factory=list)
    complexity: str = "low"  # must match balancer.py's TIER_ORDER keys
    cache_key: str = ""


def strip_and_lowercase(text: str) -> str:
    """Normalizes text by removing surrounding whitespace and lowercasing."""
    return text.strip().lower()


def build_request(
    prompt: str,
    cust_token: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    complexity: str = "low",
) -> LLMRequest:
    if tools is None:
        tools = []

    normalized_text = strip_and_lowercase(prompt)

    key_input = f"{normalized_text}_{complexity}".encode("utf-8")
    stable_cache_key = hashlib.sha256(key_input).hexdigest()

    return LLMRequest(
        prompt=prompt,           # original casing preserved for the LLM
        cust_token=cust_token,
        tools=tools,
        complexity=complexity,
        cache_key=stable_cache_key,
    )
