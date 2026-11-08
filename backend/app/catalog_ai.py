"""Product photo -> structured listing JSON.

Both providers return the same shape and pass through the same validation
(`Listing`), so callers never need to know which one ran.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app import ai_provider

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "listings.json"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}  # Claude vision formats


class Listing(BaseModel):
    """The strict listing schema. extra="forbid" rejects stray keys from the model."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    attributes: dict[str, str | int | float | bool]
    tags: list[str] = Field(min_length=1, max_length=15)
    # USD as a decimal string with exactly two places, e.g. "34.00".
    # Strings (not floats) because PayPal amounts are strings and floats round badly.
    suggested_price: str = Field(pattern=r"^\d{1,6}\.\d{2}$")


def generate_listing(image_path: str | Path, *, client_key: str | None = None) -> dict:
    """Return a validated listing dict for one product photo.

    client_key identifies the visitor for the AI rate limit (anthropic mode).
    Raises ai_budget.AIBudgetExceeded if a cost limit is hit.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported image type {path.suffix!r}; use {sorted(SUPPORTED_EXTS)}")

    if ai_provider.is_mock():
        raw = _mock_listing(path)
    else:
        raw = _claude_listing(path, client_key)

    return Listing.model_validate(raw).model_dump()


@lru_cache(maxsize=1)
def _fixtures() -> dict[str, dict]:
    return json.loads(FIXTURES.read_text())


def _mock_listing(path: Path) -> dict:
    """Pick a canned listing by keyword in the filename ("blue_mug.jpg" -> mug)."""
    fixtures = _fixtures()
    words = set(re.split(r"[^a-z]+", path.stem.lower()))
    for keyword, listing in fixtures.items():
        if keyword != "generic" and keyword in words:
            return dict(listing)
    return dict(fixtures["generic"])


# ---------- Claude vision ----------

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}

_LISTING_PROMPT = """\
You write product listings for a small independent online shop. Look at the
product photo and write the listing a careful seller would publish.

- title: specific and searchable, at most 80 characters (what it is, key
  material or brand, color). No hype words.
- description: 2-4 plain sentences. Describe only what you can see or
  reasonably infer. If the item looks used, say so. Never claim it is
  handmade, new, a specific brand or model, or a size unless the photo shows it.
- attributes: 3-8 short facts as name/value pairs (e.g. material, color,
  condition, style, approximate size). Use lowercase snake_case names.
- tags: 3-8 lowercase search keywords a shopper might type.
- suggested_price: a fair USD price for a small independent seller, as a
  string with two decimals, e.g. "24.00".
"""

# Structured outputs guarantee JSON in this exact shape. Attributes are
# name/value pairs because strict schemas can't express a free-form object;
# they are turned back into a dict before validation.
_LISTING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
                "required": ["name", "value"],
                "additionalProperties": False,
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "suggested_price": {"type": "string"},
    },
    "required": ["title", "description", "attributes", "tags", "suggested_price"],
    "additionalProperties": False,
}


def _claude_listing(path: Path, client_key: str | None) -> dict:
    """Send the photo to Claude vision; cached by image hash so the same
    photo is never sent (or billed) twice."""
    from sqlmodel import Session

    from app.db import engine
    from app.models import ListingCache

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    with Session(engine) as s:
        cached = s.get(ListingCache, digest)
        if cached is not None:
            return dict(cached.listing)

    response = ai_provider.create_message(
        client_key=client_key,
        max_tokens=4000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _LISTING_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": _MEDIA_TYPES[path.suffix.lower()],
                    "data": base64.standard_b64encode(data).decode("ascii"),
                }},
                {"type": "text", "text": _LISTING_PROMPT},
            ],
        }],
    )
    if response.stop_reason == "refusal":
        raise ValueError("The AI declined to describe this photo")
    if response.stop_reason == "max_tokens":
        raise ValueError("The AI response was cut off; please try again")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError("The AI returned no listing")

    raw = json.loads(text)
    raw["attributes"] = _attributes_dict(raw.get("attributes", []))
    raw["suggested_price"] = _normalize_price(raw.get("suggested_price", ""))
    raw["title"] = raw.get("title", "")[:120]
    raw["tags"] = [t.strip().lower() for t in raw.get("tags", []) if t.strip()][:15]

    listing = Listing.model_validate(raw).model_dump()  # same strict check as mock mode
    with Session(engine) as s:
        s.merge(ListingCache(image_sha256=digest, listing=listing, model=ai_provider.model() or ""))
        s.commit()
    return listing


def _attributes_dict(pairs: list[dict]) -> dict[str, str | int | float | bool]:
    out: dict[str, str | int | float | bool] = {}
    for pair in pairs[:12]:
        name = re.sub(r"[^a-z0-9_]+", "_", str(pair.get("name", "")).strip().lower()).strip("_")[:40]
        value = str(pair.get("value", "")).strip()[:120]
        if name and value:
            out[name] = value
    return out


def _normalize_price(value: str) -> str:
    # Reuse the API's price rules ("24" -> "24.00", "$1,200" -> "1200.00").
    from app.schemas import normalize_price

    normalized = normalize_price(str(value))
    return normalized if isinstance(normalized, str) else str(value)
