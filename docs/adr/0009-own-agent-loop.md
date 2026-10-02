# ADR-0009 — The agent loop lives in our SDK, not in a provider SDK

**Why.** Rules 3–5, 8, 11 and 18: every tool call must pass a permission gate and be recorded, runs must be bounded by steps and cost, and no single model provider may become a hard dependency.

**Impact.** `synthcut_agent_sdk.run_agent` drives the loop over provider-neutral types; providers only translate one request/response. Tool results of one turn go back together, tools from a truncated turn never run, a refusal ends the run. The Anthropic provider (Phase 5) will use the official SDK inside its adapter.

**Decision.** Own loop; provider adapters stay thin.
