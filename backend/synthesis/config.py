"""Source packs and runtime configuration for Synthesis.

A source pack is a named collection of feeds/feeds with an authority weight.
Authority is a 0.0–1.0 heuristic: how much we trust the source's editorial signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Feed:
    name: str
    url: str
    authority: float = 0.7          # 0–1 editorial trust
    region: str = "US"
    kind: str = "rss"               # rss | atom | json
    tags: list[str] = field(default_factory=list)
    section: str = ""               # default PDB section for items from this feed


@dataclass
class SourcePack:
    name: str
    description: str
    feeds: list[Feed]


AI_SOFTWARE = SourcePack(
    name="ai-software",
    description="Artificial intelligence, ML research, software engineering, and platforms.",
    feeds=[
        Feed("Hacker News", "https://hnrss.org/frontpage", authority=0.6, tags=["community", "software", "ai"]),
        Feed("Hacker News — AI", "https://hnrss.org/newest?q=AI+OR+LLM+OR+GPT+OR+model", authority=0.55, tags=["ai"]),
        Feed("Ars Technica AI", "https://feeds.arstechnica.com/arstechnica/index", authority=0.8, tags=["ai", "tech"]),
        Feed("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", authority=0.7, tags=["ai", "business"]),
        Feed("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", authority=0.7, tags=["ai", "business"]),
        Feed("MIT Tech Review", "https://www.technologyreview.com/feed/", authority=0.85, tags=["tech", "science"]),
        Feed("The Verge", "https://www.theverge.com/rss/index.xml", authority=0.75, tags=["tech"]),
        Feed("arXiv cs.AI", "http://export.arxiv.org/rss/cs.AI", authority=0.9, tags=["research", "ai"], kind="rss"),
        Feed("arXiv cs.LG", "http://export.arxiv.org/rss/cs.LG", authority=0.9, tags=["research", "ml"], kind="rss"),
        Feed("Google AI Blog", "https://blog.google/technology/ai/rss/", authority=0.8, tags=["ai", "vendor"]),
        Feed("OpenAI", "https://openai.com/blog/rss.xml", authority=0.75, tags=["ai", "vendor"]),
        Feed("DeepMind Blog", "https://deepmind.google/blog/rss.xml", authority=0.8, tags=["ai", "vendor"]),
        Feed("r/MachineLearning", "https://www.reddit.com/r/MachineLearning/.rss", authority=0.5, tags=["community", "ml"]),
        Feed("Simon Willison", "https://simonwillison.net/atom/everything/", authority=0.7, tags=["ai", "software", "practitioner"]),
        Feed("The Verge — AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", authority=0.75, tags=["ai", "tech"]),
    ],
)


# ---------------------------------------------------------------------------
# PDB — Public Daily Brief: broad, popular fields, many independent owners.
# Section keys: threat | ai | science | money | scam | myth
# Feeds verified reachable 2026-09-24. arXiv excluded: lone papers never
# corroborate and drown the public brief.
# ---------------------------------------------------------------------------

def _f(name, url, authority, section, *tags, region="US"):
    return Feed(name, url, authority=authority, region=region, tags=list(tags), section=section)


PUBLIC = SourcePack(
    name="public",
    description="PDB — Public Daily Brief: tech, threats, AI, science, money, scams, myths.",
    feeds=[
        # Threat Watch
        _f("BleepingComputer", "https://www.bleepingcomputer.com/feed/", 0.8, "threat", "security", "news"),
        _f("The Record", "https://therecord.media/feed", 0.85, "threat", "security", "news"),
        _f("SecurityWeek", "https://www.securityweek.com/feed/", 0.8, "threat", "security", "news"),
        _f("Krebs on Security", "https://krebsonsecurity.com/feed/", 0.85, "threat", "security", "news"),
        _f("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 0.7, "threat", "security", "news"),
        _f("Dark Reading", "https://www.darkreading.com/rss.xml", 0.75, "threat", "security", "news"),
        _f("Help Net Security", "https://www.helpnetsecurity.com/feed/", 0.7, "threat", "security", "news"),
        _f("The Register — Security", "https://www.theregister.com/security/headlines.atom", 0.75, "threat", "security", "news", region="UK"),
        _f("Malwarebytes Labs", "https://www.malwarebytes.com/blog/feed/index.xml", 0.7, "scam", "security", "vendor"),
        _f("ESET WeLiveSecurity", "https://www.welivesecurity.com/en/rss/feed/", 0.7, "scam", "security", "vendor"),
        _f("Kaspersky Daily", "https://www.kaspersky.com/blog/feed/", 0.65, "scam", "security", "vendor"),
        # AI & Tech
        _f("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", 0.85, "ai", "tech", "news"),
        _f("The Verge", "https://www.theverge.com/rss/index.xml", 0.75, "ai", "tech", "news"),
        _f("TechCrunch", "https://techcrunch.com/feed/", 0.7, "ai", "tech", "news"),
        _f("Wired", "https://www.wired.com/feed/rss", 0.8, "ai", "tech", "news"),
        _f("Engadget", "https://www.engadget.com/rss.xml", 0.7, "ai", "tech", "news"),
        _f("404 Media", "https://www.404media.co/rss/", 0.8, "ai", "tech", "news"),
        _f("The Register", "https://www.theregister.com/headlines.atom", 0.75, "ai", "tech", "news", region="UK"),
        _f("ZDNET", "https://www.zdnet.com/news/rss.xml", 0.65, "ai", "tech", "news"),
        _f("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", 0.85, "ai", "tech", "news", region="UK"),
        _f("Guardian Technology", "https://www.theguardian.com/technology/rss", 0.8, "ai", "tech", "news", region="UK"),
        _f("NPR Technology", "https://feeds.npr.org/1019/rss.xml", 0.85, "ai", "tech", "news"),
        _f("CNBC Tech", "https://www.cnbc.com/id/19854910/device/rss/rss.html", 0.75, "ai", "tech", "news"),
        _f("MIT Tech Review", "https://www.technologyreview.com/feed/", 0.85, "ai", "tech", "news"),
        _f("Hacker News", "https://hnrss.org/frontpage", 0.6, "ai", "community"),
        _f("OpenAI", "https://openai.com/news/rss.xml", 0.75, "ai", "ai", "vendor"),
        _f("Google AI Blog", "https://blog.google/technology/ai/rss/", 0.75, "ai", "ai", "vendor"),
        # Science & Space
        _f("Nature", "https://www.nature.com/nature.rss", 0.95, "science", "science", "research"),
        _f("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml", 0.7, "science", "science", "news"),
        _f("Phys.org", "https://phys.org/rss-feed/", 0.7, "science", "science", "news"),
        _f("NASA", "https://www.nasa.gov/news-release/feed/", 0.9, "science", "science", "primary"),
        # Money & Markets
        _f("CNBC Business", "https://www.cnbc.com/id/10001147/device/rss/rss.html", 0.75, "money", "business", "news"),
        _f("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", 0.85, "money", "business", "news", region="UK"),
        _f("Guardian Business", "https://www.theguardian.com/business/rss", 0.8, "money", "business", "news", region="UK"),
        _f("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", 0.65, "money", "crypto", "news"),
        _f("Decrypt", "https://decrypt.co/feed", 0.6, "money", "crypto", "news"),
        # Myth Busted (fact-checkers; filtered to tech/science/scam topics in sections.py)
        _f("Snopes", "https://www.snopes.com/feed/", 0.8, "myth", "factcheck"),
        _f("Full Fact", "https://fullfact.org/feed/", 0.85, "myth", "factcheck", region="UK"),
        _f("Lead Stories", "https://leadstories.com/atom.xml", 0.75, "myth", "factcheck"),
        _f("FactCheck.org", "https://www.factcheck.org/feed/", 0.85, "myth", "factcheck"),
    ],
)


PACKS: dict[str, SourcePack] = {
    "ai-software": AI_SOFTWARE,
    "public": PUBLIC,
}
