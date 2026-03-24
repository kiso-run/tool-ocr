# tool-ocr — Development Plan

Image OCR tool for kiso. Extracts text from photos, screenshots, receipts, whiteboards, and scanned documents using Gemini multimodal vision via OpenRouter.

## Architecture

```
stdin (JSON) → run.py → resolve image → base64 → Gemini chat (vision) → stdout (text)
```

- **Entry point**: `run.py` reads JSON from stdin, dispatches to action handler
- **Actions**: `extract` (default), `describe`, `info`, `list`
- **API**: Gemini 2.5 Flash via OpenRouter `/chat/completions` (image as base64 inline content)
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

## M5 — Security + robustness fixes (code review) ✅

**Path traversal prefix attack (CRITICAL):**
- [x] `run.py:_resolve_path()` — replace `str(resolved).startswith(str(ws_resolved))` with `resolved.relative_to(ws_resolved)`

**JSON input safety:**
- [x] Wrap `json.load(sys.stdin)` in try-except JSONDecodeError — print clean error + exit 1

**do_describe test coverage:**
- [x] Add tests: missing file, file too large, API error, missing file_path arg (currently only 1 test)

**Tests to add:**
- [x] Path traversal lateral escape (`../sibling-dir/file.txt`)
- [x] Malformed JSON stdin
- [x] `uv run pytest tests/ -q` passes — 38 tests

## Known Issues

- No support for multi-page TIFF (only first frame processed)
- Very low resolution images (<100px) may produce poor OCR results
- Handwriting recognition quality depends on legibility — Gemini is good but not perfect
- For scanned PDFs: docreader handles the PDF format; if no text extractable, it suggests using OCR after converting pages to images

---

### M6 — Declare `consumes` in kiso.toml (core M826)

**Context:** Core M826 adds a `consumes` field to `[kiso.tool]` in kiso.toml. The planner uses
this to auto-route session workspace files to the right tool. Vocabulary: `image`, `document`,
`audio`, `video`, `code`, `web_page`.

**Changes:**
- [x] Add `consumes = ["image"]` to `[kiso.tool]` in kiso.toml
- [ ] Enrich `usage_guide` with concrete arg examples and supported formats list

---

### M7 — Switch model from gemini-2.5-flash-lite to gemini-2.5-flash ✅

**Problem:** `_call_gemini()` uses `google/gemini-2.5-flash-lite`
which consistently returns empty text for simple screenshots (e.g.
example.com). The lite variant is too weak for vision/OCR tasks.
Even with temperature:0 and retry (M916), the API returns empty
on all attempts.

Gemini 2.5 Flash (non-lite) has proven OCR capabilities — widely
used for document processing, receipt scanning, handwriting
extraction. Cost difference is negligible at ~260 tokens/image.

**Approach:** Change the model string in `_call_gemini()` from
`google/gemini-2.5-flash-lite` to `google/gemini-2.5-flash`.

**Files:** `run.py`, `tests/test_run.py`

**Tasks:**
- [x] Change model from `google/gemini-2.5-flash-lite` to
  `google/gemini-2.5-flash` in `_call_gemini`
- [x] Update DEVPLAN.md architecture section (model reference)
- [x] No test assertions check model name — tests mock httpx.post

---

### M8 — Disable thinking for gemini-2.5-flash ✅

**Problem:** gemini-2.5-flash has built-in thinking that consumes
max_tokens, leaving content empty for OCR responses.

M8 first attempt used `"reasoning": {"effort": "none"}` — but
`"none"` is NOT a valid OpenRouter value. Valid values are `"low"`,
`"medium"`, `"high"`. The parameter was silently ignored, thinking
stayed active, and OCR kept returning empty.

**Approach:** Change to `"reasoning": {"effort": "low"}` which
uses only ~20% of max_tokens for reasoning, preserving ~6500+ tokens
for actual content. Also increase max_tokens from 4096 to 8192.

**Files:** `run.py`

**Tasks:**
- [x] ~~Add reasoning effort none~~ (invalid, reverted)
- [x] Change to `"reasoning": {"effort": "low"}`
- [x] Increase max_tokens from 4096 to 8192
