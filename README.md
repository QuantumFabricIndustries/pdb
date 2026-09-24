# PDB — Public Daily Brief

*Most people read the news. You receive a brief.*

A free, AI-run daily news brief on security threats, AI & tech, science, money, scams and viral myths,
where **every claim is traced to its source** and every story carries an evidence-based **Truth Score**.

## How the AI newsroom works

| Role | What it does | Runs on |
|---|---|---|
| Scout | Scans ~40 news feeds, groups reports of the same story, counts independent owners | code |
| Writer | Drafts each story in its own words; must attach an exact source quote to every claim | Groq (gpt-oss-120b) |
| Fact-Checker | Verifies every quote and number, finds official records (CISA KEV, .gov, journals), catches copying | code — no AI |
| Truth Score | 0–100 from evidence only: independent outlets, primary evidence, verified claims, confirmation | code — no AI |
| Editor-in-Chief | Checks overclaiming, attribution and disputes, fixes wording, then decides PUBLISH / HOLD / KILL | Gemini (a different AI company) |

Rules: nothing rated *Unverified* is published; two outlets with the same owner count once; rating changes are logged
on the public corrections page; ads are labeled and never inside a story.

## Runs itself

`.github/workflows/daily.yml` runs every morning on GitHub Actions (free), saves the issue to `data/public/`,
and publishes the website to GitHub Pages (free).

## Run it yourself

```bash
cd backend
pip install -r requirements.txt
# put GROQ_API_KEY=... and GEMINI_API_KEY=... in a .env file in the repo root (never commit it)
python -m synthesis publish            # full run + website in ../site
python -m synthesis publish --site-only  # rebuild the website from saved issues
python -m pytest -q                    # tests, including planted false claims the Fact-Checker must catch
```

House ads live in `data/public/ads.json`.

© Quantum Fabric Industries
