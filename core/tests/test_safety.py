from app.safety import FALLBACK, filter_reply, filter_sentence, is_banned, max_two_sentences

BANNED_EXAMPLES = [
    "It is safe to cross now.", "Cross safely.", "You're clear to cross.", "Go ahead.",
    "You can cross.", "It's okay to cross.", "It's ok to cross.", "All clear.",
    "No cars, so you can cross.", "It's fine to cross.", "Walk now.", "You're clear.",
    "It’s fine to cross.",
]


def test_each_banned_phrase_blocked():
    for s in BANNED_EXAMPLES:
        assert is_banned(s), s
        assert filter_sentence(s) is None


def test_sentence_level_drop_keeps_clean_sentence():
    assert filter_reply("The walk sign is on. It is safe to cross.") == "The walk sign is on."


def test_all_banned_gives_fallback():
    assert filter_reply("It is safe to cross now. Go ahead.") == FALLBACK


def test_clean_reply_unchanged():
    text = "The walk sign is on. A car is moving from your left."
    assert filter_reply(text) == text


def test_max_two_sentences():
    assert max_two_sentences("One. Two! Three? Four.") == "One. Two!"
