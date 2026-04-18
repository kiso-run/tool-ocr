"""Live integration test — runs real Gemini OCR against the fixture image."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from kiso_ocr_mcp.ocr_runner import ocr_image


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("OPENROUTER_API_KEY"),
        reason="OPENROUTER_API_KEY required for live OCR test",
    ),
]


def test_ocr_fixture_image():
    """End-to-end: encode → OpenRouter → Gemini → structured response.

    The fixture is a minimal test image; whether it contains real text is not
    the point. What matters is that the HTTP round-trip + schema parsing
    succeeds and returns the expected shape.
    """
    fixture = Path(__file__).parent / "fixtures" / "sample.png"
    assert fixture.exists(), "sample.png fixture missing"

    result = ocr_image(file_path=str(fixture))
    assert result["success"], f"OCR failed: stderr={result['stderr']!r}"
    assert result["format"] == "png"
    assert isinstance(result["has_text"], bool)
    assert result["width"] and result["height"]
