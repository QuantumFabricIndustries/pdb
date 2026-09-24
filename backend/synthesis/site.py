"""Static website generator for PDB — Public Daily Brief.

Reads data/public (issues, story index, corrections, ads) and writes a
self-contained static site: no server, no tracking, no external scripts.
Works on GitHub Pages / Cloudflare Pages from any sub-path (relative links).
"""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .truth import LABEL_HELP

TITLE = "PDB — Public Daily Brief"
TAGLINE = "Most people read the news. You receive a brief."
SECTION_ICONS = {"threat": "◆", "ai": "◇", "science": "✦", "money": "◈", "scam": "⚠", "myth": "✕"}
LABEL_CLASS = {"Confirmed": "l-confirmed", "Well-sourced": "l-well", "Developing": "l-dev",
               "Unverified": "l-unver", "Disputed": "l-disp"}

e = html.escape


def _url(u: str) -> str:
    return e(u) if urlparse(u or "").scheme in ("http", "https") else "#"


def _host(u: str) -> str:
    h = urlparse(u or "").hostname or ""
    return h[4:] if h.startswith("www.") else h


def _nice_date(d: str) -> str:
    try:
        dt = datetime.fromisoformat(d)
        return f"{dt:%A, %B} {dt.day}, {dt.year}"      # portable (no %-d, which fails on Windows)
    except Exception:
        return d


