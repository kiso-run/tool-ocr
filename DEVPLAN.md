# kiso-ocr-mcp — Development Plan

## Status

**Legacy wrapper era — closed.** The `tool-ocr` / `wrapper-ocr`
subprocess-contract implementation has been replaced by a Model
Context Protocol server.

**Current era: MCP server.** Tracked in `kiso-run/core` as M1510.

---

## v0.1 — MCP rewrite (2026-04-18)

- [x] Strip legacy wrapper files (`run.py`, `kiso.toml`, `deps.sh`,
      `validator.py`); preserve `tests/fixtures/sample.png`
- [x] New `pyproject.toml` with package name `kiso-ocr-mcp`,
      entry point, MCP SDK dep
- [x] `src/kiso_ocr_mcp/ocr_runner.py` — Gemini 2.0 Flash call via
      OpenRouter, PNG/JPEG dimension parsing, empty-response retry
      + reasoning-field fallback, 50 000-char output cap, 20 MB
      inline-image limit
- [x] `src/kiso_ocr_mcp/server.py` — FastMCP server with four tools:
      `ocr_image`, `describe_image`, `image_info`, `doctor`
- [x] 23 unit tests + 1 live test (fixture round-trip through
      OpenRouter), all green
- [x] README rewrite
- [ ] Cut `v0.1.0` tag on GitHub *(user action)*

**Design shifts from wrapper era**:

- **Single key**: only `OPENROUTER_API_KEY`. Dropped the
  `KISO_LLM_API_KEY` / `KISO_WRAPPER_OCR_MODEL` /
  `KISO_WRAPPER_OCR_BASE_URL` indirection. Model and URL are
  constants in the runner; future model overrides happen via
  a tool arg if needed.
- **Dropped the `list` action**: file discovery is the client's job.
- **Split `extract` vs `describe`**: two distinct tools
  (`ocr_image`, `describe_image`) instead of one tool with an
  `action` arg — cleaner MCP semantics.
- **Structured return**: all tools return JSON dicts with a
  consistent `success`/`stderr` shape.

The content below is the original wrapper-era devplan, kept for
historical record.

---

Image OCR tool for kiso. Extracts text from photos, screenshots, receipts, whiteboards, and scanned documents using Gemini multimodal vision via OpenRouter.

## Architecture

```
stdin (JSON) → run.py → resolve image → base64 → Gemini chat (vision) → stdout (text)
```

- **Entry point**: `run.py` reads JSON from stdin, dispatches to action handler
- **Actions**: `extract` (default), `describe`, `info`, `list`
- **API**: Gemini 2.0 Flash via OpenRouter `/chat/completions` (image as base64 inline content; model overridable via `KISO_TOOL_OCR_MODEL`)
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

---

### M9 — Mark file_path as required in schema ✅

**Problem:** `kiso.toml` declares `file_path` as `required = false`
but the tool code requires it for 3/4 actions (extract, describe,
info). The planner sees "optional" and omits it → tool fails at
runtime with "file_path argument is required".

The validation in brain.py checks the schema and passes because
the schema says optional. The error only surfaces at execution time.

**Approach:** Change `required = false` to `required = true` in
kiso.toml. The default action (extract) requires it. The `list`
action doesn't use it, but list is rarely called by the planner
and the tool code handles absent file_path for list internally.

**Files:** `kiso.toml`

**Tasks:**
- [x] Change `file_path` to `required = true` in kiso.toml

---

### M10 — Empty OCR from zero-width Unicode (core M960) ✅

**Problem:** Gemini sometimes returns only invisible Unicode characters
(U+200B zero-width space, U+FEFF BOM, U+200E LTR mark, etc.) as OCR
output.  Python's `str.strip()` considers them non-empty, so:
- `_call_gemini` retry check `content.strip()` passes → no retry
- `do_extract` empty check `not text.strip()` passes → tool returns
  `"OCR: file.png (WxH)\n\n{invisible}"` with no visible text
- Reviewer sees empty output → replan → circular loop → stuck

**Fix:** Replace both `strip()` checks with `_has_meaningful_content()`
that counts printable characters (letters, numbers, punctuation) using
`unicodedata.category`.

```python
import unicodedata

def _has_meaningful_content(text: str, min_chars: int = 3) -> bool:
    count = sum(1 for c in text if unicodedata.category(c)[0] in ('L', 'N', 'P'))
    return count >= min_chars
```

**Threshold = 3:** Catches zero-width (0 chars), single punctuation
(1 char), minimal noise (2 chars).  Rare false positive on 2-char
words ("OK", "42") causes 3-second retry delay — acceptable tradeoff
vs letting invisible text through.

