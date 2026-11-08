"""Built-in shopper agent (screen 4), so judges can buy without an MCP client.

One chat turn: chat(session, history, message) -> {history, turn}.

- `history` is the whole conversation in the **Anthropic Messages format**
  (user text, assistant tool_use blocks, user tool_result blocks). The
  frontend stores it and sends it back each turn, so the server keeps no
  per-chat state.
- `turn` is what the UI renders: reply text, every tool call (for the trace
  panel and tool chips), and cards (product / PayPal approval / confirmation).

Two "brains" decide what to do, chosen by AI_PROVIDER:
- mock: a scripted, keyword-driven shopper. It still calls the **real**
  tool functions (real search, real PayPal sandbox order), so the full
  purchase works end to end without API credits.
- anthropic (Tuesday): Claude tool use over the same four tools.

Both brains write the same message format and go through _run_tool(), so
everything else (cards, route, frontend) is identical in both modes.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable

from sqlmodel import Session

from app import ai_provider, tools
from app.checkout import MAX_QTY, CheckoutError
from app.models import Product

# The tool registry: the same functions the MCP server exposes.
TOOLS: dict[str, Callable[..., object]] = {
    "search_products": tools.search_products,
    "get_product": tools.get_product,
    "create_checkout": tools.create_checkout,
    "get_order_status": tools.get_order_status,
}

MAX_HISTORY_MESSAGES = 100  # history comes from the browser; keep it bounded


# ---------- public entry point ----------

def chat(session: Session, history: list[dict], message: str) -> dict:
    history = list(history) + [{"role": "user", "content": message}]
    turn = _Turn(session, history)

    if ai_provider.is_mock():
        _mock_brain(turn, message)
    else:
        _claude_brain(turn)

    return {
        "history": _trim(turn.history),
        "turn": {"text": turn.text, "tool_calls": turn.tool_calls, "cards": _cards(session, turn.tool_calls)},
    }


def _trim(history: list[dict]) -> list[dict]:
    """Drop the oldest turns once history passes MAX_HISTORY_MESSAGES.

    Cuts only at the start of a turn (a user message with plain text), so a
    tool_use is never separated from its tool_result: Claude's API rejects
    a history with a dangling half.
    """
    if len(history) <= MAX_HISTORY_MESSAGES:
        return history
    starts = [i for i, m in enumerate(history) if m.get("role") == "user" and isinstance(m.get("content"), str)]
    cut = next((i for i in starts if len(history) - i <= MAX_HISTORY_MESSAGES), starts[-1] if starts else 0)
    return history[cut:]


class _Turn:
    """Accumulates one turn: appends messages to history and records tool calls."""

    def __init__(self, session: Session, history: list[dict]):
        self.session = session
        self.history = history
        self.tool_calls: list[dict] = []
        self.text = ""

    def call(self, name: str, args: dict) -> tuple[object, bool]:
        """Run a tool and record it in Anthropic format (tool_use + tool_result)."""
        call = _run_tool(self.session, name, args)
        self.tool_calls.append(call)
        self.history.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": call["id"], "name": name, "input": args},
        ]})
        self.history.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call["id"],
             "content": json.dumps(call["output"]), "is_error": call["is_error"]},
        ]})
        return call["output"], call["is_error"]

    def say(self, text: str) -> None:
        self.text = text
        self.history.append({"role": "assistant", "content": text})


def _run_tool(session: Session, name: str, args: dict, call_id: str | None = None) -> dict:
    """Execute one tool. Expected failures become is_error results (the model
    reads the message), exactly like the MCP server's ToolError."""
    started = time.perf_counter()
    try:
        output, is_error = TOOLS[name](session, **args), False
    except CheckoutError as e:
        output, is_error = {"error": e.code, "message": e.message}, True
    return {
        "id": call_id or f"toolu_mock_{secrets.token_hex(6)}",
        "name": name,
        "input": args,
        "output": output,
        "is_error": is_error,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }


# ---------- cards (shared by both brains) ----------