CSS = r"""
:root{--paper:#f7f5f0;--card:#fffdf8;--ink:#15171c;--muted:#5d6068;--rule:#dcd7cc;--accent:#8a1c1c;
--confirmed:#1f7a4a;--well:#1d6b78;--dev:#a4660b;--unver:#6b6f78;--disp:#b3261e;--chip:#efebe3;--mark:#fff3c4}
@media (prefers-color-scheme:dark){:root{--paper:#111317;--card:#171a20;--ink:#e9e6df;--muted:#a3a6ae;--rule:#2c3038;
--accent:#e0655f;--confirmed:#4cc38a;--well:#4db6c6;--dev:#e3a73c;--unver:#9a9ea8;--disp:#ff6b61;--chip:#22262e;--mark:#3a3420}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.6 Charter,"Iowan Old Style","Source Serif Pro",Georgia,serif}
a{color:inherit;text-decoration-color:var(--rule);text-underline-offset:3px}a:hover{text-decoration-color:var(--accent)}
.wrap{max-width:760px;margin:0 auto;padding:0 18px}
.sans,.kicker,.meta,nav,.chip,.badge,table,.foot,.stat,.ad,.btn{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
header.mast{border-bottom:3px double var(--ink);padding:28px 0 14px;text-align:center}
.mast .logo{font:800 64px/1 Georgia,serif;letter-spacing:.06em;text-decoration:none;display:inline-block}
.mast .name{font:600 13px/1.4 -apple-system,"Segoe UI",sans-serif;letter-spacing:.32em;text-transform:uppercase;margin-top:6px}
.mast .tag{font-style:italic;color:var(--muted);margin-top:8px}
.dateline{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--rule);padding:8px 0;
font:13px/1.4 -apple-system,"Segoe UI",sans-serif;color:var(--muted)}
nav.sections{display:flex;gap:8px;flex-wrap:wrap;padding:14px 0;border-bottom:1px solid var(--rule)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:3px 11px;font-size:13px;text-decoration:none;white-space:nowrap}
h2.section{font:700 13px/1 -apple-system,"Segoe UI",sans-serif;letter-spacing:.2em;text-transform:uppercase;color:var(--accent);
margin:38px 0 6px;padding-bottom:8px;border-bottom:1px solid var(--ink)}
article.story{padding:20px 0;border-bottom:1px solid var(--rule)}
.story h3{font-size:24px;line-height:1.25;margin:0 0 8px}.story h3 a{text-decoration:none}
.story p{margin:8px 0}
.row{display:flex;gap:16px;align-items:flex-start}.row .body{flex:1;min-width:0}
.bwrap{flex:none;width:78px;display:flex;flex-direction:column;align-items:center;gap:5px}
.badge{width:60px;height:60px;border-radius:50%;border:4px solid currentColor;display:flex;align-items:center;justify-content:center;line-height:1}
.badge b{font-size:22px}.bwrap small{font:700 9.5px/1.1 -apple-system,"Segoe UI",sans-serif;letter-spacing:.05em;text-transform:uppercase;text-align:center}
.bwrap.big{width:104px}.bwrap.big .badge{width:92px;height:92px;border-width:5px}.bwrap.big .badge b{font-size:34px}.bwrap.big small{font-size:11px}
.todo ol{margin:4px 0 0;padding-left:20px}.todo li{margin:2px 0}
.l-confirmed{color:var(--confirmed)}.l-well{color:var(--well)}.l-dev{color:var(--dev)}.l-unver{color:var(--unver)}.l-disp{color:var(--disp)}
.meta{font-size:13px;color:var(--muted);display:flex;gap:6px 14px;flex-wrap:wrap;margin-top:8px}
.todo{background:var(--mark);border-left:3px solid var(--dev);padding:8px 12px;margin:10px 0;font-size:16px}
.todo b{font-family:-apple-system,"Segoe UI",sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;display:block}
.more{font:600 14px -apple-system,"Segoe UI",sans-serif;color:var(--accent);text-decoration:none}
.ad{margin:34px 0;border:1px dashed var(--muted);border-radius:8px;padding:14px 16px;background:var(--card)}
.ad .lbl{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.ad h4{margin:4px 0;font-size:17px}.ad p{margin:4px 0;font-size:14px}
.kicker{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:700}
h1.head{font-size:34px;line-height:1.18;margin:8px 0 14px}
.lede{font-size:20px;line-height:1.5}
h2.sub{font:700 12px/1 -apple-system,"Segoe UI",sans-serif;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);
margin:34px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--rule)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:9px 8px;border-bottom:1px solid var(--rule)}
th{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
td.pts{white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}
blockquote{margin:6px 0 0;padding:4px 10px;border-left:2px solid var(--rule);color:var(--muted);font-size:14px;font-style:italic}
.ok{color:var(--confirmed);font-weight:600}.warn{color:var(--dev);font-weight:600}.bad{color:var(--disp);font-weight:600}
ol.trail{padding-left:20px;font-size:15px}ol.trail li{margin:6px 0}
.first{background:var(--mark);font:600 11px -apple-system,sans-serif;padding:1px 6px;border-radius:4px;margin-left:6px}
.hype{display:flex;gap:4px;margin:6px 0}.hype span{flex:1;height:8px;border-radius:4px;background:var(--chip)}
.hype.low span:nth-child(1){background:var(--confirmed)}.hype.medium span:nth-child(-n+2){background:var(--dev)}
.hype.high span{background:var(--disp)}
.note{background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;font-size:15px}
.stat{font-size:13px;color:var(--muted);text-align:center;padding:12px 0}
footer.foot{margin:48px 0 0;padding:22px 0 40px;border-top:3px double var(--ink);font-size:13px;color:var(--muted);text-align:center}
footer.foot a{margin:0 7px}
.sub{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:18px 0;padding:14px 16px;
border:1px solid var(--ink);border-radius:8px;background:var(--card);font:15px/1.4 -apple-system,"Segoe UI",sans-serif}
.btn{display:inline-block;background:var(--ink);color:var(--paper);text-decoration:none;font:700 14px -apple-system,"Segoe UI",sans-serif;
padding:9px 16px;border-radius:6px;white-space:nowrap}.btn:hover{background:var(--accent)}
details summary{cursor:pointer;font:600 14px -apple-system,sans-serif}
@media (max-width:560px){.mast .logo{font-size:48px}h1.head{font-size:27px}.story h3{font-size:20px}
.bwrap{width:62px}.badge{width:50px;height:50px;border-width:3px}.badge b{font-size:18px}.bwrap small{font-size:8.5px}.lede{font-size:18px}}
"""


