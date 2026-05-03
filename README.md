# kiso-ocr-mcp

Image OCR exposed as a
[Model Context Protocol](https://modelcontextprotocol.io) server.

Pluggable backend, local-first by default:

- **`tesseract`** (default) — local OCR via the Tesseract binary. No
  API key, no data egress, runs in the appliance. Suitable for
  privacy-strict consumers and the common case of clean printed text
  (business documents, screenshots, scanned invoices).
- **`gemini`** — Gemini 2.0 Flash via OpenRouter. Higher quality on
  noisy scans, handwriting, and image description. The only backend
  for `describe_image`.

Part of the [`kiso-run`](https://github.com/kiso-run) project.

## Install

```sh
uvx --from git+https://github.com/kiso-run/ocr-mcp@v0.2.0 kiso-ocr-mcp
```

System dependency: install Tesseract OCR if you use the default
backend (most distros ship it):

```sh
# Debian / Ubuntu
apt install tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng
# macOS
brew install tesseract tesseract-lang
```

## Required environment

| Variable                   | Required (when)                            | Purpose                                                                          |
|----------------------------|--------------------------------------------|----------------------------------------------------------------------------------|
| `KISO_OCR_BACKEND`         | optional (default `tesseract`)             | Backend selector: `tesseract` or `gemini`                                        |
| `KISO_OCR_TESSERACT_LANGS` | optional (default `ita+eng`)               | Tesseract language stack — e.g. `ita+eng+deu`. Each language must be installed.  |
| `OPENROUTER_API_KEY`       | required when backend = `gemini`           | Gemini backend via OpenRouter                                                    |

## MCP client config

### Backend `tesseract` (default — local, no API key)

```json
{
  "mcpServers": {
    "ocr": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/kiso-run/ocr-mcp@v0.2.0",
        "kiso-ocr-mcp"
      ]
    }
  }
}
```

### Backend `gemini` (cloud, higher quality on noisy/handwritten input)

```json
{
  "mcpServers": {
    "ocr": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/kiso-run/ocr-mcp@v0.2.0",
        "kiso-ocr-mcp"
      ],
      "env": {
        "KISO_OCR_BACKEND": "gemini",
        "OPENROUTER_API_KEY": "${env:OPENROUTER_API_KEY}"
      }
    }
  }
}
```

## Tools

### `ocr_image(file_path)`

Extract text from an image. Works on both backends.

Returns `{success, text, has_text, format, width, height, truncated,
backend, stderr}`. `has_text` is `false` when no meaningful characters
were detected (blank photo, pure graphics). Output truncated at 50 000
chars with `truncated: true`.

### `describe_image(file_path)`

Scene description (subject, layout, colors, text). **Gemini-only** —
Tesseract is OCR, not vision. When `backend=tesseract` this returns a
structured error directing the caller to switch backend.

Returns `{success, description, format, width, height, truncated,
backend, stderr}`.

### `image_info(file_path)`

File metadata (no LLM call). Returns `{success, file_name, size_bytes,
format, width, height, stderr}`. PNG and JPEG dimensions are parsed
directly from the file header.

### `doctor()`

Reports runner health and active configuration:

```json
{
  "healthy": true,
  "issues": [],
  "backend": "tesseract",
  "tesseract_languages": ["eng", "ita", "osd"]
}
```

For the `gemini` backend, omits `tesseract_languages` and reports
missing `OPENROUTER_API_KEY` if relevant.

## Supported formats

`png`, `jpg`, `jpeg`, `webp`, `gif`, `bmp`, `tiff`, `tif`.
Max file size: 20 MB (Gemini inline image limit; Tesseract has no
hard limit but the same cap applies for parity).

## When to use which backend

- **Default to `tesseract`** for clean printed text: business
  documents, screenshots, well-scanned invoices and receipts. Free per
  call, runs entirely local, no data egress.
- **Switch to `gemini`** for: handwriting, complex layouts that
  Tesseract struggles with, mixed-language scans where the language
  stack is unknown ahead of time, and any `describe_image` use case
  (Tesseract has no vision capability).
- The two are independent — a tenant can default to one and override
  per-tool via env at deploy time, or run two separate MCP server
  instances pointing at each backend if both are needed concurrently.

## Reliability

- **Tesseract**: subprocess invocation with a 60 s timeout. Failures
  surface as `success=false` with the binary's stderr in `stderr`.
- **Gemini**: empty-response retry up to 2 attempts with 1s/2s
  backoff. Reasoning-field fallback for model variants that route
  output to `reasoning` instead of `content`.
- **Output cap**: 50 000 chars with `truncated: true` flag, on both
  backends.

## Migration from v0.1

v0.1 routed every call to Gemini and required `OPENROUTER_API_KEY`.
v0.2 changes the **default backend to `tesseract`**.

If you depend on v0.1 behaviour, set `KISO_OCR_BACKEND=gemini` in your
client env. Otherwise no action required — `ocr_image` calls continue
to work and now run locally and free.

## Development

```sh
uv sync
uv run pytest tests/ -q                    # unit only
OPENROUTER_API_KEY=... uv run pytest tests/ -q  # include live test
```

## License

MIT.