def _cards(session: Session, calls: list[dict]) -> list[dict]:
    """Turn tool results into UI cards. Derived from tool calls, not from the
    brain, so a Claude-driven turn gets the same cards for free."""
    cards = []
    for c in calls:
        out = c["output"]
        if c["is_error"]:
            continue
        if c["name"] == "get_product":
            product = session.get(Product, out["id"])  # photo isn't part of the agent JSON
            image = f"/uploads/{product.image_path}" if product and product.image_path else None
            cards.append({"type": "product", "product": out, "image_url": image})
        elif c["name"] == "create_checkout":
            cards.append({"type": "approval", "checkout": out})
        elif c["name"] == "get_order_status" and out["status"] == "COMPLETED":
            cards.append({"type": "confirmation", "order": out})
    return cards


# ---------- mock brain ----------

_STATUS_WORDS = {"status", "approved", "approve", "paid", "done", "finished", "completed", "complete", "check",
                 "payment", "paypal", "pay", "order"}
_CONFIRM_WORDS = {"yes", "yeah", "yep", "sure", "ok", "okay", "buy", "confirm", "checkout", "purchase",
                  "proceed", "go", "ahead", "it", "that", "one", "please", "do", "want", "take", "get"}
_STOP_WORDS = {"i", "me", "my", "a", "an", "the", "some", "any", "for", "to", "of", "and", "or", "with",
               "find", "show", "looking", "look", "search", "need", "would", "like", "can", "you", "is",
               "are", "there", "have", "something", "under", "below", "less", "than", "max", "up",
               "dollars", "usd", "cheap", "hi", "hello", "hey", "thanks", "thank", "in", "on", "what",
               "let", "now", "just", "think", "so", "all", "great", "cool", "will"}
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10}
_PRICE_RE = re.compile(r"(?:under|below|less than|max|up to|at most|<)\s*\$?\s*(\d+(?:\.\d+)?)|\$\s*(\d+(?:\.\d+)?)")


def _mock_brain(turn: _Turn, message: str) -> None:
    """Scripted shopper: search -> show product -> checkout on "yes" -> status.

    Intent comes from keywords in the message, plus what earlier tool calls
    in the history returned (the product last shown, the pending order).
    """
    text = message.lower()
    price_match = _PRICE_RE.search(text)
    max_price = float(next(g for g in price_match.groups() if g)) if price_match else None
    words = re.findall(r"[a-z]+", _PRICE_RE.sub(" ", text))
    ignored = _STOP_WORDS | _CONFIRM_WORDS | _STATUS_WORDS | set(_NUMBER_WORDS)
    # len > 1 drops contraction fragments ("I'm" -> "i", "m").
    content = [w for w in words if len(w) > 1 and w not in ignored]

    product_at, last_product = _last_result(turn.history, "get_product")
    order_at, last_order = _last_result(turn.history, "create_checkout")
    # A checkout created after the last product shown is the one in play.
    # Then "yes"/"ok"/"done" means "I approved", never "buy another".
    pending_order = last_order if last_order and order_at > product_at else None

    if not content and pending_order and (_STATUS_WORDS | _CONFIRM_WORDS) & set(words):
        return _mock_status(turn, pending_order["order_id"])
    if not content and _STATUS_WORDS & set(words) and last_order:
        return _mock_status(turn, last_order["order_id"])
    if not content and _CONFIRM_WORDS & set(words) and last_product:
        return _mock_checkout(turn, last_product, _qty(text))
    if content or max_price is not None:
        return _mock_search(turn, " ".join(content), max_price)
    turn.say("I'm the ShopMCP shopping assistant. Tell me what you're looking for, "
             "like \"a blue mug under $40\", and I'll search the shops for you.")


