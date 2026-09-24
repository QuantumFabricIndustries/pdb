"""Fact-Checker — deterministic evidence checks. No AI guessing here.

The Writer must attach an exact supporting quote (and its source number) to
every claim. This module then checks, with plain code:

  * the quote really appears in that source's text
  * every number / CVE ID in the claim appears in that source
  * which OTHER independent owners' articles also support the claim
  * every number in the Writer's prose exists somewhere in the sources
  * the Writer did not copy long word-for-word runs from any source (copyright)
  * whether primary sources exist (CISA KEV, .gov pages, journals, the subject's own statement)
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .domains import is_primary, owner

log = logging.getLogger("pdb.verify")

COPY_RUN_WORDS = 12          # a run of this many identical consecutive words = copying
CORROBORATION_OVERLAP = 0.6  # share of a claim's key words another source must contain

_STOP = set("""a an the of to in on for and or but is are was were be been being with from by at as this that
these those it its their his her our your you we they he she not no so than too very can will just into over
under then once here there when where why how all any both each few more most other some such only own same
has have had do does did says said say also after before about could would should may might new""".split())

_NUM_RE = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)(?![\d])")
_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)
_WORD_RE = re.compile(r"[a-z0-9]+")


# --- text normalization -------------------------------------------------------

_PUNCT = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
                        "\u00a0": " ", "\u202f": " "})


def norm(text: str) -> str:
    """Lowercase, NFKC, and unify curly quotes / unusual hyphens / odd spaces."""
    t = unicodedata.normalize("NFKC", text or "").lower().translate(_PUNCT)
    return re.sub(r"\s+", " ", t).strip()


def words(text: str) -> list[str]:
    return _WORD_RE.findall(norm(text))


def numbers(text: str) -> set[str]:
    """Numbers as canonical strings: '12,000' -> '12000', '2.0' -> '2'. Years included."""
    out = set()
    for m in _NUM_RE.finditer(norm(text)):
        v = m.group(1).replace(",", "")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        if v:
            out.add(v)
    return out


def cves(text: str) -> set[str]:
    return {c.upper() for c in _CVE_RE.findall(norm(text or ""))}


_LIST_MARKER_RE = re.compile(r"(?:(?<=^)|(?<=\s))\d{1,2}[.)](?=\s)")


def strip_list_markers(text: str) -> str:
    """'1. Patch 2. Reset' -> ' Patch  Reset' (list numbering is formatting, not a fact)."""
    return _LIST_MARKER_RE.sub(" ", text or "")


def source_years(src) -> set[str]:
    """A source's publication year counts as known ('June 18' in a 2026 article is June 18, 2026)."""
    from .fetcher import parse_date
    dt = parse_date(getattr(src, "published", None))
    return {str(dt.year)} if dt else set()


def _key_words(text: str) -> set[str]:
    return {w[:6] for w in words(text) if w not in _STOP and len(w) > 3 and not w.isdigit()}


# --- individual checks -------------------------------------------------------

def quote_in_text(quote: str, text: str) -> bool:
    """Exact (normalized) match, or >= 90% of the quote's 4-word sequences present.

    Quotes with an ellipsis ("A ... B") are checked fragment by fragment; each
    fragment of 4+ words must be found.
    """
    frags = [f.strip(" .,;:\"'\u201c\u201d") for f in re.split(r"\.\.\.|\u2026|\[\.\.\.\]", quote or "")]
    if len(frags) > 1:                       # quote contains an ellipsis
        long_frags = [f for f in frags if len(f.split()) >= 4]
        return bool(long_frags) and _fragments_close_in_order(long_frags, text)
    return _fragment_in_text(quote, text)


ELLIPSIS_MAX_GAP = 400   # chars; splicing sentences far apart can distort meaning


