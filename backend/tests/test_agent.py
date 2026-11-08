"""Built-in shopper agent (mock brain) over POST /api/agent/chat."""

from sqlmodel import Session

from app import agent, paypal
from app.db import engine
from app.models import Product
from test_api import captured, fake_create
from test_mcp import published_shop


class Chat:
    """Plays the frontend: keeps history and sends it back each turn."""

    def __init__(self, client):
        self.client, self.history = client, []

    def say(self, message):
        r = self.client.post("/api/agent/chat", json={"history": self.history, "message": message})
        assert r.status_code == 200, r.text
        body = r.json()
        self.history = body["history"]
        return body["turn"]


def tools_called(turn):
    return [c["name"] for c in turn["tool_calls"]]


def test_full_scripted_purchase(client, monkeypatch):
    calls = []
    monkeypatch.setattr(paypal, "create_order", fake_create(calls))
    _, ids = published_shop(client)
    client.patch(f"/api/products/{ids['mug']}", json={"stock": 5})
    chat = Chat(client)

    # 1. Search -> best match shown as a product card (with its photo).
    turn = chat.say("Find me a blue mug under $40")
    assert tools_called(turn) == ["search_products", "get_product"]
    assert turn["tool_calls"][0]["input"] == {"query": "blue mug", "max_price": 40.0}
    (card,) = turn["cards"]
    assert card["type"] == "product" and card["product"]["id"] == ids["mug"]
    assert card["image_url"].startswith("/uploads/")
    assert "checkout" in turn["text"].lower()

    # 2. "yes, 2" -> real create_checkout for qty 2 -> approval card.
    turn = chat.say("yes, 2 please")
    assert tools_called(turn) == ["create_checkout"]
    (card,) = turn["cards"]
    assert card["type"] == "approval" and card["checkout"]["amount"] == "68.00"
    assert "can't pay" in turn["text"]
    assert len(calls) == 1

    # 3. "ok" right after checkout must check status, NOT buy again.
    monkeypatch.setattr(paypal, "get_order", lambda _id: {"status": "PAYER_ACTION_REQUIRED"})
    turn = chat.say("ok")
    assert tools_called(turn) == ["get_order_status"] and turn["cards"] == []
    assert len(calls) == 1

    # 4. Buyer approved in PayPal -> status check captures -> confirmation.
    monkeypatch.setattr(paypal, "get_order", lambda _id: {"status": "APPROVED"})
    monkeypatch.setattr(paypal, "capture_order", captured)
    turn = chat.say("I'm done, I approved it")
    assert turn["cards"][0]["type"] == "confirmation"
    assert "Payment confirmed" in turn["text"]
    order_id = turn["cards"][0]["order"]["order_id"]
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "COMPLETED"
    with Session(engine) as s:
        assert s.get(Product, ids["mug"]).stock == 3  # 5 - 2


def test_history_is_anthropic_message_format(client, monkeypatch):
    published_shop(client)
    chat = Chat(client)
    chat.say("ceramic vase")
    roles = [m["role"] for m in chat.history]
    assert roles[0] == "user" and roles[-1] == "assistant"
    blocks = [b for m in chat.history if isinstance(m["content"], list) for b in m["content"]]
    uses = {b["id"] for b in blocks if b["type"] == "tool_use"}
    results = {b["tool_use_id"] for b in blocks if b["type"] == "tool_result"}
    assert uses == results and len(uses) == 2  # every tool_use has its tool_result


def test_no_results_and_small_talk(client):
    published_shop(client)
    chat = Chat(client)
    turn = chat.say("hello")
    assert turn["tool_calls"] == [] and "looking for" in turn["text"]
    turn = chat.say("yes")  # nothing shown yet: nothing to buy
    assert turn["tool_calls"] == []
    turn = chat.say("a spaceship")
    assert tools_called(turn) == ["search_products"] and "couldn't find" in turn["text"]


def test_checkout_errors_are_explained(client, monkeypatch):
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    published_shop(client, ("blue_mug.jpg",))  # stock 1
    chat = Chat(client)
    chat.say("mug")
    turn = chat.say("yes 3")
    assert turn["tool_calls"][0]["is_error"] is True and turn["cards"] == []
    assert "Only 1" in turn["text"]


def test_long_history_is_trimmed_at_turn_boundaries(client, monkeypatch):
    monkeypatch.setattr(agent, "MAX_HISTORY_MESSAGES", 10)
    published_shop(client)
    chat = Chat(client)
    for _ in range(5):
        chat.say("mug")  # 4 messages per search turn + 2 tool msgs
    assert len(chat.history) <= 10
    assert chat.history[0]["role"] == "user" and isinstance(chat.history[0]["content"], str)


def test_anthropic_mode_not_ready_yet(client, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("AI_MODEL", "test")
    r = client.post("/api/agent/chat", json={"history": [], "message": "mug"})
    assert r.status_code == 501
