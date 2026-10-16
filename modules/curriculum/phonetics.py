# -*- coding: utf-8 -*-
"""En-UK (RP) IPA enrichment for classroom vocab slides (CLASSROOM V2 · Agent E · Phase 2).

Design constraints
------------------
* **Zero new dependencies** — a small built-in word→IPA map plus a transparent,
  rule-based fallback is NOT acceptable here: an invented IPA is worse than none.
  So: known word → real IPA; unknown word → **omit the field** (the frozen contract
  C6 forbids a ``null`` sentinel and forbids faking pronunciation).
* **Accent is explicit** — the map is **en-GB / RP**; the caller must not claim
  "US pronunciation".  ``accent()`` returns the honest label.
* **Never fake** — ``lookup()`` returns ``None`` rather than guessing.  The UI is
  expected to show nothing (or "音标待补充") in that case.

The map is intentionally small (common classroom words); it is *data*, not a
service.  Extending it is a pure data edit and requires no code change.
"""

from __future__ import annotations

ACCENT_LABEL = "en-GB (RP)"

# Common classroom / textbook words → en-GB (RP) IPA (slashes omitted; stored bare).
_WORDS: dict[str, str] = {
    "reservation": "ˌrezəˈveɪʃn",
    "check-in": "ˈtʃek ɪn",
    "room": "ruːm",
    "hotel": "həʊˈtel",
    "breakfast": "ˈbrekfəst",
    "luggage": "ˈlʌɡɪdʒ",
    "passport": "ˈpɑːspɔːt",
    "ticket": "ˈtɪkɪt",
    "airport": "ˈeəpɔːt",
    "station": "ˈsteɪʃn",
    "question": "ˈkwestʃən",
    "answer": "ˈɑːnsə",
    "practice": "ˈpræktɪs",
    "lesson": "ˈlesn",
    "student": "ˈstjuːdnt",
    "teacher": "ˈtiːtʃə",
    "language": "ˈlæŋɡwɪdʒ",
    "english": "ˈɪŋɡlɪʃ",
    "welcome": "ˈwelkəm",
    "please": "pliːz",
    "thank": "θæŋk",
    "water": "ˈwɔːtə",
    "coffee": "ˈkɒfi",
    "menu": "ˈmenjuː",
    "order": "ˈɔːdə",
    "price": "praɪs",
    "double": "ˈdʌbl",
    "single": "ˈsɪŋɡl",
    "night": "naɪt",
    "today": "təˈdeɪ",
    "tomorrow": "təˈmɒrəʊ",
    "morning": "ˈmɔːnɪŋ",
    "evening": "ˈiːvnɪŋ",
    "address": "əˈdres",
    "phone": "fəʊn",
    "number": "ˈnʌmbə",
    "help": "help",
    "sorry": "ˈsɒri",
    "excuse": "ɪkˈskjuːz",
    "wifi": "ˈwaɪfaɪ",
}


def accent() -> str:
    """The accent these IPA strings describe (must be surfaced to the learner)."""
    return ACCENT_LABEL


def lookup(word: str) -> "str | None":
    """Return the en-GB (RP) IPA for a word, or ``None`` if unknown.

    **Never** guesses: an unknown word returns ``None`` so the caller omits the
    field (contract C6) instead of fabricating pronunciation.
    """
    if not isinstance(word, str):
        return None
    key = word.strip().lower()
    if not key:
        return None
    if key in _WORDS:
        return _WORDS[key]
    # strip a trailing plural / simple inflection and retry (still real data)
    for suffix, repl in (("ies", "y"), ("es", ""), ("s", "")):
        if key.endswith(suffix) and len(key) > len(suffix) + 1:
            base = key[: -len(suffix)] + repl
            if base in _WORDS:
                return _WORDS[base]
    return None


def known_count() -> int:
    """Number of words with a real IPA entry (for capability reporting)."""
    return len(_WORDS)


def enrich_vocab(slide: dict) -> dict:
    """Return a copy of a ``vocab`` slide with ``phonetic`` filled when known.

    * If the slide already carries a non-empty ``phonetic`` → left untouched.
    * If the word is unknown to the map → the field is **omitted** (never ``None``).
    """
    out = dict(slide)
    if out.get("phonetic"):
        return out
    ipa = lookup(str(out.get("word") or ""))
    if ipa:
        out["phonetic"] = ipa
    else:
        out.pop("phonetic", None)
    return out
