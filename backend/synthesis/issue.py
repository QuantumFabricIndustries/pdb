"""Assemble analyzed stories into a daily PDB brief (markdown + HTML)."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .models import Issue, StoryCard


_HYPE_BADGE = {
    "low":    "🟢 Low",
    "medium": "🟡 Medium — verify before acting",
    "high":   "🔴 High — single source or PR language",
}

_HYPE_CLASS = {"low": "hype-low", "medium": "hype-med", "high": "hype-high"}


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _relevance_bar(score: float) -> str:
    """Simple text relevance indicator for markdown."""
    if score <= 0:
        return ""
    filled = round(score * 5)
    bar = "█" * filled + "░" * (5 - filled)
    return f" · **Watch List match:** `{bar}` {int(score * 100)}%"


def _md_card(s: StoryCard, n: int) -> str:
    also = f"\n  - _Also covered by: {', '.join(s.also_covered_by)}_" if s.also_covered_by else ""
    claims = "\n".join(f"  - {c}" for c in s.key_claims) or "  - (none extracted)"
    cites = "\n".join(f"  - {u}" for u in s.citations) or "  - (none)"

    # Confidence line
    kinds_label = f"{s.source_kind_count} source type{'s' if s.source_kind_count != 1 else ''}"
    confidence = f"**Confidence:** {s.corroboration_count} source{'s' if s.corroboration_count != 1 else ''} · {kinds_label}"

    # History callbacks
    history = ""
    if s.history_refs:
        history = "\n**Prior coverage:**\n" + "\n".join(f"  - _{r}_" for r in s.history_refs)

    relevance = _relevance_bar(s.relevance_score)

    return f"""### {n}. {s.title}

> **In brief:** {s.tldr}

**So what.** {s.so_what}

**Key claims:**
{claims}

**Sources:**
{cites}{also}
{history}

