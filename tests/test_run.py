"""Unit tests for tool-ocr."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from run import (
    do_list, do_info, do_extract, do_describe,
    _resolve_path, _get_dimensions, _format_size, _check_file_size,
    _get_api_key, _has_meaningful_content, _MAX_OUTPUT_CHARS, _MAX_FILE_SIZE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    return tmp_path


def _make_png(path: Path, width: int = 100, height: int = 80) -> Path:
    """Create a minimal valid PNG file with specified dimensions."""
    import struct, zlib
    # PNG signature + IHDR + empty IDAT + IEND
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    # Minimal IDAT
    raw = b"\x00" * (width * 3 + 1) * height
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    # IEND
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    path.write_bytes(sig + ihdr + idat + iend)
    return path


@pytest.fixture
def png_file(workspace):
    return _make_png(workspace / "uploads" / "screenshot.png")


@pytest.fixture
def jpg_file(workspace):
    """Create a minimal JPEG file with SOF0 marker."""
    f = workspace / "uploads" / "photo.jpg"
    # Minimal JPEG: SOI + SOF0 (100x80) + EOI
    import struct
    soi = b"\xff\xd8"
    # SOF0 marker: FF C0, length=11, precision=8, height=80, width=100, components=3
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 80, 100) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    eoi = b"\xff\xd9"
    f.write_bytes(soi + sof0 + eoi)
    return f


@pytest.fixture
def mixed_files(workspace):
    _make_png(workspace / "uploads" / "img1.png")
    _make_png(workspace / "uploads" / "img2.png", 200, 150)
    (workspace / "uploads" / "report.pdf").write_bytes(b"\x00" * 100)
    (workspace / "uploads" / "voice.ogg").write_bytes(b"\x00" * 100)
    return workspace


# ---------------------------------------------------------------------------
# do_list
# ---------------------------------------------------------------------------


class TestDoList:
    def test_list_image_files(self, workspace, png_file, jpg_file):
        result = do_list(str(workspace))
        assert "Image files in uploads/ (2):" in result
        assert "screenshot.png" in result
        assert "photo.jpg" in result

    def test_list_filters_non_images(self, mixed_files):
        result = do_list(str(mixed_files))
        assert "2)" in result  # only 2 image files
        assert "img1.png" in result
        assert "img2.png" in result
        assert "report.pdf" not in result
        assert "voice.ogg" not in result

    def test_list_shows_dimensions(self, workspace, png_file):
        result = do_list(str(workspace))
        assert "100x80" in result

    def test_list_empty(self, workspace):
        result = do_list(str(workspace))
        assert "No image files" in result

    def test_list_no_uploads(self, tmp_path):
        result = do_list(str(tmp_path))
        assert "No uploads/" in result


# ---------------------------------------------------------------------------
# do_info
# ---------------------------------------------------------------------------


class TestDoInfo:
    def test_info_png(self, workspace, png_file):
        result = do_info(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "screenshot.png" in result
        assert ".png" in result
        assert "100x80" in result

    def test_info_jpg(self, workspace, jpg_file):
        result = do_info(str(workspace), {"file_path": "uploads/photo.jpg"})
        assert "photo.jpg" in result
        assert ".jpg" in result
        assert "100x80" in result

    def test_info_missing(self, workspace):
        with pytest.raises(FileNotFoundError):
            do_info(str(workspace), {"file_path": "uploads/nope.png"})


# ---------------------------------------------------------------------------
# do_extract
# ---------------------------------------------------------------------------


class TestDoExtract:
    def test_extract_success(self, workspace, png_file):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello World\nLine 2"}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "OCR: screenshot.png (100x80)" in result
        assert "Hello World" in result
        assert "Line 2" in result

    def test_extract_no_text_after_retries(self, workspace, png_file):
        """Empty response on all attempts (1 + 2 retries) → 'No text detected'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": ""}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
            patch("run.time.sleep"),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "No text detected" in result

    def test_extract_retry_succeeds(self, workspace, png_file):
        """Empty response on first call, success on retry."""
        empty = MagicMock()
        empty.status_code = 200
        empty.json.return_value = {"choices": [{"message": {"content": ""}}]}

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            "choices": [{"message": {"content": "Extracted text"}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", side_effect=[empty, success]),
            patch("run.time.sleep"),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "Extracted text" in result

    def test_extract_zero_width_unicode_triggers_retry(self, workspace, png_file):
        """M10: zero-width Unicode chars trigger retry, not accepted as content."""
        zwsp = "\u200b\u200c\ufeff"  # zero-width space, non-joiner, BOM
        empty_zw = MagicMock()
        empty_zw.status_code = 200
        empty_zw.json.return_value = {"choices": [{"message": {"content": zwsp}}]}

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            "choices": [{"message": {"content": "Extracted text from image"}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", side_effect=[empty_zw, success]),
            patch("run.time.sleep"),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "Extracted text" in result

    def test_extract_zero_width_all_retries_exhausted(self, workspace, png_file):
        """M10: if all retries return zero-width only, 'No text detected'."""
        zwsp = "\u200b"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": zwsp}}]}
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
            patch("run.time.sleep"),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "No text detected" in result

    def test_extract_api_error(self, workspace, png_file):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            with pytest.raises(RuntimeError, match="500"):
                do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})

    def test_extract_output_truncation(self, workspace, png_file):
        long_text = "word " * (_MAX_OUTPUT_CHARS // 3)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": long_text}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert len(result) < _MAX_OUTPUT_CHARS + 500
        assert "Showing first" in result

    def test_extract_file_too_large(self, workspace):
        big = workspace / "uploads" / "huge.png"
        big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (_MAX_FILE_SIZE + 1))
        with pytest.raises(ValueError, match="too large"):
            do_extract(str(workspace), {"file_path": "uploads/huge.png"})

    def test_extract_missing_file_path(self, workspace):
        with pytest.raises(ValueError, match="file_path"):
            do_extract(str(workspace), {})


# ---------------------------------------------------------------------------
# do_describe
# ---------------------------------------------------------------------------


class TestDoDescribe:
    def test_describe_success(self, workspace, png_file):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "A screenshot showing a code editor with Python code."}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            result = do_describe(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "Description: screenshot.png" in result
        assert "code editor" in result

    def test_describe_missing_file(self, workspace):
        with pytest.raises(FileNotFoundError):
            do_describe(str(workspace), {"file_path": "uploads/nope.png"})

    def test_describe_file_too_large(self, workspace):
        big = workspace / "uploads" / "huge.png"
        big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (_MAX_FILE_SIZE + 1))
        with pytest.raises(ValueError, match="too large"):
            do_describe(str(workspace), {"file_path": "uploads/huge.png"})

    def test_describe_api_error(self, workspace, png_file):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            with pytest.raises(RuntimeError, match="500"):
                do_describe(str(workspace), {"file_path": "uploads/screenshot.png"})

    def test_describe_missing_file_path(self, workspace):
        with pytest.raises(ValueError, match="file_path"):
            do_describe(str(workspace), {})


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------


class TestGetApiKey:
    def test_key_found(self):
        with patch.dict("os.environ", {"KISO_LLM_API_KEY": "sk-test"}, clear=True):
            assert _get_api_key() == "sk-test"

    def test_no_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="No API key"):
                _get_api_key()


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_traversal_rejected(self, workspace):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_path(str(workspace), {"file_path": "../../etc/passwd"})

    def test_valid_path(self, workspace, png_file):
        result = _resolve_path(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert result.name == "screenshot.png"

    def test_traversal_lateral_escape(self, tmp_path):
        """Sibling directory escape via prefix attack."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        sibling = tmp_path / "workspace-data"
        sibling.mkdir()
        secret = sibling / "file.png"
        secret.write_bytes(b"\x89PNG" + b"\x00" * 100)
        with pytest.raises(ValueError, match="traversal"):
            _resolve_path(str(workspace), {"file_path": "../workspace-data/file.png"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestGetDimensions:
    def test_png_dimensions(self, workspace, png_file):
        dims = _get_dimensions(png_file)
        assert dims == (100, 80)

    def test_jpeg_dimensions(self, workspace, jpg_file):
        dims = _get_dimensions(jpg_file)
        assert dims == (100, 80)

    def test_unknown_format(self, workspace):
        f = workspace / "uploads" / "data.bmp"
        f.write_bytes(b"BM" + b"\x00" * 50)
        dims = _get_dimensions(f)
        assert dims is None

    def test_png_various_sizes(self, tmp_path):
        p = _make_png(tmp_path / "big.png", 1920, 1080)
        assert _get_dimensions(p) == (1920, 1080)

        p2 = _make_png(tmp_path / "small.png", 16, 16)
        assert _get_dimensions(p2) == (16, 16)


class TestCheckFileSize:
    def test_ok(self, workspace, png_file):
        _check_file_size(png_file)  # should not raise

    def test_too_large(self, workspace):
        big = workspace / "uploads" / "huge.png"
        big.write_bytes(b"\x00" * (_MAX_FILE_SIZE + 1))
        with pytest.raises(ValueError, match="too large"):
            _check_file_size(big)


class TestReasoningFallback:
    """M981: reasoning→content fallback in _call_gemini."""

    def test_reasoning_fallback_used_when_content_empty(self, workspace, png_file, capsys):
        """Content empty but reasoning has text → fallback fires, WARNING printed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "", "reasoning": "Extracted text from reasoning"}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "Extracted text from reasoning" in result
        err = capsys.readouterr().err
        assert "reasoning-fallback" in err
        assert "WARNING" in err

    def test_reasoning_fallback_not_used_when_content_present(self, workspace, png_file, capsys):
        """Content has text → reasoning fallback is not triggered."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Normal content", "reasoning": "Should not be used"}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
        ):
            result = do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "Normal content" in result
        assert "Should not be used" not in result
        err = capsys.readouterr().err
        assert "reasoning-fallback" not in err

    def test_no_reasoning_parameter_in_payload(self, workspace, png_file):
        """M981: payload must not include the 'reasoning' key."""
        captured_payload = {}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "some text"}}],
        }

        def capture_call(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            return mock_response

        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", side_effect=capture_call),
        ):
            do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})
        assert "reasoning" not in captured_payload


class TestFormatSize:
    def test_bytes(self):
        assert _format_size(500) == "500 B"

    def test_kb(self):
        assert "KB" in _format_size(2048)

    def test_mb(self):
        assert "MB" in _format_size(5 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Functional: stdin/stdout
# ---------------------------------------------------------------------------


class TestFunctional:
    def test_list_via_stdin(self, workspace, png_file):
        input_data = json.dumps({
            "args": {"action": "list"},
            "workspace": str(workspace),
        })
        result = subprocess.run(
            [sys.executable, "run.py"],
            input=input_data, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "screenshot.png" in result.stdout

    def test_info_via_stdin(self, workspace, png_file):
        input_data = json.dumps({
            "args": {"action": "info", "file_path": "uploads/screenshot.png"},
            "workspace": str(workspace),
        })
        result = subprocess.run(
            [sys.executable, "run.py"],
            input=input_data, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "100x80" in result.stdout

    def test_missing_file_exits_1(self, workspace):
        input_data = json.dumps({
            "args": {"action": "extract", "file_path": "uploads/nope.png"},
            "workspace": str(workspace),
        })
        result = subprocess.run(
            [sys.executable, "run.py"],
            input=input_data, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_unknown_action_exits_1(self, workspace):
        input_data = json.dumps({
            "args": {"action": "explode"},
            "workspace": str(workspace),
        })
        result = subprocess.run(
            [sys.executable, "run.py"],
            input=input_data, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert "unknown" in result.stderr.lower()

    def test_malformed_json_stdin(self, workspace):
        """Malformed JSON input → exit 1, stderr contains error."""
        result = subprocess.run(
            [sys.executable, "run.py"],
            input="not json", capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert "invalid json" in result.stderr.lower() or "json" in result.stderr.lower()


class TestHasMeaningfulContent:
    """M10: _has_meaningful_content detects invisible Unicode."""

    def test_empty_string(self):
        assert not _has_meaningful_content("")

    def test_zero_width_only(self):
        assert not _has_meaningful_content("\u200b\u200c\ufeff")

    def test_whitespace_only(self):
        assert not _has_meaningful_content("   \n\t  ")

    def test_exit_passes(self):
        """4-letter word passes default threshold of 3."""
        assert _has_meaningful_content("EXIT")

    def test_real_ocr_text(self):
        assert _has_meaningful_content("Example Domain — This domain is for use in documentation.")

    def test_cjk_characters(self):
        """Chinese characters are category Lo — counted correctly."""
        assert _has_meaningful_content("你好世界")

    def test_two_char_word_fails_threshold_3(self):
        """2-char words are below default threshold 3 — triggers retry."""
        assert not _has_meaningful_content("OK")

    def test_custom_threshold(self):
        assert _has_meaningful_content("OK", min_chars=2)


# ---------------------------------------------------------------------------
# M11: KISO_WRAPPER_OCR_MODEL env var + no reasoning key in payload
# ---------------------------------------------------------------------------


class TestM11ModelEnvVar:
    """M11: model read from KISO_WRAPPER_OCR_MODEL env var, no reasoning in payload."""

    def test_env_var_overrides_model(self, workspace, png_file):
        """KISO_WRAPPER_OCR_MODEL overrides the default model sent to the API."""
        captured_payload = {}

        def fake_post(url, headers, json, timeout):
            captured_payload.update(json)
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = {
                "choices": [{"message": {"content": "OCR text result"}}]
            }
            return mock

        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", side_effect=fake_post),
            patch.dict("os.environ", {"KISO_WRAPPER_OCR_MODEL": "google/gemini-custom-model"}),
        ):
            do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})

        assert captured_payload.get("model") == "google/gemini-custom-model", (
            f"Expected custom model, got: {captured_payload.get('model')}"
        )

    def test_default_model_is_gemini_2_0_flash(self, workspace, png_file):
        """Without KISO_WRAPPER_OCR_MODEL, default model is google/gemini-2.0-flash."""
        captured_payload = {}

        def fake_post(url, headers, json, timeout):
            captured_payload.update(json)
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = {
                "choices": [{"message": {"content": "OCR text result"}}]
            }
            return mock

        env_without_model = {
            k: v for k, v in __import__("os").environ.items()
            if k != "KISO_WRAPPER_OCR_MODEL"
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", side_effect=fake_post),
            patch.dict("os.environ", env_without_model, clear=True),
        ):
            do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})

        assert captured_payload.get("model") == "google/gemini-2.0-flash-001", (
            f"Expected gemini-2.0-flash-001, got: {captured_payload.get('model')}"
        )

    def test_no_reasoning_key_in_payload(self, workspace, png_file):
        """No 'reasoning' key in the Gemini API payload (M11 requirement)."""
        captured_payload = {}

        def fake_post(url, headers, json, timeout):
            captured_payload.update(json)
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = {
                "choices": [{"message": {"content": "OCR text result"}}]
            }
            return mock

        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", side_effect=fake_post),
        ):
            do_extract(str(workspace), {"file_path": "uploads/screenshot.png"})

        assert "reasoning" not in captured_payload, (
            f"'reasoning' key found in payload: {list(captured_payload.keys())}"
        )