**Safety:**
- CJK characters: category `Lo` → counted correctly
- Accented text: base letter `L*` → counted correctly
- Retry bounded: max 3 attempts, 3 seconds total backoff
- Graceful degradation: returns "No text detected in image."
- No behavioral change for valid OCR (3+ printable chars always pass)

**Files:** `run.py`

**Tasks:**
- [x] Add `_has_meaningful_content(text, min_chars=3)` helper
- [x] Replace `content.strip()` in `_call_gemini` retry (line ~232)
      with `_has_meaningful_content(content)`
- [x] Replace `not text.strip()` in `do_extract` (line ~135) with
      `not _has_meaningful_content(text)`
- [x] Unit test: zero-width chars (U+200B, U+FEFF) trigger retry
- [x] Unit test: "EXIT" (4 chars) passes without retry
- [x] Unit test: empty string returns "No text detected"

---

### M11 — Switch model to gemini-2.0-flash, add KISO_TOOL_OCR_MODEL env var ✅

**Problem:** `google/gemini-2.5-flash` has extended thinking (reasoning)
active by default. Even with `"reasoning": {"effort": "low"}` (M8), the
model uses ~20% of max_tokens for internal thinking, and sometimes routes
all output to the `reasoning` field instead of `content`, leaving `content`
empty. M8 was not a real fix — `effort: "low"` reduces thinking but does
not eliminate it, and OpenRouter has no valid `"none"` value to disable it
entirely. The result: OCR returns only the header line (no extracted text)
for a significant fraction of calls, causing F17/F30 functional tests to
fail.

**Root cause chain:**
1. gemini-2.5-flash thinks by default → tokens consumed for reasoning
2. `effort: "low"` (M8) reduces thinking budget but doesn't disable it
3. On some calls, model routes extracted text to `reasoning` field →
   `content` is empty → `_has_meaningful_content` fails → retry → same →
   "No text detected in image."

**Fix — two parts:**

1. **Switch model to `google/gemini-2.0-flash`**: this model does not have
   built-in extended thinking. It is the direct predecessor of 2.5-flash for
   multimodal/vision tasks, widely used for OCR, predictable `content` field
   output. Cost is identical (~$0.10/1M tokens via OpenRouter).

2. **Add `KISO_TOOL_OCR_MODEL` env var**: allows overriding the model at
   deploy time without a code change. Default: `google/gemini-2.0-flash`.
   Pattern mirrors the existing `KISO_TOOL_OCR_BASE_URL`.

   ```python
   model = os.environ.get("KISO_TOOL_OCR_MODEL", "google/gemini-2.0-flash")
   ```

**Remove the `"reasoning"` parameter** from the payload entirely — it is
meaningless for gemini-2.0-flash (no built-in thinking) and was only a
workaround for 2.5-flash's behavior.

**Keep the reasoning→content fallback** added during debugging (current
working copy). It is defensive code: harmless when content is populated,
fires only when content is empty but reasoning has text. Logs a WARNING so
the anomaly is visible.

**Files:** `run.py`, `tests/test_run.py`, `DEVPLAN.md` architecture section

**Tasks:**
- [x] Change default model from `google/gemini-2.5-flash` to
      `google/gemini-2.0-flash` in `_call_gemini`
- [x] Read model from `KISO_TOOL_OCR_MODEL` env var with fallback
- [x] Remove `"reasoning"` key from the Gemini payload
- [x] Keep reasoning→content fallback (already in working copy)
- [x] Update architecture section: model reference
- [x] Unit test: `KISO_TOOL_OCR_MODEL` env var overrides default model
- [x] Unit test: no `"reasoning"` key in payload when env var not set

---

### M12 — Fix model ID: `google/gemini-2.0-flash` → `google/gemini-2.0-flash-001` ✅

**Problem:** OpenRouter rejects `google/gemini-2.0-flash` with 400
"not a valid model ID". The 2.0 generation requires the `-001` suffix
on OpenRouter (unlike 2.5 which works without suffix).

All OCR functional tests (F17, F28, F30, F36) fail 100% with:
`Error: Gemini API error (400): google/gemini-2.0-flash is not a valid model ID`

**Fix:** Change the default model from `google/gemini-2.0-flash` to
`google/gemini-2.0-flash-001` in `_call_gemini()`.

**Files:** `run.py`

**Tasks:**
- [x] Change default model in `_call_gemini` from `google/gemini-2.0-flash`
      to `google/gemini-2.0-flash-001`
- [x] Update DEVPLAN.md architecture section (model reference — display name
      unchanged, only OpenRouter ID suffix added)
- [x] Run unit tests — 55 passed

---

## v0.2 — Pluggable backend (local-first)

**Motivation**. Current v0.1 routes every `ocr_image` / `describe_image` call through OpenRouter to Gemini. That works for stand-alone kiso usage, but two scenarios it doesn't serve:

