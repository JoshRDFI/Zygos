import pytest

from zygos.cli.__main__ import main
from zygos.personalization import Personalization, SqlitePreferencesStore

HINT = ("zygos: not personalized yet: run `zygos personalize` "
        "to set your name and the assistant's.")


@pytest.fixture
def cfg(tmp_path):
    db = tmp_path / "prefs.db"
    path = tmp_path / "config.yaml"
    path.write_text(
        "providers:\n"
        "  primary: {provider: fake, model: fake-1}\n"
        "personalization:\n"
        f"  db_path: {db}\n"
    )
    return ["--config", str(path)], SqlitePreferencesStore(db)


def test_show_empty(cfg, capsys):
    base, _ = cfg
    assert main([*base, "personalize", "show"]) == 0
    assert capsys.readouterr().out.strip() == "Not personalized."


def test_set_then_show(cfg, capsys):
    base, store = cfg
    assert main([*base, "personalize", "set", "--user-name", "Josh",
                 "--assistant-name", "Rommie"]) == 0
    capsys.readouterr()
    assert main([*base, "personalize", "show"]) == 0
    out = capsys.readouterr().out
    assert "user_name: Josh" in out
    assert "assistant_name: Rommie" in out
    assert store.get().user_name == "Josh"


def test_set_merges_and_empty_string_clears(cfg):
    base, store = cfg
    main([*base, "personalize", "set", "--user-name", "Josh", "--tone", "dry"])
    main([*base, "personalize", "set", "--assistant-name", "Rommie"])
    prefs = store.get()
    assert (prefs.user_name, prefs.tone, prefs.assistant_name) == ("Josh", "dry", "Rommie")
    main([*base, "personalize", "set", "--tone", ""])
    prefs = store.get()
    assert prefs.tone is None and prefs.user_name == "Josh"


def test_set_invalid_exits_1_and_writes_nothing(cfg, capsys):
    base, store = cfg
    assert main([*base, "personalize", "set", "--user-name", "x" * 5000]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() and "Traceback" not in captured.err
    assert store.get().is_empty


def test_set_without_flags_exits_2(cfg):
    base, _ = cfg
    with pytest.raises(SystemExit) as exc:
        main([*base, "personalize", "set"])
    assert exc.value.code == 2


def test_clear(cfg, capsys):
    base, store = cfg
    store.set(Personalization(user_name="Josh"))
    assert main([*base, "personalize", "clear"]) == 0
    assert "Personalization cleared." in capsys.readouterr().out
    assert store.get().is_empty


def test_guided_skip(cfg, monkeypatch):
    base, store = cfg
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert main([*base, "personalize"]) == 0
    assert store.get().is_empty


def test_guided_ctrl_c_exits_130(cfg, monkeypatch, capsys):
    base, store = cfg

    def boom(*a):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", boom)
    assert main([*base, "personalize"]) == 130
    assert "Traceback" not in capsys.readouterr().err
    assert store.get().is_empty


def test_doctor_warns_when_unpersonalized(cfg, capsys):
    base, _ = cfg
    assert main([*base, "doctor"]) == 0
    out = capsys.readouterr().out
    assert "[warn] personalization: not set: run `zygos personalize`" in out
    assert "healthy" in out


def test_doctor_reports_set(cfg, capsys):
    base, store = cfg
    store.set(Personalization(user_name="Josh", assistant_name="Rommie"))
    assert main([*base, "doctor"]) == 0
    out = capsys.readouterr().out
    assert "[ok  ] personalization: set (assistant: Rommie, user: Josh)" in out


@pytest.fixture
def served(monkeypatch):
    calls = []
    monkeypatch.setattr("zygos.api.app.run_server",
                        lambda runtime, *, host, port: calls.append((host, port)))
    return calls


def test_serve_prints_hint_when_empty(cfg, served, capsys):
    base, _ = cfg
    assert main([*base, "serve"]) == 0
    assert HINT in capsys.readouterr().err
    assert served


def test_serve_no_hint_when_set(cfg, served, capsys):
    base, store = cfg
    store.set(Personalization(user_name="Josh"))
    assert main([*base, "serve"]) == 0
    assert "not personalized" not in capsys.readouterr().err
    assert served


def test_interrupt_escaping_asyncio_run_exits_130(cfg, monkeypatch, capsys):
    # Real Ctrl-C under asyncio.run: the runner re-raises KeyboardInterrupt
    # from asyncio.run itself, outside the coroutine.
    base, _ = cfg

    def fake_run(coro):
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr("zygos.cli.__main__.asyncio.run", fake_run)
    assert main([*base, "personalize"]) == 130
    assert "Traceback" not in capsys.readouterr().err


def _real_sigint_input(monkeypatch, kill_at, answers):
    """Fake input whose ``kill_at``-th call sends a real SIGINT to this process.

    If the signal does not stop the prompt, the call returns and the remaining
    calls keep answering with values that would save.
    """
    import os
    import signal

    state = {"calls": 0, "returned_after_kill": False}
    queue = list(answers)

    def fake_input(prompt=""):
        state["calls"] += 1
        if state["calls"] == kill_at:
            os.kill(os.getpid(), signal.SIGINT)
            state["returned_after_kill"] = True
        return queue.pop(0) if queue else "y"

    monkeypatch.setattr("builtins.input", fake_input)
    return state


@pytest.fixture
def drafting_provider(monkeypatch):
    import json

    from zygos.providers.fake import FakeProvider

    original = FakeProvider.__init__

    def init(self, *a, **k):
        k["text"] = json.dumps({"user_name": "Josh", "assistant_name": "Rommie"})
        original(self, *a, **k)

    monkeypatch.setattr(FakeProvider, "__init__", init)


def test_real_sigint_at_description_prompt_stops_immediately(
        cfg, drafting_provider, monkeypatch, capsys):
    base, store = cfg
    state = _real_sigint_input(monkeypatch, 1, ["I am Josh"] + [""] * 6 + ["y"])
    assert main([*base, "personalize"]) == 130
    assert not state["returned_after_kill"], "prompt kept waiting after Ctrl-C"
    assert state["calls"] == 1
    assert "Traceback" not in capsys.readouterr().err
    assert store.get().is_empty


def test_real_sigint_mid_review_exits_130_without_saving(
        cfg, drafting_provider, monkeypatch, capsys):
    base, store = cfg
    # call 1 = description, call 2 = "User name [Josh]:" -> Ctrl-C there.
    state = _real_sigint_input(monkeypatch, 2, ["I am Josh"] + [""] * 6 + ["y"])
    assert main([*base, "personalize"]) == 130
    assert store.get().is_empty, "saved before the Ctrl-C landed"
    assert not state["returned_after_kill"]
    assert "Traceback" not in capsys.readouterr().err


def test_sigint_handler_restored_after_onboarding(cfg, monkeypatch):
    import signal

    base, _ = cfg
    before = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert main([*base, "personalize"]) == 0
    assert signal.getsignal(signal.SIGINT) is before
