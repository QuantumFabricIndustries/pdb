"""User preferences loader — reads prefs.json from the project root.

prefs.json format:
{
  "persona": "founder",          // founder | dev | investor | researcher | general
  "watch_list": ["LLM", "RISC-V", "energy storage"]  // topics always surfaced
}

All fields are optional. Missing file → defaults used silently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("pdb.prefs")

PERSONAS = ("founder", "dev", "investor", "researcher", "general")

PERSONA_CONTEXT: dict[str, str] = {
    "founder": (
        "The reader is a technical founder building a startup. Focus on: "
        "competitive implications, build-vs-buy decisions, talent and hiring signals, "
        "market timing, and what this means for their product roadmap."
    ),
    "dev": (
        "The reader is a software engineer or ML practitioner. Focus on: "
        "APIs and tooling, implementation complexity, performance benchmarks, "
        "open-source availability, and what to actually try or watch out for."
    ),
    "investor": (
        "The reader is a technology investor. Focus on: "
        "market size signals, competitive moats, team and company credibility, "
        "and what this means for related companies in their portfolio."
    ),
    "researcher": (
        "The reader is an academic or applied researcher. Focus on: "
        "methodological novelty, reproducibility, benchmarks, open questions, "
        "and what papers, datasets, or codebases to follow up on."
    ),
    "general": "",
}


@dataclass
class Prefs:
    persona: str = "general"               # one of PERSONAS
    watch_list: list[str] = field(default_factory=list)  # lowercased topic keywords

    @property
    def persona_context(self) -> str:
        return PERSONA_CONTEXT.get(self.persona, "")

    def relevance(self, title: str, tags: list[str]) -> float:
        """Return a 0.0–1.0 relevance score vs. this user's watch list.

        1.0 = all watch-list terms matched; 0.0 = no watch list or no match.
        """
        if not self.watch_list:
            return 0.0
        combined = (title + " " + " ".join(tags)).lower()
        hits = sum(1 for term in self.watch_list if term in combined)
        return round(min(hits / len(self.watch_list), 1.0), 3)


_DEFAULT = Prefs()


def load_prefs(project_root: Path | None = None) -> Prefs:
    """Load prefs.json from project root. Returns defaults if absent or invalid."""
    root = project_root or Path(__file__).resolve().parents[2]
    p = root / "prefs.json"
    if not p.exists():
        return _DEFAULT
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        persona = data.get("persona", "general")
        if persona not in PERSONAS:
            log.warning("Unknown persona %r in prefs.json; using 'general'", persona)
            persona = "general"
        watch_list = [t.lower().strip() for t in data.get("watch_list", []) if t.strip()]
        prefs = Prefs(persona=persona, watch_list=watch_list)
        log.info("Loaded prefs: persona=%s watch_list=%s", prefs.persona, prefs.watch_list)
        return prefs
    except Exception as e:
        log.warning("Could not load prefs.json (%s); using defaults", e)
        return _DEFAULT
