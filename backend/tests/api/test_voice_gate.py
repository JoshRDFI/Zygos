from zygos.api.voice_gate import VoiceGate


def test_first_acquire_succeeds_and_sets_owner():
    gate = VoiceGate()
    assert gate.owner is None
    assert gate.try_acquire("a") is True
    assert gate.owner == "a"


def test_second_session_is_refused():
    gate = VoiceGate()
    assert gate.try_acquire("a") is True
    assert gate.try_acquire("b") is False
    assert gate.owner == "a"


def test_reacquire_by_owner_is_idempotent():
    gate = VoiceGate()
    gate.try_acquire("a")
    assert gate.try_acquire("a") is True  # back-to-back utterances on one session
    assert gate.owner == "a"


def test_release_by_owner_clears_and_reallows():
    gate = VoiceGate()
    gate.try_acquire("a")
    gate.release("a")
    assert gate.owner is None
    assert gate.try_acquire("b") is True


def test_release_by_non_owner_is_noop():
    gate = VoiceGate()
    gate.try_acquire("a")
    gate.release("b")  # b never owned it
    assert gate.owner == "a"
