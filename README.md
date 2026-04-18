# kiso-ocr-mcp

Image OCR and description exposed as a
[Model Context Protocol](https://modelcontextprotocol.io) server. Uses
Gemini 2.0 Flash via OpenRouter.

Part of the [`kiso-run`](https://github.com/kiso-run) project.

## Install

```sh
uvx --from git+https://github.com/kiso-run/ocr-mcp@v0.1.0 kiso-ocr-mcp
```

## Required environment

| Variable             | Required | Purpose                       |
|----------------------|----------|-------------------------------|
| `OPENROUTER_API_KEY` | yes      | Gemini backend via OpenRouter |

## MCP client config

```json
{
  "mcpServers": {
    "ocr": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/kiso-run/ocr-mcp@v0.1.0",
        "kiso-ocr-mcp"
      ],
      "env": { "OPENROUTER_API_KEY": "${env:OPENROUTER_API_KEY}" }
    }
  }
}
```

## Tools

### `ocr_image(file_path)`

Extract text from an image. Returns `{success, text, has_text,
format, width, height, truncated, stderr}`. `has_text` is `false`
when no meaningful characters were detected (blank photo, pure
graphics). Transcripts are truncated at 50 000 chars.

### `describe_image(file_path)`

Scene description (subject, layout, colors, text). Returns
`{success, description, format, width, height, truncated, stderr}`.

### `image_info(file_path)`

File metadata (no LLM call). Returns `{success, file_name,
size_bytes, format, width, height, stderr}`. PNG and JPEG dimensions
are parsed directly from the file header.

### `doctor()`

`{healthy, issues}` — reports missing `OPENROUTER_API_KEY`.

## Supported formats

`png`, `jpg`, `jpeg`, `webp`, `gif`, `bmp`, `tiff`, `tif`.
Max file size: 20 MB (Gemini inline image limit).

## Reliability

- **Reasoning-field fallback**: some model variants route response
  text to `reasoning` instead of `content`; the runner handles both.
- **Empty-response retry**: up to 2 retries with 1s/2s backoff.
- **Output cap**: 50 000 chars with `truncated: true` flag.

## Development

```sh
uv sync
uv run pytest tests/ -q                    # unit only
OPENROUTER_API_KEY=... uv run pytest tests/ -q  # include live test
```

## License

MIT.
