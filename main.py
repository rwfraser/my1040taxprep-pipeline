"""
IRS 2023 Tax Document Crawler - Main Orchestrator
Path: C:\\Users\\RogerIdaho\\Projects\\my1040taxprep\\
"""

import argparse
import contextlib
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from analyzer import DocumentAnalyzer
from config import Config
from crawler import IRSCrawler
from downloader import PDFDownloader
from extractor import PDFExtractor


def setup_logging(config: Config) -> None:
    """
    Configure root logging with:
      - A rotating file handler (max 10 MB per file, 3 backups kept).
      - A stream handler that echoes all output to stdout.

    Rotation ensures long crawl/analyze runs never fill the disk with a
    single unbounded log file.
    """
    log_path = config.LOGS_DIR / "main.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10_000_000,   # rotate at 10 MB
        backupCount=3,         # keep main.log, main.log.1, main.log.2, main.log.3
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, stream_handler],
    )

def _timed_phase(log: logging.Logger, label: str):
    """
    Context manager that logs the wall-clock duration of a pipeline phase.

    Usage::

        with _timed_phase(log, "Phase 1: Crawling"):
            crawler.run()
    """
    @contextlib.contextmanager
    def _ctx():
        t0 = time.perf_counter()
        log.info(f"--- {label} ---")
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            log.info(f"--- {label} complete ({elapsed:.1f}s) ---")

    return _ctx()


def main():
    parser = argparse.ArgumentParser(
        description="IRS 2023 Tax Document Crawler & Analyzer"
    )
    parser.add_argument(
        "--phase",
        choices=["crawl", "download", "extract", "analyze", "all"],
        default="all",
        help="Pipeline phase to run (default: all)",
    )
    parser.add_argument(
        "--analyze-pass",
        choices=["master_schema", "ground_truth", "mandatory_map", "calc_table", "db_schemas"],
        default=None,
        help="Which analysis pass to run (only used when phase=analyze)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of PDFs to process (useful for testing)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from previous state (default: True)",
    )
    args = parser.parse_args()

    config = Config()
    config.ensure_dirs()
    setup_logging(config)
    log = logging.getLogger("main")

    pipeline_start = time.perf_counter()

    log.info("=" * 60)
    log.info("IRS 2023 Tax Document Crawler")
    log.info(f"Base path : {config.BASE_DIR}")
    log.info(f"Phase     : {args.phase}")
    log.info(f"Resume    : {args.resume}")
    log.info("=" * 60)

    if args.phase in ("crawl", "all"):
        with _timed_phase(log, "Phase 1: Crawling IRS.gov"):
            crawler = IRSCrawler(config)
            crawler.run(resume=args.resume)

    if args.phase in ("download", "all"):
        with _timed_phase(log, "Phase 2: Downloading PDFs"):
            downloader = PDFDownloader(config)
            downloader.run(limit=args.limit, resume=args.resume)

    if args.phase in ("extract", "all"):
        with _timed_phase(log, "Phase 3: Extracting PDF text"):
            extractor = PDFExtractor(config)
            extractor.run(limit=args.limit, resume=args.resume)

    if args.phase in ("analyze", "all"):
        if not config.ANTHROPIC_API_KEY:
            log.error("ANTHROPIC_API_KEY not set in config.py. Cannot run analysis.")
            sys.exit(1)
        analyzer = DocumentAnalyzer(config)
        passes = (
            [args.analyze_pass]
            if args.analyze_pass
            else ["master_schema", "ground_truth", "mandatory_map", "calc_table", "db_schemas"]
        )
        with _timed_phase(log, "Phase 4: LLM Analysis"):
            for pass_name in passes:
                with _timed_phase(log, f"  Analysis pass: {pass_name}"):
                    analyzer.run_pass(pass_name, limit=args.limit, resume=args.resume)

    total = time.perf_counter() - pipeline_start
    log.info(f"Pipeline complete. Total time: {total:.1f}s")

if __name__ == "__main__":
    main()
