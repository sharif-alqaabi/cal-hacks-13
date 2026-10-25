"""Spoken request -> what to do: an email (to a known contact), a web lookup, YouTube (youtube.py), opening a
website (sites.py) or reading the inbox (inbox.py); the last three are rules only.

Claude Sonnet parses first (better message wording); regex rules are the fallback when there's no key,
the call fails or it takes more than 3 s. Recipients only come from DEMO_CONTACTS: the agent never guesses an address.
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import config
import inbox
import llm
import sites
import youtube
from inbox import InboxPlan
from sites import NavPlan, SitePlan, TabPlan
from youtube import YouTubePlan

log = logging.getLogger("browser.goals")


@dataclass
class EmailPlan:
    to_name: str
    message: str
    subject: str
    to_addr: str | None = None


@dataclass
class LookupPlan:
    query: str
    listing: bool = False   # "search for X" / "google X": read the top results instead of answering


@dataclass
class WebPlan:
    url: str    # https start page, ideally the site's own search URL
    goal: str   # one short instruction for Jev Ultrafast
    site: str   # spoken name, e.g. "Spotify"


@dataclass
class Unsupported:
    say: str


NOT_SUPPORTED = ("On the laptop I can send an email, read your new emails, look something up, open a website, "
                 "play YouTube videos, or do simple things on other websites.")
NO_MONEY = "I can't buy or pay for things. I can send an email or look something up."

MONEY_RX = re.compile(r"\b(buy|purchase|pay|order|checkout|check out|subscribe|donate|transfer money|venmo)\b", re.I)
LEAD = r"^(?:hey |ok |okay )?(?:can you |could you |would you |please |go ahead and )*"
EMAIL_RXS = [
    re.compile(LEAD + r"(?:send |write |shoot |draft )?(?:an? |a quick )?(?:e-?mail|message|note)(?: to)? "
               r"(?P<name>[\w.@+-]+)[,:]?\s*(?:(?:that|saying|to say|and say|and tell (?:him|her|them)(?: that)?)\s+)?"
               r"(?P<msg>.*?)[.!?]*$", re.I),
    re.compile(LEAD + r"(?:e-?mail|tell|let) (?P<name>[\w.@+-]+)(?: know)?(?: by e-?mail)?\s+(?:that\s+)?"
               r"(?P<msg>.+?)[.!?]*$", re.I),
]
LOOKUP_RX = re.compile(
    r"\b(look up|look it up|search|google|find out|when does|when do|what time|what are the hours|how late|"
    r"opening hours|closing time|is (?:the |it )?[\w' ]*open)\b", re.I)
LOOKUP_STRIP = re.compile(LEAD + r"(?:look up|search for|search|google|find out)\s+", re.I)
LISTING_RX = re.compile(LEAD + r"(?:search|google)(?: google| search)?(?:\s+for)?\s+"
                        r"(?!(?:for|google|search|when|what|how|where|who|why|is|are|does|do|can)\b)", re.I)

JEV_SUFFIX = " Never post, buy, pay, sign in or delete anything."

PARSE_SYSTEM = """You turn a blind user's spoken request for their laptop into JSON. Reply with JSON only:
{"kind": "email" | "lookup" | "web" | "unsupported", "to_name": "", "message": "", "subject": "", "query": "",
 "url": "", "goal": "", "site": ""}
