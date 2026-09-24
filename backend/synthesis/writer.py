"""Writer — drafts a story dossier from the source articles (Groq).

The Writer may only use facts in the numbered sources, must write in its own
words, and must back every claim with an exact quote + source number so the
Fact-Checker can verify it mechanically.
"""

from __future__ import annotations

import json
import logging

from .domains import owner
from .models import Cluster
from .providers import ProviderConfig, chat
from .verify import Source

log = logging.getLogger("pdb.writer")

PROMPT_CHARS_PER_SOURCE = 3000

SECTION_NAMES = {
    "threat": "Threat Watch", "ai": "AI & Tech", "science": "Science & Space",
    "money": "Money & Markets", "scam": "Scam Alert", "myth": "Myth Busted",
}

_SECTION_RULES = {
    "threat": "Fill what_to_do with 1-3 short, concrete steps a normal person or IT admin can take (patch, check, reset). "
              "Name affected products/versions only if the sources do.",
    "scam": "Fill what_to_do with 2-3 plain-language steps to avoid or recover from this scam.",
    "money": "Never give investment advice or price predictions. what_to_do must be empty.",
    "myth": "Explain what the viral claim was, what is actually true, and how it was checked. "
            "what_to_do: one line on how readers can spot this kind of claim.",
}

_SYSTEM = """You are the Writer for PDB — Public Daily Brief, a news service whose whole brand is accuracy.
Write a short, neutral story dossier using ONLY facts stated in the numbered sources.

Hard rules:
- Use your own words. Never copy more than 8 consecutive words from a source outside the "quote" fields.
- Every number, name and date you write must appear in the sources.
- Attribute contested or self-interested statements ("the hackers claim", "the company says", "police allege").
  Do not present a claim as fact when the sources only report it as a claim.
- No hype words (shocking, massive, game-changing, bombshell). No speculation beyond the sources.
- claims: 3 to 5 key factual claims. For each, give the source number and a "quote" that is an EXACT
  sentence or phrase copied character-for-character from that source proving the claim.
- hype_flag: "high" if coverage is promotional/sensational or rests on one self-interested party, "medium" if partly, else "low".

Return JSON only:
{"headline": "neutral headline, max 90 chars",
 "in_brief": "exactly 2 sentences: what happened, and why it matters",
 "so_what": "120-180 words: why it matters, context, what to watch next",
 "what_to_do": "string, may be empty",
 "claims": [{"claim": "...", "source": 1, "quote": "..."}],
 "hype_flag": "low|medium|high",
 "hype_reason": "one short phrase"}"""


def pick_sources(c: Cluster, max_sources: int = 5) -> list[Source]:
    """One article per independent owner (best-extracted, most authoritative), strongest first."""
    best: dict[str, object] = {}
    for a in c.articles:
        o = owner(a.raw.url)
        cur = best.get(o)
        key = (a.extracted_ok, a.raw.authority, a.word_count)
        if cur is None or key > (cur.extracted_ok, cur.raw.authority, cur.word_count):
            best[o] = a
    ordered = sorted(best.items(), key=lambda kv: (kv[1].extracted_ok, kv[1].raw.authority), reverse=True)
    sources = []
    for i, (o, a) in enumerate(ordered[:max_sources], 1):
        tags = set(a.raw.tags)
        kind = next((k for k in ("primary", "vendor", "factcheck", "research", "community") if k in tags), "news")
        text = a.text if len(a.text) >= len(a.raw.summary) else a.raw.summary
        sources.append(Source(n=i, outlet=a.raw.source, owner=o, url=a.raw.url, published=a.raw.published,
                              text=f"{a.raw.title}. {text}", authority=a.raw.authority, kind=kind))
    return sources


def _prompt(section: str, sources: list[Source]) -> str:
    rules = _SECTION_RULES.get(section, "what_to_do may be empty unless readers can act on this story.")
    parts = [f"SECTION: {SECTION_NAMES.get(section, section)}. {rules}", ""]
    for s in sources:
        parts.append(f"[{s.n}] {s.outlet} (owner: {s.owner}) — published {s.published or 'unknown'}")
        parts.append(s.text[:PROMPT_CHARS_PER_SOURCE])
        parts.append("")
    return "\n".join(parts)


def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        a, b = raw.find("{"), raw.rfind("}")
        if a != -1 and b > a:
            return json.loads(raw[a:b + 1])
        raise


def write(provider: ProviderConfig, section: str, sources: list[Source]) -> dict:
    raw = chat(provider, provider.analysis_model, _SYSTEM, _prompt(section, sources), json_mode=True, max_tokens=4000)
    draft = parse_json(raw)
    draft.setdefault("what_to_do", "")
    draft["hype_flag"] = str(draft.get("hype_flag", "low")).lower()
    if draft["hype_flag"] not in ("low", "medium", "high"):
        draft["hype_flag"] = "medium"
    if section == "money":
        draft["what_to_do"] = ""
    return draft
