"""Product photo -> structured listing JSON.

Both providers return the same shape and pass through the same validation
(`Listing`), so callers never need to know which one ran.
"""

from __future__ import annotations

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


def generate_listing(image_path: str | Path) -> dict:
    """Return a validated listing dict for one product photo."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported image type {path.suffix!r}; use {sorted(SUPPORTED_EXTS)}")

    if ai_provider.is_mock():
        raw = _mock_listing(path)
    else:
        raw = _claude_listing(path, ai_provider.model())

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


def _claude_listing(path: Path, model: str | None) -> dict:
    # TODO (Tuesday): send the image to Claude vision with a prompt asking for
    # exactly the Listing schema as JSON (base64 image block + text block),
    # parse the JSON from the response, and return the dict. Validation in
    # generate_listing() then applies unchanged. Cache results by image hash
    # in the DB so the same photo is never sent twice.
    raise NotImplementedError("Claude vision catalog not wired up yet (AI_PROVIDER=anthropic)")