def _page(title: str, body: str, rel: str = "", desc: str = TAGLINE) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<link rel="alternate" type="application/rss+xml" title="{TITLE}" href="{rel}feed.xml">
<link rel="stylesheet" href="{rel}assets/style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%2315171c'/%3E%3Ctext x='32' y='42' font-family='Georgia' font-weight='700' font-size='26' fill='%23f7f5f0' text-anchor='middle'%3EPDB%3C/text%3E%3C/svg%3E">
</head><body><div class="wrap">
<header class="mast"><a class="logo" href="{rel}index.html">PDB</a>
<div class="name">Public Daily Brief</div><div class="tag">{TAGLINE}</div></header>
{body}
<footer class="foot">
<div><a href="{rel}index.html">Today</a>·<a href="{rel}archive.html">Archive</a>·<a href="{rel}how-we-score.html">How we score</a>·<a href="{rel}corrections.html">Corrections</a>·<a href="{rel}ad-policy.html">Ad policy</a>·<a href="{rel}about.html">About</a>·<a href="{rel}feed.xml">RSS</a></div>
<p>Written and checked by AI, with every claim traced to its source. Free for everyone.</p>
<p>© {datetime.now(timezone.utc).year} Quantum Fabric Industries</p>
</footer></div></body></html>"""


def badge(truth: dict, big: bool = False) -> str:
    cls = LABEL_CLASS.get(truth["label"], "l-unver")
    return (f'<div class="bwrap {cls}{" big" if big else ""}" title="Truth score {truth["total"]}/100 — {e(truth["label"])}">'
            f'<div class="badge"><b>{truth["total"]}</b></div><small>{e(truth["label"])}</small></div>')


_STEP_RE = re.compile(r"(?:^|\s)(\d)[.)]\s+")


def todo_html(text: str) -> str:
    """'1. Do X. 2. Do Y.' -> an ordered list; plain text otherwise."""
    if not text:
        return ""
    parts = [p.strip() for p in _STEP_RE.split(text)]
    steps = [parts[i + 1] for i in range(1, len(parts) - 1, 2)] if len(parts) >= 3 else []
    inner = ("<ol>" + "".join(f"<li>{e(x)}</li>" for x in steps if x) + "</ol>") if len(steps) >= 2 else e(text)
    return f'<div class="todo"><b>What to do</b>{inner}</div>'


def _when(src: dict) -> str:
    iso = src.get("published_iso")
    if iso:
        try:
            dt = datetime.fromisoformat(iso)
            return f"{dt:%b} {dt.day}, {dt.year} {dt:%H:%M} UTC"
        except Exception:
            pass
    return src.get("published") or "time unknown"


def _unquote(q: str) -> str:
    return q.strip().strip('"\u201c\u201d\'').strip()


def _meta_line(st: dict) -> str:
    owners = {s["owner"] for s in st["sources"]}
    prim = any(p.get("verified") for p in st.get("primary", []))
    bits = [f"{len(owners)} independent outlet{'s' if len(owners) != 1 else ''}",
            "official evidence ✓" if prim else "no official source yet",
            f"hype: {e(st.get('hype_flag', 'low'))}"]
    if st.get("previously"):
        bits.append(f"update to {e(st['previously']['date'])} story")
    return '<div class="meta">' + "".join(f"<span>{b}</span>" for b in bits) + "</div>"


def _ad(ads: list[dict], k: int) -> str:
    if not ads:
        return ""
    a = ads[k % len(ads)]
    label = e(a.get("label", "From the maker of PDB"))
    return (f'<aside class="ad"><div class="lbl">{label}</div><h4><a href="{_url(a.get("url", ""))}" rel="sponsored noopener">'
            f'{e(a.get("title", ""))}</a></h4><p>{e(a.get("text", ""))}</p></aside>')


def subscribe_box(cfg: dict) -> str:
    """Plain link to the newsletter sign-up page (no embedded third-party script = no trackers)."""
    url = (cfg or {}).get("subscribe_url", "")
    if urlparse(url).scheme not in ("http", "https"):
        return ""
    name = e(cfg.get("newsletter_name", "PDB Weekly"))
    return (f'<aside class="sub"><div><b>Get {name} in your inbox.</b> The week\'s most important verified stories, '
            f'once a week. Free.</div><a class="btn" href="{e(url)}" rel="noopener">Subscribe free</a></aside>')


def render_issue(issue: dict, ads: list[dict], rel: str = "", cfg: dict | None = None) -> str:
    names = issue["section_names"]
    nav = "".join(f'<a class="chip" href="#{s}">{SECTION_ICONS.get(s, "")} {e(names[s])}</a>' for s in issue["sections"])
    st = issue.get("stats", {})
    out = [f'<div class="dateline"><span>{e(_nice_date(issue["date"]))}</span>'
           f'<span>{st.get("items_scanned", "?")} reports scanned · {st.get("published", len(issue["stories"]))} stories passed the Editor</span></div>',
           f'<nav class="sections">{nav}</nav>']
    out.append(subscribe_box(cfg or {}))
    if issue.get("editor_note"):
        out.append(f'<p class="note sans">{e(issue["editor_note"])}</p>')
    for i, sec in enumerate(issue["sections"]):
        out.append(f'<h2 class="section" id="{sec}">{SECTION_ICONS.get(sec, "")} {e(names[sec])}</h2>')
        for sto in [x for x in issue["stories"] if x["section"] == sec]:
            todo = todo_html(sto.get("what_to_do", ""))
            out.append(f'''<article class="story"><div class="row">{badge(sto["truth"])}<div class="body">
<h3><a href="{rel}stories/{e(sto["id"])}.html">{e(sto["headline"])}</a></h3>
<p>{e(sto["in_brief"])}</p>{todo}{_meta_line(sto)}
<p><a class="more" href="{rel}stories/{e(sto["id"])}.html">Open the dossier →</a></p></div></div></article>''')
        if i == 1:
            out.append(_ad(ads, hash(issue["date"])))
    out.append(_ad(ads, hash(issue["date"]) + 1))
    out.append(subscribe_box(cfg or {}))
    return "\n".join(out)


def render_story(st: dict, names: dict) -> str:
    t = st["truth"]
    src_by_n = {s["n"]: s for s in st["sources"]}
    claims = []
    for c in st["claims"]:
        s = src_by_n.get(c["source"], {})
        corr = c.get("corroborated_by") or []
        status = ('<span class="ok">✓ Verified in source</span>' +
                  (f'<br><span class="ok">✓ Also confirmed by {e(", ".join(corr))}</span>' if corr else ""))
        claims.append(f'<tr><td>{e(c["claim"])}<blockquote>“{e(_unquote(c["quote"]))}”</blockquote></td>'
                      f'<td>{status}<br><a href="{_url(s.get("url", ""))}">[{c["source"]}] {e(s.get("outlet", "?"))}</a></td></tr>')
    rejected = st.get("rejected_claims", [])
    rej_html = ""
    if rejected:
        items = "".join(f'<li>{e(r["claim"])} — <span class="bad">{e("; ".join(r["problems"]))}</span></li>' for r in rejected)
        rej_html = (f'<details><summary>{len(rejected)} draft claim(s) removed by the Fact-Checker</summary>'
                    f'<ul class="sans" style="font-size:14px">{items}</ul></details>')
    trail = []
    for s in sorted(st["sources"], key=lambda s: s.get("published_iso") or "~"):
        first = '<span class="first">First reported</span>' if s.get("first") else ""
        trail.append(f'<li><a href="{_url(s["url"])}">{e(s["outlet"])}</a> <span class="sans" style="color:var(--muted);font-size:13px">'
                     f'owner: {e(s["owner"])} · {e(s["kind"])} · {e(_when(s))}</span>{first}</li>')
    prim = st.get("primary", [])
    prim_html = ("".join(f'<li><a href="{_url(p["url"])}">{e(p["label"][:120])}</a> — '
                         f'<span class="{"ok" if p["verified"] else "warn"}">{e(p["type"])}{"" if p["verified"] else " (does not match this story, so no points)"}</span></li>'
                         for p in prim) if prim else "<li>None found yet. That lowers the score, but it doesn't mean the story is false.</li>")
    parts = "".join(f'<tr><td>{e(name)}<br><span style="color:var(--muted)">{e(why)}</span></td>'
                    f'<td class="pts">{pts:+d}{f" / {mx}" if mx else ""}</td></tr>' for name, pts, mx, why in t["parts"])
    ed = st.get("editor", {})
    actions = [x for x in ed.get("edits", []) if not x.startswith("editor: ")]
    findings = [x[len("editor: "):] for x in ed.get("edits", []) if x.startswith("editor: ")]
    notes = [e(x[0].upper() + x[1:]) for x in actions]
    if ed.get("disputed"):
        notes.insert(0, f'<span class="bad">Sources disagree:</span> {e(ed.get("dispute_note", ""))}')
    notes_html = "".join(f"<li>{n}</li>" for n in notes) or "<li>No changes needed.</li>"
    if findings:
        notes_html += ("<li><details><summary>What the Editor flagged</summary><ul>"
                       + "".join(f"<li>{e(f)}</li>" for f in findings) + "</ul></details></li>")
    prev = ""
    if st.get("previously"):
        p = st["previously"]
        prev = (f'<p class="note sans">Update to our <a href="{e(p["id"])}.html">{e(p["date"])} coverage</a> '
                f'(then rated {e(p["label"])}, {p["score"]}).</p>')
    todo = todo_html(st.get("what_to_do", ""))
    also = sorted({_host(u) for u in st.get("also_covered_urls", [])})
    body = f"""