1. *Privacy-strict consumers* — agent platforms operating under "your perimeter, your data" promises (e.g. EU B2B with GDPR data-residency obligations) cannot send every uploaded image out of the appliance. Invoices, scanned contracts, screenshots of internal documents routinely contain PII (fiscal codes, IBANs, names, addresses); Presidio works on text, not on images, so the egress to Gemini is a privacy hole the consumer can't close downstream.
2. *Cost-sensitive consumers* — at scale, per-call OCR cost adds up. A local backend is free per call.

The fix is a pluggable backend — Tesseract local default, Gemini opt-in for quality boost when the consumer accepts data egress. Backward-compatible: existing consumers can stay on Gemini by setting `KISO_OCR_BACKEND=gemini` (will become non-default; current behavior preserved with one env var).

### M1 — Tesseract backend ✅

- [x] System dependency: `tesseract-ocr` binary (installed via system package manager — README documents the apt/brew commands; container-image bundling lives downstream in the consumer's appliance Dockerfile, not here)
- [x] Implemented `_ocr_tesseract(image_path, langs)` runner — invokes `tesseract <input> stdout -l <langs>` via subprocess with 60s timeout
- [ ] *Deferred:* image preprocessing pipeline (deskew, grayscale via ImageMagick) — Tesseract handles standard formats natively and the common case of clean business documents doesn't need it; revisit if a quality gap is observed on real workloads
- [x] Unit tests cover: subprocess invocation with correct flags, nonzero exit raises, missing binary raises, default langs path, lang override via env, response includes `backend` field, output truncation, structured error for `describe_image` on tesseract backend
- [x] `describe_image` returns structured error `{success: false, stderr: "describe_image requires backend=gemini; current backend=tesseract..."}` when `KISO_OCR_BACKEND=tesseract`

### M2 — Pluggable backend selection: `tesseract` (default) | `gemini` ✅

- [x] New env var `KISO_OCR_BACKEND` with values `tesseract` (new default) and `gemini` (opt-in, preserves v0.1 behaviour)
- [x] Internal `_dispatch_image()` dispatcher resolves backend per-call; both `ocr_image` and `image_info` work on both backends
- [x] Migration note in README — existing consumers set `KISO_OCR_BACKEND=gemini` to preserve v0.1 behaviour
- [x] Unit tests for both backend paths with mocked subprocess (Tesseract) and mocked HTTP (Gemini)

### M3 — Tesseract language pack management ✅

- [x] README documents supported languages, default `ita+eng`, install commands
- [x] Env var `KISO_OCR_TESSERACT_LANGS` to override (e.g. `ita+eng+deu`)
- [x] `doctor()` reports installed Tesseract languages and warns when requested languages are missing

### M4 — Doctor + observability ✅

- [x] `doctor()` extended: reports active backend, validates relevant deps (Tesseract binary + language packs for `tesseract`, `OPENROUTER_API_KEY` for `gemini`); reports `tesseract_languages` list
- [ ] *Deferred:* live smoke OCR on a bundled fixture inside `doctor()` — the configuration check is sufficient at health-check time; smoke tests live in the test suite
- [x] Per-call return includes `backend` field so consumers can audit which backend served each call

### M5 — Quality trade-off documentation ✅

- [x] README "When to use which backend" section: Tesseract for clean printed text, Gemini for noisy/handwriting/description
- [x] Cost note implicit in README (Tesseract free per call CPU-bound; Gemini paid)
- [x] Privacy note in README (Tesseract local, no egress — rationale for being the new default)

### Cut criteria for v0.2.0 ✅

- [x] M1–M5 implemented and tested
- [x] All existing v0.1 tests still green when `KISO_OCR_BACKEND=gemini` (preserved via `_force_gemini_backend` autouse fixture in test classes)
- [x] README rewrite covers both backends and the migration note
- [x] `pyproject.toml` version bumped to `0.2.0`
- [ ] Cut `v0.2.0` tag on GitHub *— maintainer action: `git tag v0.2.0 && git push --tags`*

**Effort estimate**: ~4–5 days total. **Actual: completed in one TDD session with 37/37 tests green.**

---

## Out of scope for v0.2

- Other local OCR engines (PaddleOCR, EasyOCR, EasyOCR with GPU). Tesseract is the broadest-coverage, most stable, lowest-overhead option for business documents. Add others only if a consumer demonstrates a specific quality gap on their workload.
- Built-in PDF→image conversion. The docreader server already handles PDFs; if a PDF page needs OCR, the consumer pipelines docreader output to ocr-mcp (or pre-converts pages to PNG). Adding pdftoppm to ocr-mcp would duplicate concerns.
- LayoutLM / table extraction / form parsing. These are document-AI tasks, not OCR; out of scope for this server.
