"""
Configuration for IRS 2023 Tax Document Crawler
Edit ANTHROPIC_API_KEY before running the analyze phase.
"""

import os
from pathlib import Path


class Config:
    # ------------------------------------------------------------------ #
    #  ROOT PATH  –  Windows path written to by all scripts               #
    # ------------------------------------------------------------------ #
    BASE_DIR = Path(r"C:\Users\RogerIdaho\Projects\my1040taxprep")

    # ------------------------------------------------------------------ #
    #  ANTHROPIC API KEY                                                   #
    #  Set via environment variable — do NOT hardcode the key here.       #
    #  In PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."               #
    #  In the activated venv cmd shell: set ANTHROPIC_API_KEY=sk-ant-...  #
    # ------------------------------------------------------------------ #
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

    # ------------------------------------------------------------------ #
    #  DIRECTORY STRUCTURE                                                 #
    # ------------------------------------------------------------------ #
    @property
    def CRAWLER_DIR(self)   -> Path: return self.BASE_DIR / "crawler"
    @property
    def PDFS_DIR(self)      -> Path: return self.BASE_DIR / "pdfs"
    @property
    def EXTRACTED_DIR(self) -> Path: return self.BASE_DIR / "extracted"
    @property
    def SCHEMAS_DIR(self)   -> Path: return self.BASE_DIR / "schemas"
    @property
    def DB_SCHEMAS_DIR(self)-> Path: return self.BASE_DIR / "db_schemas"
    @property
    def STATE_DIR(self)     -> Path: return self.BASE_DIR / "state"
    @property
    def LOGS_DIR(self)      -> Path: return self.BASE_DIR / "logs"

    # ------------------------------------------------------------------ #
    #  STATE FILES                                                         #
    # ------------------------------------------------------------------ #
    @property
    def CRAWL_STATE_FILE(self)    -> Path: return self.STATE_DIR / "crawl_state.json"
    @property
    def DOWNLOAD_STATE_FILE(self) -> Path: return self.STATE_DIR / "download_state.json"
    @property
    def EXTRACT_STATE_FILE(self)  -> Path: return self.STATE_DIR / "extract_state.json"
    @property
    def ANALYZE_STATE_FILE(self)  -> Path: return self.STATE_DIR / "analyze_state.json"
    @property
    def URL_MANIFEST_FILE(self)   -> Path: return self.STATE_DIR / "url_manifest.json"

    # ------------------------------------------------------------------ #
    #  CRAWLER SETTINGS                                                    #
    # ------------------------------------------------------------------ #
    TARGET_YEAR          = "2023"
    START_URLS = [
        # Prior-year landing pages — the authoritative source for 2023 forms
        "https://www.irs.gov/prior-year-forms-and-instructions",
        "https://www.irs.gov/pub/irs-prior/",
        # 1040-specific prior-year pages
        "https://www.irs.gov/forms-pubs/about-form-1040",
        # NOTE: /pub/irs-pdf/ is intentionally excluded — it serves current-year
        # forms only (no year suffix) and would pull the wrong tax year.
    ]

    # Stay within these URL path prefixes
    ALLOWED_PATHS = [
        "/pub/irs-pdf/",
        "/pub/irs-prior/",
        "/forms-instructions",
        "/forms-pubs",
        "/publications",
        "/instructions",
        "/prior-year-forms-and-instructions",
    ]

    # Skip links containing these tokens (reduces noise)
    BLOCKED_URL_TOKENS = [
        "/newsroom/", "/about-irs/", "/businesses/", "/charities/",
        "/government-entities/", "/tax-professionals/", "/e-file-providers/",
        "/affordable-care-act/", "/coronavirus/", "/taxpayer-advocate/",
        "/filing/", "/refunds/", "/credits-deductions/", "/payments/",
        "javascript:", "mailto:", "#",
    ]

    # PDF filename patterns that suggest 2023 relevance
    YEAR_TOKENS_IN_FILENAME = ["2023", "ty23", "23"]

    # Known 1040-relevant form prefixes (expand as needed)
    FORM_PREFIXES = [
        "f1040", "f1040sr", "f1040nr", "f1040x", "f1040es",
        "f1040sch", "f1040sa", "f1040sb", "f1040sc", "f1040sd",
        "f1040se", "f1040sf", "f1040sh", "f1040sj",
        "f1040s1", "f1040s2", "f1040s3",
        "fw2", "fw2g", "f1099", "f4868", "f8949", "f8829",
        "f8863", "f8962", "f8812", "f8606", "f5329", "f5498",
        "f2441", "f2106", "f3903", "f4137", "f4562", "f4684",
        "f4797", "f6251", "f8283", "f8332", "f8453", "f8582",
        "f8615", "f8814", "f8824", "f8839", "f8853", "f8880",
        "f8885", "f8888", "f8889", "f8995", "f8990",
        "i1040",   # instructions
        "p17", "p501", "p502", "p503", "p504", "p505", "p519",
        "p525", "p526", "p527", "p530", "p535", "p550", "p551",
        "p554", "p590", "p596", "p915", "p946", "p970", "p972",
    ]

    MAX_CRAWL_DEPTH      = 4
    CRAWL_DELAY_SECS     = 1.5       # polite delay between requests
    CRAWL_JITTER_SECS    = 0.5       # random jitter added to delay
    REQUEST_TIMEOUT_SECS = 30
    MAX_RETRIES          = 3

    # ------------------------------------------------------------------ #
    #  DOWNLOADER SETTINGS                                                 #
    # ------------------------------------------------------------------ #
    DOWNLOAD_DELAY_SECS  = 2.0
    DOWNLOAD_JITTER_SECS = 1.0
    MAX_PDF_SIZE_MB      = 50        # skip suspiciously large files

    # ------------------------------------------------------------------ #
    #  EXTRACTOR SETTINGS                                                  #
    # ------------------------------------------------------------------ #
    # Max characters of extracted text sent per PDF chunk to the LLM
    MAX_CHARS_PER_CHUNK  = 80_000

    # ------------------------------------------------------------------ #
    #  ANALYZER SETTINGS                                                   #
    # ------------------------------------------------------------------ #
    CLAUDE_MODEL         = "claude-sonnet-4-6"
    ANALYZE_DELAY_SECS   = 2.0       # delay between API calls
    MAX_TOKENS_PER_CALL  = 4096

    # ------------------------------------------------------------------ #
    #  HELPERS                                                             #
    # ------------------------------------------------------------------ #
    def ensure_dirs(self):
        for d in [
            self.CRAWLER_DIR, self.PDFS_DIR, self.EXTRACTED_DIR,
            self.SCHEMAS_DIR, self.DB_SCHEMAS_DIR, self.STATE_DIR, self.LOGS_DIR,
        ]:
            d.mkdir(parents=True, exist_ok=True)
