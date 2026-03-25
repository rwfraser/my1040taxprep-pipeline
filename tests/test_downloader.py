"""
tests/test_downloader.py  –  Unit tests for PDFDownloader._categorise
and PDFDownloader._destination_path.

No network calls are made; PDFDownloader.__init__ only builds a
requests.Session (no I/O).
"""

import pytest

from config import Config
from downloader import PDFDownloader

# ---------------------------------------------------------------------------
#  Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def downloader():
    return PDFDownloader(Config())


# ---------------------------------------------------------------------------
#  _categorise
# ---------------------------------------------------------------------------

class TestCategorise:

    # --- Core 1040 forms ---

    def test_f1040_base(self):
        assert PDFDownloader._categorise("f1040.pdf") == "1040"

    def test_f1040_senior_is_not_a_schedule(self):
        # f1040sr starts with 'f1040s' but is Form 1040-SR, not a schedule
        assert PDFDownloader._categorise("f1040sr.pdf") == "1040"

    def test_f1040_nr(self):
        assert PDFDownloader._categorise("f1040nr.pdf") == "1040"

    def test_f1040_x(self):
        assert PDFDownloader._categorise("f1040x.pdf") == "1040"

    def test_f1040_es(self):
        # f1040es starts with f1040 but NOT f1040s, so → 1040
        assert PDFDownloader._categorise("f1040es.pdf") == "1040"

    # --- Schedules ---

    def test_schedule_letter_a(self):
        assert PDFDownloader._categorise("f1040sa.pdf") == "schedules"

    def test_schedule_letter_c(self):
        assert PDFDownloader._categorise("f1040sc.pdf") == "schedules"

    def test_schedule_number_1(self):
        assert PDFDownloader._categorise("f1040s1.pdf") == "schedules"

    def test_schedule_number_3(self):
        assert PDFDownloader._categorise("f1040s3.pdf") == "schedules"

    def test_schedule_cover_sheet(self):
        assert PDFDownloader._categorise("f1040sch.pdf") == "schedules"

    # --- Instructions ---

    def test_instructions_1040(self):
        assert PDFDownloader._categorise("i1040.pdf") == "instructions"

    def test_instructions_other_form(self):
        # IRS instruction files for other forms also start with 'i'
        assert PDFDownloader._categorise("iw2.pdf") == "instructions"

    # --- Publications ---

    def test_publication_17(self):
        assert PDFDownloader._categorise("p17.pdf") == "publications"

    def test_publication_501(self):
        assert PDFDownloader._categorise("p501.pdf") == "publications"

    # --- Supporting forms ---

    def test_w2(self):
        assert PDFDownloader._categorise("fw2.pdf") == "supporting_forms"

    def test_form_8949(self):
        assert PDFDownloader._categorise("f8949.pdf") == "supporting_forms"

    # --- Other / fallback ---

    def test_unknown_prefix(self):
        assert PDFDownloader._categorise("unknown.pdf") == "other"

    def test_numeric_start(self):
        assert PDFDownloader._categorise("1040_misc.pdf") == "other"


# ---------------------------------------------------------------------------
#  _destination_path
# ---------------------------------------------------------------------------

class TestDestinationPath:

    def test_core_1040_goes_to_1040_dir(self, downloader):
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/f1040.pdf")
        assert path == downloader.config.PDFS_DIR / "1040" / "f1040.pdf"

    def test_senior_1040_goes_to_1040_dir(self, downloader):
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/f1040sr.pdf")
        assert path == downloader.config.PDFS_DIR / "1040" / "f1040sr.pdf"

    def test_schedule_goes_to_schedules_dir(self, downloader):
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/f1040sa.pdf")
        assert path == downloader.config.PDFS_DIR / "schedules" / "f1040sa.pdf"

    def test_instructions_goes_to_instructions_dir(self, downloader):
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/i1040.pdf")
        assert path == downloader.config.PDFS_DIR / "instructions" / "i1040.pdf"

    def test_publication_goes_to_publications_dir(self, downloader):
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/p17.pdf")
        assert path == downloader.config.PDFS_DIR / "publications" / "p17.pdf"

    def test_supporting_form_goes_to_supporting_forms_dir(self, downloader):
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/fw2.pdf")
        assert path == downloader.config.PDFS_DIR / "supporting_forms" / "fw2.pdf"

    def test_filename_is_lowercased(self, downloader):
        # URLs with uppercase letters in the filename should normalise to lowercase
        path = downloader._destination_path("https://www.irs.gov/pub/irs-pdf/F1040.PDF")
        assert path == downloader.config.PDFS_DIR / "1040" / "f1040.pdf"