**Hype risk:** {_HYPE_BADGE.get(s.hype_flag, s.hype_flag)} · {confidence}{relevance} · **Score:** {s.score} · **Tags:** {', '.join(s.tags) or '—'}
"""


def build_markdown(issue: Issue) -> str:
    parts = [
        f"# {issue.headline}",
        f"_{issue.date} · PDB — Your Personal Daily Brief · pack: `{issue.pack}`_",
        "",
        "*Most people read the news. You receive a brief.*",
        "",
        "What happened, why it matters, and what to watch next — "
        "with linked sources, confidence signals, and analysis shaped around you.",
        "",
        "---",
        "",
    ]
    for i, s in enumerate(issue.stories, 1):
        parts.append(_md_card(s, i))
        parts.append("")
    parts.append("---")
    parts.append("PDB — Your Personal Daily Brief. Sources are linked; analysis is editorial.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _relevance_ring(score: float) -> str:
    """SVG ring showing watch list relevance."""
    if score <= 0:
        return ""
    pct = int(score * 100)
    # SVG circle: r=10, circumference ≈ 62.8
    circ = 62.83
    dash = round(circ * score, 1)
    return (
        f'<span class="rel-ring" title="Watch List match: {pct}%">'
        f'<svg width="28" height="28" viewBox="0 0 28 28">'
        f'<circle cx="14" cy="14" r="10" fill="none" stroke="#222831" stroke-width="3"/>'
        f'<circle cx="14" cy="14" r="10" fill="none" stroke="#7c9cff" stroke-width="3" '
        f'stroke-dasharray="{dash} {circ}" stroke-dashoffset="15.7" stroke-linecap="round" transform="rotate(-90 14 14)"/>'
        f'</svg><span class="rel-pct">{pct}%</span></span>'
    )


def _html_card(s: StoryCard, n: int) -> str:
    also = (
        f'<p class="also">Also covered by: {", ".join(html.escape(x) for x in s.also_covered_by)}</p>'
        if s.also_covered_by else ""
    )
    claims = "".join(f"<li>{html.escape(c)}</li>" for c in s.key_claims) or "<li>(none extracted)</li>"
    cites = "".join(
        f'<li><a href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(u)}</a></li>'
        for u in s.citations
    ) or "<li>(none)</li>"

    # Hype badge
    hype_cls = _HYPE_CLASS.get(s.hype_flag, "hype-low")
    hype_label = html.escape(_HYPE_BADGE.get(s.hype_flag, s.hype_flag))

    # Confidence flag
    kinds_label = f"{s.source_kind_count} source type{'s' if s.source_kind_count != 1 else ''}"
    confidence_html = (
        f'<span class="confidence" title="{s.corroboration_count} distinct sources · {kinds_label}">'
        f'📡 {s.corroboration_count} source{"s" if s.corroboration_count != 1 else ""} · {html.escape(kinds_label)}'
        f'</span>'
    )

    # Relevance ring
    ring = _relevance_ring(s.relevance_score)

    # History callbacks
    history_html = ""
    if s.history_refs:
        items = "".join(f"<li>{html.escape(r)}</li>" for r in s.history_refs)
        history_html = f'<div class="history"><strong>📅 Prior coverage</strong><ul>{items}</ul></div>'

    return f"""
  <article class="story">
    <div class="story-header">
      <h3>{n}. <a href="{html.escape(s.url)}" target="_blank" rel="noopener">{html.escape(s.title)}</a></h3>
      {ring}
    </div>
    <p class="inbrief"><strong>In brief:</strong> {html.escape(s.tldr)}</p>
    <div class="sowhat"><strong>So what.</strong> {html.escape(s.so_what)}</div>
    <h4>Key claims</h4><ul>{claims}</ul>
    <h4>Sources</h4><ul>{cites}</ul>
    {also}
    {history_html}
    <div class="meta">
      <span class="hype-badge {hype_cls}">Hype: {hype_label}</span>
      {confidence_html}
      <span class="score">Score: {s.score}</span>
      <span class="tags">Tags: {html.escape(', '.join(s.tags) or '—')}</span>
    </div>
  </article>"""


_CSS = """
:root{
  --bg:#0b0d10;--fg:#e7e9ea;--muted:#9aa4ad;--accent:#7c9cff;
  --card:#14181d;--border:#222831;
  --hype-low:#22c55e;--hype-med:#f59e0b;--hype-high:#ef4444;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,Segoe UI,sans-serif}
.wrap{max-width:780px;margin:0 auto;padding:32px 20px 80px}
header h1{font-size:28px;margin:0 0 2px}
header .tagline{color:var(--accent);font-style:italic;margin:0 0 4px;font-size:15px}
header .sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.story{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px 22px;margin:18px 0}
.story-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.story-header h3{margin:0;font-size:19px;flex:1}
.story-header h3 a{color:var(--accent);text-decoration:none}
.story-header h3 a:hover{text-decoration:underline}
.rel-ring{display:flex;align-items:center;gap:4px;flex-shrink:0}
.rel-pct{font-size:11px;color:var(--accent);font-weight:600}
.inbrief{background:#1a2128;border-left:3px solid var(--accent);padding:10px 14px;border-radius:6px;margin:10px 0}
.sowhat{margin:12px 0;line-height:1.7}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:18px 0 6px}
ul{margin:0 0 10px;padding-left:20px}
li{margin:3px 0}
a{color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;color:var(--muted);font-size:12px;border-top:1px solid var(--border);padding-top:10px;margin-top:14px}
.hype-badge{padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;color:#0b0d10}
.hype-low{background:var(--hype-low)}
.hype-med{background:var(--hype-med)}
.hype-high{background:var(--hype-high)}
.confidence{color:var(--muted);font-size:12px}
.score{color:var(--muted)}
.tags{color:var(--muted)}
.also{color:var(--muted);font-size:13px;font-style:italic;margin:4px 0}
.history{background:#0f1318;border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px}
.history ul{margin:4px 0 0;padding-left:16px}
.history li{color:var(--muted);font-style:italic}
footer{color:var(--muted);font-size:13px;margin-top:40px;border-top:1px solid var(--border);padding-top:16px}
"""


def build_html(issue: Issue) -> str:
    cards = "\n".join(_html_card(s, i) for i, s in enumerate(issue.stories, 1))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(issue.headline)}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>{html.escape(issue.headline)}</h1>
  <p class="tagline">Most people read the news. You receive a brief.</p>
  <div class="sub">{html.escape(issue.date)} · PDB — Your Personal Daily Brief · pack: <code>{html.escape(issue.pack)}</code></div>
  <p>What happened, why it matters, and what to watch next — with linked sources, confidence signals, and analysis shaped around you.</p>
</header>
{cards}
<footer>PDB — Your Personal Daily Brief. Sources are linked; analysis is editorial. Built {html.escape(issue.built_at)}.</footer>
</div></body></html>"""


def assemble(date: str, pack: str, stories: list[StoryCard]) -> Issue:
    issue = Issue(
        date=date,
        pack=pack,
        headline=f"PDB — {date}",
        stories=stories,
    )
    issue.rendered_markdown = build_markdown(issue)
    issue.rendered_html = build_html(issue)
    return issue
