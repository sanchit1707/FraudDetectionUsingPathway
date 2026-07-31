
import json
import logging

import pathway as pw
from pathway.xpacks.llm import llms
from pathway.xpacks.llm.mcp_server import McpServer, McpConfig
from pathway.udfs import ExponentialBackoffRetryStrategy, DiskCache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subclassed LiteLLMChat that preserves tool_calls + usage
# ---------------------------------------------------------------------------
class PreservingLiteLLMChat(llms.LiteLLMChat):
    """
    Same as LiteLLMChat, except __wrapped__ returns a JSON string encoding
    {content, tool_calls, usage} instead of a bare content string. __call__
    is inherited unchanged, so this still routes through Pathway's executor
    (capacity/retry_strategy/cache_strategy all apply).
    """

    def __wrapped__(self, messages, **kwargs) -> str:
        import litellm

        # NOTE: mirrors the parent class's message prep / logging structure;
        # kept minimal here since the full request/response logging the
        # parent does isn't reproduced — add it back if you need parity.
        from pathway.xpacks.llm.llms import _prepare_messages, _extract_value_inside_dict

        messages_decoded = _prepare_messages(messages)
        kwargs = {**self.kwargs, **kwargs}
        kwargs = _extract_value_inside_dict(kwargs)
        kwargs.pop("verbose", None)

        ret = litellm.completion(messages=messages_decoded, **kwargs)
        message = ret.choices[0].message

        tool_calls = []
        for tc in (message.tool_calls or []):
            tool_calls.append({
                "name": tc.function.name,
                "arguments": tc.function.arguments,  # JSON string, per OpenAI schema
            })

        payload = {
            "content": message.content,
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": ret.usage.prompt_tokens,
                "completion_tokens": ret.usage.completion_tokens,
                "total_tokens": ret.usage.total_tokens,
            },
        }
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tier instances — capacity/retry_strategy/cache_strategy actually apply
# here, since calls will go through __call__ inside the table pipeline below.
# ---------------------------------------------------------------------------
TIERS = {
    "low": PreservingLiteLLMChat(
        model="groq/llama-3.1-8b-instant",
        capacity=8,
        async_mode="fully_async",
        retry_strategy=ExponentialBackoffRetryStrategy(max_retries=2),
        cache_strategy=DiskCache(),
    ),
    "medium": PreservingLiteLLMChat(
        model="groq/llama-3.3-70b-versatile",
        capacity=8,
        async_mode="fully_async",
        retry_strategy=ExponentialBackoffRetryStrategy(max_retries=2),
        cache_strategy=DiskCache(),
    ),
    "high": PreservingLiteLLMChat(
        model="anthropic/claude-sonnet-4-6",
        capacity=4,
        async_mode="fully_async",
        retry_strategy=ExponentialBackoffRetryStrategy(max_retries=1),
        cache_strategy=DiskCache(),
    ),
}


# ---------------------------------------------------------------------------
# Input schema for the MCP tool. tools is passed as a JSON-encoded string
# (tools_json) rather than a nested structure — Pathway schema columns need
# concrete scalar/JSON types, and encoding as a string on the client side
# keeps this schema simple. Decode with json.loads inside the pipeline.
# ---------------------------------------------------------------------------
class LLMRequestSchema(pw.Schema):
    prompt: str
    cust_token: str
    complexity: str
    cache_key: str
    tools_json: str  # JSON-encoded list[dict]; "[]" if no tools


@pw.udf
def _decode_tools(tools_json: str):
    return json.loads(tools_json) if tools_json else []


def llm_request_handler(input_table: pw.Table) -> pw.Table:
    """
    Registered as the MCP tool's request handler. Routes each row to its
    tier's LiteLLMChat instance via __call__ — this is the only line in the
    whole adapter package that actually exercises the Pathway executor.
    """
    with_tools = input_table.with_columns(
        tools=_decode_tools(pw.this.tools_json),
    )

    low_rows = with_tools.filter(pw.this.complexity == "low")
    med_rows = with_tools.filter(pw.this.complexity == "medium")
    high_rows = with_tools.filter(pw.this.complexity == "high")

    low_done = low_rows.select(
        *pw.this,
        raw_response=TIERS["low"](
            llms.prompt_chat_single_qa(pw.this.prompt), tools=pw.this.tools
        ),
        model_used=pw.this.complexity,
    )
    med_done = med_rows.select(
        *pw.this,
        raw_response=TIERS["medium"](
            llms.prompt_chat_single_qa(pw.this.prompt), tools=pw.this.tools
        ),
        model_used=pw.this.complexity,
    )
    high_done = high_rows.select(
        *pw.this,
        raw_response=TIERS["high"](
            llms.prompt_chat_single_qa(pw.this.prompt), tools=pw.this.tools
        ),
        model_used=pw.this.complexity,
    )

    responses = low_done.concat_reindex(med_done).concat_reindex(high_done)

    # Return only what the client needs — raw_response is the JSON string
    # produced by PreservingLiteLLMChat.__wrapped__, decoded client-side by
    # response.py's LLMResponse.from_raw().
    return responses.select(
        pw.this.cache_key,
        pw.this.cust_token,
        pw.this.model_used,
        pw.this.raw_response,
    )


def main():
    server = McpServer.get(
        McpConfig(
            name="flashguard-llm-gateway",
            transport="streamable-http",
            host="0.0.0.0",
            port=8766,  # distinct from A5's DocumentStoreServer on 8765
        )
    )

    server.tool(
        name="llm_invoke",
        request_handler=llm_request_handler,
        schema=LLMRequestSchema,
        title="FlashGuard LLM Gateway",
        description="Routes a fraud-scoring LLM request to the correct tier and returns the raw model response.",
    )

    server.run()
    # If the pipeline doesn't execute without this, add:
    # pw.run()


if __name__ == "__main__":
    main()
