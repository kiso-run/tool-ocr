# tool-ocr

Extract text from images — photos, screenshots, receipts, whiteboards, handwriting, scanned documents.

## How it works

Uses Gemini 2.5 Flash's vision capability via OpenRouter. Images are sent as base64 inline content in a standard chat completion request. Same API key as all other kiso LLM calls — zero extra configuration.

## Actions

| Action | Description | Required args |
|--------|-------------|---------------|
| `extract` | Extract text from image (default) | `file_path` |
| `describe` | Describe image content | `file_path` |
| `info` | Image metadata (format, dimensions, size) | `file_path` |
| `list` | List image files in uploads/ | none |

## Supported formats

PNG, JPG/JPEG, WEBP, GIF, BMP, TIFF

## Cost

~260 tokens per image at Gemini 2.5 Flash pricing ($0.15/1M tokens) = **$0.00004 per image**.

1000 images/day = $0.04/day.

## Use cases

- **Voice + photo**: user sends a photo of a whiteboard via Discord → OCR extracts the text
- **Receipts**: photo of a receipt → extracted line items
- **Screenshots**: screenshot of an error → extracted error message
- **Scanned PDFs**: docreader detects no extractable text → suggests converting pages to images → OCR each page

## API key

Uses `KISO_LLM_API_KEY` — the same key kiso uses for all LLM calls. No extra configuration.

## Install

```bash
kiso tool install ocr
```

## License

MIT
