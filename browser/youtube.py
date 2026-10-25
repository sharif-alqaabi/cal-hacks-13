"""YouTube by voice: search and read the top results aloud, play one, play a channel's latest upload, pause, resume.

No model in the loop: URLs are built from the request and titles, channels and lengths are read straight from
YouTube's DOM, so it is fast and says exactly what is on the page. Selectors live only here.
Safety: the only things this file ever clicks are the video itself (keyboard "k") and "Skip ad". It never
subscribes, likes, comments, posts or buys; those requests are refused in goals.parse.
"""
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote_plus

import agents

log = logging.getLogger("browser.youtube")

TOP_N = 3
LOAD_S = 8.0

LEAD = r"^(?:hey |ok |okay )?(?:can you |could you |would you |please |go ahead and |i want to |i'd like to )*"
TAIL = r"(?:\s+(?:on|from|in) youtube)?(?:\s+please)?[.!?]*$"
ORDINALS = {"one": 1, "1": 1, "first": 1, "top": 1, "two": 2, "2": 2, "second": 2,
            "three": 3, "3": 3, "third": 3, "last": 3}

PAUSE_RX = re.compile(LEAD + r"(?:pause|stop)(?: (?:it|that|the video|the music|youtube|playing|the youtube video))?" + TAIL, re.I)
RESUME_RX = re.compile(LEAD + r"(?:resume|unpause|keep playing|continue(?: playing| the video)?|play|play it|"
                       r"start it again|keep going)(?: (?:it|the video|again))?" + TAIL, re.I)
PICK_RX = re.compile(LEAD + r"(?:play|pick|choose|open|watch|go with)?\s*(?:the\s+)?(?:number\s+)?"
                     r"(?P<n>one|two|three|1|2|3|first|second|third|top|last)(?:\s+(?:one|video|result))?" + TAIL, re.I)
LATEST_RX = re.compile(LEAD + r"(?:play|put on|show me|watch|find)?\s*(?:me\s+)?(?:the\s+)?(?:latest|newest|most recent|new)\s+"
                       r"(?:youtube\s+)?(?:video|upload|episode)\s+(?:from|by|on)\s+(?P<ch>.+?)(?:'s)?(?:\s+channel)?" + TAIL, re.I)
SEARCH_RX = re.compile(LEAD + r"(?:find|search(?: youtube)?(?: for)?|look up|look for|show me|get me|what are)\s+"
                       r"(?:me\s+)?(?:some\s+|a\s+|the\s+)?(?:youtube\s+)?(?:videos?|clips?)\s+(?:about|on|of|for|with)\s+"
                       r"(?P<q>.+?)" + TAIL, re.I)
SEARCH_YT_RX = re.compile(LEAD + r"(?:search|look up|find|look for)\s+(?:on\s+)?youtube\s+(?:for\s+)?(?P<q>.+?)[.!?]*$", re.I)
PLAY_RX = re.compile(LEAD + r"(?:play|put on|watch)\s+(?:me\s+)?(?:a video (?:about|of|on)\s+)?(?P<q>.+?)" + TAIL, re.I)
OPEN_RX = re.compile(LEAD + r"(?:open|go to|launch|pull up|bring up)\s+(?:up\s+)?youtube(?:\s+and)?\s*", re.I)
GENERIC_SEARCH_RX = re.compile(r"^(?:search|find|look up|look for|show me|get me|pull up)\s+(?:up\s+)?(?:for\s+)?(?:some\s+|a\s+)?"
                               r"(?:(?:youtube\s+)?(?:videos?|clips?)\s+(?:about|on|of|for|with)\s+)?(?P<q>.+?)" + TAIL, re.I)
UNSAFE_RX = re.compile(r"\b(subscribe|unsubscribe|comment|like (?:it|this|the video|that)|dislike|upload|post|"
                       r"super ?chat|membership|join (?:the |this )?channel)\b", re.I)
MENTIONS_RX = re.compile(r"\b(youtube|video|videos)\b", re.I)

REFUSE = "On YouTube I can find, read out, play and pause videos. I can't subscribe, like, comment or post."


@dataclass
class YouTubePlan:
    action: str          # search | play | latest | pick | pause | resume | open
    query: str = ""
    pick: int = 0


@dataclass
class Video:
    title: str
    channel: str
    length: str
    href: str


