

import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .request import LLMRequest


@dataclass
class ToolCall:
    """Normalized tool call. BDH consumes tool_name + args; raw is for debugging only."""
    tool_name: str
    args: Dict[str, Any]
    raw: Any = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    content: Optional[str]
    tool_calls: List[ToolCall] = field(default_factory=list)
    cust_token: str = ""
    cache_key: str = ""
    model_used: str = ""
    usage: Usage = field(default_factory=Usage)  # now valid: all Usage fields default to 0

    @classmethod
    def from_raw(
        cls,
        raw: Dict[str, Any],
        request: LLMRequest,
        model_used: str,
    ) -> "LLMResponse":

        content = raw.get("content")

        tool_calls: List[ToolCall] = []
        for tc in raw.get("tool_calls") or []:
            raw_args = tc.get("arguments", "{}")
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:

                parsed_args = {"_raw_arguments": raw_args}

            tool_calls.append(
                ToolCall(
                    tool_name=tc.get("name", ""),
                    args=parsed_args,
                    raw=tc,
                )
            )

        usage_raw = raw.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return cls(
            content=content,
            tool_calls=tool_calls,
            cust_token=request.cust_token,   # reattached — never sent to provider
            cache_key=request.cache_key,     # carried forward for semantic_cache.py
            model_used=model_used,
            usage=usage,
        )