email: to_name is the recipient exactly as spoken (usually a first name); message is the email body in the
user's own first-person voice, one or two short sentences, keeping their words; subject is 3 to 7 words.
lookup: query is a short web search query that answers the question.
web: a task on a website in Chrome (not YouTube, not Gmail, not opening a site only to read it). url is an https
start page that gets close to the goal (prefer the site's own search URL when possible, e.g.
https://open.spotify.com/search/bohemian%20rhapsody). goal is one short instruction for a browser agent on that page.
site is the spoken site name (e.g. Spotify).
unsupported: purchases, payments, passwords, uploads, desktop apps, or anything outside the web browser."""


def contacts() -> dict[str, str]:
    out = {}
    for pair in config.DEMO_CONTACTS.split(","):
        if "=" in pair:
            name, addr = pair.split("=", 1)
            out[name.strip().lower()] = addr.strip()
    return out


def resolve(name: str) -> str | None:
    if "@" in name:
        return name.strip()
    book = contacts()
    key = name.strip().lower()
    return book.get(key) or book.get(key.split()[0] if key else "")


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".!?,;: ")
    return (text[:1].upper() + text[1:] + ".") if text else ""


def subject_for(message: str) -> str:
    words = message.rstrip(".!?").split()
    subject = " ".join(words if len(words) <= 10 else words[:7] + ["..."])
    return subject[:1].upper() + subject[1:]


def _email(name: str, message: str, subject: str = "") -> EmailPlan:
    message = _sentence(message)
    name = name.strip().rstrip(",.")
    display = name if "@" in name else name[:1].upper() + name[1:]
    return EmailPlan(to_name=display, message=message, subject=(subject.strip() or subject_for(message)),
                     to_addr=resolve(name))


def _youtube(goal: str) -> YouTubePlan | Unsupported | None:
    yt = youtube.parse(goal)
    return Unsupported(yt) if isinstance(yt, str) else yt


def _inbox(goal: str) -> InboxPlan | Unsupported | None:
    mail = inbox.parse(goal)
    return Unsupported(mail) if isinstance(mail, str) else mail


def _site(goal: str) -> SitePlan | TabPlan | NavPlan | Unsupported | None:
    site = sites.parse(goal)
    return Unsupported(site) if isinstance(site, str) else site


def _lookup(goal: str, query: str) -> LookupPlan:
    return LookupPlan(query=query, listing=bool(LISTING_RX.match(goal.strip())))


def _valid_https(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.scheme == "https" and bool(p.netloc)
    except Exception:
        return False


def _web(j: dict) -> WebPlan | Unsupported | None:
    url, goal, site = (j.get("url") or "").strip(), (j.get("goal") or "").strip(), (j.get("site") or "").strip()
    if not url or not goal or not site or not _valid_https(url):
        return None
    if MONEY_RX.search(goal) or sites.UNSAFE_RX.search(goal):
        return Unsupported(sites.REFUSE if sites.UNSAFE_RX.search(goal) else NO_MONEY)
    if not goal.endswith(JEV_SUFFIX.strip()):
        goal = goal.rstrip(".") + "." + JEV_SUFFIX
    return WebPlan(url=url, goal=goal, site=site[:1].upper() + site[1:] if site else site)


Plan = EmailPlan | LookupPlan | YouTubePlan | SitePlan | TabPlan | NavPlan | InboxPlan | WebPlan | Unsupported


def parse_regex(goal: str) -> Plan:
    text = goal.strip()
    if yt := _youtube(text):
        return yt
    if mail := _inbox(text):
        return mail
    if MONEY_RX.search(text):
        return Unsupported(NO_MONEY)
    if site := _site(text):
        return site
    for rx in EMAIL_RXS:
        m = rx.match(text)
        if m and (m.group("name").lower() not in {"me", "him", "her", "them", "a", "an"}):
            return _email(m.group("name"), m.group("msg"))
    if LOOKUP_RX.search(text):
        q = LOOKUP_STRIP.sub("", text).strip().rstrip("?.! ")
        return _lookup(text, q or text)
    return Unsupported(NOT_SUPPORTED)


async def parse(goal: str) -> Plan:
    if yt := _youtube(goal):   # before Claude: deterministic and instant, and "pause" must not wait 3 s
        return yt
    if mail := _inbox(goal):
        return mail
    if MONEY_RX.search(goal):
        return Unsupported(NO_MONEY)
    if site := _site(goal):
        return site
    if llm.available():
        j = await llm.ask_json(PARSE_SYSTEM, goal, max_tokens=200, timeout=3.0)
        if j:
            kind = j.get("kind")
            if kind == "email" and j.get("to_name"):
                return _email(j["to_name"], j.get("message", ""), j.get("subject", ""))
            if kind == "lookup" and j.get("query"):
                return _lookup(goal, j["query"].strip())
            if kind == "web":
                web = _web(j)
                if web is not None:
                    return web
            if kind == "unsupported":
                return Unsupported(NOT_SUPPORTED)
        log.info("claude parse unavailable or unusable, using rules")
    return parse_regex(goal)
