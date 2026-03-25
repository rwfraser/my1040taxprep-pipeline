"""
analyzer.py  –  LLM-powered analysis of extracted IRS documents.

Five analysis passes, each producing a distinct output artifact:

  Pass 1: master_schema     -> schemas/master_schema.json
  Pass 2: ground_truth      -> schemas/ground_truth.json
  Pass 3: mandatory_map     -> schemas/mandatory_map.json
  Pass 4: calc_table        -> schemas/calc_table.json
  Pass 5: db_schemas        -> db_schemas/<form_name>.json (one per form)

Each pass is resume-safe: already-analyzed documents are skipped.
Results are accumulated and merged across multiple runs.
"""

import json
import logging
import re
import time
from pathlib import Path

import anthropic
from anthropic.types import TextBlock

from config import Config

log = logging.getLogger("analyzer")


# ---------------------------------------------------------------------------
#  System prompts for each analysis pass
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS = {

"master_schema": """
You are an expert US tax analyst. You are analyzing extracted text from official IRS forms,
schedules, worksheets, instructions, and publications for tax year 2023.

Your task: Extract ALL data fields present in this document and return a JSON object.
Each key is a unique field identifier (e.g., "f1040_line_1a", "sch_a_line_5").
Each value is an object with:
  - "label"       : human-readable field label exactly as printed on the form
  - "form"        : form/schedule name (e.g., "Form 1040", "Schedule A")
  - "line"        : line number or field reference on the form
  - "type"        : one of: "dollar", "integer", "text", "checkbox",
                    "date", "ssn", "percentage", "choice"
  - "description" : brief plain-English description of what this field captures

Return ONLY valid JSON. No preamble. No markdown fences. No explanation.
""",

"ground_truth": """
You are an expert US tax analyst. You are analyzing extracted text from official IRS forms,
schedules, worksheets, instructions, and publications for tax year 2023.

Your task: For every data field in this document, identify its authoritative IRS source.
Return a JSON object where each key is a field identifier and each value contains:
  - "form"        : official form or publication name
  - "line"        : line number, field name, or section reference
  - "pub_ref"     : IRS publication reference if applicable (e.g., "Pub 17, Chapter 5")
  - "instruction_ref": reference to instructions (e.g., "Instructions for Form 1040, Line 1a")
  - "immutable"   : true (all IRS source references are treated as immutable ground truth)
  - "notes"       : any cross-references to other forms or worksheets

Return ONLY valid JSON. No preamble. No markdown fences. No explanation.
""",

"mandatory_map": """
You are an expert US tax analyst. You are analyzing extracted text from official IRS forms,
schedules, worksheets, instructions, and publications for tax year 2023.

Your task: Identify which fields on this form are mandatory vs optional, and under what conditions.
Return a JSON object with:
  - "form_name"   : the official form/schedule name
  - "always_required": list of field identifiers that must always be completed
  - "conditionally_required": list of objects each with:
      - "field"     : field identifier
      - "condition" : plain-English condition that triggers this requirement
  - "optional"    : list of field identifiers that are never required
  - "minimum_required_set": list of the absolute minimum fields needed to submit this form validly

Return ONLY valid JSON. No preamble. No markdown fences. No explanation.
""",

"calc_table": """
You are an expert US tax analyst. You are analyzing extracted text from official IRS forms,
schedules, worksheets, instructions, and publications for tax year 2023.

Your task: Identify ALL calculations defined in this document.
Return a JSON array of calculation objects, each containing:
  - "calc_id"     : unique identifier (e.g., "f1040_line_11_calc")
  - "form"        : form/schedule name
  - "line"        : output line number
  - "description" : what this calculation computes
  - "formula"     : the calculation expressed in plain English or pseudo-code
                    (e.g., "Line 7 + Line 8 + Line 9")
  - "inputs"      : list of input field identifiers used in the calculation
  - "output"      : output field identifier
  - "conditional" : true/false — whether the calculation applies conditionally
  - "condition"   : if conditional, describe when it applies
  - "references"  : list of worksheets or publications that detail this calculation

Return ONLY valid JSON. No preamble. No markdown fences. No explanation.
""",

"db_schemas": """
You are an expert US tax analyst and database architect.
You are analyzing extracted text from official IRS forms for tax year 2023.

Your task: Produce a normalized relational database schema for this specific form.
Return a JSON object with:
  - "form_name"   : official form name
  - "table_name"  : snake_case SQL table name (e.g., "form_1040", "schedule_a")
  - "primary_key" : primary key definition
  - "columns"     : list of column objects, each with:
      - "name"        : snake_case column name
      - "sql_type"    : SQL data type (e.g., DECIMAL(12,2), VARCHAR(9), BOOLEAN, DATE, INTEGER)
      - "nullable"    : true/false
      - "description" : what this column stores
      - "source_line" : line number on the form
  - "foreign_keys": list of foreign key relationships to other form tables
  - "indexes"     : recommended indexes for query performance
  - "constraints" : any check constraints or business rules to enforce

Return ONLY valid JSON. No preamble. No markdown fences. No explanation.
""",
}

