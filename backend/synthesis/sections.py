"""Route story clusters into PDB sections and pick candidates per section."""

from __future__ import annotations

import re
from collections import Counter

from .cluster import owners_of
from .models import Cluster

ORDER = ["threat", "ai", "science", "money", "scam", "myth"]
QUOTAS = {"threat": 3, "ai": 3, "science": 2, "money": 2, "scam": 1, "myth": 1}

_THREAT = re.compile(r"\b(cve-\d|zero-day|0-day|ransomware|malware|breach(ed)?|hack(ed|ers?)?|exploit(ed|s)?|"
                     r"vulnerabilit|backdoor|botnet|infostealer|ddos|spyware|data leak|stolen data|cyberattack)", re.I)
_SCAM = re.compile(r"\b(scam(s|mers?)?|fraud(sters?)?|impersonat|fake (app|site|job|recruiter|support|call)|"
                   r"phishing (text|sms|email)|smishing|romance|pig butchering|gift card)", re.I)
_MYTH_OK = re.compile(r"\b(ai|a\.i\.|deepfake|fake (video|image|photo|clip)|photo|video|image|viral|hoax|scam|"
                      r"space|nasa|moon|planet|science|scientist|tech|phone|app|internet|hack|robot|"
                      r"animal|shark|weather|earthquake)\b", re.I)
_MYTH_POLITICS = re.compile(r"\b(trump|biden|harris|vance|obama|election|democrat|republican|gop|congress|senate|"
                            r"labour|tory|tories|starmer|farage|reform uk|immigra|migrant|vote|abortion|gaza|israel|"
                            r"ukraine|russia|putin|netanyahu|pride|lgbt|trans|gender|woke|asylum|protest|flag|police|religio|church|"
                            r"muslim|islam|christian|jewish|abortion|gun|shooting|war|minister|mp|mayor|governor|president|"
                            r"march|marche[sd]|rally|rallies|demonstrat|riot)\b", re.I)


def section_of(c: Cluster) -> str | None:
    titles = " ".join(a.raw.title for a in c.articles)
    feed_sections = Counter(a.raw.section for a in c.articles if a.raw.section)
    base = feed_sections.most_common(1)[0][0] if feed_sections else "ai"
    if base == "myth":
        if _MYTH_POLITICS.search(titles) or not _MYTH_OK.search(titles):
            return None           # we only fact-check tech/science/scam myths — no politics
        return "myth"
    if _SCAM.search(titles):
        return "scam"
    if _THREAT.search(titles) and base in ("ai", "money", "threat", "scam"):
        return "threat"
    return base


def candidates(ranked: list[tuple[Cluster, float]], extra: int = 2) -> dict[str, list[Cluster]]:
    """Per section: the top clusters (quota + spares), preferring multi-owner stories."""
    out: dict[str, list[Cluster]] = {s: [] for s in ORDER}
    for c, _score in ranked:
        s = section_of(c)
        if s is None or len(out[s]) >= QUOTAS[s] + extra:
            continue
        # outside myth/science, a single-owner story needs a primary/official source to be considered
        if len(owners_of(c)) < 2 and s not in ("myth", "science", "scam"):
            if not any("primary" in a.raw.tags or "vendor" in a.raw.tags for a in c.articles):
                continue
        out[s].append(c)
    return out
