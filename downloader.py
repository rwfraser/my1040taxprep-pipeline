"""
downloader.py  –  Downloads PDFs discovered by the crawler.

Features:
  - Reads URL manifest from state/url_manifest.json
  - Skips already-downloaded files (resume-safe)
  - Rate limiting with random jitter
  - Respects max file size limit
  - Organises PDFs into subdirectories by form category
  - Retries with exponential back-off on transient errors
"""

import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import Config

log = logging.getLogger("downloader")


class PDFDownloader:

    def __init__(self, config: Config):
        self.config  = config
        self.session = self._build_session()

    # ------------------------------------------------------------------
    #  Public interface
    # ------------------------------------------------------------------

    def run(self, limit: int | None = None, resume: bool = True):
        pdf_urls = self._load_manifest()
        if not pdf_urls:
            log.warning("No PDFs in manifest. Run the crawl phase first.")
            return

        state = self._load_state() if resume else {}
        downloaded: set[str] = set(state.get("downloaded", []))
        failed:     set[str] = set(state.get("failed", []))

        log.info(f"PDFs in manifest  : {len(pdf_urls)}")
        log.info(f"Already downloaded: {len(downloaded)}")
        log.info(f"Previously failed : {len(failed)}")

        pending = [u for u in pdf_urls if u not in downloaded]
        if limit:
            pending = pending[:limit]

        log.info(f"To download       : {len(pending)}")

        for i, url in enumerate(pending, 1):
            log.info(f"[{i}/{len(pending)}] {url}")
            success = self._download_pdf(url)
            if success:
                downloaded.add(url)
                failed.discard(url)
            else:
                failed.add(url)

            if i % 20 == 0:
                self._save_state(downloaded, failed)
                log.info(f"Checkpoint: {len(downloaded)} downloaded, {len(failed)} failed")

            self._polite_delay()

        self._save_state(downloaded, failed)
        log.info(f"Download phase complete. Downloaded: {len(downloaded)}, Failed: {len(failed)}")

        if failed:
            fail_log = self.config.LOGS_DIR / "failed_downloads.txt"
            with open(fail_log, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(failed)))
            log.info(f"Failed URLs written to: {fail_log}")

    # ------------------------------------------------------------------
    #  Download logic
    # ------------------------------------------------------------------

    def _download_pdf(self, url: str) -> bool:
        dest_path = self._destination_path(url)
        if dest_path.exists():
            log.info(f"  Already exists, skipping: {dest_path.name}")
            return True

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, self.config.MAX_RETRIES + 1):
            try:
                resp = self.session.get(
                    url,
                    timeout=self.config.REQUEST_TIMEOUT_SECS,
                    stream=True,
                )
                resp.raise_for_status()

                # Check size before writing
                content_length = resp.headers.get("Content-Length")
                if content_length:
                    mb = int(content_length) / (1024 * 1024)
                    if mb > self.config.MAX_PDF_SIZE_MB:
                        log.warning(f"  Skipping {url}: too large ({mb:.1f} MB)")
                        return False

                with open(dest_path, "wb") as f:
                    total_bytes = 0
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > self.config.MAX_PDF_SIZE_MB * 1024 * 1024:
                            log.warning(f"  File exceeded size limit mid-download, aborting: {url}")
                            dest_path.unlink(missing_ok=True)
                            return False

                log.info(f"  Saved: {dest_path.name} ({total_bytes / 1024:.1f} KB)")
                return True

            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response else "?"
                log.warning(f"  HTTP {status} on attempt {attempt}: {url}")
                if status in (403, 404, 410):
                    return False  # permanent error, don't retry
            except Exception as exc:
                log.warning(f"  Error on attempt {attempt}: {exc}")

            if attempt < self.config.MAX_RETRIES:
                backoff = 2 ** attempt + random.uniform(0, 1)
                log.info(f"  Retrying in {backoff:.1f}s…")
                time.sleep(backoff)

        dest_path.unlink(missing_ok=True)
        return False

    def _destination_path(self, url: str) -> Path:
        """
        Map a URL to a local path.
        Groups files into subdirectories by form category for easy navigation.
        Examples:
          f1040.pdf          -> pdfs/1040/f1040.pdf
          f1040sa.pdf        -> pdfs/schedules/f1040sa.pdf
          i1040.pdf          -> pdfs/instructions/i1040.pdf
          p17.pdf            -> pdfs/publications/p17.pdf
          fw2.pdf            -> pdfs/supporting_forms/fw2.pdf
        """
        filename = Path(urlparse(url).path).name.lower()
        subdir   = self._categorise(filename)
        return self.config.PDFS_DIR / subdir / filename

    @staticmethod
    def _categorise(filename: str) -> str:
        # Schedules: f1040sa..f1040sj (letter schedules), f1040s1/s2/s3 (numbered schedules),
        # f1040sch (schedule cover sheet).  Exclude f1040sr — that is Form 1040-SR
        # (Senior return), NOT a schedule.
        if filename.startswith("f1040s") and not filename.startswith("f1040sr"):
            return "schedules"
        # Core 1040 forms: f1040, f1040sr, f1040nr, f1040x, f1040es
        if filename.startswith("f1040"):
            return "1040"
        # Instructions: IRS instruction files are conventionally prefixed with 'i'
        # (e.g. i1040.pdf, iw2.pdf, iw4.pdf)
        if filename.startswith("i"):
            return "instructions"
        # Publications: p17.pdf, p501.pdf, etc.
        if filename.startswith("p"):
            return "publications"
        # All other 'f'-prefixed forms: fw2, f1099, f8949, etc.
        if filename.startswith("f"):
            return "supporting_forms"
        return "other"

    # ------------------------------------------------------------------
    #  Session
    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; IRS-TaxDocCrawler/1.0; "
                "+https://github.com/local/irs-tax-crawler)"
            ),
            "Accept": "application/pdf,*/*",
        })
        return s

    def _polite_delay(self):
        time.sleep(
            self.config.DOWNLOAD_DELAY_SECS
            + random.uniform(0, self.config.DOWNLOAD_JITTER_SECS)
        )

    # ------------------------------------------------------------------
    #  State & manifest
    # ------------------------------------------------------------------

    def _load_manifest(self) -> list[str]:
        path = self.config.URL_MANIFEST_FILE
        if not path.exists():
            log.error(f"Manifest not found: {path}")
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("urls", [])

    def _load_state(self) -> dict:
        path = self.config.DOWNLOAD_STATE_FILE
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                log.warning(f"Could not load download state: {exc}")
        return {}

    def _save_state(self, downloaded: set[str], failed: set[str]):
        state = {
            "downloaded": sorted(downloaded),
            "failed":     sorted(failed),
        }
        with open(self.config.DOWNLOAD_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