<p class="sans" style="margin-top:18px"><a href="../index.html">← Today's brief</a> · <a href="../issues/{e(st['date'])}.html">{e(st['date'])} issue</a></p>
<div class="kicker">{SECTION_ICONS.get(st['section'], '')} {e(names.get(st['section'], st['section']))} · Story dossier</div>
<div class="row" style="margin-top:8px"><div class="body"><h1 class="head">{e(st['headline'])}</h1></div>{badge(t, big=True)}</div>
<p class="sans" style="color:var(--muted);font-size:14px;margin-top:-4px"><b class="{LABEL_CLASS.get(t['label'], '')}">{e(t['label'])}.</b> {e(LABEL_HELP.get(t['label'], ''))}</p>
{prev}
<p class="lede">{e(st['in_brief'])}</p>
{todo}
<h2 class="sub">Why it matters</h2><p>{e(st['so_what'])}</p>
<h2 class="sub">Claims we checked</h2>
<table><tr><th>Claim and the exact source text</th><th>Check</th></tr>{''.join(claims)}</table>
{rej_html}
<h2 class="sub">Source trail</h2><ol class="trail">{''.join(trail)}</ol>
<p class="sans" style="font-size:13px;color:var(--muted)">Also covered by: {e(", ".join(also))}</p>
<h2 class="sub">Primary evidence</h2><ul class="sans" style="font-size:14px">{prim_html}</ul>
<h2 class="sub">Hype meter</h2><div class="hype {e(st.get('hype_flag', 'low'))}"><span></span><span></span><span></span></div>
<p class="sans" style="font-size:14px">{e(st.get('hype_flag', 'low').title())}{(' — ' + e(st['hype_reason'])) if st.get('hype_reason') else ''}</p>
<h2 class="sub">How we scored this: {t['total']}/100</h2><table>{parts}</table>
<h2 class="sub">Editor's notes</h2><ul class="sans" style="font-size:14px">{notes_html}</ul>
<p class="sans" style="font-size:13px;color:var(--muted)">Drafted by AI ({e(st.get('writer_model', ''))}), fact-checked by code, reviewed by an independent AI editor ({e(str(ed.get('model')))}). <a href="../how-we-score.html">How this works</a> · <a href="../corrections.html">Corrections</a></p>
"""
    return _page(f"{st['headline']} — PDB", body, rel="../", desc=st["in_brief"])


def _static_pages(ads_policy_contact: str = "") -> dict[str, tuple[str, str]]:
    how = f"""<h1 class="head">How we score the truth</h1>
