"""Unit tests for kiso_ocr_mcp.ocr_runner."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kiso_ocr_mcp.ocr_runner import (
    check_health,
    describe_image,
    image_info,
    ocr_image,
)


_PNG_MIN = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\x0dIHDR"
    + (64).to_bytes(4, "big")
    + (48).to_bytes(4, "big")
    + b"\x08\x02\x00\x00\x00"
)


@pytest.fixture
def png_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.png"
    f.write_bytes(_PNG_MIN + b"\x00" * 16)
    return f


class TestOcrImage:
    def test_missing_api_key_fails(self, monkeypatch, png_file):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        result = ocr_image(file_path=str(png_file))
        assert result["success"] is False
        assert "OPENROUTER_API_KEY" in result["stderr"]

    def test_file_not_found(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        result = ocr_image(file_path=str(tmp_path / "missing.png"))
        assert result["success"] is False
        assert "not found" in result["stderr"].lower()

    def test_unsupported_format(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        f = tmp_path / "x.txt"
        f.write_text("text")
        result = ocr_image(file_path=str(f))
        assert result["success"] is False
        assert "unsupported" in result["stderr"].lower()

    def test_file_too_large(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        huge = tmp_path / "big.png"
        huge.write_bytes(b"\x89PNG" + b"\x00" * (25 * 1024 * 1024))
        result = ocr_image(file_path=str(huge))
        assert result["success"] is False
        assert "too large" in result["stderr"].lower()

    def test_success_with_text(self, monkeypatch, png_file):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch(
            "kiso_ocr_mcp.ocr_runner._call_gemini",
            return_value="Hello World",
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["success"] is True
        assert result["text"] == "Hello World"
        assert result["has_text"] is True
        assert result["format"] == "png"
        assert result["width"] == 64
        assert result["height"] == 48
        assert result["truncated"] is False

    def test_no_text_detected(self, monkeypatch, png_file):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        # Gemini returned effectively nothing (no meaningful content).
        with patch(
            "kiso_ocr_mcp.ocr_runner._call_gemini",
            return_value="",
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["success"] is True
        assert result["text"] == ""
        assert result["has_text"] is False

    def test_truncates_long_output(self, monkeypatch, png_file):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        huge = "x" * 100_000
        with patch(
            "kiso_ocr_mcp.ocr_runner._call_gemini",
            return_value=huge,
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["truncated"] is True
        assert len(result["text"]) <= 50_000

    def test_api_error_surfaces(self, monkeypatch, png_file):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch(
            "kiso_ocr_mcp.ocr_runner._call_gemini",
            side_effect=RuntimeError("Gemini API error (500): boom"),
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["success"] is False
        assert "500" in result["stderr"]


class TestDescribeImage:
    def test_success_returns_description(self, monkeypatch, png_file):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch(
            "kiso_ocr_mcp.ocr_runner._call_gemini",
            return_value="A cat on a red sofa.",
        ):
            result = describe_image(file_path=str(png_file))
        assert result["success"] is True
        assert result["description"].startswith("A cat")
        assert "text" not in result


class TestImageInfo:
    def test_png_dimensions(self, png_file):
        info = image_info(file_path=str(png_file))
        assert info["success"] is True
        assert info["format"] == "png"
        assert info["width"] == 64
        assert info["height"] == 48

    def test_not_found(self, tmp_path):
        info = image_info(file_path=str(tmp_path / "nope.png"))
        assert info["success"] is False


class TestCallGeminiRetry:
    def test_empty_then_empty_returns_empty(self, monkeypatch, png_file):
        from kiso_ocr_mcp import ocr_runner

        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "choices": [{"message": {"content": ""}}]
        }
        with patch("httpx.post", return_value=mock_response) as post, \
             patch("kiso_ocr_mcp.ocr_runner.time.sleep"):
            result = ocr_runner._call_gemini(png_file, "k", "p")
        assert result == ""
        assert post.call_count == 3

    def test_reasoning_fallback(self, monkeypatch, png_file):
        from kiso_ocr_mcp import ocr_runner

        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "choices": [{
                "message": {"content": "", "reasoning": "fell back to here"},
            }],
        }
        with patch("httpx.post", return_value=mock_response):
            result = ocr_runner._call_gemini(png_file, "k", "p")
        assert "fell back" in result

    def test_http_error_raises(self, png_file):
        from kiso_ocr_mcp import ocr_runner

        mock_response = MagicMock(status_code=500, text="server boom")
        with patch("httpx.post", return_value=mock_response), \
             pytest.raises(RuntimeError, match="500"):
            ocr_runner._call_gemini(png_file, "k", "p")


class TestCheckHealth:
    def test_healthy(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        h = check_health()
        assert h["healthy"] is True
        assert h["issues"] == []

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        h = check_health()
        assert h["healthy"] is False
        assert any("OPENROUTER_API_KEY" in i for i in h["issues"])
