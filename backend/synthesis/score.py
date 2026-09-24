"""Score and rank clusters into a daily story selection.

Score = weighted blend of:
  - authority (max source authority in cluster)
  - coverage breadth (distinct owners — not feeds or hostnames)
  - novelty (penalize vendor-only single-source stories that look like PR)
  - recency (prefer items published within the last 24h)
  - research bonus (arXiv/research tags)

Source dedup: breadth is measured by distinct root domain (theverge.com),
not by feed name (The Verge vs The Verge — AI are the same outlet).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .domains import owner as _owner, root_domain as _root_domain
from .models import Cluster

log = logging.getLogger("pdb.score")


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None




_PR_WORDS = re.compile(
    r"\b(announces?|launches?|unveils?|introduces?|partnership|raises?|funding|series [a-z])\b",
    re.I,
)


def _source_kinds(c: Cluster) -> set[str]:
    """Classify each article's source into a kind for corroboration."""
    kinds = set()
    for a in c.articles:
        tags = set(a.raw.tags)
        if "research" in tags:
            kinds.add("research")
        elif "vendor" in tags:
            kinds.add("vendor")
        elif "community" in tags:
            kinds.add("community")
        else:
            kinds.add("news")
    return kinds


def _unique_domains(c: Cluster) -> int:
    """Count distinct root domains across all articles in a cluster.

    The Verge main feed and The Verge AI feed share theverge.com — they count
    as one domain, not two sources, for breadth and corroboration scoring.
    """
    return len({_owner(a.raw.url) for a in c.articles if a.raw.url})


def score_cluster(c: Cluster, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)

    # Use domain-deduplicated breadth — same outlet, two feeds = breadth 1
    breadth = _unique_domains(c)
    authority = c.max_authority
    kinds = _source_kinds(c)

    # recency: fraction of articles within last 36h
    recent = 0
    for a in c.articles:
        dt = _parse_dt(a.raw.published)
        if dt is None:
            recent += 0.5
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_h = (now - dt).total_seconds() / 3600
        recent += 1.0 if age_h <= 36 else (36 / age_h if age_h > 0 else 0)
    recency = recent / max(len(c.articles), 1)

    # novelty / PR penalty: single vendor source with PR language
    vendor_only = breadth == 1 and any("vendor" in a.raw.tags for a in c.articles)
    prish = any(_PR_WORDS.search(a.raw.title) for a in c.articles)
    novelty = 1.0
    if vendor_only and prish:
        novelty = 0.4
    elif prish:
        novelty = 0.7

    research = 1.15 if "research" in kinds else 1.0

    # corroboration: domain-deduplicated — two feeds from the same outlet
    # do NOT count as independent corroboration.
    if len(kinds) >= 2 and breadth >= 2:
        corroboration = 1.0 + 0.15 * (len(kinds) - 1)   # 1.15, 1.30, ...
    elif breadth >= 2:
        corroboration = 1.05                              # multiple real domains
    elif "research" in kinds:
        corroboration = 0.45                              # lone arXiv paper
    else:
        corroboration = 0.85                              # lone non-research item

    score = (
        0.30 * authority
        + 0.25 * min(breadth / 3.0, 1.0)
        + 0.20 * recency
        + 0.15 * novelty
        + 0.10 * (1.0 if breadth >= 2 else 0.0)
    ) * research * corroboration
    return round(score, 4)


def is_lone_research(c: Cluster) -> bool:
    return len(_source_kinds(c)) == 1 and "research" in _source_kinds(c)


def rank(
    clusters: list[Cluster],
    top_k: int = 7,
    max_lone_research: int = 2,
) -> list[tuple[Cluster, float]]:
    scored = [(c, score_cluster(c)) for c in clusters]
    scored.sort(key=lambda x: (x[1], len(x[0].articles), x[0].max_authority), reverse=True)

    # Diversity: cap single-source research papers so the brief shows a mix.
    selected: list[tuple[Cluster, float]] = []
    lone_research_count = 0
    for c, s in scored:
        if is_lone_research(c):
            if lone_research_count >= max_lone_research:
                continue
            lone_research_count += 1
        selected.append((c, s))
        if len(selected) >= top_k:
            break
    return selected
