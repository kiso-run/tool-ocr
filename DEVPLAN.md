# tool-ocr — Development Plan

Image OCR tool for kiso. Extracts text from photos, screenshots, receipts, whiteboards, and scanned documents using Gemini multimodal vision via OpenRouter.

## Architecture

```
stdin (JSON) → run.py → resolve image → base64 → Gemini chat (vision) → stdout (text)
```

- **Entry point**: `run.py` reads JSON from stdin, dispatches to action handler
- **Actions**: `extract` (default), `describe`, `info`, `list`
- **API**: Gemini 2.5 Flash Lite via OpenRouter `/chat/completions` (image as base64 inline content)
- **API key**: reuses `KISO_LLM_API_KEY` — zero extra config
- **No system deps**: pure Python + httpx, no Tesseract/OpenCV/etc.
- **Image dimensions**: parsed from PNG/JPEG headers (no PIL dependency)

## Token / Cost Strategy

Gemini tokenizes images at ~260 tokens per image (A4 equivalent). At $0.15/1M input tokens:

| Usage | Cost |
|-------|------|
| 1 image | $0.00004 |
| 100 images/day | $0.004/day |
| 1000 images/day | $0.04/day |

Output (extracted text): negligible cost. Total per-image cost is essentially zero.

## M1 — Core implementation ✅

- [x] Project structure: kiso.toml, pyproject.toml, run.py, deps.sh, README, LICENSE
- [x] `extract` action: resolve image → base64 → Gemini → return OCR text with header
- [x] `describe` action: describe image content (visual elements, layout, text)
- [x] `info` action: file metadata (format, dimensions, size)
- [x] `list` action: enumerate image files in uploads/ with dimensions
- [x] Path traversal guard
- [x] File size guard (20 MB limit — Gemini inline image limit)
- [x] Output truncation at 50K chars
- [x] Image dimension detection from PNG/JPEG headers (no PIL)
- [x] API key: `KISO_LLM_API_KEY` only

## M2 — Unit tests ✅

- [x] `do_list`: image files, mixed (filters non-images), dimensions, empty dir, no uploads/
- [x] `do_info`: PNG with dimensions, JPEG with dimensions, missing file
- [x] `do_extract`: success, no text detected, API error, output truncation, file too large, missing file_path
- [x] `do_describe`: success with mocked Gemini
- [x] API key: present → ok, missing → error
- [x] Path traversal guard
- [x] `_get_dimensions`: PNG, JPEG, unknown format, various sizes
- [x] `_check_file_size`, `_format_size`
- [x] Functional: list, info, missing file exits 1, unknown action exits 1
- 32 tests, all passing

## M3 — Static fixture files ✅

- [x] `tests/fixtures/sample.png` — 200x100 PNG (137 bytes, generated via pure Python)
- [x] Tests create real PNG/JPEG files inline via `_make_png()` helper — real header parsing, no mocks

## M4 — Integration with kiso registry (pending — needs VPS)

- [x] tool-ocr added to core registry.json
- [ ] Verify `kiso tool install ocr` works end-to-end (needs Docker + VPS)
- [ ] Live test: send photo via Discord → OCR text appears in response

## M5 — Security + robustness fixes (code review)

**Path traversal prefix attack (CRITICAL):**
- [ ] `run.py:_resolve_path()` — replace `str(resolved).startswith(str(ws_resolved))` with `resolved.relative_to(ws_resolved)`

**JSON input safety:**
- [ ] Wrap `json.load(sys.stdin)` in try-except JSONDecodeError — print clean error + exit 1

**do_describe test coverage:**
- [ ] Add tests: missing file, file too large, API error, missing file_path arg (currently only 1 test)

**Tests to add:**
- [ ] Path traversal lateral escape (`../sibling-dir/file.txt`)
- [ ] Malformed JSON stdin
- [ ] `uv run pytest tests/ -q` passes

## Known Issues

- No support for multi-page TIFF (only first frame processed)
- Very low resolution images (<100px) may produce poor OCR results
- Handwriting recognition quality depends on legibility — Gemini is good but not perfect
- For scanned PDFs: docreader handles the PDF format; if no text extractable, it suggests using OCR after converting pages to images
