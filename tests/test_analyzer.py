"""
tests/test_analyzer.py  –  Unit tests for DocumentAnalyzer._parse_json_response
and DocumentAnalyzer._merge_result.

No Anthropic API calls are made; both methods under test are @staticmethods
that operate purely on in-memory data.
"""

import json
from pathlib import Path

from analyzer import DocumentAnalyzer
from config import Config

# ---------------------------------------------------------------------------
#  Helper: a minimal Config that writes to a tmp directory
# ---------------------------------------------------------------------------

def _tmp_config(tmp_path: Path) -> Config:
    """Return a Config whose DB_SCHEMAS_DIR and SCHEMAS_DIR point to tmp_path."""
    class _TmpConfig(Config):
        @property
        def DB_SCHEMAS_DIR(self) -> Path:
            return tmp_path / "db_schemas"

        @property
        def SCHEMAS_DIR(self) -> Path:
            return tmp_path / "schemas"

    cfg = _TmpConfig()
    cfg.ensure_dirs()
    return cfg


# ---------------------------------------------------------------------------
#  _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:

    def test_bare_object(self):
        result = DocumentAnalyzer._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_bare_array(self):
        result = DocumentAnalyzer._parse_json_response('[{"id": 1}, {"id": 2}]')
        assert result == [{"id": 1}, {"id": 2}]

    def test_fenced_json_block(self):
        raw = "```json\n{\"key\": \"value\"}\n```"
        assert DocumentAnalyzer._parse_json_response(raw) == {"key": "value"}

    def test_fenced_block_no_language_tag(self):
        raw = "```\n{\"key\": \"value\"}\n```"
        assert DocumentAnalyzer._parse_json_response(raw) == {"key": "value"}

    def test_leading_and_trailing_whitespace(self):
        raw = "  \n  {\"key\": \"value\"}  \n  "
        assert DocumentAnalyzer._parse_json_response(raw) == {"key": "value"}

    def test_malformed_json_returns_none(self):
        assert DocumentAnalyzer._parse_json_response("not json at all") is None

    def test_truncated_json_returns_none(self):
        assert DocumentAnalyzer._parse_json_response('{"key": "val') is None

    def test_empty_string_returns_none(self):
        assert DocumentAnalyzer._parse_json_response("") is None


# ---------------------------------------------------------------------------
#  _merge_result – master_schema
# ---------------------------------------------------------------------------

class TestMergeResultMasterSchema:

    def test_adds_new_fields(self, tmp_path):
        config = _tmp_config(tmp_path)
        new = {"f1040_line_1a": {"label": "Wages", "type": "dollar"}}
        result = DocumentAnalyzer._merge_result("master_schema", {}, new, "Form 1040", config)
        assert "f1040_line_1a" in result
        assert result["f1040_line_1a"]["label"] == "Wages"

    def test_accumulates_across_calls(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = {"f1040_line_1a": {"label": "Wages"}}
        new = {"sch_a_line_5": {"label": "State taxes"}}
        result = DocumentAnalyzer._merge_result("master_schema", acc, new, "Schedule A", config)
        assert "f1040_line_1a" in result
        assert "sch_a_line_5" in result

    def test_ignores_non_dict_result(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = {"existing": {}}
        result = DocumentAnalyzer._merge_result("master_schema", acc, ["bad"], "Form 1040", config)
        assert result == {"existing": {}}


# ---------------------------------------------------------------------------
#  _merge_result – ground_truth (same merge strategy as master_schema)
# ---------------------------------------------------------------------------

class TestMergeResultGroundTruth:

    def test_accumulates_source_refs(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = {}
        new = {"f1040_line_1a": {"form": "Form 1040", "line": "1a", "immutable": True}}
        result = DocumentAnalyzer._merge_result("ground_truth", acc, new, "Form 1040", config)
        assert result["f1040_line_1a"]["immutable"] is True


# ---------------------------------------------------------------------------
#  _merge_result – mandatory_map
# ---------------------------------------------------------------------------

class TestMergeResultMandatoryMap:

    def test_keyed_by_form_name(self, tmp_path):
        config = _tmp_config(tmp_path)
        new = {
            "form_name": "Form 1040",
            "always_required": ["ssn", "filing_status"],
            "optional": [],
        }
        result = DocumentAnalyzer._merge_result("mandatory_map", {}, new, "Form 1040", config)
        assert "Form 1040" in result
        assert result["Form 1040"]["always_required"] == ["ssn", "filing_status"]

    def test_falls_back_to_form_name_argument(self, tmp_path):
        config = _tmp_config(tmp_path)
        # If LLM omits "form_name" key, falls back to the form_name argument
        new = {"always_required": ["ssn"]}
        result = DocumentAnalyzer._merge_result("mandatory_map", {}, new, "Fallback Name", config)
        assert "Fallback Name" in result


# ---------------------------------------------------------------------------
#  _merge_result – calc_table
# ---------------------------------------------------------------------------

class TestMergeResultCalcTable:

    def test_appends_new_calculations(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = []
        new = [{"calc_id": "f1040_line_11_calc", "description": "AGI"}]
        result = DocumentAnalyzer._merge_result("calc_table", acc, new, "Form 1040", config)
        assert len(result) == 1
        assert result[0]["calc_id"] == "f1040_line_11_calc"

    def test_deduplicates_by_calc_id(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = [{"calc_id": "calc_1", "description": "original"}]
        new = [
            {"calc_id": "calc_1", "description": "duplicate — should be ignored"},
            {"calc_id": "calc_2", "description": "new entry"},
        ]
        result = DocumentAnalyzer._merge_result("calc_table", acc, new, "Form 1040", config)
        assert len(result) == 2
        # Original entry must be preserved, not overwritten
        assert result[0]["description"] == "original"
        assert result[1]["calc_id"] == "calc_2"

    def test_ignores_non_list_result(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = [{"calc_id": "calc_1"}]
        result = DocumentAnalyzer._merge_result(
            "calc_table", acc, {"bad": "type"}, "Form 1040", config
        )
        assert result == [{"calc_id": "calc_1"}]


# ---------------------------------------------------------------------------
#  _merge_result – db_schemas
# ---------------------------------------------------------------------------

class TestMergeResultDbSchemas:

    def test_accumulates_by_form_name(self, tmp_path):
        config = _tmp_config(tmp_path)
        new = {"form_name": "Form 1040", "table_name": "form_1040", "columns": []}
        result = DocumentAnalyzer._merge_result("db_schemas", {}, new, "Form 1040", config)
        assert "Form 1040" in result

    def test_writes_per_form_json_file(self, tmp_path):
        config = _tmp_config(tmp_path)
        new = {"form_name": "Form 1040", "table_name": "form_1040", "columns": []}
        DocumentAnalyzer._merge_result("db_schemas", {}, new, "Form 1040", config)
        out_file = config.DB_SCHEMAS_DIR / "form_1040.json"
        assert out_file.exists()
        with open(out_file) as f:
            saved = json.load(f)
        assert saved["table_name"] == "form_1040"

    def test_ignores_non_dict_result(self, tmp_path):
        config = _tmp_config(tmp_path)
        acc = {}
        result = DocumentAnalyzer._merge_result("db_schemas", acc, ["bad"], "Form 1040", config)
        assert result == {}
