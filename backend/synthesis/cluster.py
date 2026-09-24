"""Cluster duplicate/near-duplicate stories and merge coverage.

Strategy: TF-IDF cosine over title (x2) + opening text, seed-and-centroid
gating, and a publication-time window. No paid embedding API needed.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter

from .domains import unique_owners
from .fetcher import parse_date
from .models import Article, Cluster

log = logging.getLogger("synthesis.cluster")

_STOP = set("""a an the of to in on for and or but is are was were be been being with from by at as this that these those it its their his her our your you we they he she i not no nor so than too very can will just into over under again further then once here there when where why how all any both each few more most other some such only own same s t """.split())
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Terms that justify keeping the "ai" tag on a story.
_AI_TERMS = re.compile(
    r"\b(ai|artificial intelligence|machine learning|ml|llm|gpt|neural|model|"
    r"transformer|diffusion|deep learning|chatgpt|claude|gemini|copilot|"
    r"inference|training|fine.?tun|embedding|rag|agent|foundation model)\b",
    re.I,
)


def _tokens(text: str) -> set[str]:
    return {w for w in (m.group(0).lower() for m in _TOKEN_RE.finditer(text)) if w not in _STOP and len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b) or 1
    return inter / union


def _clean_inherited_tags(cluster: Cluster) -> None:
    """Strip tags inherited from feed metadata that don't match the story content.

    The main case: the HN AI feed tags every story 'ai', but many stories it
    surfaces (e.g. a WordPress CEO drama) have nothing to do with AI. If the
    'ai' tag is present but no article in the cluster mentions AI terms in
    its title or excerpt, strip it.
    """
    if "ai" not in cluster.tags:
        return
    combined = " ".join(a.raw.title + " " + a.excerpt[:300] for a in cluster.articles)
    if not _AI_TERMS.search(combined):
        cluster.tags.discard("ai")
        log.debug("stripped inherited 'ai' tag: %s", cluster.centroid_title[:60])


# Headline words too generic to prove two articles are the same story (stemmed).
_GENERIC = {"patche", "patch", "exploi", "zero", "day", "flaw", "flaws", "critic", "hacker", "hackers",
            "attack", "attacks", "vulner", "update", "launch", "launche", "announ", "new", "says",
            "report", "warns", "compan", "users", "data", "breach", "securi", "releas", "rce"}


def _stem(w: str) -> str:
    """Cheap prefix stem: 'australian'/'australia' -> 'austra'. Good enough for matching."""
    return w[:6] if len(w) > 6 else w


def _words(text: str) -> list[str]:
    return [_stem(w) for w in (m.group(0).lower() for m in _TOKEN_RE.finditer(text.replace("’s", "").replace("'s", "")))
            if w not in _STOP and len(w) > 2]


def _title_words(a: Article) -> set[str]:
    return set(_words(a.raw.title))


def _doc_tokens(a: Article) -> list[str]:
    """Title counted twice (headline words matter most) + opening of the body."""
    body_src = (a.raw.summary or a.excerpt or "")[:400]
    return _words(a.raw.title) * 2 + _words(body_src)


def _tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    idf = {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}
    vecs = []
    for d in docs:
        tf = Counter(d)
        v = {w: (1 + math.log(c)) * idf[w] for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    return vecs


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def _hours_apart(a: Article, b: Article) -> float:
    da, db = parse_date(a.raw.published), parse_date(b.raw.published)
    if da is None or db is None:
        return 0.0
    return abs((da - db).total_seconds()) / 3600


def cluster_articles(articles: list[Article], threshold: float = 0.32, max_gap_hours: float = 96) -> list[Cluster]:
    """Group articles about the same story (TF-IDF cosine, complete-link-ish).

    An article joins a cluster only if it is similar to the cluster's seed
    (threshold) AND to the cluster centroid (0.8 x threshold), and was published
    within max_gap_hours of the seed. This stops long chains of loosely related
    items collapsing into one mega-cluster.
    """
    vecs = _tfidf([_doc_tokens(a) for a in articles])
    titles = [_title_words(a) for a in articles]
    title_df: Counter = Counter()
    for t in titles:
        title_df.update(t)
    rare_cut = max(4, int(0.02 * len(articles)))

    def shares_rare(i: int, j: int) -> bool:
        """Same story must share a specific headline word (a name, product, CVE...)."""
        return any(title_df[w] <= rare_cut and w not in _GENERIC for w in titles[i] & titles[j])

    order = sorted(range(len(articles)), key=lambda i: articles[i].raw.authority, reverse=True)
    clusters: list[Cluster] = []
    seeds: list[int] = []
    centroids: list[dict[str, float]] = []

    for i in order:
        art, v = articles[i], vecs[i]
        best, best_sim = -1, 0.0
        for k, seed in enumerate(seeds):
            if not shares_rare(i, seed):
                continue
            sim = _cos(v, vecs[seed])
            if sim > best_sim:
                best, best_sim = k, sim
        if best >= 0 and best_sim >= threshold:
            c = clusters[best]
            cn = centroids[best]
            cn_norm = math.sqrt(sum(x * x for x in cn.values())) or 1.0
            if _cos(v, cn) / cn_norm >= 0.8 * threshold and _hours_apart(art, articles[seeds[best]]) <= max_gap_hours:
                c.articles.append(art)
                c.tags |= set(art.raw.tags)
                c.max_authority = max(c.max_authority, art.raw.authority)
                for w, x in v.items():
                    cn[w] = cn.get(w, 0.0) + x
                continue
        clusters.append(Cluster(id="", articles=[art], centroid_title=art.raw.title,
                                tags=set(art.raw.tags), max_authority=art.raw.authority))
        seeds.append(i)
        centroids.append(dict(v))

    # Second pass: merge clusters that are the same story told differently.
    def unit(cn: dict[str, float]) -> dict[str, float]:
        n = math.sqrt(sum(x * x for x in cn.values())) or 1.0
        return {w: x / n for w, x in cn.items()}

    units = [unit(cn) for cn in centroids]
    alive = [True] * len(clusters)
    for a in range(len(clusters)):
        if not alive[a]:
            continue
        for b in range(a + 1, len(clusters)):
            if not alive[b] or not shares_rare(seeds[a], seeds[b]):
                continue
            if _cos(units[a], units[b]) >= 0.9 * threshold and \
                    _hours_apart(articles[seeds[a]], articles[seeds[b]]) <= max_gap_hours:
                clusters[a].articles += clusters[b].articles
                clusters[a].tags |= clusters[b].tags
                clusters[a].max_authority = max(clusters[a].max_authority, clusters[b].max_authority)
                alive[b] = False
    clusters = [c for c, ok in zip(clusters, alive) if ok]

    clusters.sort(key=lambda c: (len(owners_of(c)), len(c.articles), c.max_authority), reverse=True)
    for idx, c in enumerate(clusters):
        c.id = f"c{idx}"
        _clean_inherited_tags(c)
    log.info("clustered %d articles into %d clusters (%d multi-owner)", len(articles), len(clusters),
             sum(1 for c in clusters if len(owners_of(c)) >= 2))
    return clusters


def owners_of(c: Cluster) -> set[str]:
    """Independent owners covering a cluster (Google blog + DeepMind = one)."""
    return unique_owners([a.raw.url for a in c.articles])


def top_keywords(articles: list[Article], n: int = 8) -> list[str]:
    bag = Counter()
    for a in articles:
        bag.update(_tokens(a.raw.title))
        bag.update(_tokens(a.excerpt[:400]))
    return [w for w, _ in bag.most_common(n)]