def parse(goal: str) -> YouTubePlan | str | None:
    """A plan, REFUSE for unsafe YouTube asks, or None when this isn't a YouTube request."""
    text = " ".join(goal.replace("’", "'").split())
    if MENTIONS_RX.search(text) and UNSAFE_RX.search(text):
        return REFUSE
    if PAUSE_RX.match(text):
        return YouTubePlan("pause")
    if RESUME_RX.match(text):
        return YouTubePlan("resume")
    if m := PICK_RX.match(text):
        return YouTubePlan("pick", pick=ORDINALS[m.group("n").lower()])
    if m := LATEST_RX.match(text):
        return YouTubePlan("latest", query=m.group("ch").strip())
    if m := (SEARCH_RX.match(text) or SEARCH_YT_RX.match(text)):
        return YouTubePlan("search", query=m.group("q").strip())
    if m := PLAY_RX.match(text):
        return YouTubePlan("play", query=m.group("q").strip())
    if MENTIONS_RX.search(text):   # "open YouTube and search for iPhone 16 reviews", "search for X on YouTube"
        rest = OPEN_RX.sub("", text, count=1)
        if not rest.strip(" .!?"):
            return YouTubePlan("open")
        if rest != text and (m := PLAY_RX.match(rest)):
            return YouTubePlan("play", query=m.group("q").strip())
        if m := GENERIC_SEARCH_RX.match(rest):
            q = m.group("q").strip()
            return YouTubePlan("open") if q.lower() in {"videos", "a video", "something", "youtube"} else YouTubePlan("search", query=q)
    return None


# ---- page reading -----------------------------------------------------------

RESULTS_JS = r"""(() => [...document.querySelectorAll('ytd-video-renderer')].slice(0, 8).map(r => {
  const a = r.querySelector('a#video-title');
  const ch = r.querySelector('ytd-channel-name a');
  return {title: a ? (a.getAttribute('title') || a.innerText || '').trim() : '', aria: a ? a.getAttribute('aria-label') || '' : '',
          href: a ? a.href : '', channel: ch ? ch.innerText.trim() : '', channel_href: ch ? ch.href : ''};
}).filter(v => v.title && v.href.includes('/watch')))()"""

CHANNEL_JS = r"""(() => {
  const c = document.querySelector('ytd-channel-renderer');
  const a = c && c.querySelector('a[href*="/@"], a#main-link, a.channel-link');
  const n = c && c.querySelector('#channel-title #text, ytd-channel-name #text');
  return a ? {href: a.href, name: n ? n.innerText.trim() : ''} : null;
})()"""

UPLOADS_JS = r"""(() => [...document.querySelectorAll('ytd-rich-item-renderer')].slice(0, 3).map(r => {
  const a = r.querySelector('a#video-title-link, a#video-title, a.yt-lockup-metadata-view-model__title, h3 a');
  return {title: a ? (a.getAttribute('title') || a.innerText || '').trim() : '', aria: a ? a.getAttribute('aria-label') || '' : '',
          href: a ? a.href : ''};
}).filter(v => v.title && v.href.includes('/watch')))()"""

PLAYER_JS = r"""(() => {
  const v = document.querySelector('#movie_player video, video');
  const p = document.querySelector('#movie_player');
  const ch = document.querySelector('ytd-watch-metadata ytd-channel-name a, #owner ytd-channel-name a');
  const t = document.querySelector('ytd-watch-metadata h1, h1.ytd-watch-metadata');
  return {ok: !!v, paused: v ? v.paused : true, ad: !!(p && p.classList.contains('ad-showing')),
          channel: ch ? ch.innerText.trim() : '', title: t ? t.innerText.trim() : document.title.replace(/ - YouTube$/, '')};
})()"""

SKIP_RECT_JS = r"""(() => {
  const b = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button');
  if (!b || !b.offsetParent) return null;
  const r = b.getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
})()"""


def search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)


def goal(plan: YouTubePlan) -> str:
    return (f"On YouTube, find videos for \"{plan.query}\". Never subscribe, like, comment, sign in or buy anything.")


def _length(title: str, aria: str) -> str:
    """aria-label is '<title> 4 minutes, 21 seconds' (sometimes with views); keep the duration words."""
    rest = aria[len(title):] if aria.startswith(title) else aria
    m = re.search(r"(\d+ hours?,? ?)?(\d+ minutes?,? ?)?(\d+ seconds?)?", rest.strip())
    words = (m.group(0) if m else "").strip(" ,")
    if not words:
        return ""
    # "4 minutes, 21 seconds" -> "4 minutes" (seconds don't help a listener choose); under a minute keep seconds
    return re.sub(r",? ?\d+ seconds?$", "", words) if "minute" in words or "hour" in words else words


def _video(raw: dict, channel: str = "") -> Video:
    return Video(title=raw["title"], channel=raw.get("channel") or channel, length=_length(raw["title"], raw.get("aria", "")),
                 href=raw["href"])


def _wait_for(browser, js: str, timeout: float = LOAD_S, ready=bool):
    deadline = time.monotonic() + timeout
    while True:
        try:
            v = browser.evaluate(js)
        except Exception:
            v = None
        if ready(v) or time.monotonic() >= deadline:
            return v
        time.sleep(0.25)


def read_results(browser) -> list[Video]:
    return [_video(r) for r in (_wait_for(browser, RESULTS_JS) or [])][:TOP_N]


