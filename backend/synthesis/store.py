"""Published-story index and the public corrections / updates log.

When a story we already published comes back with a different verdict
(e.g. Developing -> Confirmed, or anything -> Disputed), we log it publicly.
"""

from __future__ import annotations

import json
from datetime import date as _date, timedelta
from pathlib import Path

from .verify import _key_words


def _load(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _same_story(a: dict, b: dict) -> bool:
    if set(a.get("also_covered_urls", [])) & set(b.get("also_covered_urls", [])):
        return True
    ka, kb = _key_words(a["headline"]), _key_words(b["headline"])
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def record(out: Path, issue: dict) -> list[dict]:
    idx_p, cor_p = out / "stories.json", out / "corrections.json"
    index: list[dict] = _load(idx_p, [])
    corrections: list[dict] = _load(cor_p, [])
    today = _date.fromisoformat(issue["date"])
    window = [s for s in index if s["date"] != issue["date"]
              and today - _date.fromisoformat(s["date"]) <= timedelta(days=14)]
    new_entries = []
    for st in issue["stories"]:
        entry = {"id": st["id"], "date": st["date"], "section": st["section"], "headline": st["headline"],
                 "label": st["truth"]["label"], "score": st["truth"]["total"],
                 "also_covered_urls": st["also_covered_urls"]}
        prior = next((p for p in sorted(window, key=lambda s: s["date"], reverse=True) if _same_story(p, st)), None)
        if prior:
            st["previously"] = {"id": prior["id"], "date": prior["date"], "label": prior["label"], "score": prior["score"]}
            if prior["label"] != entry["label"]:
                c = {"date": issue["date"], "story_id": st["id"], "prior_id": prior["id"], "headline": st["headline"],
                     "from": prior["label"], "to": entry["label"], "from_score": prior["score"], "to_score": entry["score"],
                     "note": f"Rating changed from {prior['label']} ({prior['score']}) to {entry['label']} ({entry['score']}) as new evidence came in."}
                corrections.append(c)
                new_entries.append(c)
        index.append(entry)
    index = [s for s in index if s["date"] != issue["date"]] + [e for e in index if e["date"] == issue["date"]]
    # de-duplicate same-day reruns (keep the latest)
    seen, deduped = set(), []
    for e in reversed(index):
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        deduped.append(e)
    idx_p.write_text(json.dumps(list(reversed(deduped)), ensure_ascii=False, indent=1), encoding="utf-8")
    corrections = [c for i, c in enumerate(corrections)
                   if (c["date"], c["story_id"]) not in {(x["date"], x["story_id"]) for x in corrections[i + 1:]}]
    cor_p.write_text(json.dumps(corrections, ensure_ascii=False, indent=1), encoding="utf-8")
    # rewrite the issue file so 'previously' links are saved
    (out / "issues" / f"{issue['date']}.json").write_text(json.dumps(issue, ensure_ascii=False, indent=1), encoding="utf-8")
    return new_entries
