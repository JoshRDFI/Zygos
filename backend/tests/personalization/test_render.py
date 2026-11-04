from zygos.personalization import Personalization
from zygos.personalization.render import render_identity


def test_empty_renders_none():
    assert render_identity(Personalization()) is None


def test_names_only():
    out = render_identity(Personalization(user_name="Josh", assistant_name="Rommie"))
    assert "You are Rommie, the user's personal assistant." in out
    assert "The user's name is Josh." in out
    assert "Tone" not in out and "Persona" not in out


def test_all_fields_in_order():
    out = render_identity(Personalization(
        user_name="Josh", address="boss", pronouns="he/him",
        assistant_name="Rommie", tone="calm", persona="Be brief."))
    needles = ["You are Rommie", "The user's name is Josh.", "Address the user as boss.",
               "The user's pronouns are he/him.", "Tone: calm.",
               "Persona, written and approved by the user:\nBe brief."]
    idx = [out.index(n) for n in needles]
    assert idx == sorted(idx) and len(set(idx)) == len(idx)


def test_tone_period_not_doubled():
    out = render_identity(Personalization(tone="calm."))
    assert "Tone: calm." in out and "calm.." not in out
