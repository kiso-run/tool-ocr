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
    """OCR via the Gemini backend (opt-in). Set KISO_OCR_BACKEND=gemini
    to force this path; the new default is tesseract (see TestOcrImageTesseract)."""

    @pytest.fixture(autouse=True)
    def _force_gemini_backend(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "gemini")

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
    """describe_image is Gemini-only — Tesseract is OCR not vision."""

    @pytest.fixture(autouse=True)
    def _force_gemini_backend(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "gemini")

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
    def test_gemini_backend_healthy(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "gemini")
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        h = check_health()
        assert h["healthy"] is True
        assert h["issues"] == []
        assert h["backend"] == "gemini"

    def test_gemini_backend_missing_key(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "gemini")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        h = check_health()
        assert h["healthy"] is False
        assert any("OPENROUTER_API_KEY" in i for i in h["issues"])

    def test_default_backend_is_tesseract(self, monkeypatch):
        """Privacy-first default: Tesseract local (no API key, no egress)."""
        monkeypatch.delenv("KISO_OCR_BACKEND", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        h = check_health()
        assert h["backend"] == "tesseract"

    def test_tesseract_backend_reports_languages(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "tesseract")
        with patch(
            "kiso_ocr_mcp.ocr_runner._tesseract_installed_languages",
            return_value=["eng", "ita", "osd"],
        ):
            h = check_health()
        assert h["backend"] == "tesseract"
        assert "tesseract_languages" in h
        assert "ita" in h["tesseract_languages"]

    def test_unknown_backend_unhealthy(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "bogus")
        h = check_health()
        assert h["healthy"] is False
        assert any("bogus" in i for i in h["issues"])

    def test_tesseract_missing_binary_unhealthy(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "tesseract")
        with patch(
            "kiso_ocr_mcp.ocr_runner._tesseract_installed_languages",
            side_effect=FileNotFoundError("tesseract not installed"),
        ):
            h = check_health()
        assert h["healthy"] is False
        assert any("tesseract" in i.lower() for i in h["issues"])


class TestOcrImageTesseract:
    """OCR via the Tesseract local backend (new default in v0.2)."""

    @pytest.fixture(autouse=True)
    def _force_tesseract_backend(self, monkeypatch):
        monkeypatch.setenv("KISO_OCR_BACKEND", "tesseract")

    def test_no_api_key_required(self, monkeypatch, png_file):
        """Tesseract runs locally — no OPENROUTER_API_KEY needed."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with patch(
            "kiso_ocr_mcp.ocr_runner._ocr_tesseract",
            return_value="Hello from Tesseract",
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["success"] is True
        assert result["text"] == "Hello from Tesseract"

    def test_uses_default_languages(self, monkeypatch, png_file):
        monkeypatch.delenv("KISO_OCR_TESSERACT_LANGS", raising=False)
        with patch(
            "kiso_ocr_mcp.ocr_runner._ocr_tesseract",
            return_value="text",
        ) as run:
            ocr_image(file_path=str(png_file))
        # Default langs from M1 spec: ita+eng
        called_langs = run.call_args.kwargs.get("langs") or run.call_args.args[1]
        assert called_langs == "ita+eng"

    def test_lang_override_via_env(self, monkeypatch, png_file):
        monkeypatch.setenv("KISO_OCR_TESSERACT_LANGS", "deu+fra")
        with patch(
            "kiso_ocr_mcp.ocr_runner._ocr_tesseract",
            return_value="text",
        ) as run:
            ocr_image(file_path=str(png_file))
        called_langs = run.call_args.kwargs.get("langs") or run.call_args.args[1]
        assert called_langs == "deu+fra"

    def test_describe_image_returns_structured_error(self, monkeypatch, png_file):
        """Tesseract is OCR-only; describe requires Gemini backend."""
        result = describe_image(file_path=str(png_file))
        assert result["success"] is False
        assert "describe_image requires backend=gemini" in result["stderr"]
        assert result["description"] == ""

    def test_response_includes_backend_field(self, monkeypatch, png_file):
        with patch(
            "kiso_ocr_mcp.ocr_runner._ocr_tesseract",
            return_value="text",
        ):
            result = ocr_image(file_path=str(png_file))
        assert result.get("backend") == "tesseract"

    def test_subprocess_error_surfaces(self, monkeypatch, png_file):
        with patch(
            "kiso_ocr_mcp.ocr_runner._ocr_tesseract",
            side_effect=RuntimeError("tesseract: cannot read image"),
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["success"] is False
        assert "tesseract" in result["stderr"].lower()

    def test_truncates_long_output(self, monkeypatch, png_file):
        long_text = "x" * 100_000
        with patch(
            "kiso_ocr_mcp.ocr_runner._ocr_tesseract",
            return_value=long_text,
        ):
            result = ocr_image(file_path=str(png_file))
        assert result["truncated"] is True
        assert len(result["text"]) <= 50_000


class TestOcrTesseractRunner:
    """Direct unit tests for the _ocr_tesseract subprocess wrapper."""

    def test_invokes_tesseract_binary(self, png_file):
        from kiso_ocr_mcp import ocr_runner

        completed = MagicMock(returncode=0, stdout="extracted text\n", stderr="")
        with patch(
            "kiso_ocr_mcp.ocr_runner.subprocess.run",
            return_value=completed,
        ) as run:
            text = ocr_runner._ocr_tesseract(png_file, langs="ita+eng")
        assert text == "extracted text\n"
        cmd = run.call_args.args[0]
        assert cmd[0] == "tesseract"
        assert str(png_file) in cmd
        assert "stdout" in cmd
        assert "-l" in cmd
        assert "ita+eng" in cmd

    def test_nonzero_exit_raises(self, png_file):
        from kiso_ocr_mcp import ocr_runner

        completed = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch(
            "kiso_ocr_mcp.ocr_runner.subprocess.run",
            return_value=completed,
        ), pytest.raises(RuntimeError, match="tesseract"):
            ocr_runner._ocr_tesseract(png_file, langs="ita+eng")

    def test_binary_missing_raises(self, png_file):
        from kiso_ocr_mcp import ocr_runner

        with patch(
            "kiso_ocr_mcp.ocr_runner.subprocess.run",
            side_effect=FileNotFoundError("tesseract not in PATH"),
        ), pytest.raises(RuntimeError, match="tesseract"):
            ocr_runner._ocr_tesseract(png_file, langs="ita+eng")
