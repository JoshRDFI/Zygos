from pathlib import Path

from zygos.config.loader import load_config
from zygos.home import zygos_home


def _write(tmp_path: Path, body: str) -> Path:
    folder = tmp_path / "cfg"
    folder.mkdir(exist_ok=True)
    path = folder / "z.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_resolve_against_root():
    r = zygos_home().root
    cfg = load_config(None)
    assert cfg.memory.db_path == str(r / ".zygos/memory.db")
    assert cfg.personalization.db_path == str(r / ".zygos/preferences.db")
    assert cfg.tools.workspace_root == str(r / ".zygos/workspace")
    assert cfg.models.profiles_dir == str(r / ".zygos/models/profiles")
    assert cfg.voice.stt.download_root is None
    assert cfg.voice.tts.download_root is None
    assert cfg.voice.tts.worker_python is None


def test_relative_file_values_resolve_against_root_not_config_folder(tmp_path):
    r = zygos_home().root
    path = _write(tmp_path, "personalization:\n  db_path: data/p.db\n")
    assert load_config(path).personalization.db_path == str(r / "data/p.db")


def test_absolute_values_unchanged(tmp_path):
    target = str(tmp_path / "abs" / "m.db")
    path = _write(tmp_path, f"memory:\n  db_path: {target}\n")
    assert load_config(path).memory.db_path == target


def test_tilde_value_is_expanded(tmp_path):
    path = _write(tmp_path, "personalization:\n  db_path: ~/zp/p.db\n")
    assert load_config(path).personalization.db_path == str(Path.home() / "zp/p.db")


def test_voice_values(tmp_path):
    r = zygos_home().root
    path = _write(
        tmp_path,
        "voice:\n  tts:\n    download_root: m/k\n    worker_python: python3\n"
        "  stt:\n    download_root: m/s\n",
    )
    cfg = load_config(path)
    assert cfg.voice.tts.download_root == str(r / "m/k")
    assert cfg.voice.stt.download_root == str(r / "m/s")
    assert cfg.voice.tts.worker_python == "python3"
    path = _write(tmp_path, "voice:\n  tts:\n    worker_python: venvs/x/bin/python\n")
    assert load_config(path).voice.tts.worker_python == str(r / "venvs/x/bin/python")


def test_ollama_models_dir_untouched(tmp_path):
    path = _write(tmp_path, "models:\n  ollama_models_dir: rel/models\n")
    assert load_config(path).models.ollama_models_dir == "rel/models"


def test_load_creates_nothing(tmp_path, monkeypatch):
    fresh = tmp_path / "fresh"
    monkeypatch.setenv("ZYGOS_HOME", str(fresh))
    from zygos.home import reset_zygos_home_cache

    reset_zygos_home_cache()
    load_config(None)
    assert not fresh.exists()
