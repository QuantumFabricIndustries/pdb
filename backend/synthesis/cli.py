"""PDB CLI — run the daily pipeline end to end.

Usage:
    python -m pdb build [--pack ai-software] [--top 7] [--no-enrich] [--out data/issues]
    python -m pdb providers

Steps: fetch -> enrich -> cluster -> rank -> analyze -> history -> assemble -> write files.

LLM providers (tried in order): Groq -> Gemini -> Ollama -> stub.
Set GROQ_API_KEY, GEMINI_API_KEY, or run Ollama locally for real analysis.

Personalization: create prefs.json in the project root to set your persona and Watch List.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import PACKS
from .fetcher import enrich, fetch_pack
from .cluster import cluster_articles
from .score import rank
from .summarize import analyze_cluster
from .issue import assemble
from .prefs import load_prefs
from .history import find_history_refs


def _load_dotenv() -> None:
    """Load .env from project root if present (no python-dotenv dependency)."""
    for p in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
            break


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def build(pack_name: str, top: int, do_enrich: bool, out_dir: Path, brief_mode: bool = False) -> int:
    log = logging.getLogger("pdb.build")
    pack = PACKS[pack_name]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load user preferences (persona + watch list)
    project_root = Path(__file__).resolve().parents[2]
    prefs = load_prefs(project_root)

    log.info(
        "building brief for %s | pack=%s enrich=%s top=%d brief_mode=%s persona=%s watch_list=%s",
        date, pack_name, do_enrich, top, brief_mode, prefs.persona, prefs.watch_list or "(none)",
    )

    raw = fetch_pack(pack)
    log.info("fetched %d raw items", len(raw))
    if not raw:
        log.warning("no items fetched; aborting")
        return 1

    if do_enrich:
        articles = enrich(raw)
    else:
        from .models import Article
        articles = [
            Article(
                raw=r,
                text=r.summary,
                excerpt=r.summary[:280],
                extracted_ok=False,
                word_count=len(r.summary.split()),
            )
            for r in raw
        ]
    log.info("enriched %d articles", len(articles))

    clusters = cluster_articles(articles)
    ranked = rank(clusters, top_k=top)
    log.info("selected %d stories", len(ranked))

    # Analyze stories (persona-aware)
    stories = [analyze_cluster(c, score, prefs=prefs, brief_mode=brief_mode) for c, score in ranked]

    # Brief History callbacks — attach prior coverage refs
    out_dir.mkdir(parents=True, exist_ok=True)
    for story in stories:
        story.history_refs = find_history_refs(
            title=story.title,
            tags=story.tags,
            issues_dir=out_dir,
            current_date=date,
        )

    issue = assemble(date, pack_name, stories)

    stem = out_dir / f"{date}-{pack_name}"
    (stem.with_suffix(".md")).write_text(issue.rendered_markdown, encoding="utf-8")
    (stem.with_suffix(".html")).write_text(issue.rendered_html, encoding="utf-8")
    log.info("wrote %s.md and %s.html", stem, stem)
    return 0


def _cmd_providers() -> int:
    """Show which LLM providers are available."""
    from .providers import get_providers
    print("LLM provider chain (tried in order):")
    print()
    for p in get_providers():
        status = "READY" if p.available else "not available"
        models = f"tldr={p.tldr_model}, analysis={p.analysis_model}"
        print(f"  {'>' if p.available else ' '} {p.name:8s}  {status:16s}  {models}")
    print()
    print("To enable a provider:")
    print("  Groq:   set GROQ_API_KEY   (free key at https://console.groq.com/keys)")
    print("  Gemini: set GEMINI_API_KEY (free key at https://aistudio.google.com/apikey)")
    print("  Ollama: install from https://ollama.com and run: ollama pull qwen2.5:1.5b")
    print()
    print("Or create a .env file in the project root with your key.")
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(prog="pdb", description="PDB — Your Personal Daily Brief")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build a daily brief")
    b.add_argument("--pack", default="ai-software", choices=list(PACKS))
    b.add_argument("--top", type=int, default=7)
    b.add_argument("--no-enrich", action="store_true", help="skip full-text fetch (faster, shallower)")
    b.add_argument("--brief", action="store_true", help="brief mode: cap So What at ~150 words, lead with 3-bullet action list")
    b.add_argument("--out", default="data/issues")
    b.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("providers", help="Show available LLM providers")

    pub = sub.add_parser("publish", help="PDB — Public Daily Brief: run the AI newsroom and build the website")
    pub.add_argument("--data", default="data", help="data directory (issues, logs, caches)")
    pub.add_argument("--site", default="site", help="output directory for the static website")
    pub.add_argument("--quota", type=int, default=0, help="stories per section (0 = default quotas)")
    pub.add_argument("--site-only", action="store_true", help="rebuild the website from saved issues, no fetching")
    pub.add_argument("--time-budget", type=float, default=0, help="seconds to work before pausing (resume by re-running)")
    pub.add_argument("--base-url", default="", help="public site URL, used in RSS and email links")
    pub.add_argument("-v", "--verbose", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "build":
        _setup_logging(args.verbose)
        out = Path(args.out)
        if not out.is_absolute():
            out = Path(__file__).resolve().parents[2] / out
        return build(args.pack, args.top, not args.no_enrich, out, brief_mode=args.brief)
    if args.cmd == "providers":
        return _cmd_providers()
    if args.cmd == "publish":
        _setup_logging(args.verbose)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        root = Path(__file__).resolve().parents[2]
        data = Path(args.data) if Path(args.data).is_absolute() else root / args.data
        site_dir = Path(args.site) if Path(args.site).is_absolute() else root / args.site
        if not args.site_only:
            from .newsroom import PipelineError, run
            from .sections import QUOTAS
            quotas = {k: args.quota for k in QUOTAS} if args.quota else None
            try:
                issue = run(data, quotas=quotas, time_budget_s=args.time_budget or None)
            except PipelineError as e:
                logging.getLogger("pdb.publish").error("NOT PUBLISHED: %s", e)
                return 2
            if issue is None:
                print("PAUSED — time budget used; run the same command again to continue")
                return 3
            print(f"Published {len(issue['stories'])} stories for {issue['date']}")
        from .site import build_site
        build_site(data / "public", site_dir, base_url=args.base_url)
        print(f"Website built in {site_dir}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
