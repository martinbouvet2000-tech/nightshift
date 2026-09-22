from __future__ import annotations

from nightshift.classify import classify_text
from nightshift.linking import NoteRef, related
from nightshift.models import Item
from nightshift.profile import Profile, load_profile, score_idea
from nightshift.scoring import signal_score, tool_recurrence

from conftest import PROFILE


def _item(transcript, tools=(), author="a", title="t", **ext):
    extraction = {"tools": [{"name": n} for n in tools], "urls": [], "techniques": [], "prompts": []}
    extraction.update(ext)
    return Item(id=title, source="t", title=title, author=author, transcript=transcript,
                extraction=extraction)


def test_score_bounds_and_thin_content():
    assert 0 <= signal_score(_item("")) <= 100
    assert signal_score(_item("")) < signal_score(_item("word " * 100))


def test_density_and_tools_raise_score():
    short = signal_score(_item("x " * 150))
    long = signal_score(_item("x " * 1500, tools=["A", "B", "C"]))
    assert long > short


def test_hype_penalty():
    clean = _item("Useful content " * 100)
    baity = _item("Useful content " * 100 + " comment below and check the link in bio, "
                  "follow for more, limited time")
    assert signal_score(baity) <= signal_score(clean) - 21


def test_cross_author_recurrence():
    items = [_item("x " * 500, tools=["Tool"], author=a, title=a) for a in "abcd"]
    rec = tool_recurrence(items)
    assert rec["Tool"] == {"a", "b", "c", "d"}
    alone = signal_score(items[0], {"Tool": {"a"}})
    assert signal_score(items[0], rec) == alone + 10


def test_github_repos_raise_score():
    base = _item("x " * 500)
    repo = _item("x " * 500 + " see github.com/example-org/repo-one and github.com/example-org/repo-two")
    assert signal_score(repo) == signal_score(base) + 6


def test_profile_fit_interests_and_avoid():
    p = Profile(interests=["developer tools", "education"], skills=["python"], avoid=["crypto"])
    good, verdict, reasons = score_idea({"title": "Developer tools for education written in python"}, p)
    neutral, _, _ = score_idea({"title": "A bakery delivery app"}, p)
    bad, bad_verdict, _ = score_idea({"title": "Crypto trading bot for developer tools"}, p)
    assert good > neutral > bad
    assert verdict == "strong fit" and bad_verdict in ("weak fit", "skip")
    assert any("interests" in r for r in reasons)


def test_profile_constraints():
    p = Profile(solo=True, max_budget_usd=1000, hours_per_week=5)
    idea = {"title": "Agency", "idea": "Hire a team of five, costs $20k, runs 24/7"}
    score, verdict, reasons = score_idea(idea, p)
    assert score == 5 and verdict == "skip" and len(reasons) == 3


def test_example_profile_loads():
    p = load_profile(str(PROFILE))
    assert p.interests and p.skills and p.avoid and p.solo is True
    assert load_profile(None).interests == []
    assert load_profile("does-not-exist.yaml").interests == []


def test_classify():
    assert classify_text("an agent with tool use and function calling, agents everywhere")[0] == "agents"
    assert classify_text("") == ["general"]


def test_related_links():
    a = NoteRef("A", {"agents", "coding"}, "x", {"python", "agents"})
    b = NoteRef("B", {"agents", "coding"}, "y", set())
    c = NoteRef("C", {"design"}, "z", set())
    rel = related(a, [a, b, c])
    assert [s for s, _ in rel] == ["B"]
    assert "shared topics" in rel[0][1]
