"""Photo -> listing JSON check. Works in mock mode with no API key.

Run from the repo root:
    backend/.venv/bin/python scripts/vision_smoke_test.py path/to/photo.jpg [more.jpg ...]

With no arguments it creates placeholder images named after each mock
keyword (plus one unmatched name) in a temp dir, so every fixture path and
the generic fallback get exercised.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import ai_provider, catalog_ai  # noqa: E402

DEMO_NAMES = ["blue_mug.jpg", "white-vase.png", "sage_bowl.jpeg", "IMG_0042.jpg"]


def main(paths: list[str]) -> int:
    print(f"AI_PROVIDER={ai_provider.provider()}  AI_MODEL={ai_provider.model()}")
    with tempfile.TemporaryDirectory() as tmp:
        if not paths:
            for name in DEMO_NAMES:
                (Path(tmp) / name).write_bytes(b"placeholder")  # mock mode reads only the name
            paths = [str(Path(tmp) / n) for n in DEMO_NAMES]

        for p in paths:
            listing = catalog_ai.generate_listing(p)
            print(f"\n== {Path(p).name} ==")
            print(json.dumps(listing, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
