"""Spoken request -> what to do: an email (to a known contact) or a web lookup.

Claude Sonnet parses first (better message wording); regex rules are the fallback when there's no key,
the call fails or it takes more than 3 s. Recipients only come from DEMO_CONTACTS: the agent never guesses an address.
"""
import logging
import re
from dataclasses import dataclass

import config
import llm

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


@dataclass
class Unsupported:
    say: str


NOT_SUPPORTED = "On the laptop I can send an email or look something up."
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

PARSE_SYSTEM = """You turn a blind user's spoken request for their laptop into JSON. Reply with JSON only:
{"kind": "email" | "lookup" | "unsupported", "to_name": "", "message": "", "subject": "", "query": ""}
email: to_name is the recipient exactly as spoken (usually a first name); message is the email body in the
user's own first-person voice, one or two short sentences, keeping their words; subject is 3 to 7 words.
lookup: query is a short web search query that answers the question.
unsupported: anything else, including purchases, payments, passwords, uploads or apps other than the web browser."""


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


def parse_regex(goal: str) -> EmailPlan | LookupPlan | Unsupported:
    text = goal.strip()
    if MONEY_RX.search(text):
        return Unsupported(NO_MONEY)
    for rx in EMAIL_RXS:
        m = rx.match(text)
        if m and (m.group("name").lower() not in {"me", "him", "her", "them", "a", "an"}):
            return _email(m.group("name"), m.group("msg"))
    if LOOKUP_RX.search(text):
        q = LOOKUP_STRIP.sub("", text).strip().rstrip("?.! ")
        return LookupPlan(query=q or text)
    return Unsupported(NOT_SUPPORTED)


async def parse(goal: str) -> EmailPlan | LookupPlan | Unsupported:
    if MONEY_RX.search(goal):
        return Unsupported(NO_MONEY)
    if llm.available():
        j = await llm.ask_json(PARSE_SYSTEM, goal, max_tokens=200, timeout=3.0)
        if j:
            kind = j.get("kind")
            if kind == "email" and j.get("to_name"):
                return _email(j["to_name"], j.get("message", ""), j.get("subject", ""))
            if kind == "lookup" and j.get("query"):
                return LookupPlan(query=j["query"].strip())
            if kind == "unsupported":
                return Unsupported(NOT_SUPPORTED)
        log.info("claude parse unavailable or unusable, using rules")
    return parse_regex(goal)
