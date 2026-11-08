"""Deployment wiring: URL defaults, serving the built frontend, visitor key."""

from fastapi.testclient import TestClient
from starlette.requests import Request

from app import config, main


def test_render_url_defaults():
    assert config.resolve({}) == ("http://localhost:8000", None, "http://localhost:5173")
    # On Render: the automatic RENDER_EXTERNAL_URL, frontend served same-origin.
    assert config.resolve({"RENDER_EXTERNAL_URL": "https://shopmcp.onrender.com/", "FRONTEND_DIST": "/app/dist"}) == (
        "https://shopmcp.onrender.com", "/app/dist", "https://shopmcp.onrender.com")
    # Explicit values always win.
    assert config.resolve({"RENDER_EXTERNAL_URL": "https://x.onrender.com", "APP_BASE_URL": "https://shop.example",
                           "FRONTEND_URL": "https://web.example"})[::2] == ("https://shop.example", "https://web.example")


def test_serves_built_frontend_with_spa_fallback(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    monkeypatch.setattr(config, "FRONTEND_DIST", str(tmp_path))

    with TestClient(main.app, base_url="http://localhost:8000") as c:
        assert "id=root" in c.get("/").text
        assert "id=root" in c.get("/sell/shop_123/dashboard").text  # client-side route
        r = c.get("/assets/app.js")
        assert r.status_code == 200 and "console.log" in r.text
        assert c.get("/api/health").json()["ok"] is True  # API routes still win
        r = c.get("/api/nope")
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}  # never HTML for /api
        r = c.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200 and len(r.json()["result"]["tools"]) == 4


def test_without_built_frontend_unknown_paths_are_404(client):
    assert client.get("/sell/shop_123").status_code == 404


def _request(headers: dict, peer=("10.0.0.1", 1234)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": peer})


def test_client_key_prefers_forwarding_headers():
    assert main._client_key(_request({})) == "10.0.0.1"
    assert main._client_key(_request({"X-Forwarded-For": "203.0.113.7, 10.1.1.1"})) == "203.0.113.7"
    assert main._client_key(_request({"True-Client-IP": "198.51.100.2", "X-Forwarded-For": "1.2.3.4"})) == "198.51.100.2"
