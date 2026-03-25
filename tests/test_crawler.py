"""
tests/test_crawler.py  –  Unit tests for IRSCrawler._is_relevant_pdf.

All tests are offline: network calls (_load_robots, _build_session) are
patched so no HTTP traffic is made during the test run.
"""

from unittest.mock import MagicMock, patch

import pytest

from config import Config
from crawler import IRSCrawler

# ---------------------------------------------------------------------------
#  Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def crawler():
    """Return an IRSCrawler with network calls suppressed."""
    config = Config()
    with patch.object(IRSCrawler, "_load_robots", return_value=MagicMock()):
        return IRSCrawler(config)


# ---------------------------------------------------------------------------
#  _is_relevant_pdf – form-prefix matches (branch 1)
# ---------------------------------------------------------------------------

class TestIsRelevantPdfByPrefix:

    def test_core_1040_form(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/f1040.pdf") is True

    def test_1040_senior(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/f1040sr.pdf") is True

    def test_1040_nr(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/f1040nr.pdf") is True

    def test_schedule_a(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/f1040sa.pdf") is True

    def test_schedule_1(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/f1040s1.pdf") is True

    def test_w2(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/fw2.pdf") is True

    def test_instructions_1040(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/i1040.pdf") is True

    def test_publication_17(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/p17.pdf") is True

    def test_form_8949(self, crawler):
        assert crawler._is_relevant_pdf("https://www.irs.gov/pub/irs-pdf/f8949.pdf") is True


# ---------------------------------------------------------------------------
#  _is_relevant_pdf – prior-year directory year-token match (branch 2)
# ---------------------------------------------------------------------------

class TestIsRelevantPdfPriorYear:

    def test_prior_year_with_2023_token(self, crawler):
        url = "https://www.irs.gov/pub/irs-prior/f1040--2023.pdf"
        assert crawler._is_relevant_pdf(url) is True

    def test_prior_year_with_ty23_token(self, crawler):
        url = "https://www.irs.gov/pub/irs-prior/f1040ty23.pdf"
        assert crawler._is_relevant_pdf(url) is True

    def test_prior_year_wrong_year_rejected(self, crawler):
        # A prior-year file from 2021 should not match year tokens
        url = "https://www.irs.gov/pub/irs-prior/fw9--2021.pdf"
        assert crawler._is_relevant_pdf(url) is False

    # ------------------------------------------------------------------
    # Regression tests for the case-ordering bug:
    # Prior-year forms with known prefixes but wrong year must be REJECTED.
    # These tests would FAIL against the original code where the prefix
    # check (Case 1) ran before the prior-year gate (Case 2).
    # ------------------------------------------------------------------

    def test_prior_year_f1040_wrong_year_rejected(self, crawler):
        # f1040--2022.pdf has prefix 'f1040' but is NOT a 2023 form.
        url = "https://www.irs.gov/pub/irs-prior/f1040--2022.pdf"
        assert crawler._is_relevant_pdf(url) is False

    def test_prior_year_f1040_2021_rejected(self, crawler):
        url = "https://www.irs.gov/pub/irs-prior/f1040--2021.pdf"
        assert crawler._is_relevant_pdf(url) is False

    def test_prior_year_fw2_wrong_year_rejected(self, crawler):
        # fw2 is in FORM_PREFIXES but the archive copy from 2020 is not wanted
        url = "https://www.irs.gov/pub/irs-prior/fw2--2020.pdf"
        assert crawler._is_relevant_pdf(url) is False

    def test_prior_year_schedule_a_wrong_year_rejected(self, crawler):
        url = "https://www.irs.gov/pub/irs-prior/f1040sa--2019.pdf"
        assert crawler._is_relevant_pdf(url) is False

    def test_prior_year_correct_year_accepted(self, crawler):
        # Sanity check: 2023 form in prior-year archive must still be accepted
        url = "https://www.irs.gov/pub/irs-prior/fw2--2023.pdf"
        assert crawler._is_relevant_pdf(url) is True


# ---------------------------------------------------------------------------
#  _is_relevant_pdf – general year-token fallback (branch 3)
# ---------------------------------------------------------------------------

class TestIsRelevantPdfYearTokenFallback:

    def test_filename_contains_2023(self, crawler):
        url = "https://www.irs.gov/pub/irs-pdf/someform2023.pdf"
        assert crawler._is_relevant_pdf(url) is True


# ---------------------------------------------------------------------------
#  _is_relevant_pdf – rejected files
# ---------------------------------------------------------------------------

class TestIsRelevantPdfRejected:

    def test_unknown_form_no_year(self, crawler):
        # fw9 is not in FORM_PREFIXES and has no year token
        url = "https://www.irs.gov/pub/irs-pdf/fw9.pdf"
        assert crawler._is_relevant_pdf(url) is False

    def test_completely_unrelated_pdf(self, crawler):
        url = "https://www.irs.gov/pub/irs-pdf/unrelated_document.pdf"
        assert crawler._is_relevant_pdf(url) is False
