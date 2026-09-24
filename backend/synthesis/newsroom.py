"""PDB — Public Daily Brief pipeline.

fetch -> cluster -> route to sections -> enrich candidates
  -> Writer (Groq) -> Fact-Checker (code) -> Truth Score (code) -> Editor-in-Chief (Gemini)
  -> store issue + corrections -> build static website
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import editor as editor_mod
from . import truth as truth_mod
from .cluster import cluster_articles, owners_of
from .config import PACKS
from .fetcher import enrich, fetch_pack, get_with_deadline, make_client, parse_date, shallow
from .models import Cluster
from .providers import get_provider, validate
from .score import rank
from .sections import ORDER, QUOTAS, candidates
from .verify import kev_catalog, verify
from .writer import SECTION_NAMES, pick_sources, write

log = logging.getLogger("pdb.newsroom")


class PipelineError(RuntimeError):
    pass


def story_id(date: str, headline: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:60].strip("-")
    return f"{date}-{slug}-{hashlib.sha1(headline.encode()).hexdigest()[:5]}"


def _fetch_primary_pages(urls: list[str], limit: int = 2) -> dict[str, str]:
    from .fetcher import _extract
    pages: dict[str, str] = {}
    with make_client() as client:
        for u in urls[:limit]:
            try:
                status, body, final = get_with_deadline(client, u, deadline_s=20)
                if status == 200:
                    pages[u], _ = _extract(body.decode("utf-8", "replace"), final, "")
            except Exception as e:
                log.debug("primary fetch failed %s: %s", u, e)
    return pages


def produce_story(c: Cluster, section: str, writer_p, editor_p, date: str, kev: dict, backup_editor=None) -> dict:
    sources = pick_sources(c)
    draft = write(writer_p, section, sources)
    prim_urls: list[str] = []
    for a in c.articles:
        for u in a.primary_links:
            if u not in prim_urls:
                prim_urls.append(u)
    report = verify(draft, sources, _fetch_primary_pages(prim_urls), kev)
    pre = truth_mod.compute(report, sources, draft.get("hype_flag", "low"))
    decision = editor_mod.review(editor_p, section, draft, report, sources, pre.total, backup=backup_editor)
    final = truth_mod.compute(report, sources, decision.draft.get("hype_flag", "low"), disputed=decision.disputed)
    if decision.verdict == "PUBLISH" and final.total < editor_mod.PUBLISH_BAR.get(section, editor_mod.PUBLISH_BAR["default"]):
        decision.verdict, decision.reasons = "HOLD", decision.reasons + [f"truth score {final.total} below bar"]

    far = datetime.max.replace(tzinfo=timezone.utc)
    first = min(sources, key=lambda s: parse_date(s.published) or far)
    d = decision.draft
    return {
        "id": story_id(date, d.get("headline", c.centroid_title)),
        "date": date,
        "section": section,
        "verdict": decision.verdict,
        "headline": d.get("headline", ""),
        "in_brief": d.get("in_brief", ""),
        "so_what": d.get("so_what", ""),
        "what_to_do": d.get("what_to_do", ""),
        "hype_flag": d.get("hype_flag", "low"),
        "hype_reason": d.get("hype_reason", ""),
        "claims": [asdict(x) for x in d.get("claims", [])],
        "rejected_claims": [asdict(x) for x in report.claims if x.status != "verified"],
        "sources": [{"n": s.n, "outlet": s.outlet, "owner": s.owner, "url": s.url, "published": s.published,
                     "published_iso": (parse_date(s.published).astimezone(timezone.utc).isoformat() if parse_date(s.published) else None),
                     "kind": s.kind, "first": s is first} for s in sources],
        "also_covered_urls": [a.raw.url for a in c.articles],
        "primary": report.primary,
        "truth": {"total": final.total, "label": final.label, "parts": final.parts},
        "editor": {"reasons": decision.reasons, "edits": decision.edits, "disputed": decision.disputed,
                   "dispute_note": decision.dispute_note, "model": decision.model or None},
        "writer_model": f"{writer_p.name}/{writer_p.analysis_model}",
    }


def _work(data_dir: Path, date: str) -> Path:
    return data_dir / "work" / date


def _providers(validate_now: bool, force_backup_editor: bool = False):
    writer_p = get_provider("groq")
    if writer_p is None or (validate_now and validate(writer_p)):
        raise PipelineError(f"Writer (Groq) unavailable: {validate(writer_p) if writer_p else 'no GROQ_API_KEY'}")
    backup_editor = writer_p.__class__(**{**writer_p.__dict__, "analysis_model": writer_p.tldr_model})
    editor_p = get_provider("gemini")
    note = ""
    if force_backup_editor or editor_p is None or (validate_now and validate(editor_p)):
        log.warning("Gemini editor unavailable — using the backup editor model (less independent)")
        editor_p, backup_editor = backup_editor, None
        note = "Today's Editor ran on a backup model, which is less independent than usual."
    return writer_p, editor_p, backup_editor, note


def prepare(data_dir: Path, date: str, max_age_hours: float = 48, quotas: dict | None = None) -> dict:
    """Stage 1: check AI providers, fetch, cluster, pick + enrich candidates. Saved to data/work/<date>/."""
    _, _, _, note = _providers(validate_now=True)
    raw = fetch_pack(PACKS["public"], max_per_feed=40, max_age_hours=max_age_hours)
    if len(raw) < 50:
        raise PipelineError(f"only {len(raw)} items fetched — network problem? Not publishing a thin brief.")
    arts = shallow(raw)
    clusters = cluster_articles(arts)
    ranked = rank(clusters, top_k=len(clusters), max_lone_research=10_000)
    cands = candidates(ranked)
    pool = [(s, c) for s in ORDER for c in cands[s]]
    enriched = iter(enrich([a.raw for _, c in pool for a in c.articles]))
    for _, c in pool:
        c.articles = [next(enriched) for _ in c.articles]
    work = _work(data_dir, date)
    (work / "done").mkdir(parents=True, exist_ok=True)
    meta = {"date": date, "quotas": quotas or QUOTAS, "editor_note": note, "backup_editor": bool(note), "items_scanned": len(raw),
            "outlets": len({a.raw.source for a in arts}),
            "pool": [{"section": s, "title": c.centroid_title, "articles": [asdict(a) for a in c.articles]} for s, c in pool]}
    (work / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    log.info("prepared %d candidates from %d items", len(pool), len(raw))
    return meta


def _load_cluster(entry: dict) -> Cluster:
    from .models import Article, RawItem
    arts = []
    for d in entry["articles"]:
        d = dict(d)
        arts.append(Article(raw=RawItem(**d.pop("raw")), **d))
    return Cluster(id="", articles=arts, centroid_title=entry["title"],
                   tags={t for a in arts for t in a.raw.tags}, max_authority=max(a.raw.authority for a in arts))


def process(data_dir: Path, date: str, time_budget_s: float | None = None, per_story_s: float = 75) -> bool:
    """Stage 2: write/check/edit candidates one at a time, checkpointing each. Returns True when finished."""
    started = time.monotonic()
    work = _work(data_dir, date)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    writer_p, editor_p, backup_editor, _ = _providers(validate_now=False,
                                                      force_backup_editor=meta.get("backup_editor", False))
    kev = kev_catalog(data_dir / "cache" / "kev.json")
    quotas = meta["quotas"]
    published: dict[str, int] = {s: 0 for s in ORDER}
    for i, entry in enumerate(meta["pool"]):
        done_p = work / "done" / f"{i:03d}.json"
        s = entry["section"]
        if done_p.exists():
            rec = json.loads(done_p.read_text(encoding="utf-8"))
            published[s] += rec.get("verdict") == "PUBLISH"
            continue
        if published[s] >= quotas.get(s, 0):
            continue
        if time_budget_s is not None and time.monotonic() - started > time_budget_s - per_story_s:
            return False
        c = _load_cluster(entry)
        try:
            st = produce_story(c, s, writer_p, editor_p, date, kev, backup_editor)
        except Exception as e:
            log.warning("story failed (%s): %s", type(e).__name__, c.centroid_title[:80])
            st = {"verdict": "ERROR", "section": s, "headline": c.centroid_title, "error": str(e)[:200]}
        st["owners_count"] = len(owners_of(c))
        done_p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        published[s] += st["verdict"] == "PUBLISH"
        log.info("[%s] %-7s %3s  %s", s, st["verdict"], st.get("truth", {}).get("total", "-"), st.get("headline", "")[:80])
    return True


def finalize(data_dir: Path, date: str) -> dict:
    """Stage 3: assemble the issue from checkpoints, write the editor log, record corrections."""
    work = _work(data_dir, date)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((work / "done").glob("*.json"))]
    stories = [r for r in recs if r.get("verdict") == "PUBLISH"]
    log_rows = [{"section": r.get("section"), "title": r.get("headline"), "verdict": r.get("verdict"),
                 "truth": r.get("truth", {}).get("total"), "reasons": r.get("editor", {}).get("reasons", [r.get("error")]),
                 "edits": r.get("editor", {}).get("edits", []), "owners": r.get("owners_count")} for r in recs]
    if len(stories) < 3:
        raise PipelineError(f"only {len(stories)} stories passed the editor — not publishing a thin brief")
    issue = {"date": date, "built_at": datetime.now(timezone.utc).isoformat(), "stories": stories,
             "sections": [s for s in ORDER if any(x["section"] == s for x in stories)],
             "section_names": SECTION_NAMES, "editor_note": meta.get("editor_note", ""),
             "stats": {"items_scanned": meta["items_scanned"], "stories_considered": len(recs),
                       "published": len(stories), "outlets": meta["outlets"]}}
    out = data_dir / "public"
    (out / "issues").mkdir(parents=True, exist_ok=True)
    (out / "editor_log").mkdir(parents=True, exist_ok=True)
    (out / "issues" / f"{date}.json").write_text(json.dumps(issue, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "editor_log" / f"{date}.json").write_text(json.dumps(log_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    from .store import record
    record(out, issue)
    return issue


def run(data_dir: Path, date: str | None = None, max_age_hours: float = 48, quotas: dict | None = None,
        time_budget_s: float | None = None) -> dict | None:
    """Full pipeline; resumes from checkpoints. Returns the issue, or None if the time budget ran out."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    t0 = time.monotonic()
    if not (_work(data_dir, date) / "meta.json").exists():
        prepare(data_dir, date, max_age_hours, quotas)
    remaining = None if time_budget_s is None else time_budget_s - (time.monotonic() - t0)
    if not process(data_dir, date, remaining):
        return None
    return finalize(data_dir, date)
