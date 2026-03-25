"""
extractor.py  –  Extracts text and form-field data from downloaded PDFs.

Strategy (per the pdf-reading skill):
  1. Try pdfplumber for text-layer extraction (best for layout-heavy IRS forms).
  2. Use pypdf to read fillable form fields (IRS PDFs are often fillable forms).
  3. If text extraction returns very little text (< 200 chars), flag as
     potentially scanned so the analyzer can handle it differently.

Output per PDF:
  extracted/<category>/<stem>.json  containing:
    {
      "source_pdf"    : "pdfs/1040/f1040.pdf",
      "filename"      : "f1040.pdf",
      "page_count"    : 2,
      "form_fields"   : { "field_name": "field_type" },
      "text_by_page"  : { "1": "...", "2": "..." },
      "full_text"     : "...",
      "possibly_scanned": false,
      "char_count"    : 12345
    }
"""

import json
import logging
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from config import Config

log = logging.getLogger("extractor")

SCANNED_THRESHOLD = 200   # chars; below this we flag as possibly scanned


class PDFExtractor:

    def __init__(self, config: Config):
        self.config = config

    # ------------------------------------------------------------------
    #  Public interface
    # ------------------------------------------------------------------

    def run(self, limit: int | None = None, resume: bool = True):
        state     = self._load_state() if resume else {}
        processed: set[str] = set(state.get("processed", []))
        failed:    set[str] = set(state.get("failed", []))

        pdf_files = sorted(self.config.PDFS_DIR.rglob("*.pdf"))
        if limit:
            pdf_files = pdf_files[:limit]

        log.info(f"PDFs to process   : {len(pdf_files)}")
        log.info(f"Already processed : {len(processed)}")

        pending = [p for p in pdf_files if str(p) not in processed]
        log.info(f"Pending           : {len(pending)}")

        for i, pdf_path in enumerate(pending, 1):
            rel = str(pdf_path.relative_to(self.config.BASE_DIR))
            log.info(f"[{i}/{len(pending)}] Extracting: {rel}")
            try:
                result = self._extract(pdf_path)
                self._save_extraction(pdf_path, result)
                processed.add(str(pdf_path))
            except Exception as exc:
                log.warning(f"  Failed: {exc}")
                failed.add(str(pdf_path))

            if i % 50 == 0:
                self._save_state(processed, failed)

        self._save_state(processed, failed)
        log.info(f"Extraction complete. Processed: {len(processed)}, Failed: {len(failed)}")

    # ------------------------------------------------------------------
    #  Extraction
    # ------------------------------------------------------------------

    def _extract(self, pdf_path: Path) -> dict:
        text_by_page: dict[str, str] = {}
        form_fields:  dict[str, str] = {}
        page_count = 0

        # --- Text extraction via pdfplumber ---
        try:
            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    text_by_page[str(i)] = text.strip()
        except Exception as exc:
            log.warning(f"  pdfplumber error on {pdf_path.name}: {exc}")

        # --- Form fields via pypdf ---
        try:
            reader = PdfReader(str(pdf_path))
            if not page_count:
                page_count = len(reader.pages)
            all_fields = reader.get_fields() or {}
            for name, field in all_fields.items():
                field_type = field.get("/FT", "/Tx")
                # Map PDF field type codes to readable strings
                type_map = {"/Tx": "text", "/Btn": "checkbox", "/Ch": "choice", "/Sig": "signature"}
                form_fields[name] = type_map.get(str(field_type), str(field_type))
        except Exception as exc:
            log.warning(f"  pypdf error on {pdf_path.name}: {exc}")

        full_text   = "\n\n".join(text_by_page.values())
        char_count  = len(full_text)
        possibly_scanned = char_count < SCANNED_THRESHOLD and page_count > 0

        if possibly_scanned:
            log.warning(f"  Low text yield ({char_count} chars) — may be scanned: {pdf_path.name}")

        return {
            "source_pdf"      : str(pdf_path.relative_to(self.config.BASE_DIR)),
            "filename"        : pdf_path.name,
            "page_count"      : page_count,
            "form_fields"     : form_fields,
            "text_by_page"    : text_by_page,
            "full_text"       : full_text,
            "possibly_scanned": possibly_scanned,
            "char_count"      : char_count,
        }

    # ------------------------------------------------------------------
    #  Save output
    # ------------------------------------------------------------------

    def _save_extraction(self, pdf_path: Path, data: dict):
        # Mirror the pdfs/ subdirectory structure under extracted/
        rel_subdir = pdf_path.parent.relative_to(self.config.PDFS_DIR)
        out_dir    = self.config.EXTRACTED_DIR / rel_subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path   = out_dir / (pdf_path.stem + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info(
            f"  Saved: {out_path.name} ({data['char_count']} chars, {data['page_count']} pages)"
        )

    # ------------------------------------------------------------------
    #  State
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        path = self.config.EXTRACT_STATE_FILE
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self, processed: set[str], failed: set[str]):
        state = {"processed": sorted(processed), "failed": sorted(failed)}
        with open(self.config.EXTRACT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
