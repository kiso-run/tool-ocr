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

## M2 — Unit tests

- [ ] Test `do_list` with image files, mixed files (filters non-images), empty dir, no uploads/
- [ ] Test `do_info` with PNG and JPEG files (real header parsing for dimensions)
- [ ] Test `do_extract` with mocked Gemini API response
- [ ] Test `do_describe` with mocked Gemini API response
- [ ] Test API key resolution (present → ok, missing → error)
- [ ] Test file size guard (>20 MB rejected)
- [ ] Test path traversal guard
- [ ] Test output truncation on very long OCR result
- [ ] Test `_get_dimensions` for PNG and JPEG (real small fixture images)
- [ ] Test `_format_size` helper
- [ ] Functional test: stdin/stdout contract (list, extract, missing file, unknown action)

## M3 — Static fixture files

- [ ] `tests/fixtures/sample.png` — small PNG with text "Hello World" (generated via Python)
- [ ] `tests/fixtures/sample.jpg` — small JPEG with text
- [ ] `create_fixtures.py` script to regenerate
- [ ] Use fixtures in dimension detection tests (real parsing, no mock)

## M4 — Integration with kiso registry

- [ ] Add tool-ocr to core registry.json
- [ ] Verify `kiso tool install ocr` works end-to-end (needs Docker + VPS)
- [ ] Live test: send photo via Discord → OCR text appears in response

## Known Issues

- No support for multi-page TIFF (only first frame processed)
- Very low resolution images (<100px) may produce poor OCR results
- Handwriting recognition quality depends on legibility — Gemini is good but not perfect
- For scanned PDFs: docreader handles the PDF format; if no text extractable, it suggests using OCR after converting pages to images