# ---------------------------------------------------------------------------
#  Output file mapping
# ---------------------------------------------------------------------------

def output_path_for_pass(config: Config, pass_name: str, form_name: str | None = None) -> Path:
    if pass_name == "db_schemas" and form_name:
        safe = re.sub(r"[^\w]", "_", form_name.lower())
        return config.DB_SCHEMAS_DIR / f"{safe}.json"
    return config.SCHEMAS_DIR / f"{pass_name}.json"


# ---------------------------------------------------------------------------
#  Main analyzer class
# ---------------------------------------------------------------------------

class DocumentAnalyzer:

    def __init__(self, config: Config):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # ------------------------------------------------------------------
    #  Public interface
    # ------------------------------------------------------------------

    def run_pass(self, pass_name: str, limit: int | None = None, resume: bool = True):
        state     = self._load_state() if resume else {}
        done_pass = set(state.get(pass_name, {}).get("processed", []))

        extraction_files = sorted(self.config.EXTRACTED_DIR.rglob("*.json"))
        if limit:
            extraction_files = extraction_files[:limit]

        pending = [f for f in extraction_files if str(f) not in done_pass]
        log.info(f"Pass [{pass_name}]: {len(pending)} files to analyze")

        # Load existing accumulated results
        accumulated = self._load_accumulated(pass_name)

        for i, ext_file in enumerate(pending, 1):
            log.info(f"  [{i}/{len(pending)}] {ext_file.name}")
            try:
                extraction = self._load_extraction(ext_file)
                if not extraction.get("full_text", "").strip():
                    log.warning("    No text content, skipping.")
                    done_pass.add(str(ext_file))
                    continue

                result = self._call_llm(pass_name, extraction)

                if result is not None:
                    form_name = self._infer_form_name(extraction)
                    accumulated = self._merge_result(
                        pass_name, accumulated, result, form_name, config=self.config
                    )
                    done_pass.add(str(ext_file))
                    log.info("    OK")
                else:
                    log.warning("    LLM returned no usable result.")

            except Exception as exc:
                log.warning(f"    Error: {exc}")

            # Save progress every 10 documents
            if i % 10 == 0:
                self._persist_accumulated(pass_name, accumulated)
                state.setdefault(pass_name, {})["processed"] = sorted(done_pass)
                self._save_state(state)
                log.info("    Checkpoint saved.")

            time.sleep(self.config.ANALYZE_DELAY_SECS)

        # Final save
        self._persist_accumulated(pass_name, accumulated)
        state.setdefault(pass_name, {})["processed"] = sorted(done_pass)
        self._save_state(state)
        log.info(f"Pass [{pass_name}] complete.")

    # ------------------------------------------------------------------
    #  LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, pass_name: str, extraction: dict) -> dict | list | None:
        system_prompt = SYSTEM_PROMPTS[pass_name]

        # Truncate text to stay within token budget
        text = extraction.get("full_text", "")
        if len(text) > self.config.MAX_CHARS_PER_CHUNK:
            text = text[: self.config.MAX_CHARS_PER_CHUNK] + "\n\n[TEXT TRUNCATED]"

        # Build a compact context block
        context = (
            f"DOCUMENT: {extraction.get('filename', 'unknown')}\n"
            f"PAGES: {extraction.get('page_count', '?')}\n"
            f"FORM FIELDS DETECTED: {len(extraction.get('form_fields', {}))}\n"
            f"FIELD NAMES: {', '.join(list(extraction.get('form_fields', {}).keys())[:50])}\n\n"
            f"EXTRACTED TEXT:\n{text}"
        )

        try:
            response = self.client.messages.create(
                model=self.config.CLAUDE_MODEL,
                max_tokens=self.config.MAX_TOKENS_PER_CALL,
                system=system_prompt.strip(),
                messages=[{"role": "user", "content": context}],
            )
            # response.content[0] may be TextBlock, ThinkingBlock, ToolUseBlock, etc.
            # Only TextBlock has a .text attribute; other block types are not expected
            # here since we make a standard completion request without tools or extended thinking.
            first = response.content[0] if response.content else None
            raw = first.text if isinstance(first, TextBlock) else ""
            return self._parse_json_response(raw)
        except Exception as exc:
            log.warning(f"    API error: {exc}")
            return None

    # ------------------------------------------------------------------
    #  Merge / accumulate results
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_result(pass_name: str, accumulated, new_result, form_name: str, config: Config):
        """Merge a new LLM result into the running accumulated output for this pass.

        Each pass uses a different container type and merge strategy:

          master_schema  → dict[field_id -> field_def]      — dict.update() (last write wins)
          ground_truth   → dict[field_id -> source_ref]     — dict.update() (last write wins)
          mandatory_map  → dict[form_name -> map_obj]       — keyed replacement per form
          calc_table     → list[calc_obj]                   — append, deduplicated by calc_id
          db_schemas     → dict[form_name -> schema_obj]    — keyed replacement per form
                           + immediate write of a per-form JSON file to DB_SCHEMAS_DIR

        Args:
            pass_name:   One of the five analysis pass identifiers.
            accumulated: Existing accumulated container (mutated in place and returned).
            new_result:  Parsed JSON returned by the LLM for a single document.
            form_name:   Human-readable form name inferred from the source filename;
                         used as a fallback key when the LLM omits a "form_name" field.
            config:      Config instance; only consumed by the db_schemas branch to
                         resolve the per-form output file path via DB_SCHEMAS_DIR.
        """

        if pass_name == "master_schema":
            # accumulated is a dict of field_id -> field_def
            if isinstance(new_result, dict):
                accumulated.update(new_result)

        elif pass_name == "ground_truth":
            # accumulated is a dict of field_id -> source_ref
            if isinstance(new_result, dict):
                accumulated.update(new_result)

        elif pass_name == "mandatory_map":
            # accumulated is a dict of form_name -> mandatory_map
            if isinstance(new_result, dict):
                key = new_result.get("form_name", form_name)
                accumulated[key] = new_result

        elif pass_name == "calc_table":
            # accumulated is a list of calculation objects
            if isinstance(new_result, list):
                existing_ids = {c.get("calc_id") for c in accumulated}
                for calc in new_result:
                    if calc.get("calc_id") not in existing_ids:
                        accumulated.append(calc)

        elif pass_name == "db_schemas":
            # accumulated is a dict of form_name -> db_schema
            # Also write individual per-form file
            if isinstance(new_result, dict):
                key = new_result.get("form_name", form_name)
                accumulated[key] = new_result
                # Write per-form file immediately
                out = output_path_for_pass(config, "db_schemas", key)
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(new_result, f, indent=2)

        return accumulated

    def _persist_accumulated(self, pass_name: str, accumulated):
        out_path = output_path_for_pass(self.config, pass_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(accumulated, f, indent=2, ensure_ascii=False)
        log.info(f"    Saved accumulated results: {out_path}")

    def _load_accumulated(self, pass_name: str):
        out_path = output_path_for_pass(self.config, pass_name)
        if out_path.exists():
            try:
                with open(out_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Return appropriate empty container per pass
        if pass_name == "calc_table":
            return []
        return {}

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_response(raw: str) -> dict | list | None:
        """Strip markdown fences and parse JSON."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.warning(f"JSON parse error: {exc}\nRaw (first 200): {raw[:200]}")
            return None

    @staticmethod
    def _infer_form_name(extraction: dict) -> str:
        filename = extraction.get("filename", "unknown")
        stem = Path(filename).stem.lower()
        # Attempt to derive a human-readable form name from filename
        stem = re.sub(r"[-_]", " ", stem)
        return stem.title()

    @staticmethod
    def _load_extraction(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    #  State
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        path = self.config.ANALYZE_STATE_FILE
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self, state: dict):
        with open(self.config.ANALYZE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
