import asyncio
import time

import gmail
import lookup
import readback
import work


def test_readback_names_recipient_subject_and_body():
    line = asyncio.run(readback.body_line("I'm at the Palace of Fine Arts"))
    say = readback.compose("Sam", "At the Palace of Fine Arts", line)
    assert say == ("Draft to Sam, subject: At the Palace of Fine Arts. "
                   "It says: I'm at the Palace of Fine Arts. Say send, or cancel.")


def test_readback_without_subject():
    assert readback.compose("Sam", "", "Hi.").startswith("Draft to Sam, no subject.")


def test_long_body_is_shortened_without_claude():
    line = asyncio.run(readback.body_line(" ".join(["word"] * 60)))
    assert len(line.split()) <= readback.MAX_WORDS + 2 and line.endswith(".")


def test_addressed_to():
    d = gmail.Draft(emails=["sam.calhacks.demo@gmail.com"], to_text="Sam Demo")
    assert gmail.addressed_to(d, "sam.calhacks.demo@gmail.com", "Sam")
    assert not gmail.addressed_to(gmail.Draft(emails=["x@y.com"]), "sam.calhacks.demo@gmail.com", "Sam")
    assert not gmail.addressed_to(gmail.Draft(emails=["x@y.com", "sam.calhacks.demo@gmail.com"]),
                                  "sam.calhacks.demo@gmail.com", "Sam")
    assert gmail.addressed_to(gmail.Draft(to_text="Sam Demo"), "sam.calhacks.demo@gmail.com", "Sam")


def test_sent_row_matching_needs_recipient_text_and_a_recent_time():
    now = time.mktime((2026, 10, 24, 15, 42, 0, 0, 0, -1))
    d = gmail.Draft(subject="I'm at the Palace of Fine Arts", body="I'm at the Palace of Fine Arts.")
    row = "To: Sam I'm at the Palace of Fine Arts - I'm at the Palace of Fine Arts. 3:41 PM"
    assert gmail.row_matches(row, d, "Sam", "sam.calhacks.demo@gmail.com", now)
    assert not gmail.row_matches(row.replace("3:41", "1:05"), d, "Sam", "sam.calhacks.demo@gmail.com", now)
    assert not gmail.row_matches(row.replace("Sam", "Alex"), d, "Sam", "zzz@x.com", now)
    assert not gmail.row_matches("To: Sam Lunch plans 3:41 PM", d, "Sam", "sam.calhacks.demo@gmail.com", now)


def test_sent_row_matching_uses_the_whole_subject():
    now = time.mktime((2026, 10, 24, 15, 42, 0, 0, 0, -1))
    d = gmail.Draft(subject="I'm at the Palace of Fine Arts, test 2", body="x")
    row = "To: Sam I'm at the Palace of Fine Arts, test 1 - x 3:41 PM"
    assert not gmail.row_matches(row, d, "Sam", "sam.calhacks.demo@gmail.com", now)


def test_lookup_hours_without_claude():
    text = "Ace Hardware Polk St\nOpen ⋅ Closes 9 PM"
    assert lookup.regex_answer("when does it close today", text) == "It's open now and closes at 9 PM."
    assert lookup.regex_answer("what's the weather", text) is None


def test_work_mode_steps_through_the_order():
    assert work.reply_for(1, "blue notebook") == "That's the blue notebook, item 1 of 3. Next, find the stapler."
    assert work.reply_for(None, "a coffee mug") == ("That looks like a coffee mug, which isn't on order 12. "
                                                    "You still need the stapler.")
    assert work.reply_for(1, "blue notebook") == "You already have the blue notebook. Next, find the stapler."
    assert work.reply_for(2, "stapler") == "That's the stapler, item 2 of 3. Next, find the roll of tape."
    assert work.reply_for(3, "tape") == "That's the roll of tape. That's all 3 items for order 12."


def test_work_mode_reset():
    work.reply_for(1, "notebook")
    assert asyncio.run(work.check("start over", "")) == "Starting order 12 again. First, find the blue notebook."
