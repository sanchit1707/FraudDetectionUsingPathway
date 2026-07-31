
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional

from .request import build_request, LLMRequest
from .response import LLMResponse
from .balancer import LLMBalancer
from . import semantic_cache

logger = logging.getLogger(__name__)

GATEWAY_URL = "http://localhost:8766" 
CALL_TIMEOUT_S = 15.0

_balancer = LLMBalancer()


async def _call_gateway(tier: str, request: LLMRequest) -> Dict[str, Any]:
    """
    Calls gateway_server.py's `llm_invoke` MCP tool for the given tier.
    Returns the decoded raw_response payload (content/tool_calls/usage dict).
    """
    from fastmcp import Client  

    payload = {
        "prompt": request.prompt,
        "cust_token": request.cust_token,
        "complexity": tier,
        "cache_key": request.cache_key,
        "tools_json": json.dumps(request.tools),
    }

    async with Client(GATEWAY_URL) as client:
        result = await client.call_tool("llm_invoke", payload)

        row = result[0] if isinstance(result, list) else result

    raw_response_str = row["raw_response"]
    return json.loads(raw_response_str)


async def invoke(
    prompt: str,
    tools: Optional[List[Dict[str, Any]]],
    complexity: str,
    cust_token: str,
) -> LLMResponse:
    request = build_request(
        prompt=prompt,
        cust_token=cust_token,
        tools=tools,
        complexity=complexity,
    )

    cached = await semantic_cache.lookup(request.cache_key)
    if cached is not None:
        return cached

    tier = _balancer.route(complexity)
    attempted = []

    while True:
        attempted.append(tier)
        try:
            raw = await asyncio.wait_for(
                _call_gateway(tier, request),
                timeout=CALL_TIMEOUT_S,
            )
            _balancer.mark_success(tier)
            response = LLMResponse.from_raw(raw, request, model_used=tier)
            await semantic_cache.store(request.cache_key, response)
            return response

        except asyncio.TimeoutError:
            logger.warning(f"tier={tier} timed out for cust_token={cust_token}")
            _balancer.mark_failure(tier)

        except Exception as e:

            logger.warning(f"tier={tier} failed for cust_token={cust_token}: {e}")
            _balancer.mark_failure(tier)

        next_tier = _balancer.next_tier(tier)
        if next_tier is None or next_tier in attempted:
            raise RuntimeError(
                f"All tiers exhausted for cust_token={cust_token}, attempted={attempted}"
            )
        tier = next_tier