def latest_from(browser, channel: str) -> Video | None:
    """The channel's newest upload: its card at the top of the search page (already open), then its Videos tab."""
    ch = _wait_for(browser, CHANNEL_JS, timeout=4.0)
    name = (ch or {}).get("name", "")
    href = (ch or {}).get("href")
    if not href:   # no channel card: take the channel of the top video result
        rows = _wait_for(browser, RESULTS_JS) or []
        href = next((r["channel_href"] for r in rows if r.get("channel_href")), None)
        name = next((r["channel"] for r in rows if r.get("channel_href")), "")
    if not href:
        return None
    agents.navigate(browser, href.rstrip("/") + "/videos")
    time.sleep(0.5)   # the old page's cards can linger for a moment
    ups = _wait_for(browser, UPLOADS_JS)
    return _video(ups[0], channel=name or channel) if ups else None


def play(browser, video: Video) -> dict:
    """Open the watch page and make sure it is playing. Returns the player state."""
    agents.navigate(browser, video.href)
    time.sleep(0.5)
    st = _wait_for(browser, PLAYER_JS, ready=lambda v: bool(v and v.get("ok"))) or {}
    if not st.get("ok"):
        return {}
    deadline = time.monotonic() + 3
    while st and st.get("paused") and not st.get("ad") and time.monotonic() < deadline:
        resume(browser)
        time.sleep(0.5)
        st = browser.evaluate(PLAYER_JS) or st
    return st


def pause(browser) -> bool:
    return bool(_eval_gesture(browser, "(() => { const v = document.querySelector('video'); if (!v) return false; "
                                       "v.pause(); return true; })()"))


def resume(browser) -> bool:
    return bool(_eval_gesture(browser, "(async () => { const v = document.querySelector('video'); if (!v) return false; "
                                       "try { await v.play(); } catch (e) {} return !v.paused; })()"))


def player(browser) -> dict:
    try:
        return browser.evaluate(PLAYER_JS) or {}
    except Exception:
        return {}


def _eval_gesture(browser, expression: str):
    """Runtime.evaluate as a user gesture, so Chrome's autoplay policy lets play() through."""
    try:
        r = browser.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True,
                         userGesture=True)
        return (r or {}).get("result", {}).get("value")
    except Exception as e:
        log.warning("player call failed: %r", e)
        return None


skip_stop = threading.Event()   # set when the next request arrives, so "pause" never waits behind the skipper


def skip_ads(browser, budget_s: float = 12.0) -> None:
    """Press "Skip ad" when it appears (a real mouse click; YouTube ignores synthetic ones).
    Runs on the browser thread after the reply; stops when the ad ends or another request comes in."""
    skip_stop.clear()
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline and not skip_stop.is_set():
        st = player(browser)
        if not st.get("ad"):
            return
        try:
            rect = browser.evaluate(SKIP_RECT_JS)
        except Exception:
            rect = None
        if rect:
            for kind in ("mousePressed", "mouseReleased"):
                browser.call("Input.dispatchMouseEvent", type=kind, x=rect["x"], y=rect["y"], button="left", clickCount=1)
            log.info("skipped an ad")
        time.sleep(0.5)


# ---- what to say ------------------------------------------------------------

NUMBER_WORDS = ["one", "two", "three"]


def _clean(title: str) -> str:
    """Titles as speech: emoji and symbols dropped, "|" read as a pause."""
    title = "".join(c for c in title if unicodedata.category(c) not in {"So", "Sk", "Cs"})
    return " ".join(re.sub(r"\s*\|\s*", ", ", title).split()).rstrip(".")


def describe(v: Video, with_channel: bool = True) -> str:
    out = _clean(v.title)
    if with_channel and v.channel:
        out += f", by {v.channel}"
    if v.length:
        out += f", {v.length}"
    return out


def results_say(query: str, videos: list[Video]) -> str:
    if not videos:
        return f"I couldn't find any YouTube videos for {query}."
    lines = " ".join(f"{NUMBER_WORDS[i].capitalize()}: {describe(v)}." for i, v in enumerate(videos))
    choices = ", ".join(NUMBER_WORDS[:len(videos)])
    choices = choices.rsplit(", ", 1)[0] + " or " + NUMBER_WORDS[len(videos) - 1] if len(videos) > 1 else choices
    return f"Top results for {query}. {lines} Say play {choices}."


def playing_say(v: Video, st: dict, latest: bool = False) -> str:
    if not st:
        return f"I opened {_clean(v.title)}, but I couldn't start the video."
    head = f"Playing the latest video from {v.channel}: " if latest and v.channel else "Playing "
    body = describe(v, with_channel=not latest)
    tail = " An ad is playing first; I'll skip it when I can." if st.get("ad") else ""
    return f"{head}{body}.{tail} Say pause to stop it."
