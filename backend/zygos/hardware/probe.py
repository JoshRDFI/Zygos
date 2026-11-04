"""Hardware probe: GPU, RAM, CPU and model-disk space (RFC-0013 section 1).

Anything undetected is ``None`` -- never a guess. ``scan`` never raises.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

NVIDIA_SMI_ARGS = ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                   "--format=csv,noheader,nounits"]
_MIB = 1024**2


class Gpu(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    vram_total_bytes: int
    vram_free_bytes: int


class HardwareSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gpus: tuple[Gpu, ...] | None
    ram_total_bytes: int | None
    ram_available_bytes: int | None
    cpu_model: str | None
    cpu_cores: int | None
    disk_path: str | None
    disk_free_bytes: int | None
    scanned_at: datetime

    @property
    def vram_total_bytes(self) -> int | None:
        return None if self.gpus is None else sum(g.vram_total_bytes for g in self.gpus)

    @property
    def vram_free_bytes(self) -> int | None:
        return None if self.gpus is None else sum(g.vram_free_bytes for g in self.gpus)


def run_nvidia_smi() -> str | None:
    try:
        done = subprocess.run(NVIDIA_SMI_ARGS, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_nvidia_smi(raw: str | None) -> tuple[Gpu, ...] | None:
    if not raw or not raw.strip():
        return None
    gpus: list[Gpu] = []
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not parts[0] or not parts[1].isdigit() or not parts[2].isdigit():
            return None
        gpus.append(Gpu(name=parts[0], vram_total_bytes=int(parts[1]) * _MIB,
                        vram_free_bytes=int(parts[2]) * _MIB))
    return tuple(gpus)


def _meminfo_kb(text: str, key: str) -> int | None:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            fields = line.split(":", 1)[1].split()
            if fields and fields[0].isdigit():
                return int(fields[0]) * 1024
    return None


def parse_meminfo(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    return _meminfo_kb(text, "MemTotal"), _meminfo_kb(text, "MemAvailable")


def parse_cpuinfo(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("model name") and ":" in line:
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def ollama_models_dir(env: Mapping[str, str], exists: Callable[[str], bool]) -> str | None:
    candidates = [env.get("OLLAMA_MODELS"), os.path.expanduser("~/.ollama/models"),
                  "/usr/share/ollama/.ollama/models"]
    for path in candidates:
        if path and exists(path):
            return path
    return None


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _disk_free(path: str) -> int:
    return shutil.disk_usage(path).free


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe(fn: Callable[[], object]) -> object | None:
    try:
        return fn()
    except Exception:  # noqa: BLE001 - a failed reader means "unknown", never a crash
        return None


class HardwareProbe:
    def __init__(
        self,
        *,
        run_nvidia_smi: Callable[[], str | None] = run_nvidia_smi,
        read_text: Callable[[str], str | None] = _read_text,
        disk_free: Callable[[str], int] = _disk_free,
        cpu_count: Callable[[], int | None] = os.cpu_count,
        env: Mapping[str, str] = os.environ,
        exists: Callable[[str], bool] = os.path.isdir,
        clock: Callable[[], datetime] = _now,
        models_dir: str | None = None,
    ) -> None:
        self._run_nvidia_smi = run_nvidia_smi
        self._read_text = read_text
        self._disk_free = disk_free
        self._cpu_count = cpu_count
        self._env = env
        self._exists = exists
        self._clock = clock
        self._models_dir = models_dir
        self._last: HardwareSnapshot | None = None

    def scan(self) -> HardwareSnapshot:
        gpus = _safe(lambda: parse_nvidia_smi(self._run_nvidia_smi()))
        meminfo = _safe(lambda: self._read_text("/proc/meminfo"))
        ram_total, ram_avail = _safe(lambda: parse_meminfo(meminfo)) or (None, None)
        cpuinfo = _safe(lambda: self._read_text("/proc/cpuinfo"))
        cpu_model = _safe(lambda: parse_cpuinfo(cpuinfo))
        cores = _safe(self._cpu_count)
        disk_path = self._models_dir or _safe(
            lambda: ollama_models_dir(self._env, self._exists))
        disk_free = (_safe(lambda: self._disk_free(disk_path))
                     if isinstance(disk_path, str) else None)
        snapshot = HardwareSnapshot(
            gpus=gpus if isinstance(gpus, tuple) else None,
            ram_total_bytes=ram_total if isinstance(ram_total, int) else None,
            ram_available_bytes=ram_avail if isinstance(ram_avail, int) else None,
            cpu_model=cpu_model if isinstance(cpu_model, str) else None,
            cpu_cores=cores if isinstance(cores, int) else None,
            disk_path=disk_path if isinstance(disk_path, str) else None,
            disk_free_bytes=disk_free if isinstance(disk_free, int) else None,
            scanned_at=self._clock(),
        )
        self._last = snapshot
        return snapshot

    def last(self) -> HardwareSnapshot | None:
        return self._last
