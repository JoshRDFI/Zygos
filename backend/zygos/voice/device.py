"""Engine-neutral voice device resolution (RFC-0005 §2a).

Decides which interpreter/device a voice sidecar is launched with, and opens ONNX
sessions with the right execution providers while reporting the provider actually
obtained. Pure; no zygos.config import. Shared by TTS now and STT later.

Stability: Experimental.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import PureWindowsPath, PurePosixPath
from typing import Callable

DEFAULT_GPU_VENV = ".zygos/venvs/voice-gpu"
SETUP_HINT = "run: zygos voice setup-gpu"

_CUDA = "CUDAExecutionProvider"
_CPU = "CPUExecutionProvider"


@dataclass(frozen=True)
class WorkerLaunch:
    python: str
    device: str
    fallback_reason: str | None


@dataclass(frozen=True)
class OnnxSession:
    session: object
    device: str
    reason: str | None


def venv_python(venv_dir: str, *, os_name: str = os.name) -> str:
    if os_name == "nt":
        return str(PureWindowsPath(venv_dir) / "Scripts" / "python.exe")
    return str(PurePosixPath(venv_dir) / "bin" / "python")


def resolve_worker_launch(
    requested: str,
    worker_python: str | None,
    default_venv_python: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
    main_python: str = sys.executable,
) -> WorkerLaunch:
    if requested != "cuda":
        return WorkerLaunch(python=main_python, device="cpu", fallback_reason=None)
    candidate = worker_python or default_venv_python
    if exists(candidate):
        return WorkerLaunch(python=candidate, device="cuda", fallback_reason=None)
    if worker_python:
        reason = f"worker_python not found at {worker_python}; running on CPU"
    else:
        reason = f"GPU venv not found at {default_venv_python}; {SETUP_HINT}"
    return WorkerLaunch(python=main_python, device="cpu", fallback_reason=reason)


def onnx_providers(device: str) -> list[str]:
    return [_CUDA, _CPU] if device == "cuda" else [_CPU]


def active_device(session_providers: list[str]) -> str:
    return "cuda" if session_providers and session_providers[0] == _CUDA else "cpu"


def preload_gpu_libs(ort_module) -> None:
    # pip onnxruntime-gpu silently lands on CPU unless its CUDA/cuDNN DLLs are
    # preloaded before the first InferenceSession.
    preload = getattr(ort_module, "preload_dlls", None)
    if callable(preload):
        preload()


def open_onnx_session(ort_module, model_path: str, device: str) -> OnnxSession:
    if device == "cuda":
        preload_gpu_libs(ort_module)
    session = ort_module.InferenceSession(model_path, providers=onnx_providers(device))
    active = active_device(list(session.get_providers()))
    reason = None
    if device == "cuda" and active != "cuda":
        available = ", ".join(ort_module.get_available_providers())
        reason = f"CUDAExecutionProvider unavailable (available: {available}); running on CPU"
    return OnnxSession(session=session, device=active, reason=reason)
