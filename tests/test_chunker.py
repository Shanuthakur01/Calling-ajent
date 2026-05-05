"""Unit tests for the sentence chunker in llm/groq_client.py."""

from llm.llm_client import _split_sentence, _split_for_tts

_ENDS = frozenset(".!?")


def split(text):
    return _split_sentence(text, _ENDS)


# ── Basic splitting ────────────────────────────────────────────────────────

def test_single_complete_sentence():
    s, r = split("Hello there. How are you?")
    assert s == "Hello there."
    assert r == "How are you?"


def test_question_mark():
    s, r = split("What is your name? My name is Saanvi.")
    assert s == "What is your name?"
    assert r == "My name is Saanvi."


def test_exclamation():
    s, r = split("That is wonderful! Tell me more please.")
    assert s == "That is wonderful!"
    assert r == "Tell me more please."


# ── Minimum length guard ───────────────────────────────────────────────────

def test_short_fragment_not_split():
    # The period in "Hi." sits at index 2, which is below _MIN_SENTENCE-1=11,
    # so the chunker must NOT split there.  The whole string has no later
    # sentence-ending delimiter, so nothing splits.
    s, r = split("Hi. Not enough yet")
    assert s == ""
    assert r == "Hi. Not enough yet"


def test_early_period_skipped_full_sentence_still_splits():
    # "Hi." is skipped (index 2 < 11) but the trailing "?" at index 21 IS valid.
    s, r = split("Hi. How are you today?")
    assert s == "Hi. How are you today?"
    assert r == ""


def test_exactly_min_length():
    # "Hello world." is 12 chars — exactly _MIN_SENTENCE, should split
    s, r = split("Hello world. Next sentence.")
    assert s == "Hello world."
    assert r == "Next sentence."


# ── No complete sentence ───────────────────────────────────────────────────

def test_no_sentence_yet():
    s, r = split("This is still")
    assert s == ""
    assert r == "This is still"


def test_empty_string():
    s, r = split("")
    assert s == ""
    assert r == ""


# ── Punctuation not at word boundary ──────────────────────────────────────

def test_decimal_number_not_split():
    # "3.14" — period followed by digit, not a sentence boundary
    s, r = split("The value is 3.14 which is pi.")
    # Should split at the trailing period, not at "3.14"
    assert s == "The value is 3.14 which is pi."
    assert r == ""


def test_abbreviation_mid_sentence():
    # "Mr. Smith" — period followed by uppercase letter (no space rule means no split)
    # The period in "Mr." is followed by " " which IS a word boundary...
    # So "Mr. Smith is coming." should NOT split at "Mr." because it's < _MIN_SENTENCE
    s, r = split("Mr. Smith is here.")
    # "Mr." is 3 chars < 12, so no split there. "Mr. Smith is here." is 18 chars total.
    # The period at position 17 (0-indexed) is followed by end-of-string → split.
    assert s == "Mr. Smith is here."
    assert r == ""


# ── Token-stream simulation ────────────────────────────────────────────────

def test_incremental_token_stream():
    """Simulate LLM token-by-token accumulation — two sentences split correctly."""
    tokens = [
        "That", "'s", " a", " great", " question",
        ".", " Let", " me", " explain", " it", " clearly", ".",
    ]
    buf = ""
    sentences = []
    for tok in tokens:
        buf += tok
        s, buf = split(buf)
        if s:
            sentences.append(s)

    # Both sentences must be extracted; nothing left in the buffer.
    assert sentences == ["That's a great question.", "Let me explain it clearly."]
    assert buf == ""


def test_multiple_sentences_sequential():
    """Sequential split extracts all sentences."""
    text = "First sentence. Second one here. Third and final."
    sentences = []
    buf = text
    while True:
        s, buf = split(buf)
        if not s:
            break
        sentences.append(s)
    if buf.strip():
        sentences.append(buf.strip())

    assert sentences == [
        "First sentence.",
        "Second one here.",
        "Third and final.",
    ]


# ===========================================================================
# _split_for_tts — Phase 2 TTS-optimised chunker
# ===========================================================================

_TTS_ENDS = frozenset(".!?")


def split_tts(text):
    return _split_for_tts(text, _TTS_ENDS)


# ── Sentence boundary (same behaviour as _split_sentence) ─────────────────

def test_tts_sentence_boundary():
    s, r = split_tts("Hello there. How are you?")
    assert s == "Hello there."
    assert r == "How are you?"


def test_tts_no_split_on_short_fragment():
    s, r = split_tts("Hi. Not enough yet")
    assert s == ""
    assert r == "Hi. Not enough yet"


# ── Comma flush at _MIN_COMMA_FLUSH_CHARS (20) ────────────────────────────

def test_tts_comma_flush_triggers():
    # 24 chars before the comma: should flush at comma
    text = "Well, that is a long idea, more text"
    s, r = split_tts(text)
    assert s == "Well, that is a long idea,"
    assert r == "more text"


def test_tts_comma_flush_does_not_trigger_too_early():
    # comma at index 4 — before _MIN_COMMA_FLUSH_CHARS=20, no flush
    text = "Hmm, short"
    s, r = split_tts(text)
    assert s == ""
    assert r == text


def test_tts_comma_flush_requires_trailing_space():
    # comma at end of string (no space after) — must NOT flush
    text = "This is a longer sentence fragment,"
    s, r = split_tts(text)
    # no space after comma → no comma flush; also no sentence end → no split
    assert s == ""
    assert r == text


# ── 8-word hard cap ──────────────────────────────────────────────────────

def test_tts_word_cap_triggers_at_8_words():
    text = "one two three four five six seven eight nine"
    s, r = split_tts(text)
    assert s == "one two three four five six seven eight"
    assert r == "nine"


def test_tts_word_cap_does_not_trigger_at_7_words():
    text = "one two three four five six seven"
    s, r = split_tts(text)
    assert s == ""
    assert r == text


def test_tts_empty_string():
    s, r = split_tts("")
    assert s == ""
    assert r == ""
