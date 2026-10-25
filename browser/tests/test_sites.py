"""Opening a website by voice: parsing, what gets spoken, and the flow on the fake agent (no Chrome)."""
import asyncio

import goals
import runner
import sites
from sites import SitePlan


def p(text):
    return goals.parse_regex(text)


def test_known_names_and_domains():
    assert p("go to Instagram") == SitePlan("https://www.instagram.com/", "Instagram")
    assert p("open X") == SitePlan("https://x.com/", "X")
    assert p("Can you open Twitter please") == SitePlan("https://x.com/", "X")
    assert p("take me to reddit.") == SitePlan("https://www.reddit.com/", "Reddit")
    assert p("go to nytimes.com") == SitePlan("https://nytimes.com", "The New York Times")
    assert p("go to the New York Times website") == SitePlan("https://www.nytimes.com/", "The New York Times")
    assert p("open hacker news") == SitePlan("https://news.ycombinator.com/", "Hacker News")
    assert p("go to calhacks dot io") == SitePlan("https://calhacks.io", "Cal Hacks")
    assert p("open example.org/about") == SitePlan("https://example.org/about", "example.org")


def test_unknown_name_goes_through_google():
    assert p("go to the Exploratorium website") == SitePlan("", "Exploratorium")


def test_other_goals_unchanged():
    assert p("open youtube") == goals.YouTubePlan("open")
    assert p("go to YouTube and play lofi") == goals.YouTubePlan("play", "lofi")
    assert p("open the first one") == goals.YouTubePlan("pick", pick=1)
    assert isinstance(p("email Sam that I'm running late"), goals.EmailPlan)
    assert isinstance(p("when does Ace Hardware close"), goals.LookupPlan)


def test_refuses_engagement():
    for text in ["go to Instagram and like the first post", "open X and post hello", "go to reddit and delete my comment"]:
        assert p(text) == goals.Unsupported(sites.REFUSE), text
    assert p("go to Amazon and buy batteries") == goals.Unsupported(goals.NO_MONEY)


def test_say():
    plan = SitePlan("https://www.nytimes.com/", "The New York Times")
    page = {"title": "The New York Times - Breaking News, US News, World News and Videos"}
    assert sites.say(plan, page, "Top story: a storm hits the coast.") == "The New York Times is open. Top story: a storm hits the coast."
    assert sites.say(SitePlan("https://x.com/", "X"), {"title": "Home / X"}, "") == "X is open."
    assert sites.say(SitePlan("", "Exploratorium"), {"title": "Exploratorium | Museum"}, "") == "Exploratorium is open."


def test_summary_without_claude_uses_description():
    page = {"title": "Cal Hacks", "description": "The largest collegiate hackathon in the world, at UC Berkeley."}
    assert asyncio.run(sites.summary(page)) == "The largest collegiate hackathon in the world, at UC Berkeley."


def test_run_task_opens_known_site():
    out = asyncio.run(runner.run_task("go to Instagram"))
    assert out["say"].startswith("Instagram is open")
    assert runner.store.current.browser.url == "https://www.instagram.com/"


def test_run_task_resolves_unknown_site_via_google():
    out = asyncio.run(runner.run_task("open the cal hacks event page website"))
    assert "is open" in out["say"]
    assert runner.store.current.browser.url == "https://www.calhacks.io/"
