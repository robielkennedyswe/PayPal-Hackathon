"""Seller tokens: only the shop's own token can manage it (seller_auth.py)."""

import pytest
from sqlmodel import Session, select

from app import seller_auth
from app.db import engine, init_db
from app.models import Product, Shop
from test_api import make_shop, upload

TOKEN = seller_auth.HEADER


def seller_calls(shop_id, product_id):
    """(method, url, kwargs) for every seller-only route."""
    return [
        ("GET", f"/api/shops/{shop_id}", {}),
        ("GET", f"/api/shops/{shop_id}/dashboard", {}),
        ("POST", f"/api/shops/{shop_id}/products", {"files": {"file": ("blue_mug.jpg", b"x", "image/jpeg")}}),
        ("PATCH", f"/api/products/{product_id}", {"json": {"price": "0.01"}}),
        ("POST", f"/api/shops/{shop_id}/publish", {}),
        ("DELETE", f"/api/products/{product_id}", {}),
    ]


def setup_two_shops(client):
    mine = make_shop(client, "Mine")
    product = upload(client, mine["id"]).json()
    mine["price"] = product["price"]
    other = make_shop(client, "Other")
    client.headers.pop(TOKEN)
    return mine, product["id"], other


def test_token_is_returned_once_and_never_stored_in_plain_text(client):
    shop = make_shop(client)
    token = shop["seller_token"]
    assert len(token) >= 40
    again = client.get(f"/api/shops/{shop['id']}").json()
    assert "seller_token" not in again and "seller_token_hash" not in again
    with Session(engine) as s:
        stored = s.get(Shop, shop["id"]).seller_token_hash
    assert stored == seller_auth.hash_token(token) and token not in stored


@pytest.mark.parametrize("index", range(6))
def test_seller_routes_need_the_shops_own_token(client, index):
    mine, pid, other = setup_two_shops(client)
    method, url, kwargs = seller_calls(mine["id"], pid)[index]

    assert client.request(method, url, **kwargs).status_code == 401
    wrong = {TOKEN: other["seller_token"]}  # a real token, but for another shop
    r = client.request(method, url, headers=wrong, **kwargs)
    assert r.status_code == 403 and "seller link" in r.json()["detail"]
    ok = client.request(method, url, headers={TOKEN: mine["seller_token"]}, **kwargs)
    assert ok.status_code < 300, ok.text


def test_rejected_requests_change_nothing(client):
    mine, pid, other = setup_two_shops(client)
    for method, url, kwargs in seller_calls(mine["id"], pid):
        client.request(method, url, headers={TOKEN: other["seller_token"]}, **kwargs)
    with Session(engine) as s:
        products = s.exec(select(Product).where(Product.shop_id == mine["id"])).all()
        assert [(p.id, p.price) for p in products] == [(pid, mine["price"])]  # no upload, edit or delete
        assert s.get(Shop, mine["id"]).published is False


def test_public_routes_need_no_token(client):
    shop = make_shop(client)
    upload(client, shop["id"])
    client.post(f"/api/shops/{shop['id']}/publish")
    client.headers.pop(TOKEN)
    assert client.get("/api/storefronts").status_code == 200
    assert client.get(f"/api/storefront/{shop['slug']}").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_shop_without_a_token_is_locked_until_one_is_issued(client, capsys):
    shop = make_shop(client)
    with Session(engine) as s:  # a shop created before tokens existed
        old = s.get(Shop, shop["id"])
        old.seller_token_hash = None
        s.add(old)
        s.commit()
    assert client.get(f"/api/shops/{shop['id']}").status_code == 403  # fail closed

    seller_auth._issue(shop["id"])
    link = capsys.readouterr().out.strip().splitlines()[-1]
    assert link.startswith("http") and f"/sell/{shop['id']}/dashboard#seller=" in link
    new_token = link.split("#seller=")[1]
    assert client.get(f"/api/shops/{shop['id']}", headers={TOKEN: new_token}).status_code == 200
    # The token sent so far (from make_shop) is replaced, not added.
    assert client.get(f"/api/shops/{shop['id']}", headers={TOKEN: shop["seller_token"]}).status_code == 403


def test_init_db_adds_the_column_to_an_older_database(client):
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE shops DROP COLUMN seller_token_hash")
    init_db()
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shops)")}
    assert "seller_token_hash" in columns
