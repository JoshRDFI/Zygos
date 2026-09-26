"""`zygos voice setup-gpu`: build the GPU sidecar venv (RFC-0005 §2a).

The venv holds zygos (editable, [voice]) + onnxruntime-gpu and never the CPU
onnxruntime (they share the `onnxruntime` import package). It is never the main
environment, so fastembed's CPU onnxruntime is untouched.

Stability: Experimental.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import zygos
from zygos.voice.device import DEFAULT_GPU_VENV, venv_python

# Minimum onnxruntime-gpu with Blackwell (sm_120) CUDA kernels; verified on RTX 5080
# (pip installed 1.30.0 at pin time).
ORT_GPU_MIN = "1.30"

Runner = Callable[[list[str], "dict[str, str] | None"], int]


def _subprocess_run(argv: list[str], env: dict[str, str] | None = None) -> int:
    return subprocess.run(argv, env={**os.environ, **env} if env else None).returncode


def backend_dir() -> Path:
    return Path(zygos.__file__).resolve().parent.parent


def setup_gpu(
    *,
    venv_dir: str = DEFAULT_GPU_VENV,
    force: bool = False,
    run: Runner = _subprocess_run,
    exists: Callable[[str], bool] = os.path.exists,
    remove: Callable[[str], None] = shutil.rmtree,
    out: Callable[[str], None] = print,
) -> int:
    py = venv_python(venv_dir)
    abs_venv_dir = os.path.abspath(venv_dir)
    steps: list[tuple[str, list[str], dict[str, str] | None]] = []
    if force and exists(venv_dir):
        out(f"removing {abs_venv_dir}")
        remove(venv_dir)
    if force or not exists(py):
        steps.append(("create venv", [sys.executable, "-m", "venv", venv_dir], None))
    else:
        out(f"reusing {abs_venv_dir}")
    steps += [
        ("install zygos[voice]", [py, "-m", "pip", "install", "-e", f"{backend_dir()}[voice]"], None),
        # `pip install -e .[voice]` can pull the CPU `onnxruntime` back in as a
        # transitive dependency of faster-whisper, even when this venv already
        # has onnxruntime-gpu installed — the two distributions share the same
        # importable `onnxruntime/` package, so whichever installs last wins on
        # disk and a subsequent uninstall of just one can leave the other's
        # files half-deleted. Remove BOTH builds every run (not just the CPU
        # one) so the next install always starts from a clean slate — this
        # repairs a half-built venv on rerun, not only a venv built from
        # scratch. `pip uninstall` on a package that isn't installed just
        # warns and exits 0, so this is a no-op on a venv that never drifted.
        ("remove onnxruntime builds",
         [py, "-m", "pip", "uninstall", "-y", "onnxruntime", "onnxruntime-gpu"], None),
        ("install onnxruntime-gpu",
         [py, "-m", "pip", "install", f"onnxruntime-gpu[cuda,cudnn]>={ORT_GPU_MIN}"], None),
        ("self-check on CUDA", [py, "-m", "zygos.voice.sidecar.kokoro", "--self-check"],
         {"ZYGOS_TTS_DEVICE": "cuda"}),
    ]
    for label, argv, env in steps:
        out(f"==> {label}")
        code = run(argv, env)
        if code != 0:
            out(f"setup-gpu failed at '{label}' (exit {code})")
            return code
    out(f"GPU venv ready at {abs_venv_dir}. To use it, set in your config:  voice.tts.device: cuda")
    return 0
