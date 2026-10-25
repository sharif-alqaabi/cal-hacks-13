"""Spoken request -> what to do: an email (to a known contact), a web lookup, YouTube (youtube.py), opening a
website or tab (sites.py) or reading the inbox (inbox.py).

The exact phrases in each module's rules are instant shortcuts. Anything they miss goes to Claude Sonnet, which maps
loose wording ("put on some lofi", "anything from Sam?") onto the same plans; the regex rules are the fallback when
there's no key, the call fails or it takes more than 3 s. Claude labels post/like/subscribe/delete asks unsupported,
and the YouTube, inbox and site flows can't do those anyway: they never click anything but a video.
Recipients only come from DEMO_CONTACTS: the agent never guesses an address.
"""
import logging
import re
from dataclasses import dataclass

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
class Unsupported:
    say: str


NOT_SUPPORTED = ("On the laptop I can send an email, read your new emails, look something up, open a website "
                 "or play YouTube videos.")
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

PARSE_SYSTEM = """You turn a blind user's spoken request for their laptop's web browser into JSON. The wording is
loose speech: work out what they mean, not what they literally said. Reply with JSON only:
{"kind": "...", "to_name": "", "message": "", "subject": "", "query": "", "action": "", "pick": 0, "sender": "", "site": ""}
kind is one of:
email: write an email. to_name is the recipient exactly as spoken (usually a first name); message is the email body
  in the user's own first-person voice, one or two short sentences, keeping their words; subject is 3 to 7 words.
lookup: a question to answer from the web. query is a short web search query that answers it.
search: they want Google results listed, not one answer ("google X", "find me some pages about X"). query as above.
youtube: videos or music. action is search (list videos), play (play the top video for query), latest (newest upload
  from the channel in query), pause, resume, or open (just open YouTube). query is what to search for.
inbox: reading their email. action is list (new or unread emails) or read (one email: sender is who it's from, or
  pick is its number 1-3 from the list read out).
pick: choose a numbered result just read out ("the second one", "go with number three"). pick is 1-3.
site: open a website. site is its name or domain ("instagram", "nytimes.com").
new_tab: open a new browser tab; site is optional, the site to open in it.
close_tab: close the current tab.
back / forward: the browser's back or forward arrow.
unsupported: anything else, including purchases, payments, passwords, uploads, apps other than the web browser,
  or posting, liking, subscribing, commenting, deleting, archiving or forwarding anything.
Questions ("what time does Ace close?", "what's the weather?") are lookup, not site."""


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


Plan = EmailPlan | LookupPlan | YouTubePlan | SitePlan | TabPlan | NavPlan | InboxPlan | Unsupported


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


def _ordinal(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= 3 else 0


def _open_site(name: str) -> SitePlan | Unsupported | None:
    """Claude's site name through sites.py's rules, so known names, domains and refusals behave as when spoken."""
    name = name.strip(" .")
    if not name:
        return None
    site = _site(f"open {name}")
    return site if isinstance(site, (SitePlan, Unsupported)) else SitePlan("", sites._title_case(name))


def from_claude(goal: str, j: dict) -> Plan | None:
    """Claude's JSON -> one of the plans the rules make. None when the answer is unusable (the rules then decide)."""
    kind = (j.get("kind") or "").strip().lower()
    action = (j.get("action") or "").strip().lower()
    query = (j.get("query") or "").strip()
    pick = _ordinal(j.get("pick"))
    text = " ".join(goal.replace("’", "'").split())
    if kind == "email" and j.get("to_name"):
        return _email(j["to_name"], j.get("message", ""), j.get("subject", ""))
    if kind in {"lookup", "search"} and query:
        return LookupPlan(query=query, listing=kind == "search" or bool(LISTING_RX.match(goal.strip())))
    if kind == "youtube":
        if action in {"pause", "resume", "open"}:
            return YouTubePlan(action)
        if action in {"search", "play", "latest"} and query:
            return YouTubePlan(action, query=query)
        return YouTubePlan("open") if not query else YouTubePlan("search", query=query)
    if kind == "pick" and pick:
        return YouTubePlan("pick", pick=pick)   # the runner opens a search result or a video, whichever was read out
    if kind == "inbox":
        sender = (j.get("sender") or "").strip()
        if inbox.UNSAFE_RX.search(text.replace(sender, "") if sender else text):   # "Mark" is a name, not "mark as read"
            return Unsupported(inbox.REFUSE)
        if action == "read" and (sender or pick):
            return InboxPlan("read", sender=sender, pick=0 if sender else pick)
        return InboxPlan("list")
    if kind in {"site", "new_tab"}:
        site = _open_site(j.get("site") or "")
        if kind == "new_tab":
            return site if isinstance(site, Unsupported) else TabPlan("new", site)
        return site
    if kind == "close_tab":
        return TabPlan("close")
    if kind in {"back", "forward"}:
        return NavPlan(kind)
    if kind == "unsupported":
        return Unsupported(NOT_SUPPORTED)
    return None


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
        if j and (plan := from_claude(goal, j)):
            return plan
        log.info("claude parse unavailable or unusable, using rules")
    return parse_regex(goal)
