"""
crawler.py  –  Crawls IRS.gov and collects 2023 tax-relevant PDF URLs.

State is persisted to state/crawl_state.json so interrupted runs resume
from where they left off.
"""

import json
import logging
import random
import time
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from config import Config

log = logging.getLogger("crawler")


class IRSCrawler:
    """
    BFS crawler scoped to IRS.gov.
    Collects all PDF URLs that look like 2023 Form-1040-relevant documents.
    """

    BASE_DOMAIN = "www.irs.gov"
    ROBOTS_URL  = "https://www.irs.gov/robots.txt"

    def __init__(self, config: Config):
        self.config  = config
        self.session = self._build_session()
        self.rp      = self._load_robots()

    # ------------------------------------------------------------------
    #  Public interface
    # ------------------------------------------------------------------

    def run(self, resume: bool = True):
        state = self._load_state() if resume else self._empty_state()

        visited: set[str]  = set(state["visited"])
        queued:  set[str]  = set(state["queued"])
        pdf_urls: set[str] = set(state["pdf_urls"])
        queue: deque       = deque(state["queue"])

        # Seed the queue with start URLs if empty
        if not queue:
            for url in self.config.START_URLS:
                if url not in visited:
                    queue.append((url, 0))
                    queued.add(url)

        log.info(
            f"Starting crawl. Queue: {len(queue)}, Visited: {len(visited)}, PDFs: {len(pdf_urls)}"
        )

        checkpoint_every = 50
        steps = 0

        while queue:
            url, depth = queue.popleft()

            if url in visited:
                continue
            visited.add(url)

            if depth > self.config.MAX_CRAWL_DEPTH:
                continue

            log.info(f"[depth={depth}] Crawling: {url}")
            links, found_pdfs = self._fetch_and_parse(url)

            for pdf_url in found_pdfs:
                if pdf_url not in pdf_urls:
                    pdf_urls.add(pdf_url)
                    log.info(f"  Found PDF: {pdf_url}")

            for link in links:
                if link not in visited and link not in queued:
                    queue.append((link, depth + 1))
                    queued.add(link)

            steps += 1
            if steps % checkpoint_every == 0:
                self._save_state(visited, queued, pdf_urls, list(queue))
                log.info(f"Checkpoint saved. Visited: {len(visited)}, PDFs: {len(pdf_urls)}")

            self._polite_delay(self.config.CRAWL_DELAY_SECS, self.config.CRAWL_JITTER_SECS)

        self._save_state(visited, queued, pdf_urls, [])
        self._save_manifest(pdf_urls)
        log.info(f"Crawl complete. Total PDFs found: {len(pdf_urls)}")

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _fetch_and_parse(self, url: str) -> tuple[list[str], list[str]]:
        """Fetch a page, return (internal_html_links, pdf_links)."""
        try:
            resp = self.session.get(url, timeout=self.config.REQUEST_TIMEOUT_SECS)
            resp.raise_for_status()
        except Exception as exc:
            log.warning(f"Failed to fetch {url}: {exc}")
            return [], []

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type:
            return [], []

        soup = BeautifulSoup(resp.text, "html.parser")
        html_links: list[str] = []
        pdf_links:  list[str] = []

        for tag in soup.find_all("a", href=True):
            raw_href = str(tag["href"])  # BeautifulSoup may return list[str]; cast to str
            abs_url, _ = urldefrag(urljoin(url, raw_href))
            abs_url = abs_url.rstrip("/")

            if not self._is_irs_url(abs_url):
                continue
            if self._is_blocked(abs_url):
                continue

            if abs_url.lower().endswith(".pdf"):
                if self._is_relevant_pdf(abs_url):
                    pdf_links.append(abs_url)
            else:
                if self._is_crawlable_path(abs_url):
                    html_links.append(abs_url)

        return html_links, pdf_links

    def _is_irs_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc in ("www.irs.gov", "irs.gov", "")

    def _is_blocked(self, url: str) -> bool:
        lower = url.lower()
        return any(token in lower for token in self.config.BLOCKED_URL_TOKENS)

    def _is_crawlable_path(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(path.startswith(p) for p in self.config.ALLOWED_PATHS)

    def _is_relevant_pdf(self, url: str) -> bool:
        """
        Return True if the PDF URL is relevant to 2023 Form 1040 preparation.

        Three acceptance criteria are checked in order.  ORDER IS CRITICAL:
        the prior-year directory gate (Case 1) must run before the prefix
        check (Case 2), otherwise forms from 2019-2022 in /pub/irs-prior/
        pass through because their filenames share the same prefix as 2023
        forms (e.g. f1040--2022.pdf starts with "f1040").

        Case 1 — Prior-year archive gate (most restrictive):
            Files under /pub/irs-prior/ MUST contain a year token from
            YEAR_TOKENS_IN_FILENAME ("2023", "ty23", "23").  A matching
            prefix alone is NOT sufficient — f1040--2022.pdf would otherwise
            be accepted. This gate is evaluated first for all /irs-prior/ URLs.

        Case 2 — Known form prefix (for non-archive paths):
            The filename starts with an entry in FORM_PREFIXES.  Used for
            /pub/irs-pdf/ files that carry no year in their name because they
            are always the current-year version (e.g. f1040.pdf, fw2.pdf).

        Case 3 — Year-token fallback (broadest net):
            Any IRS PDF whose filename contains a year token ("2023", "ty23",
            or "23") is accepted regardless of path, catching edge cases not
            covered by the prefix list.
        """
        filename = Path(urlparse(url).path).name.lower()
        path = urlparse(url).path.lower()

        # Case 1: prior-year archive — year token is REQUIRED, prefix alone
        # is not enough.  This must run before Case 2 to block multi-year
        # forms such as f1040--2022.pdf, f1040--2021.pdf, etc.
        if "/irs-prior/" in path:
            return any(tok in filename for tok in self.config.YEAR_TOKENS_IN_FILENAME)

        # Case 2: non-archive paths — accept by known form prefix
        for prefix in self.config.FORM_PREFIXES:
            if filename.startswith(prefix):
                return True

        # Case 3: year token anywhere in the filename (fallback)
        if any(tok in filename for tok in self.config.YEAR_TOKENS_IN_FILENAME):
            return True

        return False

    def _load_robots(self) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            rp.set_url(self.ROBOTS_URL)
            rp.read()
            log.info("robots.txt loaded.")
        except Exception as exc:
            log.warning(f"Could not load robots.txt: {exc}")
        return rp

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; IRS-TaxDocCrawler/1.0; "
                "+https://github.com/local/irs-tax-crawler)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        return s

    @staticmethod
    def _polite_delay(base: float, jitter: float):
        time.sleep(base + random.uniform(0, jitter))

    # ------------------------------------------------------------------
    #  State persistence
    # ------------------------------------------------------------------

    def _empty_state(self) -> dict:
        return {"visited": [], "queued": [], "pdf_urls": [], "queue": []}

    def _load_state(self) -> dict:
        path = self.config.CRAWL_STATE_FILE
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    state = json.load(f)
                log.info(f"Resumed crawl state from {path}")
                return state
            except Exception as exc:
                log.warning(f"Could not load crawl state: {exc}. Starting fresh.")
        return self._empty_state()

    def _save_state(self, visited, queued, pdf_urls, queue):
        state = {
            "visited":  list(visited),
            "queued":   list(queued),
            "pdf_urls": list(pdf_urls),
            "queue":    list(queue),
        }
        with open(self.config.CRAWL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def _save_manifest(self, pdf_urls: set[str]):
        """Save the final list of discovered PDF URLs to the manifest file."""
        manifest = {
            "total": len(pdf_urls),
            "urls": sorted(pdf_urls),
        }
        with open(self.config.URL_MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        log.info(f"URL manifest saved: {self.config.URL_MANIFEST_FILE}")
