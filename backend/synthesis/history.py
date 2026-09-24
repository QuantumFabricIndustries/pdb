"""Brief History — find prior PDB coverage of a story in past issues.

Scans past issue markdown files for title/tag overlap and returns
human-readable callback strings like:
  "Previously covered: 2026-09-03 — OpenAI releases o3 reasoning model"

Runs purely on local files — no DB needed. Fast enough for 30-day windows.
"""

from __future__ import annotations

import re
import logging
from pathlib import Path

log = logging.getLogger("pdb.history")

# Words that don't help identify topic overlap
_STOP = frozenset({
    "the","a","an","of","in","on","at","to","for","and","or","is","are","was",
    "were","with","from","by","that","this","it","as","be","but","not","have",
    "has","had","its","will","can","we","our","their","how","what","why","when",
    "new","via","over","into","after","before","about","more","than","just",
    "also","first","using","says","said","used","based","release","releases",
    "update","updates","version","model","models","team","company","open",
})

_TITLE_RE = re.compile(r"^### \d+\. (.+)$", re.MULTILINE)
_DATE_RE   = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _keywords(text: str, tags: list[str]) -> set[str]:
    words = set(re.findall(r"\b[a-z]{4,}\b", text.lower())) - _STOP
    words |= {t.lower().strip() for t in tags if len(t) >= 3}
    return words


def _overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


def find_history_refs(
    title: str,
    tags: list[str],
    issues_dir: Path,
    current_date: str,
    max_refs: int = 2,
    min_overlap: int = 2,
    lookback_days: int = 30,
) -> list[str]:
    """Return up to `max_refs` prior-coverage strings for a story.

    Args:
        title:         The current story title to match against.
        tags:          The story's topic tags.
        issues_dir:    Directory containing past issue .md files.
        current_date:  Today's date string (YYYY-MM-DD) — excluded from search.
        max_refs:      Maximum callbacks to return.
        min_overlap:   Minimum keyword overlap count to consider a match.
        lookback_days: Only scan files from the last N days.
    """
    if not issues_dir.exists():
        return []

    kw = _keywords(title, tags)
    if len(kw) < 2:
        return []

    # Collect and sort .md files newest-first, skip today
    candidates = sorted(
        [f for f in issues_dir.glob("*.md") if not f.stem.startswith(current_date)],
        reverse=True,
    )[:lookback_days]  # rough cap — one file per day

    refs: list[str] = []

    for md_file in candidates:
        # Extract date from filename stem (YYYY-MM-DD-*)
        m = _DATE_RE.match(md_file.stem)
        date_str = m.group(1) if m else md_file.stem[:10]

        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for match in _TITLE_RE.finditer(text):
            prev_title = match.group(1).strip()
            prev_kw = _keywords(prev_title, [])
            if _overlap(kw, prev_kw) >= min_overlap:
                refs.append(f"Previously covered: {date_str} — {prev_title}")
                log.debug("History match: %r → %r", title[:60], prev_title[:60])
                if len(refs) >= max_refs:
                    return refs

    return refs
