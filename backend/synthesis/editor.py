"""Editor-in-Chief — the final gate before anything is published.

Runs on a DIFFERENT model family (Gemini) than the Writer (Groq), because a
model checking its own work tends to miss its own mistakes.

Order of operations:
  1. Hard rules in code (can't be talked around):
       - drop claims that failed the Fact-Checker
       - numbers in the prose must exist in the sources
       - no long word-for-word copying
  2. AI editorial review: overclaiming, missing attribution, sources that
     contradict each other, advice we don't give (financial/medical).
     The editor may FIX wording; fixes are re-checked by the same hard rules.
  3. Verdict: PUBLISH, HOLD (not ready — reconsidered on a later run) or KILL.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .providers import ProviderConfig, chat
from .verify import Report, Source, copied_runs, prose_number_problems
from .writer import parse_json

log = logging.getLogger("pdb.editor")

MIN_VERIFIED_CLAIMS = 2
PUBLISH_BAR = {"default": 35}   # never publish a story rated "Unverified"
_PROSE_FIELDS = ("headline", "in_brief", "so_what", "what_to_do")

_SYSTEM = """You are the Editor-in-Chief of PDB — Public Daily Brief. Accuracy is the entire brand.
You receive a draft story, the claims our Fact-Checker already verified, and the source texts.
Check the draft prose (headline, in_brief, so_what, what_to_do) against the sources:
1. Does any sentence state something the sources do not support, or state as fact what sources only report as a claim?
2. Are claims by interested parties attributed (hackers claim / company says / officials allege)?
3. Do the sources contradict EACH OTHER on a key fact (numbers, who, what happened)? If so, the story is disputed.
4. Any investment, legal or medical advice, or hype language? Remove it.
5. Is the headline accurate and not clickbait?

If fixes are needed, rewrite only the fields that need it, in your own words, using only facts from the sources.
Return JSON only:
{"verdict": "PUBLISH" | "FIX" | "KILL",
 "problems": ["short description of each problem found"],
 "fixed": {"headline": "...", "in_brief": "...", "so_what": "...", "what_to_do": "..."},
 "disputed": false,
 "dispute_note": "if disputed: which facts the sources disagree on, else empty"}
Use KILL only if the story is fundamentally unsupported or not news. "fixed" may omit unchanged fields."""


@dataclass
class Decision:
    verdict: str                      # PUBLISH | HOLD | KILL
    draft: dict
    reasons: list[str] = field(default_factory=list)
    edits: list[str] = field(default_factory=list)
    disputed: bool = False
    dispute_note: str = ""
    model: str = ""


_LOST_APOS = re.compile(r"\b([A-Za-z]+) s\b")


def restore_apostrophes(text: str, sources: list[Source]) -> str:
    """Some models drop apostrophes ("Rubik s Cube"). Restore when the sources spell it "Rubik's"."""
    joined = " ".join(s.text for s in sources).lower().replace("\u2019", "'")

    def fix(m: re.Match) -> str:
        return f"{m.group(1)}'s" if f"{m.group(1).lower()}'s" in joined else m.group(0)
    return _LOST_APOS.sub(fix, text)


def hard_problems(draft: dict, sources: list[Source]) -> list[str]:
    prose = " ".join(str(draft.get(k, "")) for k in _PROSE_FIELDS)
    probs = prose_number_problems(prose, sources)
    runs = copied_runs(prose, [s.text for s in sources])
    if runs:
        probs.append(f"copied {len(runs)} long word-for-word run(s) from a source, e.g. \"{runs[0]}\"")
    return probs


def _editor_prompt(draft: dict, report: Report, sources: list[Source], problems: list[str]) -> str:
    verified = [{"claim": c.claim, "source": c.source} for c in report.verified_claims]
    body = {k: draft.get(k, "") for k in _PROSE_FIELDS}
    lines = ["DRAFT:", json.dumps(body, ensure_ascii=False, indent=1),
             "", "VERIFIED CLAIMS:", json.dumps(verified, ensure_ascii=False),
             "", "PROBLEMS FOUND BY AUTOMATED CHECKS (must be fixed): " + ("; ".join(problems) or "none"), "", "SOURCES:"]
    for s in sources:
        lines += [f"[{s.n}] {s.outlet} (owner: {s.owner})", s.text[:2500], ""]
    return "\n".join(lines)


def review(provider: ProviderConfig | None, section: str, draft: dict, report: Report,
           sources: list[Source], truth_total: int, backup: ProviderConfig | None = None) -> Decision:
    d = Decision(verdict="PUBLISH", draft=dict(draft))

    # 1. Hard rule: only verified claims survive.
    failed = [c for c in report.claims if c.status != "verified"]
    if failed:
        d.edits.append(f"removed {len(failed)} claim(s) that failed fact-checking")
    d.draft["claims"] = [c for c in report.claims if c.status == "verified"]
    if len(d.draft["claims"]) < MIN_VERIFIED_CLAIMS:
        d.verdict = "HOLD"
        d.reasons.append(f"only {len(d.draft['claims'])} verified claim(s); need {MIN_VERIFIED_CLAIMS}")
        return d

    problems = hard_problems(d.draft, sources)

    # 2. AI editorial review (independent model).
    if provider is None:
        d.reasons.append("no independent editor available")
        if problems:
            d.verdict = "HOLD"
            d.reasons += problems
            return d
    else:
        ed = None
        for p in [x for x in (provider, backup) if x is not None]:
            try:
                raw = chat(p, p.analysis_model, _SYSTEM,
                           _editor_prompt(d.draft, report, sources, problems), json_mode=True, max_tokens=3000,
                           max_retries=3)
                ed = parse_json(raw)
                d.model = f"{p.name}/{p.analysis_model}"
                break
            except Exception as e:
                log.warning("editor %s failed (%s)", p.name, type(e).__name__)
        if ed is None:
            d.verdict = "HOLD"
            d.reasons.append("editor unavailable")
            return d
        verdict = str(ed.get("verdict", "PUBLISH")).upper()
        d.disputed = bool(ed.get("disputed"))
        d.dispute_note = str(ed.get("dispute_note") or "")
        eprobs = [str(p) for p in ed.get("problems") or []]
        if verdict == "KILL":
            d.verdict = "KILL"
            d.reasons += eprobs or ["killed by editor"]
            return d
        fixed = ed.get("fixed") or {}
        if verdict == "FIX" or problems:
            for k in _PROSE_FIELDS:
                if isinstance(fixed.get(k), str) and fixed[k].strip() and fixed[k].strip() != str(d.draft.get(k, "")).strip():
                    d.draft[k] = restore_apostrophes(fixed[k].strip(), sources)
                    d.edits.append(f"editor rewrote {k}")
            d.edits += [f"editor: {p}" for p in eprobs]

    # 3. Re-check hard rules after any edits.
    remaining = hard_problems(d.draft, sources)
    if remaining:
        d.verdict = "HOLD"
        d.reasons += remaining
        return d

    bar = PUBLISH_BAR.get(section, PUBLISH_BAR["default"])
    if truth_total < bar:
        d.verdict = "HOLD"
        d.reasons.append(f"truth score {truth_total} below publish bar {bar}")
    return d
