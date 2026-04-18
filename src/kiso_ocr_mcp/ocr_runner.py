"""Image OCR core — Gemini multimodal call via OpenRouter.

Sends base64-encoded images to Gemini 2.0 Flash through OpenRouter's
``chat/completions`` endpoint. Two prompts are supported: ``extract``
(text only) and ``describe`` (scene description).

Dimension detection for PNG and JPEG is dependency-free (parses file
headers directly) so the server stays Pillow-free.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import time
import unicodedata
from pathlib import Path


_MAX_OUTPUT_CHARS = 50_000
_MAX_FILE_SIZE = 20 * 1024 * 1024  # Gemini inline image limit
_EMPTY_RETRIES = 2
_RETRY_BACKOFF = (1, 2)

_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif",
})

_EXTRACT_PROMPT = (
    "Extract ALL text from this image exactly as written. "
    "Preserve the original layout, line breaks, and formatting as much as possible. "
    "Return only the extracted text, no commentary or description."
)

_DESCRIBE_PROMPT = (
    "Describe what is in this image. Include: main subject, text content if any, "
    "layout, colors, and any notable visual elements. Be concise but thorough."
)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_GEMINI_MODEL = "google/gemini-2.0-flash-001"


def ocr_image(*, file_path: str) -> dict:
    return _call_vision(file_path=file_path, prompt=_EXTRACT_PROMPT, mode="ocr")


def describe_image(*, file_path: str) -> dict:
    return _call_vision(file_path=file_path, prompt=_DESCRIBE_PROMPT, mode="describe")


def image_info(*, file_path: str) -> dict:
    path = Path(file_path).expanduser()
    if not path.is_file():
        return {
            "success": False,
            "file_name": None,
            "size_bytes": None,
            "format": None,
            "width": None,
            "height": None,
            "stderr": f"file not found: {file_path}",
        }
    dims = _get_dimensions(path)
    return {
        "success": True,
        "file_name": path.name,
        "size_bytes": path.stat().st_size,
        "format": path.suffix.lower().lstrip("."),
        "width": dims[0] if dims else None,
        "height": dims[1] if dims else None,
        "stderr": "",
    }


def check_health() -> dict:
    issues: list[str] = []
    if not os.environ.get("OPENROUTER_API_KEY"):
        issues.append("OPENROUTER_API_KEY is not set")
    return {"healthy": not issues, "issues": issues}


def _call_vision(*, file_path: str, prompt: str, mode: str) -> dict:
    path = Path(file_path).expanduser()
    if not path.is_file():
        return _fail(mode, f"file not found: {file_path}")
    if path.suffix.lower() not in _IMAGE_EXTENSIONS:
        return _fail(mode, f"unsupported image format: {path.suffix}")
    size = path.stat().st_size
    if size > _MAX_FILE_SIZE:
        return _fail(
            mode,
            f"file too large ({_format_size(size)}); limit is "
            f"{_format_size(_MAX_FILE_SIZE)}",
        )
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return _fail(mode, "OPENROUTER_API_KEY is not set")

    try:
        text = _call_gemini(path, api_key, prompt)
    except RuntimeError as exc:
        return _fail(mode, str(exc), size=size, path=path)

    truncated = False
    if len(text) > _MAX_OUTPUT_CHARS:
        shown = text[:_MAX_OUTPUT_CHARS]
        last_nl = shown.rfind("\n")
        if last_nl > 0:
            shown = shown[:last_nl]
        text = shown
        truncated = True

    dims = _get_dimensions(path)
    result = {
        "success": True,
        "format": path.suffix.lower().lstrip("."),
        "width": dims[0] if dims else None,
        "height": dims[1] if dims else None,
        "truncated": truncated,
        "stderr": "",
    }
    if mode == "ocr":
        result["text"] = text
        result["has_text"] = _has_meaningful_content(text)
    else:  # describe
        result["description"] = text
    return result


def _call_gemini(file_path: Path, api_key: str, prompt: str) -> str:
    import httpx

    image_data = base64.b64encode(file_path.read_bytes()).decode()
    mime_type = mimetypes.guess_type(str(file_path))[0] or "image/png"

    payload = {
        "model": _GEMINI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        "max_tokens": 8192,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(_EMPTY_RETRIES + 1):
        response = httpx.post(_OPENROUTER_URL, headers=headers, json=payload, timeout=120)
        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini API error ({response.status_code}): {response.text[:500]}"
            )
        result = response.json()
        choices = result.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "") or ""
        # Reasoning→content fallback for models that route through reasoning field.
        if not _has_meaningful_content(content):
            reasoning = message.get("reasoning", "") or ""
            if _has_meaningful_content(reasoning):
                content = reasoning
        if _has_meaningful_content(content):
            return content
        if attempt < _EMPTY_RETRIES:
            time.sleep(_RETRY_BACKOFF[attempt])
    return ""


def _has_meaningful_content(text: str, min_chars: int = 3) -> bool:
    count = sum(1 for c in text if unicodedata.category(c)[0] in ("L", "N", "P"))
    return count >= min_chars


def _get_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()[:32]
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return (
                int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"),
            )
        if data[:2] == b"\xff\xd8":
            return _jpeg_dimensions(path)
    except OSError:
        return None
    return None


def _jpeg_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return (w, h)
        i += 2 + length
    return None


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _fail(mode: str, message: str, **_extra) -> dict:
    result = {
        "success": False,
        "format": None,
        "width": None,
        "height": None,
        "truncated": False,
        "stderr": message,
    }
    if mode == "ocr":
        result["text"] = ""
        result["has_text"] = False
    else:
        result["description"] = ""
    return result
