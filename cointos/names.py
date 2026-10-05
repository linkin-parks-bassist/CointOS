"""Agents' personal names, generated from sound patterns rather than chosen from a list.

A name is two or three syllables assembled from a broad inventory of onsets, vowels and codas
drawn from many languages' sound systems. Common sounds are weighted heavily and exotic ones
lightly, so names come out familiar (Ringo), mythic (Halthor) or alien (Zyrtek) but stay easy to
say. Names are unique among all tasks and belong to a task for its whole life.
"""
from __future__ import annotations

import random
import re

# (sound, weight): plain consonants dominate; clusters and exotic sounds add colour.
ONSETS = [("", 3), *((c, 4) for c in "bdgklmnprstvz"), *((c, 2) for c in "fhjwy"),
          *((c, 1) for c in ("th", "sh", "kh", "ch", "zh", "ts", "dr", "tr", "br", "gr", "kr", "vr", "st", "sk",
                              "zy", "ny", "x", "q", "rh", "kw"))]
VOWELS = [*((v, 6) for v in "aeiou"), ("y", 2), *((v, 1) for v in ("ae", "ai", "au", "ei", "io", "ou"))]
CODAS = [("", 10), *((c, 3) for c in "nrls"), *((c, 1) for c in ("k", "m", "x", "th", "rn", "nd", "st", "ng", "rk", "z", "tek"))]
MIDDLE_CODAS = [("", 8), *((c, 2) for c in "nrls")]  # inside a name, a closed syllable is short
SIMPLE = {sound for sound, _ in ONSETS if len(sound) <= 1}
AWKWARD = re.compile(r"[bcdfghjklmnpqrstvwxz]{3}|([aeiouy])\1|q[^u]|yy|ww")


def pick(rng: random.Random, sounds: list) -> str:
    return rng.choices([s for s, _ in sounds], weights=[w for _, w in sounds])[0]


def invent(taken: set[str], rng: random.Random | None = None) -> str:
    """A new pronounceable name not in `taken` (compared case-insensitively)."""
    rng = rng or random.SystemRandom()
    lowered = {name.lower() for name in taken}
    while True:
        syllables = rng.choices((2, 3), weights=(3, 1))[0]
        name, coda = "", ""
        for index in range(syllables):
            onset = pick(rng, ONSETS)
            while coda and onset not in SIMPLE:  # no consonant pile-up where syllables join
                onset = pick(rng, ONSETS)
            coda = pick(rng, CODAS if index == syllables - 1 else MIDDLE_CODAS)
            name += onset + pick(rng, VOWELS) + coda
        if 3 <= len(name) <= 8 and not AWKWARD.search(name) and name not in lowered:
            return name.capitalize()
