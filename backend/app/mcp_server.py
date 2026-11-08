"""MCP server: exposes the four shopping tools to any MCP-compatible agent.

Mounted inside the FastAPI app at /mcp (streamable HTTP), so one Render
service serves the API, PayPal redirects and MCP. Connect a client with e.g.
    claude mcp add --transport http shopmcp http://localhost:8000/mcp

Built on the official `mcp` Python SDK 2.x, where FastMCP was renamed
MCPServer. Each tool is a thin wrapper over app/tools.py: open a DB session,
call the shared function, turn CheckoutError into ToolError (which the SDK
returns to the model as a readable is_error result instead of a crash).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlmodel import Session
from starlette.applications import Starlette
from typing import Annotated

from app import tools
from app.checkout import MAX_QTY, CheckoutError
from app.db import engine

# Sent to the agent when it connects. This is where we state the payment
# safety rule in words the model will follow.
INSTRUCTIONS = """\
ShopMCP lets you search and buy handmade goods from small independent shops.

Typical flow: search_products -> get_product -> create_checkout -> get_order_status.

Payment rules (important):
- You cannot pay. create_checkout returns an approve_url; give that link to
  the user so they can review and approve the payment in PayPal themselves.
- Confirm the item, quantity and total with the user before creating a checkout.
- Never tell the user an order is paid until get_order_status returns COMPLETED.
"""

mcp = MCPServer(
    name="ShopMCP",
    instructions=INSTRUCTIONS,
    website_url=os.getenv("FRONTEND_URL") or None,
)

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _run(fn, *args):
    """Call a shared tool function with its own DB session."""
    with Session(engine) as session:
        try:
            return fn(session, *args)
        except CheckoutError as e:
            raise ToolError(f"{e.code}: {e.message}") from e


@mcp.tool(title="Search products", annotations=_READ_ONLY)
def search_products(
    query: Annotated[str, Field(description="Keywords, e.g. 'blue mug' or 'ceramic vase'. Empty lists everything.")] = "",
    max_price: Annotated[float | None, Field(description="Only items at or under this price, in USD.", gt=0)] = None,
) -> list[dict]:
    """Search all published shops. Returns up to 10 matches, best first,
    with id, title, price, shop, short description and stock."""
    return _run(tools.search_products, query, max_price)


@mcp.tool(title="Get product details", annotations=_READ_ONLY)
def get_product(
    product_id: Annotated[str, Field(description="Product id from search_products, e.g. 'prod_3f9a1c2b7d4e'.")],
) -> dict:
    """Full listing for one product: description, attributes, tags, price and stock."""
    return _run(tools.get_product, product_id)


@mcp.tool(
    title="Create PayPal checkout",
    # Creates an unpaid PayPal order; nothing is charged until the human
    # approves. Not idempotent: each call makes a new order.
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True),
)
def create_checkout(
    product_id: Annotated[str, Field(description="Product id to buy.")],
    qty: Annotated[int, Field(description="How many to buy.", ge=1, le=MAX_QTY)] = 1,
) -> dict:
    """Start a PayPal checkout for a product. Returns order_id, approve_url and
    the total. The user must open approve_url and approve the payment in
    PayPal; you cannot pay for them. Confirm item, quantity and total first."""
    return _run(tools.create_checkout, product_id, qty)


@mcp.tool(title="Get order status", annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True, open_world_hint=True))
def get_order_status(
    order_id: Annotated[str, Field(description="order_id returned by create_checkout, e.g. 'ord_94ffee981a04'.")],
) -> dict:
    """Check an order: CREATED (waiting for the buyer to approve in PayPal),
    APPROVED (capturing), or COMPLETED (paid). Call after the user says they
    approved."""
    # read_only_hint=False: if PayPal shows the order approved but our
    # return URL was never hit, this call finishes the capture.
    return _run(tools.get_order_status, order_id)


def build_http_app() -> Starlette:
    """Fresh streamable-HTTP app for one FastAPI lifespan.

    The SDK's session manager can only run once per instance, so main.py
    builds a new one on every startup (matters for tests, which start the
    app many times).
    """
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        # Stateless + plain JSON responses: our tools are simple
        # request/response calls with no server-pushed events, so no
        # per-client session state is needed. Also survives restarts.
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection: only accept requests addressed to our own
    host. The SDK's default allows localhost only, which would reject every
    request on Render, so add the public host from APP_BASE_URL.
    """
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for url in (os.getenv("APP_BASE_URL"), os.getenv("FRONTEND_URL")):
        parsed = urlparse(url or "")
        if parsed.netloc:
            hosts.append(parsed.netloc)
            origins.append(f"{parsed.scheme}://{parsed.netloc}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )
