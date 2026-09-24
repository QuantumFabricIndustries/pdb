"""PDB newsroom tests: ownership, fact-checking (planted false claims), copying, scoring, editor rules."""

from synthesis import editor, truth
from synthesis.domains import owner, root_domain, unique_owners
from synthesis.verify import Source, copied_runs, numbers, quote_in_text, verify

A = ("Microsoft said on Tuesday it disrupted EvilTokens, a device-code phishing service that compromised "
     "12,000 inboxes. The operation targeted Microsoft 365 users across 40 countries, the company said. "
     "Researchers tracked the flaw as CVE-2026-41234 and CISA added it to its catalog.")
B = ("EvilTokens, the phishing-as-a-service platform, was taken down by Microsoft. According to Microsoft, "
     "the service was tied to 12,000 inbox compromises in 40 countries.")
SOURCES = [
    Source(n=1, outlet="Dark Reading", owner="Informa TechTarget", url="https://www.darkreading.com/a", published="x", text=A, authority=0.75),
    Source(n=2, outlet="The Hacker News", owner="thehackernews.com", url="https://thehackernews.com/b", published="y", text=B, authority=0.7),
]
GOOD = {"claim": "Microsoft disrupted the EvilTokens phishing service, which compromised 12,000 inboxes.", "source": 1,
        "quote": "it disrupted EvilTokens, a device-code phishing service that compromised 12,000 inboxes"}


# --- ownership ---------------------------------------------------------------
def test_root_domain_bug_fixed():
    assert root_domain("https://www.wired.com/x") == "wired.com"      # old code gave 'ired.com'
    assert root_domain("https://feeds.bbci.co.uk/news") == "bbci.co.uk"

def test_same_owner_is_one_source():
    assert owner("https://blog.google/a") == owner("https://deepmind.google/b") == "Google"
    assert len(unique_owners(["https://wired.com/a", "https://arstechnica.com/b"])) == 1


# --- planted false claims: the Fact-Checker must catch all three --------------
def _statuses(claims):
    rep = verify({"headline": "Microsoft disrupts EvilTokens", "claims": claims}, SOURCES)
    return [c.status for c in rep.claims], rep

def test_planted_wrong_number_caught():
    bad = {"claim": "EvilTokens compromised 120,000 inboxes.", "source": 1,
           "quote": "it disrupted EvilTokens, a device-code phishing service that compromised 12,000 inboxes"}
    st, _ = _statuses([bad])
    assert st == ["number_mismatch"]

def test_planted_invented_quote_caught():
    bad = {"claim": "Microsoft blamed a nation-state group.", "source": 1,
           "quote": "Microsoft attributed the operation to a Russian state-backed group"}
    st, _ = _statuses([bad])
    assert st == ["quote_not_found"]

def test_planted_fake_cve_caught():
    bad = {"claim": "The flaw is tracked as CVE-2026-99999.", "source": 1,
           "quote": "Researchers tracked the flaw as CVE-2026-41234 and CISA added it to its catalog"}
    st, _ = _statuses([bad])
    assert st == ["number_mismatch"]

def test_nonexistent_source_caught():
    st, _ = _statuses([{**GOOD, "source": 7}])
    assert st == ["bad_source"]

def test_good_claim_verified_and_corroborated():
    st, rep = _statuses([GOOD])
    assert st == ["verified"]
    assert rep.claims[0].corroborated_by == ["thehackernews.com"]


# --- helpers -----------------------------------------------------------------
def test_numbers_normalized():
    assert numbers("12,000 inboxes in 40 countries, v2.0") == {"12000", "40", "2"}

def test_quote_tolerates_typography():
    assert quote_in_text("the company said", "... across 40 countries, the company said.")
    assert quote_in_text("Microsoft’s  team said it disrupted EvilTokens", "Microsoft's team said it disrupted EvilTokens today")

def test_copy_detection():
    prose = "Microsoft said on Tuesday it disrupted EvilTokens, a device-code phishing service that compromised 12,000 inboxes."
    assert copied_runs(prose, [A])
    assert not copied_runs("Microsoft shut down a phishing kit linked to thousands of hacked mailboxes.", [A])


# --- truth score -------------------------------------------------------------
def test_truth_score_rewards_evidence():
    _, rep = _statuses([GOOD])
    two = truth.compute(rep, SOURCES)
    one = truth.compute(rep, SOURCES[:1])
    assert two.total > one.total
    assert truth.compute(rep, SOURCES, disputed=True).label == "Disputed"
    assert sum(p[1] for p in two.parts) == two.total


# --- editor hard rules (no AI needed) -----------------------------------------
def _draft(**kw):
    d = {"headline": "Microsoft takes down EvilTokens phishing kit",
         "in_brief": "Microsoft shut down a phishing service tied to 12,000 hacked inboxes. It worked across 40 countries.",
         "so_what": "Device-code phishing is growing.", "what_to_do": "", "claims": [GOOD, GOOD]}
    d.update(kw)
    return d

def test_editor_holds_on_invented_number():
    d = _draft(in_brief="Microsoft shut down a phishing service tied to 90,000 hacked inboxes.")
    rep = verify(d, SOURCES)
    dec = editor.review(None, "threat", d, rep, SOURCES, truth_total=60)
    assert dec.verdict == "HOLD" and any("90000" in r for r in dec.reasons)

def test_editor_holds_on_copying():
    d = _draft(so_what="Microsoft said on Tuesday it disrupted EvilTokens, a device-code phishing service that compromised 12,000 inboxes.")
    rep = verify(d, SOURCES)
    dec = editor.review(None, "threat", d, rep, SOURCES, truth_total=60)
    assert dec.verdict == "HOLD" and any("copied" in r for r in dec.reasons)

def test_editor_holds_when_too_few_verified_claims():
    d = _draft(claims=[GOOD, {"claim": "x 5", "source": 1, "quote": "nope nope nope nope nope nope"}])
    rep = verify(d, SOURCES)
    dec = editor.review(None, "threat", d, rep, SOURCES, truth_total=60)
    assert dec.verdict == "HOLD"

def test_editor_publishes_clean_draft_without_ai():
    d = _draft()
    rep = verify(d, SOURCES)
    dec = editor.review(None, "threat", d, rep, SOURCES, truth_total=60)
    assert dec.verdict == "PUBLISH", dec.reasons


# --- primary evidence must match THIS story -------------------------------------
def test_kev_counts_only_for_cves_the_story_names():
    kev = {"CVE-2026-41234": {"vulnerabilityName": "x"}}
    d = {"headline": "Microsoft disrupts EvilTokens", "claims": [GOOD], "in_brief": "", "so_what": ""}
    assert verify(d, SOURCES, kev=kev).kev_hits == []            # CVE only in source background
    d2 = {**d, "so_what": "The flaw is tracked as CVE-2026-41234."}
    assert verify(d2, SOURCES, kev=kev).kev_hits == ["CVE-2026-41234"]

def test_subject_own_statement_detected():
    vendor = Source(n=3, outlet="OpenAI", owner="openai.com", url="https://openai.com/news/x", published="z",
                    text="OpenAI will give Ukraine access to Daybreak.", authority=0.75, kind="vendor")
    rep = verify({"headline": "OpenAI gives Ukraine Daybreak access", "claims": []}, SOURCES + [vendor])
    assert any(p["type"] == "subject's own statement" for p in rep.primary)

def test_myth_section_skips_politics():
    from synthesis.models import Article, Cluster, RawItem
    def cl(title):
        a = Article(raw=RawItem(source="Full Fact", title=title, url="https://fullfact.org/x", section="myth"))
        return Cluster(id="c", articles=[a], centroid_title=title)
    from synthesis.sections import section_of
    assert section_of(cl("AI image of teachers protesting pride flag removal is fake")) is None
    assert section_of(cl("Viral video of shark on flooded highway is AI-generated")) == "myth"


# --- false-alarm fixes found in the first live run -------------------------------
def test_list_numbering_is_not_a_fact():
    from synthesis.verify import prose_number_problems
    assert prose_number_problems("1. Patch now. 2. Reset passwords. 3. Enable MFA.", SOURCES) == []
    assert prose_number_problems("Patch within 7 days.", SOURCES) != []

def test_unicode_hyphen_cve():
    from synthesis.verify import cves
    assert cves("CVE‑2026‑41234") == {"CVE-2026-41234"}

def test_ellipsis_quote_fragments():
    assert quote_in_text("Microsoft said on Tuesday it disrupted EvilTokens ... the company said", A)
    assert not quote_in_text("Microsoft said on Tuesday it disrupted EvilTokens ... it was a Russian group all along", A)

def test_source_year_counts_as_known():
    src = Source(n=1, outlet="X", owner="x.com", url="https://x.com/a", published="Tue, 22 Sep 2026 10:00:00 GMT",
                 text="The attack happened on June 18 and was disclosed Sept. 10.", authority=0.8)
    rep = verify({"headline": "h", "claims": [{"claim": "The attack happened in June 2026.", "source": 1,
                                               "quote": "The attack happened on June 18 and was disclosed"}]}, [src])
    assert rep.claims[0].status == "verified"


def test_restore_lost_apostrophes():
    from synthesis.editor import restore_apostrophes
    src = [Source(n=1, outlet="G", owner="g", url="https://g.com", published=None,
                  text="She set the women’s Rubik's Cube record.", authority=0.8)]
    assert restore_apostrophes("New women s Rubik s Cube standard", src) == "New women's Rubik's Cube standard"
    assert restore_apostrophes("It s fine", src) == "It s fine"   # not in sources: untouched


def test_ellipsis_cannot_splice_distant_sentences():
    far = "Coinbase already offers floating-rate loans to many customers. " + ("Filler sentence here. " * 40) + \
          "The lending business has more than $1.4 billion in active loans."
    assert not quote_in_text("Coinbase already offers floating-rate loans ... has more than $1.4 billion in active loans", far)
    near = "Coinbase already offers floating-rate loans to customers, and the lending business has more than $1.4 billion in active loans."
    assert quote_in_text("Coinbase already offers floating-rate loans ... has more than $1.4 billion in active loans", near)


# --- weekly newsletter + sign-up box ---------------------------------------------
def _st(i, section, score, head, date="2026-09-24", urls=None):
    return {"id": f"s{i}", "date": date, "section": section, "headline": head, "in_brief": "b", "what_to_do": "",
            "truth": {"total": score, "label": "Confirmed"}, "sources": [{"owner": "a"}, {"owner": "b"}],
            "also_covered_urls": urls or [f"https://x.com/{i}"]}

def test_weekly_picks_best_per_section_and_skips_repeats():
    from synthesis.site import pick_weekly
    issues = [
        {"date": "2026-09-10", "stories": [_st(0, "threat", 99, "Too old to include")]},
        {"date": "2026-09-23", "stories": [_st(1, "threat", 80, "F5 BIG-IP zero-day exploited", urls=["https://a.com/f5"]),
                                           _st(2, "threat", 70, "WordPress plugin flaw exploited")]},
        {"date": "2026-09-24", "stories": [_st(3, "threat", 90, "F5 BIG-IP zero-day exploited update", urls=["https://a.com/f5"]),
                                           _st(4, "threat", 60, "Third threat story"), _st(5, "ai", 50, "AI story")]},
    ]
    ids = [s["id"] for s in pick_weekly(issues)]
    assert "s0" not in ids                      # outside the 7-day window
    assert "s3" in ids and "s1" not in ids      # same story twice -> keep the better-scored one
    assert sum(1 for s in pick_weekly(issues) if s["section"] == "threat") == 2
    assert ids[-1] == "s5"                      # sections in brief order

def test_subscribe_box_only_with_real_url():
    from synthesis.site import subscribe_box
    assert subscribe_box({"subscribe_url": ""}) == ""
    assert subscribe_box({"subscribe_url": "javascript:alert(1)"}) == ""
    assert "https://pdb.kit.com" in subscribe_box({"subscribe_url": "https://pdb.kit.com"})
