import pytest
from synthcut_model_router import (
    DEFAULT_ROUTES,
    CompletionRequest,
    CompletionResponse,
    ModelRole,
    ModelRouter,
    NoRouteError,
    ProviderError,
    RouteTable,
    ScriptedProvider,
    StopReason,
    TextBlock,
    Usage,
    cost_usd,
)

REQ = CompletionRequest(system="s", messages=[])


def ok(text="hi", usage=None):
    return CompletionResponse(
        provider="?",
        model="?",
        content=[TextBlock(text=text)],
        stop_reason=StopReason.END_TURN,
        usage=usage or Usage(input_tokens=1000, output_tokens=200),
    )


def test_defaults_route_every_role_to_a_model():
    table = RouteTable.from_json(None)
    for role in ModelRole:
        assert table.targets(role)
    assert DEFAULT_ROUTES[ModelRole.REASONING] == ("anthropic:claude-opus-5",)


def test_routes_are_configurable_without_code():
    table = RouteTable.from_json('{"fast": ["local:llama-x", "anthropic:claude-haiku-4-5"]}')
    assert [str(t) for t in table.targets(ModelRole.FAST)] == ["local:llama-x", "anthropic:claude-haiku-4-5"]


def test_failover_to_next_target_and_cost_recorded():
    seen = []
    a = ScriptedProvider("a", [ProviderError("rate limited", failover=True)])
    b = ScriptedProvider("anthropic", [ok()])
    router = ModelRouter(
        RouteTable({ModelRole.FAST: ("a:m1", "anthropic:claude-sonnet-5")}),
        {"a": a, "anthropic": b},
        on_usage=lambda role, r: seen.append((role, r.model, r.cost_usd)),
    )
    r = router.complete(ModelRole.FAST, REQ)
    assert r.provider == "anthropic" and r.model == "claude-sonnet-5"
    assert r.cost_usd == pytest.approx((1000 * 2 + 200 * 10) / 1_000_000)
    assert seen == [(ModelRole.FAST, "claude-sonnet-5", r.cost_usd)]


def test_bad_request_does_not_fail_over():
    a = ScriptedProvider("a", [ProviderError("invalid schema", failover=False)])
    b = ScriptedProvider("b", [ok()])
    router = ModelRouter(RouteTable({ModelRole.FAST: ("a:m", "b:m")}), {"a": a, "b": b})
    with pytest.raises(ProviderError):
        router.complete(ModelRole.FAST, REQ)
    assert b.requests == []


def test_all_targets_down():
    router = ModelRouter(RouteTable({ModelRole.FAST: ("missing:m",)}), {})
    with pytest.raises(NoRouteError):
        router.complete(ModelRole.FAST, REQ)


def test_cache_tokens_priced_separately():
    u = Usage(
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    assert cost_usd("anthropic:claude-opus-5", u) == pytest.approx(5 + 0.5 + 6.25)
    assert cost_usd("nobody:unknown", u) is None
