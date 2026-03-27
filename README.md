# IRS 2023 Tax Document Crawler & Analyzer

Crawls IRS.gov, downloads all 2023 Form 1040-relevant PDFs, extracts their
content, and uses Claude to build five structured output artifacts.

---

## Requirements

- Python 3.11+
- An Anthropic API key (for the analyze phase)
- Internet access to reach www.irs.gov
- venv virtual environment

---

## Setup

### 1. Install Python dependencies

Open a terminal (PowerShell or Command Prompt) and run:

```
cd C:\Users\RogerIdaho\Projects\my1040taxprep
pip install -r requirements.txt
```

### 2. Add your Anthropic API key

Open `config.py` and replace the placeholder on this line:

```python
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
```

Either paste your key directly, or set it as an environment variable:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Your API key is available at: https://console.anthropic.com/settings/keys

---

## Running the pipeline

### Run all phases in sequence

```
python main.py --phase all
```

### Run individual phases

```
python main.py --phase crawl      # Phase 1: discover PDFs on IRS.gov
python main.py --phase download   # Phase 2: download discovered PDFs
python main.py --phase extract    # Phase 3: extract text from PDFs
python main.py --phase analyze    # Phase 4: LLM analysis (all 5 passes)
```

### Run a specific analysis pass

```
python main.py --phase analyze --analyze-pass master_schema
python main.py --phase analyze --analyze-pass ground_truth
python main.py --phase analyze --analyze-pass mandatory_map
python main.py --phase analyze --analyze-pass calc_table
python main.py --phase analyze --analyze-pass db_schemas
```

### Test with a small batch

```
python main.py --phase all --limit 10
```

### All runs resume automatically from where they left off.

---

## Output files

| File | Description |
|---|---|
| `schemas/master_schema.json` | All possible data fields across all forms |
| `schemas/ground_truth.json` | Authoritative IRS source for every field |
| `schemas/mandatory_map.json` | Required vs optional fields, form by form |
| `schemas/calc_table.json` | All calculations and formulas |
| `db_schemas/<form>.json` | Normalized database schema per form |

---

## Directory structure

```
C:\Users\RogerIdaho\Projects\my1040taxprep\
├── main.py                   Orchestrator
├── config.py                 Settings (edit your API key here)
├── crawler.py                IRS.gov BFS crawler
├── downloader.py             Rate-limited PDF downloader
├── extractor.py              PDF text & form-field extractor
├── analyzer.py               Claude API analysis engine
├── requirements.txt          Python dependencies
│
├── pdfs\                     Downloaded PDFs
│   ├── 1040\
│   ├── schedules\
│   ├── instructions\
│   ├── publications\
│   └── supporting_forms\
│
├── extracted\                Extracted text (JSON per PDF)
├── schemas\                  Analysis output (master schema, etc.)
├── db_schemas\               Per-form database schemas
├── state\                    Resume state files
└── logs\                     Log files
```

---

## Notes

- The crawler respects robots.txt and uses polite rate limiting (1.5–2s between requests).
- All phases are resume-safe. If interrupted, re-run the same command and it will pick up where it left off.
- The analyze phase makes many API calls. Monitor your usage at https://console.anthropic.com/usage
- To reduce API costs during testing, use `--limit 5` to process only a few PDFs per pass.
- Analysis passes can be re-run as many times as needed. Results are merged/accumulated, not overwritten.

---

## Troubleshooting

**"No PDFs in manifest"** — Run `--phase crawl` first.

**"ANTHROPIC_API_KEY not set"** — Add your key to `config.py` or set the environment variable.

**"pdfplumber error"** — Some IRS PDFs are scanned images with no text layer. These are flagged in
the extraction output as `possibly_scanned: true`. The analyzer skips them gracefully.

**Rate limit errors from Anthropic API** — Increase `ANALYZE_DELAY_SECS` in `config.py`.
