"""The spoken read-back of a draft (PRD 4 B-4): recipient, subject and what it says, then "send or cancel".

The wording is a template filled from the draft as read off the page, so a wrong recipient is always audible.
Only a long body goes through Claude, and only to shorten it to one sentence.
"""
import logging

import llm

log = logging.getLogger("browser.readback")

MAX_WORDS = 25
SUMMARY_SYSTEM = ("Summarize this email body in one short spoken sentence, written as 'it says ...' content "
                  "without the words 'it says'. Keep names, times and places. No preamble.")


def _sentence(text: str) -> str:
    text = " ".join(text.split()).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


async def body_line(body: str) -> str:
    words = " ".join(body.split()).split(" ")
    if len(words) <= MAX_WORDS:
        return _sentence(body)
    if llm.available():
        try:
            return _sentence(await llm.ask(SUMMARY_SYSTEM, body, max_tokens=80, timeout=4.0))
        except Exception as e:
            log.warning("summary failed: %r", e)
    return _sentence(" ".join(words[:MAX_WORDS]) + " and more")


def compose(name: str, subject: str, line: str) -> str:
    subject = subject.strip().rstrip(".")
    head = f"Draft to {name}, subject: {subject}." if subject else f"Draft to {name}, no subject."
    return f"{head} It says: {line} Say send, or cancel."
