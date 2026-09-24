"""Domain, ownership, and primary-source helpers.

Independence is judged by *owner*, not by feed or hostname:
blog.google and deepmind.google are both Google; Wired and Ars Technica are
both Condé Nast. Two outlets with one owner count as ONE independent source.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Multi-part public suffixes we are likely to see (keeps bbc.co.uk intact).
_MULTI_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au", "gov.au", "co.jp",
    "co.nz", "co.in", "com.br", "com.cn", "co.za", "com.sg",
}

# root domain -> owning organization (only relationships we are sure of)
OWNERS: dict[str, str] = {
    # Google / Alphabet
    "google.com": "Google", "blog.google": "Google", "deepmind.google": "Google",
    "deepmind.com": "Google", "youtube.com": "Google", "googleblog.com": "Google",
    # Microsoft
    "microsoft.com": "Microsoft", "github.com": "Microsoft", "github.blog": "Microsoft",
    "linkedin.com": "Microsoft",
    # Meta
    "meta.com": "Meta", "facebook.com": "Meta", "instagram.com": "Meta", "whatsapp.com": "Meta",
    # Amazon
    "amazon.com": "Amazon", "aboutamazon.com": "Amazon",
    # Condé Nast
    "wired.com": "Condé Nast", "arstechnica.com": "Condé Nast", "newyorker.com": "Condé Nast",
    # Vox Media
    "theverge.com": "Vox Media", "vox.com": "Vox Media", "polygon.com": "Vox Media",
    # Yahoo
    "techcrunch.com": "Yahoo", "engadget.com": "Yahoo", "yahoo.com": "Yahoo",
    # Comcast (NBCUniversal + Sky)
    "cnbc.com": "Comcast", "nbcnews.com": "Comcast", "skynews.com": "Comcast", "sky.com": "Comcast",
    # Ziff Davis
    "zdnet.com": "Ziff Davis", "pcmag.com": "Ziff Davis", "mashable.com": "Ziff Davis", "cnet.com": "Ziff Davis",
    # Future plc
    "space.com": "Future", "techradar.com": "Future", "tomshardware.com": "Future", "livescience.com": "Future",
    # Others (single-outlet owners, listed for readable names)
    "bbc.co.uk": "BBC", "bbc.com": "BBC",
    "theguardian.com": "Guardian Media Group",
    "darkreading.com": "Informa TechTarget",
    "therecord.media": "Recorded Future",
    "theregister.com": "Situation Publishing",
}

# Organizations whose own publications are *primary sources* about themselves
# or about the matters they govern.
_PRIMARY_DOMAINS = {
    "cisa.gov", "nist.gov", "cve.org", "mitre.org", "sec.gov", "justice.gov", "fbi.gov",
    "ftc.gov", "fcc.gov", "nasa.gov", "noaa.gov", "nih.gov", "cdc.gov", "fda.gov",
    "europa.eu", "ncsc.gov.uk", "arxiv.org", "doi.org", "nature.com", "science.org",
    "courtlistener.com", "supremecourt.gov", "uscourts.gov",
}
_PRIMARY_SUFFIXES = (".gov", ".mil", ".gov.uk", ".europa.eu", ".int", ".edu")


def hostname(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def root_domain(url_or_host: str) -> str:
    """Registrable domain: 'feeds.bbci.co.uk' -> 'bbci.co.uk', 'www.wired.com' -> 'wired.com'."""
    host = hostname(url_or_host) if "://" in url_or_host else url_or_host.lower().removeprefix("www.")
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host
    if ".".join(parts[-2:]) in _MULTI_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def owner(url: str) -> str:
    """Owning organization for a URL; falls back to its root domain."""
    rd = root_domain(url)
    if rd == "bbci.co.uk":
        rd = "bbc.co.uk"
    return OWNERS.get(rd, rd)


def is_primary(url: str) -> bool:
    host = hostname(url)
    rd = root_domain(url)
    return rd in _PRIMARY_DOMAINS or host in _PRIMARY_DOMAINS or host.endswith(_PRIMARY_SUFFIXES)


def unique_owners(urls: list[str]) -> set[str]:
    return {owner(u) for u in urls if u}
