from sqlmodel import Session, select

from app import paypal
from app.db import engine
from app.models import Order, OrderStatus

SELLER = "seller@business.example.com"


def make_shop(client, name="Clay Corner"):
    r = client.post("/api/shops", json={"name": name, "paypal_payee_email": SELLER})
    assert r.status_code == 201
    return r.json()


def upload(client, shop_id, filename="blue_mug.jpg", data=b"fake-image"):
    return client.post(f"/api/shops/{shop_id}/products", files={"file": (filename, data, "image/jpeg")})


# ---------- shops & products ----------

def test_health_reports_mock_provider(client):
    assert client.get("/api/health").json() == {"ok": True, "ai_provider": "mock"}


def test_slugs_are_unique(client):
    assert make_shop(client)["slug"] == "clay-corner"
    assert make_shop(client)["slug"] == "clay-corner-2"


def test_shop_validation(client):
    r = client.post("/api/shops", json={"name": "  ", "paypal_payee_email": SELLER})
    assert r.status_code == 422
    r = client.post("/api/shops", json={"name": "X", "paypal_payee_email": "not-an-email"})
    assert r.status_code == 422


def test_upload_creates_draft_from_mock_ai(client):
    shop = make_shop(client)
    r = upload(client, shop["id"])
    assert r.status_code == 201
    p = r.json()
    assert "Mug" in p["title"]
    assert p["price"] == "34.00" and p["stock"] == 1
    assert client.get(p["image_url"]).content == b"fake-image"  # served from /uploads


def test_upload_rejects_bad_files(client):
    shop = make_shop(client)
    assert upload(client, shop["id"], "notes.txt").status_code == 400
    assert upload(client, shop["id"], data=b"").status_code == 400
    assert upload(client, shop["id"], data=b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert upload(client, "shop_missing").status_code == 404


def test_upload_filename_cannot_escape_upload_dir(client):
    shop = make_shop(client)
    p = upload(client, shop["id"], "../../evil_mug.jpg").json()
    assert ".." not in p["image_url"]
    assert p["image_url"].startswith(f"/uploads/{shop['id']}/")


def test_update_product(client):
    shop = make_shop(client)
    pid = upload(client, shop["id"]).json()["id"]
    assert client.patch(f"/api/products/{pid}", json={"price": "34.567"}).status_code == 422
    assert client.patch(f"/api/products/{pid}", json={"stock": -1}).status_code == 422
    assert client.patch(f"/api/products/{pid}", json={"title": None}).status_code == 422
    r = client.patch(f"/api/products/{pid}", json={"price": "36.00", "stock": 4})
    assert (r.json()["price"], r.json()["stock"]) == ("36.00", 4)


def test_price_input_is_normalized(client):
    shop = make_shop(client)
    pid = upload(client, shop["id"]).json()["id"]
    for given, stored in [("100", "100.00"), ("20.5", "20.50"), ("$1,200", "1200.00"), (" 7.25 ", "7.25"), (45, "45.00")]:
        r = client.patch(f"/api/products/{pid}", json={"price": given})
        assert r.status_code == 200 and r.json()["price"] == stored, given
    for bad in ["0", "0.00", "abc", "12.345", "-5", "1234567", True]:
        assert client.patch(f"/api/products/{pid}", json={"price": bad}).status_code == 422, bad


def test_delete_product(client):
    shop = make_shop(client)
    pid = upload(client, shop["id"]).json()["id"]
    assert client.delete(f"/api/products/{pid}").status_code == 204
    assert client.get(f"/api/shops/{shop['id']}").json()["products"] == []


def test_publish_requires_products(client):
    shop = make_shop(client)
    assert client.post(f"/api/shops/{shop['id']}/publish").status_code == 400
    upload(client, shop["id"])
    r = client.post(f"/api/shops/{shop['id']}/publish")
    assert r.json()["published"] is True and len(r.json()["products"]) == 1


def test_storefront_only_shows_published_shops(client):
    shop = make_shop(client)
    upload(client, shop["id"])
    assert client.get(f"/api/storefront/{shop['slug']}").status_code == 404
    assert client.get("/api/storefront/no-such-shop").status_code == 404
    client.post(f"/api/shops/{shop['id']}/publish")
    r = client.get(f"/api/storefront/{shop['slug']}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Clay Corner" and len(body["products"]) == 1
    assert "paypal_payee_email" not in body  # seller email stays private


# ---------- PayPal return / capture ----------

def captured(order_id="PAYPAL123"):
    return {
        "id": order_id,
        "status": "COMPLETED",
        "purchase_units": [{"payments": {"captures": [{"id": "CAP1", "status": "COMPLETED"}]}}],
    }


def make_order(client, stock=3, qty=1):
    shop = make_shop(client)
    pid = upload(client, shop["id"]).json()["id"]
    client.patch(f"/api/products/{pid}", json={"stock": stock})
    with Session(engine) as s:
        o = Order(paypal_order_id="PAYPAL123", product_id=pid, qty=qty, amount="34.00")
        s.add(o)
        s.commit()
        return o.id, pid, shop["id"]


def stock_of(client, shop_id):
    return client.get(f"/api/shops/{shop_id}").json()["products"][0]["stock"]


def test_return_captures_and_decrements_stock(client, monkeypatch):
    calls = []
    monkeypatch.setattr(paypal, "capture_order", lambda oid: calls.append(oid) or captured(oid))
    oid, _, shop_id = make_order(client, stock=3, qty=2)

    r = client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"/checkout/result?status=completed&order={oid}")
    order = client.get(f"/api/orders/{oid}").json()
    assert (order["status"], order["paypal_capture_id"]) == ("COMPLETED", "CAP1")
    assert stock_of(client, shop_id) == 1

    # Refreshing the return page must not capture or decrement again.
    client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)
    assert calls == ["PAYPAL123"]
    assert stock_of(client, shop_id) == 1


