"""Data models for the PDB pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RawItem:
    """A single feed entry before extraction/dedup."""
    source: str
    title: str
    url: str
    published: str | None = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    authority: float = 0.7
    region: str = "US"
    section: str = ""
    fetched_at: str = field(default_factory=_now_iso)


@dataclass
class Article:
    """A RawItem enriched with extracted body text."""
    raw: RawItem
    text: str = ""
    excerpt: str = ""
    extracted_ok: bool = False
    word_count: int = 0
    primary_links: list[str] = field(default_factory=list)  # outbound links to primary sources


@dataclass
class Cluster:
    """A group of Articles about the same story."""
    id: str
    articles: list[Article] = field(default_factory=list)
    centroid_title: str = ""
    tags: set[str] = field(default_factory=set)
    max_authority: float = 0.0

    @property
    def best(self) -> Article:
        # Pick the highest-authority, longest article as the representative.
        return max(self.articles, key=lambda a: (a.raw.authority, a.word_count))


@dataclass
class StoryCard:
    """A ranked, analyzed story ready for the brief."""
    cluster_id: str
    title: str
    url: str
    source: str
    region: str
    tags: list[str]
    tldr: str
    so_what: str
    key_claims: list[str]
    citations: list[str]
    hype_flag: str          # "low" | "medium" | "high"
    score: float
    also_covered_by: list[str] = field(default_factory=list)
    # Confidence / corroboration metadata
    corroboration_count: int = 0    # distinct source count in cluster
    source_kind_count: int = 0      # distinct source kinds (news/research/vendor/community)
    # Personalization
    relevance_score: float = 0.0    # 0.0–1.0 match against user's Watch List
    # Brief History callbacks
    history_refs: list[str] = field(default_factory=list)  # e.g. "Previously covered: 2026-09-03 — ..."


@dataclass
class Issue:
    date: str
    pack: str
    headline: str
    stories: list[StoryCard]
    rendered_markdown: str = ""
    rendered_html: str = ""
    built_at: str = field(default_factory=_now_iso)
