"""Reading the top Google results / opening one, and reading the inbox, on the fake agent (no Chrome)."""
import asyncio

import goals
import inbox
import lookup
import runner
from inbox import InboxPlan


def p(text):
    return goals.parse_regex(text)


def run(text):
    return asyncio.run(runner.run_task(text))["say"]


def test_inbox_phrases():
    for text in ["any new emails?", "Do I have any new emails", "read my inbox", "check my email", "what's in my inbox",
                 "read me my new emails", "do I have unread messages", "can you check my mail please"]:
        assert p(text) == InboxPlan("list"), text
    assert p("read the one from Sam") == InboxPlan("read", sender="Sam")
    assert p("read me the email from Sam") == InboxPlan("read", sender="Sam")
    assert p("open the email from Priya") == InboxPlan("read", sender="Priya")
    assert p("read the second one") == InboxPlan("read", pick=2)
    assert p("read it") == InboxPlan("read", pick=1)


def test_inbox_refuses_changes():
    for text in ["delete the email from Sam", "archive my emails", "forward the one from Sam to Priya",
                 "mark my emails as read"]:
        assert p(text) == goals.Unsupported(inbox.REFUSE), text


def test_other_goals_unchanged():
    assert isinstance(p("email Sam that I'm running late"), goals.EmailPlan)
    assert p("open the first one") == goals.YouTubePlan("pick", pick=1)
    assert p("open the second result") == goals.YouTubePlan("pick", pick=2)
    for text in ["click on second result", "click the second link", "open the second website", "go to the second one",
                 "click on the second one", "open result number two", "take me to the second site", "click two",
                 "open up the second search result please"]:
        assert p(text) == goals.YouTubePlan("pick", pick=2), text
    assert p("read the second one") == InboxPlan("read", pick=2)
    assert isinstance(p("go to the Exploratorium website"), goals.SitePlan)
    assert p("when does Ace Hardware close") == goals.LookupPlan("when does Ace Hardware close")
    assert p("search for best tacos in SF") == goals.LookupPlan("best tacos in SF", listing=True)
    assert p("google best tacos in SF") == goals.LookupPlan("best tacos in SF", listing=True)
    assert p("search for when Ace closes").listing is False


def test_results_say():
    rs = [lookup.Result("Where to Find the Best Tacos in San Francisco", "Eater San Francisco", "https://a"),
          lookup.Result("Taco spot : r/AskSF", lookup._site({"site": "Reddit · r/AskSF"}), "https://b")]
    assert lookup.results_say("tacos", rs) == ("Top results for tacos. One: Where to Find the Best Tacos, from Eater "
                                               "San Francisco. Two: Taco spot : r/AskSF, from Reddit. Say open one or two.")


def test_search_then_open_a_result():
    say = run("search for Ace Hardware Polk")
    assert say.startswith("Top results for Ace Hardware Polk. One: Ace Hardware Polk St. Two: Ace Hardware, from Yelp.")
    assert say.endswith("Say open one, two or three.")
    say = run("open the second result")
    assert say.startswith("Opened Yelp.")
    assert runner.store.current.browser.url == "https://www.yelp.com/biz/ace-polk"
    assert run("open the third result").startswith("Opened example.com")


def test_pick_without_search_is_youtube():
    assert run("open the second result") == "Ask me to find videos first, then pick one."


def test_question_keeps_answer_and_results():
    assert run("when does the hardware store close today?") == "It's open now and closes at 9 PM."
    assert run("open the first result").startswith("Opened Ace Hardware.")


def test_inbox_list_and_read():
    say = run("any new emails?")
    assert say == ("You have 2 unread emails. One: from Sam Lee, Lunch tomorrow?. Two: from Google, Security alert. "
                   "Say read the one from, and a name.")
    say = run("read the one from Sam")
    assert say == "From Sam Lee, Lunch tomorrow?. Hi! Want to grab lunch tomorrow at noon at Tartine? Let me know. Sam"
    assert run("read the second one").startswith("From Google, Security alert.")
    assert run("read the email from Priya").startswith("From Priya, Slides.")
    assert run("read the one from Bob") == "I don't see an email from Bob in your inbox."


def test_read_without_listing_first():
    assert run("read the email from Sam").startswith("From Sam Lee")