def test_return_skips_capture_when_out_of_stock(client, monkeypatch):
    monkeypatch.setattr(paypal, "capture_order", lambda oid: (_ for _ in ()).throw(AssertionError("captured!")))
    oid, _, _ = make_order(client, stock=1, qty=2)
    r = client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)
    assert "status=out_of_stock" in r.headers["location"]
    assert client.get(f"/api/orders/{oid}").json()["status"] == OrderStatus.CREATED


def test_return_handles_already_captured(client, monkeypatch):
    def already(_oid):
        raise paypal.PayPalError(422, {"name": "UNPROCESSABLE_ENTITY",
                                       "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})
    monkeypatch.setattr(paypal, "capture_order", already)
    monkeypatch.setattr(paypal, "get_order", captured)
    oid, _, shop_id = make_order(client, stock=3)
    r = client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)
    assert "status=completed" in r.headers["location"]
    assert stock_of(client, shop_id) == 2


def test_return_reports_other_paypal_errors(client, monkeypatch):
    def boom(_oid):
        raise paypal.PayPalError(500, {"name": "INTERNAL_SERVER_ERROR"})
    monkeypatch.setattr(paypal, "capture_order", boom)
    oid, _, shop_id = make_order(client, stock=3)
    r = client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)
    assert "status=failed" in r.headers["location"]
    assert stock_of(client, shop_id) == 3


def test_return_and_cancel_unknown_token(client):
    r = client.get("/paypal/return?token=NOPE", follow_redirects=False)
    assert r.headers["location"].endswith("/checkout/result?status=not_found")
    r = client.get("/paypal/cancel?token=NOPE", follow_redirects=False)
    assert "status=cancelled" in r.headers["location"]


# ---------- create_checkout ----------

def published_product(client, stock=3, price="19.99"):
    shop = make_shop(client)
    pid = upload(client, shop["id"]).json()["id"]
    client.patch(f"/api/products/{pid}", json={"stock": stock, "price": price})
    client.post(f"/api/shops/{shop['id']}/publish")
    return pid, shop["id"]


def fake_create(calls):
    def _create(amount, currency="USD", **kw):
        calls.append({"amount": amount, "currency": currency, **kw})
        return {"id": "PAYPAL123", "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "payer-action", "href": "https://sandbox.paypal.com/approve?token=PAYPAL123"}]}
    return _create


def test_checkout_creates_order_with_seller_as_payee(client, monkeypatch):
    calls = []
    monkeypatch.setattr(paypal, "create_order", fake_create(calls))
    pid, _ = published_product(client)

    r = client.post("/api/checkout", json={"product_id": pid, "qty": 3})
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == "59.97"  # Decimal math, not float
    assert body["approve_url"].startswith("https://sandbox.paypal.com/")
    assert body["order_id"].startswith("ord_") and body["status"] == "CREATED"

    (call,) = calls
    assert call["amount"] == "59.97" and call["payee_email"] == SELLER
    assert call["item"] == {"name": body["title"], "quantity": 3, "unit_amount": "19.99"}

    order = client.get(f"/api/orders/{body['order_id']}").json()
    assert (order["paypal_order_id"], order["qty"], order["amount"]) == ("PAYPAL123", 3, "59.97")


def test_checkout_rejections(client, monkeypatch):
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    pid, _ = published_product(client, stock=2)
    post = lambda **b: client.post("/api/checkout", json={"product_id": pid, **b})
    assert post(qty=3).json()["detail"]["code"] == "OUT_OF_STOCK"
    assert post(qty=3).status_code == 409
    assert post(qty=0).status_code == 422
    assert post(qty=11).status_code == 422
    assert client.post("/api/checkout", json={"product_id": "prod_nope"}).status_code == 404


def test_checkout_hides_unpublished_products(client):
    shop = make_shop(client)
    pid = upload(client, shop["id"]).json()["id"]  # never published
    r = client.post("/api/checkout", json={"product_id": pid})
    assert r.status_code == 404  # and no PayPal call (no_network would fail)


def test_checkout_reports_paypal_errors_without_saving(client, monkeypatch):
    def boom(*_a, **_k):
        raise paypal.PayPalError(422, {"name": "UNPROCESSABLE_ENTITY"})
    monkeypatch.setattr(paypal, "create_order", boom)
    pid, _ = published_product(client)
    r = client.post("/api/checkout", json={"product_id": pid})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "PAYMENT_PROVIDER_ERROR"
    with Session(engine) as s:
        assert s.exec(select(Order)).first() is None


def test_checkout_then_return_completes_sale(client, monkeypatch):
    monkeypatch.setattr(paypal, "create_order", fake_create([]))
    monkeypatch.setattr(paypal, "capture_order", captured)
    pid, shop_id = published_product(client, stock=3)
    oid = client.post("/api/checkout", json={"product_id": pid, "qty": 2}).json()["order_id"]
    r = client.get("/paypal/return?token=PAYPAL123", follow_redirects=False)
    assert "status=completed" in r.headers["location"]
    assert client.get(f"/api/orders/{oid}").json()["status"] == "COMPLETED"
    assert stock_of(client, shop_id) == 1
