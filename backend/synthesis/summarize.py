"""LLM analysis pipeline: TL;DR + So What + key claims + citations + hype flag.

Uses a multi-provider fallback chain (Groq → Gemini → Ollama → stub) so the
pipeline produces real analysis with any free provider, and always works
even with no keys and no local model installed.

Supports persona-aware "So What for You" analysis when a Prefs object is passed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from .domains import owner as _owner, root_domain as _root_domain
from .models import Article, Cluster, StoryCard
from .providers import ProviderConfig, chat, get_active_provider

log = logging.getLogger("pdb.summarize")


# --- stub (no provider available) -------------------------------------------

def _stub_tldr(a: Article) -> str:
    return a.raw.summary[:280] or a.raw.title


def _stub_so_what(a: Article) -> str:
    return (
        "Why it matters: this story is worth attention because it touches "
        f"{', '.join(a.raw.tags[:3]) or 'a notable area of technology'}. "
        "The reporting is primarily descriptive; the practical implications "
        "for builders and decision-makers are not spelled out in the source. "
        "Watch for follow-up reporting that clarifies scope, adoption, and "
        "any competing responses before acting on it."
    )


def _stub_claims(a: Article) -> list[str]:
    sents = [s.strip() for s in a.excerpt.replace("…", " ").split(".") if len(s.strip()) > 40]
    return sents[:3] or [a.raw.title]


def _stub_hype(a: Article) -> str:
    pr = any(w in a.raw.title.lower() for w in ("announces", "launches", "unveils", "raises"))
    single = a.raw.tags.count("vendor") > 0
    if pr and single:
        return "high"
    if pr:
        return "medium"
    return "low"


# --- so_what post-processing -------------------------------------------------

_BULLET_START = re.compile(r"^\s*[-•*]\s+")
_NUMBERED_START = re.compile(r"^\s*\d+\.\s+")


def _normalize_so_what(text: str) -> str:
    """Ensure So What leads with prose, not a bullet list.

    If the LLM returned bullets before the prose paragraph, restructure so
    the prose comes first and the bullet action list follows as a section.
    """
    if not text:
        return text

    lines = text.strip().splitlines()
    prose_lines: list[str] = []
    bullet_lines: list[str] = []
    in_bullets = False

    for line in lines:
        is_bullet = bool(_BULLET_START.match(line) or _NUMBERED_START.match(line))
        if is_bullet:
            in_bullets = True
        if in_bullets and not is_bullet and line.strip():
            # Prose resumed after bullets — treat this paragraph as the main body
            # and move it before the bullets.
            prose_lines.append(line)
        elif is_bullet:
            bullet_lines.append(line)
        else:
            prose_lines.append(line)

    # If prose came AFTER bullets, reorder: prose first, then "Next actions:" header + bullets
    if bullet_lines and prose_lines:
        # Check if bullets appeared before any prose (bad LLM output order)
        first_bullet_idx = next(
            (i for i, l in enumerate(lines) if _BULLET_START.match(l) or _NUMBERED_START.match(l)),
            len(lines),
        )
        first_prose_idx = next(
            (i for i, l in enumerate(lines) if l.strip() and not _BULLET_START.match(l) and not _NUMBERED_START.match(l)),
            len(lines),
        )
        if first_bullet_idx < first_prose_idx:
            # Bullets came first — reorder
            prose_block = "\n".join(l for l in prose_lines if l.strip())
            bullet_block = "\n".join(bullet_lines)
            return f"{prose_block}\n\n**Next actions:**\n{bullet_block}"

    return text.strip()


# --- source dedup helpers ----------------------------------------------------



def _unique_domains(urls: list[str]) -> int:
    """Count distinct root domains in a list of URLs."""
    return len({_root_domain(u) for u in urls if u})


def _source_kinds(c: Cluster) -> set[str]:
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


def _unique_source_domains(c: Cluster) -> int:
    """Count distinct root domains across all articles in a cluster."""
    return len({_owner(a.raw.url) for a in c.articles if a.raw.url})


# --- LLM analysis ------------------------------------------------------------

_TLDR_SYS = (
    "You are a senior technology analyst writing for technically literate readers. "
    "Summarize the story in exactly 2 plain sentences: what happened, and the single "
    "most important consequence. No marketing language, no hedging, no filler."
)

_ANALYSIS_SYS_BASE = (
    "You are a senior technology analyst. Given a story and its source text, write a "
    "300-500 word 'So What' analysis for engineers, founders, and technical PMs. "
    "Structure: write 3-4 prose paragraphs first covering (1) why this matters, "
    "(2) what precedent or shift it signals, (3) what to watch next. "
    "Then end with a short bullet list under the header 'Next actions:'. "
    "Do NOT start with bullets. Start with a prose paragraph. "
    "Be specific and concrete. Cite the source by name. Do not speculate "
    "beyond what the source supports; flag uncertainty explicitly. "
    "Return JSON with keys: so_what (string), "
    "key_claims (array of 2-4 short factual strings), hype_flag (low|medium|high)."
)

_PERSONA_INTRO = (
    "You are a senior technology analyst writing a personalized brief. {persona_context} "
    "Given a story and its source text, write a 300-500 word 'So What for You' analysis "
    "tailored to this reader's perspective. "
    "Structure: write 3-4 prose paragraphs first covering (1) why this matters to them "
    "specifically, (2) what precedent or shift it signals, (3) concrete implications. "
    "Then end with a short bullet list under the header 'Next actions:'. "
    "Do NOT start with bullets. Start with a prose paragraph. "
    "If the story has no direct relevance to this reader's role, say so in one sentence, "
    "then explain the 2nd-order implications that may still matter to them. "
    "Cite the source by name. Flag uncertainty explicitly. "
    "Return JSON with keys: so_what (string), "
    "key_claims (array of 2-4 short factual strings), hype_flag (low|medium|high)."
)

_BRIEF_MODE_SUFFIX = (
    " IMPORTANT: This is brief mode. Keep so_what to 3 concise action bullets only "
    "(no prose paragraphs). Each bullet: one tight sentence, no filler. "
    "Total so_what must be under 150 words."
)


def _build_analysis_sys(persona_context: str, brief_mode: bool = False) -> str:
    if persona_context:
        base = _PERSONA_INTRO.format(persona_context=persona_context)
    else:
        base = _ANALYSIS_SYS_BASE
    return base + _BRIEF_MODE_SUFFIX if brief_mode else base


def _llm_tldr(provider: ProviderConfig, a: Article) -> str:
    user = f"TITLE: {a.raw.title}\nSOURCE: {a.raw.source}\nEXCERPT: {a.excerpt}\nBODY:\n{a.text[:6000]}"
    return chat(provider, provider.tldr_model, _TLDR_SYS, user).strip()


def _llm_analysis(provider: ProviderConfig, a: Article, persona_context: str = "", brief_mode: bool = False) -> dict[str, Any]:
    sys_prompt = _build_analysis_sys(persona_context, brief_mode=brief_mode)
    user = (
        f"TITLE: {a.raw.title}\nSOURCE: {a.raw.source} ({a.raw.region})\n"
        f"TAGS: {', '.join(a.raw.tags)}\nEXCERPT: {a.excerpt}\nBODY:\n{a.text[:8000]}"
    )
    raw = chat(provider, provider.analysis_model, sys_prompt, user, json_mode=True)
    try:
        return json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                pass
        return {"so_what": raw, "key_claims": [], "hype_flag": "low"}


# --- public API --------------------------------------------------------------

_provider_cache: ProviderConfig | None = None
_provider_checked: bool = False


def _get_provider() -> ProviderConfig | None:
    global _provider_cache, _provider_checked
    if not _provider_checked:
        _provider_cache = get_active_provider()
        _provider_checked = True
    return _provider_cache


def analyze_cluster(c: Cluster, score: float, prefs=None, brief_mode: bool = False) -> StoryCard:
    """Build a StoryCard from a ranked Cluster.

    Args:
        c:          The cluster of articles.
        score:      Pre-computed ranking score.
        prefs:      Optional Prefs object for persona + watch list relevance.
        brief_mode: If True, cap So What to ~150 words (3 tight bullets).
    """
    a = c.best
    citations = list(dict.fromkeys([art.raw.url for art in c.articles]))[:6]
    also = [art.raw.source for art in c.articles if art.raw.source != a.raw.source]

    # Corroboration metadata — deduplicated by root domain
    corroboration_count = _unique_source_domains(c)
    kinds = _source_kinds(c)
    source_kind_count = len(kinds)

    # Persona context
    persona_context = prefs.persona_context if prefs else ""

    provider = _get_provider()
    if provider is not None:
        try:
            tldr = _llm_tldr(provider, a)
            # Pause between calls to avoid exhausting Groq free-tier 8k TPM window
            time.sleep(20)
            analysis = _llm_analysis(provider, a, persona_context=persona_context, brief_mode=brief_mode)
            so_what = _normalize_so_what(analysis.get("so_what", "").strip())
            key_claims = analysis.get("key_claims", []) or []
            hype = (analysis.get("hype_flag") or "low").strip().lower()
            if hype not in ("low", "medium", "high"):
                hype = "low"
            if not so_what:
                so_what = _stub_so_what(a)
        except Exception as e:
            log.warning("LLM call failed (%s); using stub for %s", e, a.raw.title)
            tldr, so_what, key_claims, hype = _stub_tldr(a), _stub_so_what(a), _stub_claims(a), _stub_hype(a)
    else:
        tldr, so_what, key_claims, hype = _stub_tldr(a), _stub_so_what(a), _stub_claims(a), _stub_hype(a)

    # Watch list relevance score
    relevance = prefs.relevance(a.raw.title, list(c.tags)) if prefs else 0.0

    return StoryCard(
        cluster_id=c.id,
        title=a.raw.title,
        url=a.raw.url,
        source=a.raw.source,
        region=a.raw.region,
        tags=sorted(c.tags),
        tldr=tldr,
        so_what=so_what,
        key_claims=key_claims,
        citations=citations,
        hype_flag=hype,
        score=score,
        also_covered_by=also,
        corroboration_count=corroboration_count,
        source_kind_count=source_kind_count,
        relevance_score=relevance,
    )