def _fragments_close_in_order(frags: list[str], text: str) -> bool:
    """Each fragment must appear verbatim (normalized), in order, near the previous one."""
    t = norm(text)
    pos = -1
    for f in frags:
        fn = norm(f)
        if pos < 0:
            i = t.find(fn)
        else:
            i = t.find(fn, pos)
            if i - pos > ELLIPSIS_MAX_GAP:
                i = -1
        if i < 0:
            return False
        pos = i + len(fn)
    return True


def _fragment_in_text(quote: str, text: str) -> bool:
    q, t = norm(quote), norm(text)
    if len(q) < 12:
        return False
    if q in t:
        return True
    qw, tw = words(quote), words(text)
    if len(qw) < 6:
        return False
    grams = {tuple(qw[i:i + 4]) for i in range(len(qw) - 3)}
    tgrams = {tuple(tw[i:i + 4]) for i in range(len(tw) - 3)}
    return len(grams & tgrams) / len(grams) >= 0.9


def supports(claim: str, text: str) -> bool:
    """Does a source text plausibly support a claim? All numbers/CVEs present + most key words."""
    tn = numbers(text)
    if not numbers(claim) <= tn or not cves(claim) <= cves(text):
        return False
    kw = _key_words(claim)
    if not kw:
        return False
    tkw = _key_words(text)
    return len(kw & tkw) / len(kw) >= CORROBORATION_OVERLAP


def copied_runs(prose: str, sources: list[str], n: int = COPY_RUN_WORDS) -> list[str]:
    """Word runs of length n appearing verbatim in any source (copyright guard)."""
    pw = words(prose)
    if len(pw) < n:
        return []
    src_grams = set()
    for s in sources:
        sw = words(s)
        src_grams |= {tuple(sw[i:i + n]) for i in range(len(sw) - n + 1)}
    hits = []
    for i in range(len(pw) - n + 1):
        g = tuple(pw[i:i + n])
        if g in src_grams:
            hits.append(" ".join(g))
    return hits


# --- CISA Known Exploited Vulnerabilities (primary source) ----------------------

_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_kev: dict[str, dict] | None = None


def kev_catalog(cache: Path | None = None) -> dict[str, dict]:
    """CVE -> KEV entry. Cached on disk for 12h. Empty dict if unreachable."""
    global _kev
    if _kev is not None:
        return _kev
    data = None
    if cache and cache.exists() and time.time() - cache.stat().st_mtime < 12 * 3600:
        data = json.loads(cache.read_text(encoding="utf-8"))
    if data is None:
        try:
            import httpx
            r = httpx.get(_KEV_URL, timeout=30, follow_redirects=True)
            r.raise_for_status()
            data = r.json()
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            log.warning("CISA KEV unavailable: %s", e)
            data = {"vulnerabilities": []}
    _kev = {v["cveID"].upper(): v for v in data.get("vulnerabilities", [])}
    return _kev


# --- report ----------------------------------------------------------------------

@dataclass
class Source:
    n: int                 # 1-based number the Writer cites
    outlet: str
    owner: str
    url: str
    published: str | None
    text: str
    authority: float
    kind: str = "news"      # news | vendor | primary | community | factcheck | research


@dataclass
class ClaimCheck:
    claim: str
    source: int
    quote: str
    status: str                                   # verified | quote_not_found | number_mismatch | bad_source
    corroborated_by: list[str] = field(default_factory=list)  # other independent owners
    problems: list[str] = field(default_factory=list)


@dataclass
class Report:
    claims: list[ClaimCheck]
    owners: list[str]
    primary: list[dict]                     # {"url","type","verified"}
    prose_number_problems: list[str]
    copied: list[str]
    kev_hits: list[str]

    @property
    def verified_claims(self) -> list[ClaimCheck]:
        return [c for c in self.claims if c.status == "verified"]


