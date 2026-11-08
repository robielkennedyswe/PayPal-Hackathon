"""MCP tools: the shared functions (tools.py) and the real protocol over /mcp."""

import json

from sqlmodel import Session

from app import paypal, tools
from app.db import engine
from test_api import captured, fake_create, make_shop, upload

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def published_shop(client, files=("blue_mug.jpg", "white_vase.jpg", "green_bowl.jpg")):
    shop = make_shop(client)
    ids = {f.split("_")[1].split(".")[0]: upload(client, shop["id"], f).json()["id"] for f in files}
    client.post(f"/api/shops/{shop['id']}/publish")
    return shop, ids


def rpc(client, method, params=None, id=1):
    r = client.post("/mcp", headers=MCP_HEADERS,
                    json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def call_tool(client, name, **args):
    return rpc(client, "tools/call", {"name": name, "arguments": args})["result"]


# ---------- shared tool functions ----------

def test_search_ranks_matches_and_filters_price(client):
    _, ids = published_shop(client)
    with Session(engine) as s:
        assert [r["id"] for r in tools.search_products(s, "blue mugs")][0] == ids["mug"]  # plural ok
        assert {r["id"] for r in tools.search_products(s, "ceramic")} == {ids["mug"], ids["vase"]}
        assert {r["id"] for r in tools.search_products(s, "", max_price=30)} == {ids["vase"]}  # $28
        assert tools.search_products(s, "spaceship") == []
        assert len(tools.search_products(s, "")) == 3


def test_search_puts_sold_out_last(client):
    _, ids = published_shop(client)
    client.patch(f"/api/products/{ids['mug']}", json={"stock": 0})
    with Session(engine) as s:
        results = tools.search_products(s, "")
    assert results[-1]["id"] == ids["mug"] and results[-1]["available"] is False


def test_unpublished_shops_are_invisible(client):
    shop = make_shop(client, "Hidden Kiln")
    pid = upload(client, shop["id"]).json()["id"]
    with Session(engine) as s:
        assert tools.search_products(s, "mug") == []
        try:
            tools.get_product(s, pid)
            raise AssertionError("expected PRODUCT_NOT_FOUND")
        except tools.CheckoutError as e:
            assert e.code == "PRODUCT_NOT_FOUND"


def test_get_product_matches_agent_view_shape(client):
    """frontend/src/agentView.ts shows sellers this exact shape."""
    shop, ids = published_shop(client, ("blue_mug.jpg",))
    with Session(engine) as s:
        p = tools.get_product(s, ids["mug"])
    assert list(p) == ["id", "title", "description", "price", "stock", "available",
                       "attributes", "tags", "shop", "checkout"]
    assert p["price"] == {"value": "34.00", "currency": "USD"}
    assert p["shop"] == {"name": shop["name"], "slug": shop["slug"]}


def test_order_status_captures_if_return_url_was_missed(client, monkeypatch):
    """Buyer approved in PayPal but /paypal/return never ran: polling finishes the sale."""
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    monkeypatch.setattr(paypal, "capture_order", captured)
    _, ids = published_shop(client, ("blue_mug.jpg",))
    with Session(engine) as s:
        oid = tools.create_checkout(s, ids["mug"])["order_id"]

        monkeypatch.setattr(paypal, "get_order", lambda _id: {"status": "PAYER_ACTION_REQUIRED"})
        assert tools.get_order_status(s, oid)["status"] == "CREATED"

        monkeypatch.setattr(paypal, "get_order", lambda _id: {"status": "APPROVED"})
        status = tools.get_order_status(s, oid)
    assert status["status"] == "COMPLETED" and "Paid" in status["message"]


def test_order_status_survives_paypal_outage(client, monkeypatch):
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    def down(_id):
        raise paypal.PayPalError(503, {"name": "SERVICE_UNAVAILABLE"})
    monkeypatch.setattr(paypal, "get_order", down)
    _, ids = published_shop(client, ("blue_mug.jpg",))
    with Session(engine) as s:
        oid = tools.create_checkout(s, ids["mug"])["order_id"]
        assert tools.get_order_status(s, oid)["status"] == "CREATED"


# ---------- MCP protocol over HTTP ----------

def test_mcp_lists_four_tools_with_instructions(client):
    init = rpc(client, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    })
    assert init["result"]["serverInfo"]["name"] == "ShopMCP"
    assert "approve_url" in init["result"]["instructions"]

    listed = rpc(client, "tools/list", id=2)["result"]["tools"]
    assert {t["name"] for t in listed} == {"search_products", "get_product", "create_checkout", "get_order_status"}


def test_mcp_search_and_checkout_round_trip(client, monkeypatch):
    calls = []
    monkeypatch.setattr(paypal, "create_order", fake_create(calls))
    _, ids = published_shop(client)
    client.patch(f"/api/products/{ids['mug']}", json={"stock": 5})

    found = call_tool(client, "search_products", query="mug")
    assert found["isError"] is False
    first = json.loads(found["content"][0]["text"])
    assert first["id"] == ids["mug"]

    result = call_tool(client, "create_checkout", product_id=ids["mug"], qty=2)
    checkout = json.loads(result["content"][0]["text"])
    assert checkout["amount"] == "68.00" and checkout["approve_url"].startswith("https://")
    assert calls[0]["payee_email"] == "seller@business.example.com"


def test_mcp_errors_are_readable_for_the_model(client):
    published_shop(client, ("blue_mug.jpg",))
    result = call_tool(client, "get_product", product_id="prod_nope")
    assert result["isError"] is True
    assert "PRODUCT_NOT_FOUND" in result["content"][0]["text"]
    # Schema validation (qty > 10) is rejected before our code runs.
    assert call_tool(client, "create_checkout", product_id="prod_x", qty=50)["isError"] is True


def test_mcp_rejects_foreign_host(client):
    r = client.post("/mcp", headers={**MCP_HEADERS, "Host": "evil.example.com"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 421
