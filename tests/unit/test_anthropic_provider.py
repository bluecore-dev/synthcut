"""The Claude adapter: request shape (streaming, adaptive thinking, cached
prefix, eager tool input), thinking blocks carried back verbatim, usage,
stop reasons, and which errors fail over to another target."""

import anthropic
import httpx2
import pytest
from anthropic.types import Message as ApiMessage
from synthcut_model_router import (
    AnthropicProvider,
    CompletionRequest,
    Message,
    ProviderBlock,
    ProviderError,
    StopReason,
    TextBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)


def api_message(**over) -> ApiMessage:
    data = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig-abc"},
            {"type": "text", "text": "Rejani tekshiraman."},
            {"type": "tool_use", "id": "toolu_1", "name": "get_edit_plan", "input": {"version": 1}},
        ],
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0},
    }  # fmt: skip
    data.update(over)
    return ApiMessage.model_validate(data)


class FakeStream:
    def __init__(self, outcome):
        self.outcome = outcome

    def __enter__(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.outcome


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.messages = self

    def stream(self, **params):
        self.calls.append(params)
        return FakeStream(self.outcomes.pop(0))


def request(**over) -> CompletionRequest:
    data = dict(
        system="Sen montajchisan.",
        messages=[Message(role="user", content=[TextBlock(text="Montaj qil")])],
        tools=[ToolDefinition(name="get_edit_plan", description="Plan", input_schema={"type": "object"})],
        effort="high",
    )
    data.update(over)
    return CompletionRequest(**data)


def test_request_shape_and_response_mapping():
    client = FakeClient(api_message())
    out = AnthropicProvider(client=client).complete("claude-opus-5", request())
    params = client.calls[0]
    assert params["model"] == "claude-opus-5" and params["thinking"] == {"type": "adaptive"}
    assert params["cache_control"] == {"type": "ephemeral"} and params["output_config"] == {"effort": "high"}
    assert params["tools"][0]["eager_input_streaming"] is True
    assert params["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Montaj qil"}]}]
    assert out.stop_reason is StopReason.TOOL_USE and out.text == "Rejani tekshiraman."
    assert out.tool_uses[0].input == {"version": 1}
    assert out.usage.cache_read_input_tokens == 900 and out.provider == "anthropic"
    thinking = out.content[0]
    assert isinstance(thinking, ProviderBlock) and thinking.data["signature"] == "sig-abc"


def test_thinking_goes_back_verbatim_with_the_tool_results():
    client = FakeClient(api_message(content=[{"type": "text", "text": "Tayyor."}], stop_reason="end_turn"))
    first = api_message()
    history = [
        Message(role="user", content=[TextBlock(text="Montaj qil")]),
        Message(
            role="assistant",
            content=AnthropicProvider(client=FakeClient(first)).complete("m", request()).content,
        ),
        Message(role="user", content=[ToolResultBlock(tool_use_id="toolu_1", content='{"ok": true}')]),
        Message(
            role="assistant", content=[ProviderBlock(provider="other", data={"x": 1}), TextBlock(text="...")]
        ),
    ]
    AnthropicProvider(client=client).complete("claude-opus-5", request(messages=history))
    sent = client.calls[0]["messages"]
    assert sent[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert sent[1]["content"][2] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "get_edit_plan",
        "input": {"version": 1},
    }
    assert sent[2]["content"][0]["type"] == "tool_result" and sent[2]["content"][0]["is_error"] is False
    assert sent[3]["content"] == [{"type": "text", "text": "..."}]  # another provider's block is not sent


def _status_error(cls, code: int):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(
        code, request=req, headers={"retry-after": "7"}, json={"error": {"type": "x", "message": "m"}}
    )
    return cls("m", response=resp, body=None)


@pytest.mark.parametrize(
    ("error", "failover"),
    [
        (lambda: _status_error(anthropic.RateLimitError, 429), True),
        (lambda: _status_error(anthropic.InternalServerError, 529), True),
        (lambda: _status_error(anthropic.NotFoundError, 404), True),
        (lambda: _status_error(anthropic.BadRequestError, 400), False),
        (lambda: _status_error(anthropic.AuthenticationError, 401), False),
    ],
)
def test_errors_fail_over_only_where_another_target_can_help(error, failover):
    with pytest.raises(ProviderError) as info:
        AnthropicProvider(client=FakeClient(error())).complete("claude-opus-5", request())
    assert info.value.failover is failover


def test_unparseable_tool_input_is_asked_again_then_refused():
    ok = api_message(content=[{"type": "text", "text": "ok"}], stop_reason="end_turn")
    client = FakeClient(ValueError("bad json"), ok)
    assert AnthropicProvider(client=client).complete("m", request()).text == "ok" and len(client.calls) == 2
    with pytest.raises(ProviderError):
        AnthropicProvider(client=FakeClient(*[ValueError("bad")] * 3)).complete("m", request())


def test_refusal_and_truncation_are_reported_as_such():
    refusal = api_message(content=[], stop_reason="refusal")
    assert (
        AnthropicProvider(client=FakeClient(refusal)).complete("m", request()).stop_reason
        is StopReason.REFUSAL
    )
    cut = api_message(stop_reason="max_tokens")
    assert (
        AnthropicProvider(client=FakeClient(cut)).complete("m", request()).stop_reason
        is StopReason.MAX_TOKENS
    )
    assert ToolUseBlock  # imported for the type checks above