<p class="lede">Every story gets a Truth Score from 0 to 100. The number is computed only from evidence we can show you. No AI opinion goes into it.</p>
<h2 class="sub">Where the points come from</h2>
<table><tr><th>Evidence</th><th>Points</th></tr>
<tr><td><b>Independent outlets.</b> Different owners reporting the story. Two sites with the same parent company count once (for example, Wired and Ars Technica are both Condé Nast).</td><td class="pts">up to 30</td></tr>
<tr><td><b>Primary evidence.</b> Official records such as CISA's list of actively exploited vulnerabilities, government, court and journal pages, or a statement from the organization involved (worth less, because it isn't independent).</td><td class="pts">up to 25</td></tr>
<tr><td><b>Claims verified.</b> Each key claim must come with an exact quote from its source. Code checks that the quote exists and that every number matches.</td><td class="pts">up to 25</td></tr>
<tr><td><b>Claims confirmed elsewhere.</b> The same claim appears in another independent outlet's reporting.</td><td class="pts">up to 10</td></tr>
<tr><td><b>Outlet track record.</b> The reliability rating of the outlets involved.</td><td class="pts">up to 10</td></tr>
<tr><td><b>Penalties.</b> Draft claims that failed checking, and sensational coverage.</td><td class="pts">−5 each</td></tr></table>
<h2 class="sub">Ratings</h2><table>
{''.join(f'<tr><td><b class="{LABEL_CLASS[k]}">{k}</b></td><td>{e(v)}</td></tr>' for k, v in LABEL_HELP.items())}
<tr><td colspan="2" style="color:var(--muted)">Confirmed 75+ · Well-sourced 55–74 · Developing 35–54 · Unverified under 35. We never publish a story rated Unverified.</td></tr></table>
<h2 class="sub">The AI newsroom</h2>
<ol><li><b>Scout</b> scans dozens of news feeds and groups reports of the same story.</li>
<li><b>Writer</b> (one AI) drafts the story in its own words and must attach an exact source quote to every claim.</li>
<li><b>Fact-Checker</b> (plain code, not AI) confirms every quote and number, finds official records, and counts independent confirmation.</li>
<li><b>Editor-in-Chief</b> (a different company's AI) looks for overclaiming, missing attribution and sources that disagree, fixes the wording, and decides whether to publish, hold or kill the story. Its fixes are re-checked by the same code.</li></ol>
<p>We use two different AI companies on purpose: a model checking its own work tends to miss its own mistakes.</p>"""
    ads = """<h1 class="head">Ad policy</h1>
<p class="lede">PDB is free. Ads pay for it. Ads never buy coverage or scores.</p>
<ol><li>Every ad is labeled and kept in its own box. Ads never appear inside a scored story.</li>
<li>Advertisers have no say in which stories we run, how they're written, or how they score.</li>
<li>If an advertiser is in the news, the story is scored like any other and the relationship is disclosed on it.</li>
<li>Ads marked <i>“From the maker of PDB”</i> promote products from Quantum Fabric Industries, the company that publishes PDB. We never recommend our own products inside a news story.</li>
<li>No tracking pixels, no data selling. The site has no third-party scripts.</li></ol>"""
    about = """<h1 class="head">About PDB</h1>
<p class="lede">PDB — Public Daily Brief is a free daily news brief on security threats, AI and tech, science, money and scams. An AI newsroom writes it and checks it, and every claim is traced back to its source.</p>
<p>Think of each story as a background check on the news: who reported it first, who confirmed it independently, what the official record says, and how much of the coverage is hype.</p>
<p>PDB is produced automatically. Machines make mistakes too, so every story shows its evidence and every rating change is logged publicly on the <a href="corrections.html">corrections page</a>.</p>
<p>Published by Quantum Fabric Industries.</p>"""
    return {"how-we-score.html": ("How we score — PDB", how), "ad-policy.html": ("Ad policy — PDB", ads),
            "about.html": ("About — PDB", about)}


def _rss(stories: list[dict], base: str) -> str:
    items = []
    for s in stories[:50]:
        link = f"{base}stories/{s['id']}.html"
        try:
            pub = datetime.fromisoformat(s["date"]).replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 12:00:00 +0000")
        except Exception:
            pub = ""
        items.append(f"<item><title>{e(s['headline'])} [{e(s['label'])} {s['score']}]</title><link>{e(link)}</link>"
                     f"<guid isPermaLink=\"false\">{e(s['id'])}</guid><pubDate>{pub}</pubDate></item>")
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{TITLE}</title>'
            f"<link>{e(base or './')}</link><description>{TAGLINE}</description>{''.join(items)}</channel></rss>")


def render_email(issue: dict, site_base: str) -> str:
    """Simple inline-styled email version of an issue (for the newsletter)."""
    names = issue["section_names"]
    rows = [f'<h1 style="font:800 40px Georgia,serif;margin:0">PDB</h1><p style="margin:0 0 4px;font:600 12px Arial;letter-spacing:3px">PUBLIC DAILY BRIEF</p>'
            f'<p style="font:italic 15px Georgia;color:#555;margin:0 0 16px">{TAGLINE} · {e(_nice_date(issue["date"]))}</p>']
    for sec in issue["sections"]:
        rows.append(f'<h2 style="font:700 13px Arial;letter-spacing:2px;color:#8a1c1c;border-bottom:1px solid #111;padding-bottom:6px;margin-top:28px">{e(names[sec].upper())}</h2>')
        for s in [x for x in issue["stories"] if x["section"] == sec]:
            link = f"{site_base}stories/{s['id']}.html"
            todo = f'<p style="background:#fff3c4;padding:6px 10px;font:14px Georgia"><b>What to do:</b> {e(s["what_to_do"])}</p>' if s.get("what_to_do") else ""
            rows.append(f'<p style="font:700 19px Georgia;margin:16px 0 4px"><a href="{e(link)}" style="color:#111">{e(s["headline"])}</a></p>'
                        f'<p style="font:12px Arial;color:#555;margin:0">Truth score {s["truth"]["total"]}/100 · {e(s["truth"]["label"])}</p>'
                        f'<p style="font:16px/1.5 Georgia;margin:6px 0">{e(s["in_brief"])}</p>{todo}')
    rows.append('<p style="font:12px Arial;color:#777;margin-top:30px">Written and checked by AI, with every claim traced to its source. '
                f'<a href="{e(site_base)}how-we-score.html">How we score</a></p>')
    return f'<div style="max-width:640px;margin:0 auto;padding:16px;color:#111;background:#fff">{"".join(rows)}</div>'


def pick_weekly(all_issues: list[dict], days: int = 7, per_section: int = 2, max_total: int = 10) -> list[dict]:
    """Best verified stories of the last `days` days: highest Truth Score per section, no repeats of the same story."""
    from datetime import date as _d, timedelta as _td
    from .verify import _key_words
    if not all_issues:
        return []
    end = _d.fromisoformat(all_issues[-1]["date"])
    pool = [st for iss in all_issues if end - _d.fromisoformat(iss["date"]) < _td(days=days) for st in iss["stories"]]
    pool.sort(key=lambda st: (st["truth"]["total"], st["date"]), reverse=True)
    chosen: list[dict] = []
    for st in pool:
        kw = _key_words(st["headline"])
        dup = any((kw and len(kw & _key_words(c["headline"])) / max(1, min(len(kw), len(_key_words(c["headline"])))) >= 0.6)
                  or set(st.get("also_covered_urls", [])) & set(c.get("also_covered_urls", [])) for c in chosen)
        if dup or sum(1 for c in chosen if c["section"] == st["section"]) >= per_section:
            continue
        chosen.append(st)
        if len(chosen) >= max_total:
            break
    order = ["threat", "ai", "science", "money", "scam", "myth"]
    chosen.sort(key=lambda st: (order.index(st["section"]) if st["section"] in order else 99, -st["truth"]["total"]))
    return chosen


def _n_outlets(st: dict) -> str:
    n = len({x["owner"] for x in st["sources"]})
    return f"{n} independent outlet{'s' if n != 1 else ''}"


def render_weekly(stories: list[dict], names: dict, week_end: str, site_base: str, ads: list[dict]) -> str:
    """Inline-styled weekly newsletter body to paste into Kit (email clients ignore external CSS)."""
    base = site_base or "./"
    label_color = {"Confirmed": "#1f7a4a", "Well-sourced": "#1d6b78", "Developing": "#a4660b", "Disputed": "#b3261e"}
    rows = [f'<h1 style="font:800 42px Georgia,serif;margin:0;letter-spacing:2px">PDB</h1>'
            f'<p style="margin:0 0 2px;font:700 12px Arial,sans-serif;letter-spacing:3px">PDB WEEKLY &middot; PUBLIC DAILY BRIEF</p>'
            f'<p style="font:italic 15px Georgia,serif;color:#555;margin:0 0 18px">Week ending {e(_nice_date(week_end))}. '
            f'The most important stories of the week, each one checked against its sources.</p>']
    sec = None
    for st in stories:
        if st["section"] != sec:
            sec = st["section"]
            rows.append(f'<h2 style="font:700 13px Arial,sans-serif;letter-spacing:2px;color:#8a1c1c;border-bottom:1px solid #111;'
                        f'padding-bottom:6px;margin:28px 0 4px">{e(names.get(sec, sec).upper())}</h2>')
        link = f"{base}stories/{st['id']}.html"
        t = st["truth"]
        todo = (f'<p style="background:#fff3c4;padding:8px 10px;font:14px/1.5 Georgia,serif;margin:6px 0"><b>What to do:</b> '
                f'{e(st["what_to_do"])}</p>') if st.get("what_to_do") else ""
        rows.append(f'<p style="font:700 19px/1.3 Georgia,serif;margin:16px 0 4px"><a href="{e(link)}" style="color:#111;text-decoration:none">'
                    f'{e(st["headline"])}</a></p>'
                    f'<p style="font:700 12px Arial,sans-serif;color:{label_color.get(t["label"], "#555")};margin:0">'
                    f'TRUTH SCORE {t["total"]}/100 &middot; {e(t["label"].upper())} &middot; '
                    f'{_n_outlets(st)}</p>'
                    f'<p style="font:16px/1.55 Georgia,serif;margin:6px 0">{e(st["in_brief"])}</p>{todo}'
                    f'<p style="font:13px Arial,sans-serif;margin:4px 0"><a href="{e(link)}" style="color:#8a1c1c">See the sources and evidence &rarr;</a></p>')
    if ads:
        a = ads[hash(week_end) % len(ads)]
        rows.append(f'<div style="border:1px dashed #888;border-radius:8px;padding:12px 14px;margin:28px 0">'
                    f'<p style="font:11px Arial,sans-serif;letter-spacing:2px;color:#777;margin:0">{e(a.get("label", "From the maker of PDB").upper())}</p>'
                    f'<p style="font:700 16px Arial,sans-serif;margin:4px 0"><a href="{_url(a.get("url", ""))}" style="color:#111">{e(a.get("title", ""))}</a></p>'
                    f'<p style="font:14px Arial,sans-serif;margin:0">{e(a.get("text", ""))}</p></div>')
    rows.append(f'<p style="font:13px/1.5 Arial,sans-serif;color:#666;margin-top:26px">New stories every day at '
                f'<a href="{e(base)}" style="color:#111">{e(base)}</a>. Written and checked by AI, with every claim traced to its source. '
                f'<a href="{e(base)}how-we-score.html" style="color:#111">How we score</a>.</p>')
    return f'<div style="max-width:640px;margin:0 auto;padding:16px;color:#111;background:#ffffff">{"".join(rows)}</div>'


def build_site(public_dir: Path, site_dir: Path, base_url: str = "") -> None:
    issues = sorted((public_dir / "issues").glob("*.json"))
    if not issues:
        raise SystemExit("no issues to publish yet")
    ads = json.loads((public_dir / "ads.json").read_text(encoding="utf-8")) if (public_dir / "ads.json").exists() else []
    cfg = json.loads((public_dir / "site.json").read_text(encoding="utf-8")) if (public_dir / "site.json").exists() else {}
    index = json.loads((public_dir / "stories.json").read_text(encoding="utf-8")) if (public_dir / "stories.json").exists() else []
    corrections = json.loads((public_dir / "corrections.json").read_text(encoding="utf-8")) if (public_dir / "corrections.json").exists() else []

    if site_dir.exists():
        shutil.rmtree(site_dir)
    for d in ("assets", "issues", "stories"):
        (site_dir / d).mkdir(parents=True, exist_ok=True)
    (site_dir / "assets" / "style.css").write_text(CSS.strip(), encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    all_issues = [json.loads(p.read_text(encoding="utf-8")) for p in issues]
    for iss in all_issues:
        names = iss["section_names"]
        (site_dir / "issues" / f"{iss['date']}.html").write_text(
            _page(f"{TITLE} — {iss['date']}", render_issue(iss, ads, rel="../", cfg=cfg), rel="../"), encoding="utf-8")
        (site_dir / "issues" / f"{iss['date']}-email.html").write_text(render_email(iss, base_url), encoding="utf-8")
        for st in iss["stories"]:
            (site_dir / "stories" / f"{st['id']}.html").write_text(render_story(st, names), encoding="utf-8")

    latest = all_issues[-1]
    (site_dir / "index.html").write_text(_page(TITLE, render_issue(latest, ads, cfg=cfg)), encoding="utf-8")

    # Weekly newsletter: body to paste into Kit + a preview page. Rebuilt every day; send it on Sundays.
    (site_dir / "weekly").mkdir(exist_ok=True)
    weekly = render_weekly(pick_weekly(all_issues), latest["section_names"], latest["date"], base_url, ads)
    (site_dir / "weekly" / "latest-email.html").write_text(weekly, encoding="utf-8")
    (site_dir / "weekly" / "latest.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>PDB Weekly — {e(latest["date"])}</title><meta name="robots" content="noindex"></head>'
        f'<body style="margin:0;background:#eee">{weekly}</body></html>', encoding="utf-8")

    arch = "".join(f'<tr><td><a href="issues/{i["date"]}.html">{e(_nice_date(i["date"]))}</a></td>'
                   f'<td>{len(i["stories"])} stories</td></tr>' for i in reversed(all_issues))
    (site_dir / "archive.html").write_text(_page("Archive — PDB", f'<h1 class="head">Archive</h1><table>{arch}</table>'), encoding="utf-8")

    if corrections:
        rows = "".join(f'<tr><td>{e(c["date"])}</td><td><a href="stories/{e(c["story_id"])}.html">{e(c["headline"])}</a><br>'
                       f'<span style="color:var(--muted)">{e(c["note"])}</span></td></tr>' for c in reversed(corrections))
        cor_body = f"<table><tr><th>Date</th><th>Change</th></tr>{rows}</table>"
    else:
        cor_body = "<p>No rating changes or corrections yet.</p>"
    (site_dir / "corrections.html").write_text(_page("Corrections — PDB", '<h1 class="head">Corrections &amp; updates</h1>'
        '<p class="lede">When new evidence changes a story\'s rating, or we get something wrong, it\'s logged here. Nothing gets quietly deleted.</p>'
        + cor_body), encoding="utf-8")

    for fname, (title, body) in _static_pages().items():
        (site_dir / fname).write_text(_page(title, body), encoding="utf-8")
    (site_dir / "feed.xml").write_text(_rss(list(reversed(index)), base_url), encoding="utf-8")
    (site_dir / "404.html").write_text(_page("Not found — PDB", '<h1 class="head">Page not found</h1><p><a href="index.html">Go to today\'s brief</a></p>'), encoding="utf-8")