def check_claims(raw_claims: list[dict], sources: list[Source]) -> list[ClaimCheck]:
    by_n = {s.n: s for s in sources}
    out = []
    for rc in raw_claims:
        claim = str(rc.get("claim", "")).strip()
        quote = str(rc.get("quote", "")).strip()
        try:
            n = int(rc.get("source", 0))
        except Exception:
            n = 0
        cc = ClaimCheck(claim=claim, source=n, quote=quote, status="verified")
        src = by_n.get(n)
        if not claim or src is None:
            cc.status, cc.problems = "bad_source", ["cites a source that does not exist"]
            out.append(cc)
            continue
        if not quote_in_text(quote, src.text):
            cc.status = "quote_not_found"
            cc.problems.append(f"quote not found in source [{n}]")
        missing_nums = numbers(claim) - numbers(src.text) - source_years(src)
        missing_cves = cves(claim) - cves(src.text)
        if missing_nums or missing_cves:
            cc.status = "number_mismatch"
            cc.problems.append(f"not in source [{n}]: {', '.join(sorted(missing_nums | missing_cves))}")
        if cc.status == "verified":
            cc.corroborated_by = sorted({s.owner for s in sources
                                         if s.owner != src.owner and supports(claim, s.text)})
        out.append(cc)
    return out


def check_primary(sources: list[Source], primary_pages: dict[str, str], headline: str,
                  claim_texts: list[str], kev: dict[str, dict], prose: str = "") -> tuple[list[dict], list[str]]:
    """Primary evidence that matches what THIS story says.

    - CISA KEV: only CVEs the story itself names (headline, claims, prose) — a CVE merely
      mentioned somewhere in a source article is background, not evidence for this story.
    - Linked official pages: must name one of the story's CVEs, or share >= 60% of the headline's key words.
    - Sources that are themselves official (.gov, journals) or the organization the story is about.
    """
    found: list[dict] = []
    all_cves = set()
    for t in claim_texts + [headline, prose]:
        all_cves |= cves(t)
    kev_hits = sorted(c for c in all_cves if c in kev)
    for c in kev_hits:
        found.append({"url": f"https://nvd.nist.gov/vuln/detail/{c}", "type": "CISA KEV: actively exploited",
                      "verified": True, "label": f"{c} — {kev[c].get('vulnerabilityName', '')}"})
    story_kw = _key_words(headline)
    for url, text in primary_pages.items():
        tkw = _key_words(text)
        if cves(text) & all_cves:
            found.append({"url": url, "type": "official record", "verified": True, "label": url})
        elif story_kw and len(story_kw & tkw) / len(story_kw) >= 0.6:
            found.append({"url": url, "type": "related official record", "verified": True, "label": url})
        else:
            found.append({"url": url, "type": "linked official page", "verified": False, "label": url})
    head_words = set(words(headline))
    for s in sources:
        subject_names = set(words(s.owner)) | {s.owner.split(".")[0].lower()}
        if s.kind == "primary" or is_primary(s.url):
            found.append({"url": s.url, "type": "official record", "verified": True, "label": s.outlet})
        elif s.kind == "vendor" and subject_names & head_words:
            found.append({"url": s.url, "type": "subject's own statement", "verified": True, "label": s.outlet})
    return found, kev_hits


def prose_number_problems(prose: str, sources: list[Source]) -> list[str]:
    allnums = set()
    for s in sources:
        allnums |= numbers(s.text) | source_years(s)
    missing = sorted(numbers(strip_list_markers(prose)) - allnums)
    return [f"number '{m}' does not appear in any source" for m in missing]


def verify(draft: dict, sources: list[Source], primary_pages: dict[str, str] | None = None,
           kev: dict[str, dict] | None = None) -> Report:
    kev = kev if kev is not None else {}
    claims = check_claims(draft.get("claims", []), sources)
    prose = " ".join(str(draft.get(k, "")) for k in ("headline", "in_brief", "so_what", "what_to_do"))
    primary, kev_hits = check_primary(sources, primary_pages or {}, draft.get("headline", ""),
                                      [c.claim for c in claims], kev, prose)
    return Report(
        claims=claims,
        owners=sorted({s.owner for s in sources}),
        primary=primary,
        prose_number_problems=prose_number_problems(prose, sources),
        copied=copied_runs(prose, [s.text for s in sources]),
        kev_hits=kev_hits,
    )
