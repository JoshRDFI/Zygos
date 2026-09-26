import sys

from zygos.voice import gpu_setup
from zygos.voice.device import venv_python


class _Rec:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, argv, env=None):
        self.calls.append((argv, env))
        return 1 if self.fail_on and self.fail_on(argv) else 0


def _joined(rec):
    return [" ".join(a) for a, _ in rec.calls]


def test_fresh_setup_step_order(tmp_path):
    venv = str(tmp_path / "v")
    rec, removed = _Rec(), []
    code = gpu_setup.setup_gpu(venv_dir=venv, run=rec, exists=lambda p: False,
                               remove=removed.append, out=lambda s: None)
    assert code == 0 and removed == []
    cmds = _joined(rec)
    py = venv_python(venv)
    assert cmds[0] == f"{sys.executable} -m venv {venv}"
    assert cmds[1].startswith(f"{py} -m pip install -e ") and cmds[1].endswith("[voice]")
    assert cmds[2] == f"{py} -m pip uninstall -y onnxruntime"
    assert cmds[3] == f'{py} -m pip install onnxruntime-gpu[cuda,cudnn]>={gpu_setup.ORT_GPU_MIN}'
    assert cmds[4] == f"{py} -m zygos.voice.sidecar.kokoro --self-check"
    assert rec.calls[4][1] == {"ZYGOS_TTS_DEVICE": "cuda"}
    # uninstall strictly before the GPU install (they share the onnxruntime/ package)
    assert cmds.index(f"{py} -m pip uninstall -y onnxruntime") < 3


def test_rerun_reuses_existing_venv_but_repeats_install_swap_check(tmp_path):
    # Review Focus #5
    venv = str(tmp_path / "v")
    rec, removed = _Rec(), []
    code = gpu_setup.setup_gpu(venv_dir=venv, run=rec, exists=lambda p: True,
                               remove=removed.append, out=lambda s: None)
    cmds = _joined(rec)
    assert code == 0 and removed == []
    assert not any(" -m venv " in c for c in cmds)
    assert len(cmds) == 4 and cmds[-1].endswith("--self-check")


def test_force_removes_and_recreates(tmp_path):
    venv = str(tmp_path / "v")
    rec, removed = _Rec(), []
    gpu_setup.setup_gpu(venv_dir=venv, force=True, run=rec, exists=lambda p: True,
                        remove=removed.append, out=lambda s: None)
    assert removed == [venv]
    assert _joined(rec)[0] == f"{sys.executable} -m venv {venv}"


def test_step_failure_stops_and_is_nonzero(tmp_path):
    rec = _Rec(fail_on=lambda argv: "uninstall" in argv)
    lines = []
    code = gpu_setup.setup_gpu(venv_dir=str(tmp_path / "v"), run=rec, exists=lambda p: False,
                               remove=lambda p: None, out=lines.append)
    assert code != 0
    assert not any("onnxruntime-gpu" in c for c in _joined(rec))   # stopped at the failed step
    assert any("failed" in ln.lower() for ln in lines)


def test_self_check_reporting_cpu_is_nonzero(tmp_path):
    rec = _Rec(fail_on=lambda argv: "--self-check" in argv)
    lines = []
    code = gpu_setup.setup_gpu(venv_dir=str(tmp_path / "v"), run=rec, exists=lambda p: False,
                               remove=lambda p: None, out=lines.append)
    assert code != 0
    assert not any("voice.tts.device: cuda" in ln for ln in lines)


def test_success_prints_config_hint(tmp_path):
    lines = []
    gpu_setup.setup_gpu(venv_dir=str(tmp_path / "v"), run=_Rec(), exists=lambda p: False,
                        remove=lambda p: None, out=lines.append)
    assert any("voice.tts.device: cuda" in ln for ln in lines)


def test_backend_dir_has_pyproject():
    assert (gpu_setup.backend_dir() / "pyproject.toml").is_file()
