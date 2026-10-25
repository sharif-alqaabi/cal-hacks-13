"""YouTube goal: parsing and what gets spoken (no Chrome)."""
import goals
import youtube
from youtube import Video, YouTubePlan


def p(text):
    return goals.parse_regex(text)


def test_parse_actions():
    assert p("play the latest video from James Hoffmann on YouTube") == YouTubePlan("latest", "James Hoffmann")
    assert p("Play the newest video by MKBHD") == YouTubePlan("latest", "MKBHD")
    assert p("find videos about cold brew coffee on YouTube") == YouTubePlan("search", "cold brew coffee")
    assert p("search YouTube for lofi hip hop") == YouTubePlan("search", "lofi hip hop")
    assert p("play lofi hip hop on YouTube") == YouTubePlan("play", "lofi hip hop")
    assert p("play number two") == YouTubePlan("pick", pick=2)
    assert p("play the first one") == YouTubePlan("pick", pick=1)
    assert p("three") == YouTubePlan("pick", pick=3)
    assert p("pause") == YouTubePlan("pause")
    assert p("pause the video.") == YouTubePlan("pause")
    assert p("resume") == YouTubePlan("resume")
    assert p("keep playing") == YouTubePlan("resume")


def test_email_and_lookup_unchanged():
    assert isinstance(p("email Sam that I'm at the Palace of Fine Arts"), goals.EmailPlan)
    assert isinstance(p("when does Ace Hardware close"), goals.LookupPlan)


def test_refuses_engagement_and_money():
    for text in ["subscribe to James Hoffmann on YouTube", "like this video", "comment on the YouTube video",
                 "buy YouTube premium"]:
        plan = p(text)
        assert isinstance(plan, goals.Unsupported), text
    assert p("subscribe to James Hoffmann on YouTube").say == youtube.REFUSE


def test_length_from_aria():
    assert youtube._length("Cold Brew", "Cold Brew 4 minutes, 21 seconds") == "4 minutes"
    assert youtube._length("Q&A", "Q&A 1 hour, 2 minutes") == "1 hour, 2 minutes"
    assert youtube._length("Short", "Short 45 seconds") == "45 seconds"
    assert youtube._length("Live", "Live") == ""


def test_results_say():
    vs = [Video("A | B", "Chan", "4 minutes", "u1"), Video("C", "D", "", "u2"), Video("E", "F", "1 hour", "u3")]
    say = youtube.results_say("cold brew", vs)
    assert say == ("Top results for cold brew. One: A, B, by Chan, 4 minutes. Two: C, by D. "
                   "Three: E, by F, 1 hour. Say play one, two or three.")


def test_clean_drops_emoji():
    assert youtube._clean("lofi hip hop radio 📚 beats | study") == "lofi hip hop radio beats, study"