def _mock_search(turn: _Turn, query: str, max_price: float | None) -> None:
    args = {"query": query} | ({"max_price": max_price} if max_price is not None else {})
    results, _ = turn.call("search_products", args)
    available = [r for r in results if r["available"]]
    budget = f" under ${max_price:g}" if max_price is not None else ""
    if not available:
        turn.say(f"I couldn't find anything in stock matching \"{query or 'that'}\"{budget}. "
                 "Try different words or a higher budget.")
        return

    product, is_error = turn.call("get_product", {"product_id": available[0]["id"]})
    if is_error:  # e.g. unpublished between the two calls
        turn.say("That item just became unavailable. Want me to search again?")
        return

    others = "".join(f"\n- {r['title']}: ${r['price']['value']}" for r in available[1:4])
    turn.say(
        f"I found {len(available)} match{'es' if len(available) != 1 else ''}{budget}. "
        f"The best one is **{product['title']}** from {product['shop']['name']} "
        f"for ${product['price']['value']} ({product['stock']} in stock)."
        + (f"\n\nOther options:{others}" if others else "")
        + "\n\nWant me to start a PayPal checkout for it? You can also say how many, e.g. \"yes, 2\"."
    )


def _mock_checkout(turn: _Turn, product: dict, qty: int) -> None:
    checkout, is_error = turn.call("create_checkout", {"product_id": product["id"], "qty": qty})
    if is_error:
        turn.say(f"I couldn't start the checkout: {checkout['message']}.")
        return
    turn.say(
        f"Your PayPal checkout is ready: {qty} × {checkout['title']}, total "
        f"**${checkout['amount']} {checkout['currency']}**.\n\n"
        "Open the PayPal link to review and approve the payment. I can't pay for you; "
        "nothing is charged until you approve. Tell me when you're done and I'll confirm the order."
    )


def _mock_status(turn: _Turn, order_id: str) -> None:
    status, is_error = turn.call("get_order_status", {"order_id": order_id})
    if is_error:
        turn.say(f"I couldn't check that order: {status['message']}.")
    elif status["status"] == "COMPLETED":
        turn.say(f"Payment confirmed! {status['qty']} × {status['title']} is yours, "
                 f"${status['amount']['value']} paid via PayPal. The seller has the order.")
    elif status["status"] == "CREATED":
        turn.say("I don't see your approval yet. Open the PayPal link above, approve the payment, "
                 "then tell me and I'll check again.")
    else:
        turn.say(status["message"])  # APPROVED (capturing) or sold out: tool wording fits


def _qty(text: str) -> int:
    m = re.search(r"\b(\d{1,3})\b", text)
    n = int(m[1]) if m else next((v for w, v in _NUMBER_WORDS.items() if re.search(rf"\b{w}\b", text) and w != "one"), 1)
    return min(max(n, 1), MAX_QTY)


def _last_result(history: list[dict], tool_name: str) -> tuple[int, dict | None]:
    """(message index, output) of the most recent successful `tool_name`
    call in the conversation, or (-1, None)."""
    names: dict[str, str] = {}
    at, last = -1, None
    for i, msg in enumerate(history):
        if not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_use":
                names[block.get("id")] = block.get("name")
            elif (block.get("type") == "tool_result" and not block.get("is_error")
                  and names.get(block.get("tool_use_id")) == tool_name):
                try:
                    out = json.loads(block["content"])
                except (TypeError, ValueError, KeyError):
                    continue
                if isinstance(out, dict):
                    at, last = i, out
    return at, last


# ---------- Claude brain (Tuesday) ----------

def _claude_brain(turn: _Turn) -> None:
    # TODO (Tuesday): Claude tool use over TOOLS. Loop: messages.create with
    # turn.history + tool schemas (reuse the MCP tool descriptions and the
    # server INSTRUCTIONS as the system prompt) -> for each tool_use block run
    # _run_tool(..., call_id=block.id) and append tool_result -> repeat until
    # stop_reason == "end_turn", then turn.say(final text). Cap the loop
    # (e.g. 6 tool rounds) so a confused model can't spin.
    raise NotImplementedError("Claude shopper agent not wired up yet (AI_PROVIDER=anthropic)")

