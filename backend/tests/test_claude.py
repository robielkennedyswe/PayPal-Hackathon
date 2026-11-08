"""AI_PROVIDER=anthropic paths with a fake Claude client (no network, no cost)."""

import json

import pytest
from anthropic.types.beta import BetaMessage
from sqlmodel import Session

from app import agent, ai_budget, ai_provider, catalog_ai, paypal
from app.db import engine
from app.models import AIUsage
from test_api import fake_create, make_shop
from test_mcp import published_shop


def message(content, stop_reason="end_turn", tokens=(1000, 200)):
    return BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
    })


class FakeClaude:
    """Returns scripted responses and records every request it receives."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = self
        self.messages = self

    def create(self, **params):
        self.requests.append(json.loads(json.dumps(params, default=lambda o: o.model_dump(mode="json"))))
        return self.responses.pop(0)


@pytest.fixture
def claude(monkeypatch):
    """claude(*responses) switches to anthropic mode with a fake client.
    Call it after test setup, so setup uploads still use mock AI."""

    def install(*responses):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        monkeypatch.setenv("AI_MODEL", "claude-opus-5-5")
        fake = FakeClaude(*responses)
        monkeypatch.setattr(ai_provider, "client", lambda: fake)
        return fake

    return install


def chat(client, message_text, history=None):
    r = client.post("/api/agent/chat", json={"history": history or [], "message": message_text})
    assert r.status_code == 200, r.text
    return r.json()


THINK = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


# ---------- agent ----------

def test_claude_agent_tool_loop(client, claude):
    _, ids = published_shop(client)
    fake = claude(
        message([THINK, {"type": "tool_use", "id": "toolu_1", "name": "search_products",
                         "input": {"query": "mug", "max_price": 40}}], "tool_use"),
        message([THINK, {"type": "tool_use", "id": "toolu_2", "name": "get_product",
                         "input": {"product_id": ids["mug"]}}], "tool_use"),
        message([THINK, {"type": "text", "text": "I found a **blue mug** for $34. Want it?"}]),
    )
    body = chat(client, "a mug under 40 bucks")
    turn = body["turn"]
    assert [c["name"] for c in turn["tool_calls"]] == ["search_products", "get_product"]
    assert turn["cards"][0]["type"] == "product"
    assert "blue mug" in turn["text"]

    first, second, third = fake.requests
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["betas"]
    assert first["output_config"] == {"effort": "low"}
    assert {t["name"] for t in first["tools"]} == set(agent.TOOLS)
    assert "approve_url" in first["system"]  # MCP instructions included
    # Within the turn, thinking blocks go back to the API unchanged...
    assert third["messages"][1]["content"][0] == THINK
    # ...but the history handed to the browser has no thinking blocks.
    blocks = [b for m in body["history"] if isinstance(m["content"], list) for b in m["content"]]
    assert {b["type"] for b in blocks} == {"tool_use", "tool_result", "text"}


def test_claude_agent_parallel_tools_share_one_result_message(client, claude):
    _, ids = published_shop(client)
    claude(
        message([{"type": "tool_use", "id": "t1", "name": "get_product", "input": {"product_id": ids["mug"]}},
                 {"type": "tool_use", "id": "t2", "name": "get_product", "input": {"product_id": ids["vase"]}}],
                "tool_use"),
        message([{"type": "text", "text": "Here are both."}]),
    )
    history = chat(client, "compare the mug and the vase")["history"]
    results = [m for m in history if m["role"] == "user" and isinstance(m["content"], list)]
    assert len(results) == 1 and len(results[0]["content"]) == 2


def test_bad_tool_arguments_become_tool_errors(client, claude):
    published_shop(client)
    fake = claude(
        message([{"type": "tool_use", "id": "t1", "name": "get_product", "input": {"wrong": 1}},
                 {"type": "tool_use", "id": "t2", "name": "delete_everything", "input": {}}], "tool_use"),
        message([{"type": "text", "text": "Sorry, let me try again."}]),
    )
    turn = chat(client, "hi")["turn"]
    assert [c["is_error"] for c in turn["tool_calls"]] == [True, True]
    sent = fake.requests[1]["messages"][-1]["content"]
    assert "INVALID_ARGUMENTS" in sent[0]["content"] and "UNKNOWN_TOOL" in sent[1]["content"]


def test_tool_round_cap(client, claude, monkeypatch):
    published_shop(client)
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 2)
    loop = lambda i: message([{"type": "tool_use", "id": f"t{i}", "name": "search_products", "input": {}}], "tool_use")
    fake = claude(loop(1), loop(2))
    body = chat(client, "find everything forever")
    assert len(fake.requests) == 2 and "too many steps" in body["turn"]["text"]
    assert body["history"][-1]["role"] == "assistant"


def test_claude_checkout_uses_real_tools(client, claude, monkeypatch):
    calls = []
    monkeypatch.setattr(paypal, "create_order", fake_create(calls))
    _, ids = published_shop(client)
    claude(
        message([{"type": "tool_use", "id": "t1", "name": "create_checkout",
                  "input": {"product_id": ids["mug"], "qty": 1}}], "tool_use"),
        message([{"type": "text", "text": "Use the PayPal button below to approve."}]),
    )
    turn = chat(client, "yes buy the mug")["turn"]
    assert turn["cards"][0]["type"] == "approval" and len(calls) == 1


def test_refusal_is_not_kept_in_history(client, claude):
    claude(message([{"type": "text", "text": ""}], "refusal"))
    body = chat(client, "something unsafe")
    assert "can't help" in body["turn"]["text"]
    assert all(m["role"] != "assistant" or m["content"] == body["turn"]["text"] for m in body["history"])


# ---------- cost limits ----------

def test_daily_call_limit_stops_the_agent(client, claude, monkeypatch):
    monkeypatch.setenv("AI_DAILY_CALL_LIMIT", "1")
    published_shop(client)
    fake = claude(message([{"type": "text", "text": "Hello!"}]))
    assert chat(client, "hi")["turn"]["text"] == "Hello!"
    turn = chat(client, "hi again")["turn"]
    assert "today's AI usage limit" in turn["text"]
    assert len(fake.requests) == 1  # the second request never reached the API


def test_daily_budget_counts_estimated_cost(client, claude, monkeypatch):
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "0.01")
    published_shop(client)
    # 1000 in @ $4/M + 200 out @ $20/M = $0.008: under budget, then over.
    claude(message([{"type": "text", "text": "a"}]), message([{"type": "text", "text": "b"}]),
           message([{"type": "text", "text": "c"}]))
    chat(client, "1")
    chat(client, "2")
    assert "limit" in chat(client, "3")["turn"]["text"]
    usage = client.get("/api/ai/usage").json()
    assert usage["today"]["calls"] == 2
    assert usage["today"]["cost_usd"] == pytest.approx(0.016)


def test_total_budget(client, claude, monkeypatch):
    monkeypatch.setenv("AI_TOTAL_BUDGET_USD", "1")
    with Session(engine) as s:
        s.add(AIUsage(day="2026-01-01", calls=5, cost_usd=1.5))
        s.commit()
    claude()
    assert "used its AI budget" in chat(client, "hi")["turn"]["text"]


def test_per_visitor_hourly_limit(client, claude, monkeypatch):
    monkeypatch.setenv("AI_CLIENT_HOURLY_CALL_LIMIT", "2")
    claude(*[message([{"type": "text", "text": "ok"}]) for _ in range(2)])
    chat(client, "1")
    chat(client, "2")
    assert "hourly AI limit" in chat(client, "3")["turn"]["text"]
    ai_budget.reserve("someone-else")  # other visitors are unaffected


# ---------- catalog vision ----------

LISTING = {"title": "Black Over-Ear Headphones", "description": "Used over-ear headphones in black. Light wear on the headband.",
           "attributes": [{"name": "Color", "value": "black"}, {"name": "condition", "value": "used"}],
           "tags": ["Headphones", "audio", " "], "suggested_price": "85"}


def test_claude_listing_from_photo_is_cached(client, claude):
    shop = make_shop(client)
    fake = claude(message([{"type": "text", "text": json.dumps(LISTING)}]))
    files = {"file": ("IMG_0042.jpg", b"same-photo-bytes", "image/jpeg")}
    p = client.post(f"/api/shops/{shop['id']}/products", files=files).json()
    assert p["title"] == "Black Over-Ear Headphones" and p["price"] == "85.00"
    assert p["attributes"] == {"color": "black", "condition": "used"}
    assert p["tags"] == ["headphones", "audio"]

    req = fake.requests[0]
    assert req["messages"][0]["content"][0]["type"] == "image"
    assert req["output_config"]["format"]["type"] == "json_schema"

    # Same bytes again: served from the cache, no second API call.
    client.post(f"/api/shops/{shop['id']}/products", files=files)
    assert len(fake.requests) == 1


def test_listing_upload_reports_budget_limit(client, claude, monkeypatch):
    monkeypatch.setenv("AI_DAILY_CALL_LIMIT", "0")
    shop = make_shop(client)
    claude()
    r = client.post(f"/api/shops/{shop['id']}/products", files={"file": ("x.jpg", b"new", "image/jpeg")})
    assert r.status_code == 429 and "limit" in r.json()["detail"]
    assert client.get(f"/api/shops/{shop['id']}").json()["products"] == []


def test_listing_rejects_invalid_ai_output(client, claude):
    shop = make_shop(client)
    claude(message([{"type": "text", "text": json.dumps({**LISTING, "suggested_price": "free"})}]))
    r = client.post(f"/api/shops/{shop['id']}/products", files={"file": ("y.jpg", b"other", "image/jpeg")})
    assert r.status_code == 502


def test_mock_mode_never_touches_the_budget(client):
    published_shop(client)
    client.post("/api/agent/chat", json={"history": [], "message": "mug"})
    assert client.get("/api/ai/usage").json()["today"]["calls"] == 0
    assert catalog_ai  # imported for side-effect-free mock path
