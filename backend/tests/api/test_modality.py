"""Per-turn interaction-modality context (RFC-0010 §3a).

Stability: Experimental (test-only).
"""

from __future__ import annotations

from zygos.api.modality import TurnModality, render_modality

# Clause markers. Exact wording is an implementation detail (RFC-0010 §3a); the
# tests pin the presence of each clause, not the text.
INPUT_MARK = "speech-to-text"
OUTPUT_MARK = "text-to-speech"


def test_typed_turn_renders_nothing():
    assert render_modality(TurnModality()) is None


def test_spoken_input_only_describes_the_transcript():
    text = render_modality(TurnModality(spoken_input=True))
    assert text is not None
    assert INPUT_MARK in text
    assert OUTPUT_MARK not in text


def test_spoken_output_only_asks_for_speakable_text():
    text = render_modality(TurnModality(spoken_output=True))
    assert text is not None
    assert OUTPUT_MARK in text
    assert "markdown" in text
    assert INPUT_MARK not in text


def test_full_voice_turn_has_both_clauses_input_first():
    text = render_modality(TurnModality(spoken_input=True, spoken_output=True))
    assert text is not None
    assert text.index(INPUT_MARK) < text.index(OUTPUT_MARK)


def test_does_not_claim_the_model_perceives_audio():
    # Honesty note (RFC-0010 §3a): the model reads a transcript; it cannot hear
    # tone or non-speech sounds, so the template must not say it can.
    text = render_modality(TurnModality(spoken_input=True, spoken_output=True))
    assert "you can hear" not in text.lower()
