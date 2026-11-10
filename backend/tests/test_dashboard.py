"""Seller dashboard (screen 3): activity events, stats and polling."""

from app import paypal
from test_agent import Chat
from test_api import TOKENS, captured, fake_create
from test_mcp import call_tool, published_shop


def dash(client, shop_id, after=0):
    headers = {"X-Seller-Token": TOKENS[shop_id]} if shop_id in TOKENS else {}
    r = client.get(f"/api/shops/{shop_id}/dashboard", params={"after": after}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def kinds(d):
    return [e["kind"] for e in reversed(d["events"])]  # oldest first


def test_full_sale_via_mcp_shows_up_on_dashboard(client, monkeypatch):
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    monkeypatch.setattr(paypal, "capture_order", captured)
    shop, ids = published_shop(client)
    client.patch(f"/api/products/{ids['mug']}", json={"stock": 5})

    call_tool(client, "search_products", query="mug")
    call_tool(client, "get_product", product_id=ids["mug"])
    call_tool(client, "create_checkout", product_id=ids["mug"], qty=2)
    client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)  # PayPal redirect: source "web"
    client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)  # refresh: no duplicate events

    d = dash(client, shop["id"])
    assert kinds(d) == ["search", "view", "checkout", "approved", "sold"]
    # Approval and sale arrive via PayPal's redirect but are credited to the MCP agent.
    assert {e["source"] for e in d["events"]} == {"mcp"}
    sold = d["events"][0]
    assert sold["product_title"] and sold["detail"]["amount"] == "68.00"
    assert d["stats"] == {"searches": 1, "views": 1, "checkouts": 1, "sales": 1, "units_sold": 2, "revenue": "68.00"}
    assert d["units_sold"] == {ids["mug"]: 2}
    assert d["mcp_url"] == "http://localhost:8000/mcp"
    assert next(p for p in d["shop"]["products"] if p["id"] == ids["mug"])["stock"] == 3


def test_built_in_agent_events_are_credited_to_agent(client):
    shop, _ = published_shop(client)
    Chat(client).say("blue mug")
    d = dash(client, shop["id"])
    assert kinds(d) == ["search", "view"] and {e["source"] for e in d["events"]} == {"agent"}


def test_search_events_only_for_shops_in_results(client):
    shop_a, _ = published_shop(client)
    shop_b, _ = published_shop(client, ("white_vase.jpg",))
    call_tool(client, "search_products", query="mug")
    assert kinds(dash(client, shop_a["id"])) == ["search"]
    assert kinds(dash(client, shop_b["id"])) == []
    detail = dash(client, shop_a["id"])["events"][0]["detail"]
    assert detail["query"] == "mug" and detail["matches"] == 1


def test_polling_returns_only_new_events(client):
    shop, ids = published_shop(client)
    call_tool(client, "search_products", query="mug")
    last = dash(client, shop["id"])["events"][0]["id"]
    assert dash(client, shop["id"], after=last)["events"] == []
    call_tool(client, "get_product", product_id=ids["vase"])
    assert kinds(dash(client, shop["id"], after=last)) == ["view"]


def test_cancel_and_sold_out_are_recorded_once(client, monkeypatch):
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    shop, ids = published_shop(client, ("blue_mug.jpg",))  # stock 1
    call_tool(client, "create_checkout", product_id=ids["mug"])
    client.get("/paypal/cancel?token=PAYPAL123", follow_redirects=False)
    client.get("/paypal/cancel?token=PAYPAL123", follow_redirects=False)
    assert kinds(dash(client, shop["id"])) == ["checkout", "cancelled"]

    # Sold out between checkout and approval: repeated status polls log one "missed".
    client.patch(f"/api/products/{ids['mug']}", json={"stock": 0})
    monkeypatch.setattr(paypal, "get_order", lambda _id: {"status": "APPROVED"})
    oid = dash(client, shop["id"])["events"][-1]["order_id"]
    for _ in range(3):
        call_tool(client, "get_order_status", order_id=oid)
    assert kinds(dash(client, shop["id"])).count("missed") == 1
    assert dash(client, shop["id"])["stats"]["sales"] == 0


def test_dashboard_404(client):
    assert client.get("/api/shops/shop_nope/dashboard").status_code == 404
