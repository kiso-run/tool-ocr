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
    _get_api_key, _MAX_OUTPUT_CHARS, _MAX_FILE_SIZE,
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

    def test_extract_no_text(self, workspace, png_file):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": ""}}],
        }
        with (
            patch("run._get_api_key", return_value="sk-test"),
            patch("httpx.post", return_value=mock_response),
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
