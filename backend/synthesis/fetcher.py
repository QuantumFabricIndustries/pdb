"""Feed fetching and article extraction.

Uses httpx for HTTP and feedparser for RSS/Atom. Article body extraction
prefers trafilatura; falls back to a regex-based HTML stripper.

Every request has a hard wall-clock deadline (streamed read), and feeds and
articles are fetched concurrently, so one slow site can never hang a run.
"""

from __future__ import annotations

import concurrent.futures as cf
import html
import json
import logging
import re
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from .config import Feed, SourcePack
from .domains import is_primary, root_domain
from .models import Article, RawItem

log = logging.getLogger("synthesis.fetcher")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PDB-PublicDailyBrief/1.0; +https://github.com/QuantumFabricIndustries)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*",
}
_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)
_MAX_BYTES = 3_000_000

# --- low-level GET with a hard deadline -----------------------------------------

def get_with_deadline(client: httpx.Client, url: str, deadline_s: float = 25.0) -> tuple[int, bytes, str]:
    """GET url, aborting if the whole transfer exceeds deadline_s. Returns (status, body, final_url)."""
    start = time.monotonic()
    with client.stream("GET", url) as r:
        chunks, size = [], 0
        for chunk in r.iter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_BYTES or time.monotonic() - start > deadline_s:
                raise TimeoutError(f"deadline/size exceeded for {url}")
        return r.status_code, b"".join(chunks), str(r.url)


def make_client() -> httpx.Client:
    return httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=_TIMEOUT)


# --- extraction ----------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)


def _strip_html(html_str: str) -> str:
    text = _TAG_RE.sub(" ", html_str)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _try_trafilatura(html_str: str, url: str) -> str | None:
    try:
        import trafilatura  # type: ignore
    except Exception:
        return None
    try:
        return trafilatura.extract(html_str, include_comments=False, include_tables=False, url=url)
    except Exception:
        return None


def _extract(html_str: str, url: str, fallback_text: str) -> tuple[str, bool]:
    """Return (text, extracted_ok)."""
    body = _try_trafilatura(html_str, url)
    if body and len(body) > 200:
        return body, True
    stripped = _strip_html(html_str)
    if len(stripped) > len(fallback_text):
        return stripped[:20000], False
    return fallback_text, False


def primary_links(html_str: str, base_url: str, limit: int = 8) -> list[str]:
    """Outbound links from an article to primary sources (.gov, CISA, courts, journals...)."""
    own = root_domain(base_url)
    out: list[str] = []
    for href in _HREF_RE.findall(html_str):
        link = urljoin(base_url, href.strip())
        if not link.startswith("http") or root_domain(link) == own:
            continue
        if is_primary(link) and link not in out:
            out.append(link)
        if len(out) >= limit:
            break
    return out


# --- feeds ---------------------------------------------------------------------

_ARXIV_NOISE_RE = re.compile(r"^arXiv:\S+\s+(Announce Type:\S+\s+)?Abstract:\s*", re.I)


def _clean_summary(summary: str, feed: Feed) -> str:
    """Strip feed-specific metadata noise (arXiv prefixes, HN link metadata)."""
    if "arxiv" in feed.url.lower():
        summary = _ARXIV_NOISE_RE.sub("", summary)
    if "hnrss" in feed.url.lower():
        summary = re.sub(r"(Article URL|Comments URL|Points|# Comments|Comments?):\s*\S*", "", summary)
        summary = re.sub(r"https?://\S+", "", summary)
    return summary.strip()


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s.strip(), fmt)
                break
            except Exception:
                continue
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_feed_entry(entry, feed: Feed) -> RawItem | None:
    url = entry.get("link")
    title = html.unescape((entry.get("title") or "").strip())
    if not url or not title:
        return None
    summary = _clean_summary(_strip_html(entry.get("summary") or entry.get("description") or ""), feed)
    published = entry.get("published") or entry.get("updated")
    return RawItem(
        source=feed.name, title=title, url=url, published=published, summary=summary,
        tags=list(feed.tags), authority=feed.authority, region=feed.region, section=feed.section,
    )


def fetch_feed(feed: Feed, client: httpx.Client) -> list[RawItem]:
    try:
        status, body, _ = get_with_deadline(client, feed.url)
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
    except Exception as e:
        log.warning("feed fetch failed: %s — %s", feed.name, e)
        return []
    parsed = feedparser.parse(body)
    items = [i for i in (_parse_feed_entry(e, feed) for e in parsed.entries) if i]
    log.info("feed %-24s -> %d items", feed.name, len(items))
    return items


def fetch_pack(pack: SourcePack, max_per_feed: int = 40, max_age_hours: float | None = None) -> list[RawItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours) if max_age_hours else None
    items: list[RawItem] = []
    with make_client() as client, cf.ThreadPoolExecutor(max_workers=12) as ex:
        for feed_items in ex.map(lambda f: fetch_feed(f, client), pack.feeds):
            kept = []
            for it in feed_items:
                if cutoff is not None:
                    dt = parse_date(it.published)
                    if dt is not None and dt < cutoff:
                        continue
                kept.append(it)
            items.extend(kept[:max_per_feed])
    return items


# --- enrichment ----------------------------------------------------------------

def _enrich_one(client: httpx.Client, it: RawItem, max_chars: int) -> Article:
    text, ok, links = it.summary, False, []
    try:
        if urlparse(it.url).netloc:
            status, body, final = get_with_deadline(client, it.url)
            if status == 200:
                page = body.decode("utf-8", errors="replace")
                text, ok = _extract(page, final, it.summary)
                links = primary_links(page, final)
    except Exception as e:
        log.debug("enrich failed for %s — %s", it.url, e)
    text = text[:max_chars]
    excerpt = (text[:280] + "…") if len(text) > 280 else text
    return Article(raw=it, text=text, excerpt=excerpt, extracted_ok=ok,
                   word_count=len(text.split()), primary_links=links)


def enrich(items: list[RawItem], max_chars: int = 20000, workers: int = 12) -> list[Article]:
    """Fetch full article text for each RawItem (concurrently, order preserved)."""
    with make_client() as client, cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda it: _enrich_one(client, it, max_chars), items))


def shallow(items: list[RawItem]) -> list[Article]:
    """Articles from feed data only (no page fetch)."""
    return [Article(raw=r, text=r.summary, excerpt=r.summary[:280], extracted_ok=False,
                    word_count=len(r.summary.split())) for r in items]


# --- cache (lets us re-run clustering/verification without refetching) ---------

def save_articles(articles: list[Article], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(a) for a in articles], ensure_ascii=False), encoding="utf-8")


def load_articles(path: Path) -> list[Article]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Article(raw=RawItem(**d.pop("raw")), **d) for d in data]
