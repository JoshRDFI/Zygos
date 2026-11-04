"""RFC-0012 §4: spoken thinking phrase matching."""

import pytest

from zygos.api.voice_commands import VoiceCommand, parse_voice_command


@pytest.mark.parametrize("text,expected", [
    ("Think it through, what's 17 times 23?",
     VoiceCommand("think_turn", "think it through", "what's 17 times 23?")),
    ("think about this: why is the sky blue",
     VoiceCommand("think_turn", "think about this", "why is the sky blue")),
    ("Think carefully. Is 91 prime?", VoiceCommand("think_turn", "think carefully", "Is 91 prime?")),
    ("Think harder.", VoiceCommand("rethink", "think harder", "")),
    ("think it through", VoiceCommand("rethink", "think it through", "")),
    ("Think about that", VoiceCommand("rethink", "think about that", "")),
    ("Turn thinking on.", VoiceCommand("think_on", "turn thinking on", "")),
    ("thinking off", VoiceCommand("think_off", "thinking off", "")),
    ("Turn thinking off!", VoiceCommand("think_off", "turn thinking off", "")),
    ("think it throughout the day", None),
    ("I think harder questions are fun", None),
    ("rethink this", None),
    ("thinking onions", None),
    ("think about this", None),
    ("what do you think about this", None),
    ("", None),
])
def test_parse_voice_command(text, expected):
    assert parse_voice_command(text) == expected
