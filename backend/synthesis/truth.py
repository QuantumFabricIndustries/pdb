"""Truth Score — 0 to 100, computed ONLY from the Fact-Checker's evidence.

No model opinion goes into the number. Every point is explainable and shown
to readers on the story page ("How we scored this").

  Independent owners reporting it ..... up to 30
  Primary / official evidence ......... up to 25
  Claims verified in their sources .... up to 25
  Claims confirmed by 2+ owners ....... up to 10
  Track record of the outlets ......... up to 10
  Penalties: writer errors caught, high hype
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .verify import Report, Source

LABELS = [(75, "Confirmed"), (55, "Well-sourced"), (35, "Developing"), (0, "Unverified")]  # < 35 is never published

LABEL_HELP = {
    "Confirmed": "What this brief reports is backed by multiple independent outlets and official evidence. (If we report that someone claims something, the claim being made is what's confirmed.)",
    "Well-sourced": "Solid reporting from independent outlets; limited official evidence so far.",
    "Developing": "Real reporting, but few independent sources yet. Details may change.",
    "Unverified": "Thin evidence. Treat as a claim, not a fact.",
    "Disputed": "Sources disagree on key facts. See the notes.",
}


@dataclass
class Score:
    total: int
    label: str
    parts: list[tuple[str, int, int, str]] = field(default_factory=list)  # (name, points, max, why)


def _independent_points(n: int) -> int:
    return {0: 0, 1: 0, 2: 15, 3: 25}.get(n, 30)


def compute(report: Report, sources: list[Source], hype: str = "low", disputed: bool = False) -> Score:
    owners = sorted({s.owner for s in sources})
    n_owners = len(owners)
    parts: list[tuple[str, int, int, str]] = []

    ind = _independent_points(n_owners)
    parts.append(("Independent outlets", ind, 30,
                  f"{n_owners} independent owner{'s' if n_owners != 1 else ''}: {', '.join(owners)}"))

    types = {p["type"] for p in report.primary if p["verified"]}
    if any(t.startswith("CISA KEV") or t == "official record" for t in types):
        t = next(t for t in types if t.startswith("CISA KEV") or t == "official record")
        prim, why = 25, f"Official record matching this story ({t})"
    elif "subject's own statement" in types:
        prim, why = 15, "Statement from the organization involved (not independent)"
    elif "related official record" in types:
        prim, why = 12, "Related official record (on the same subject, not this specific event)"
    else:
        prim, why = 0, "No primary or official source found for this specific story yet"
    parts.append(("Primary evidence", prim, 25, why))

    total_claims = len(report.claims) or 1
    ver = report.verified_claims
    vpts = round(25 * len(ver) / total_claims)
    parts.append(("Claims verified", vpts, 25, f"{len(ver)} of {len(report.claims)} claims matched their cited source"))

    corr = [c for c in ver if c.corroborated_by]
    cpts = round(10 * len(corr) / total_claims)
    parts.append(("Claims confirmed elsewhere", cpts, 10,
                  f"{len(corr)} claim{'s' if len(corr) != 1 else ''} also supported by another independent outlet"))

    by_owner: dict[str, float] = {}
    for s in sources:
        by_owner[s.owner] = max(by_owner.get(s.owner, 0.0), s.authority)
    rel = round(10 * (sum(by_owner.values()) / len(by_owner))) if by_owner else 0
    parts.append(("Outlet track record", rel, 10, "Average reliability rating of the outlets"))

    penalty = 0
    bad = [c for c in report.claims if c.status != "verified"]
    if bad:
        penalty += 5 * len(bad)
        parts.append(("Writer errors caught", -5 * len(bad), 0,
                      f"{len(bad)} draft claim(s) failed checking and were removed"))
    if hype == "high":
        penalty += 5
        parts.append(("Hype", -5, 0, "Promotional or sensational framing in coverage"))

    total = max(0, min(100, ind + prim + vpts + cpts + rel - penalty))
    label = next(name for cut, name in LABELS if total >= cut)
    if disputed:
        label = "Disputed"
    return Score(total=total, label=label, parts=parts)
