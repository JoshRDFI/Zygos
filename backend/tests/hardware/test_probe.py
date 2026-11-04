from __future__ import annotations

from datetime import datetime, timezone

from zygos.hardware.probe import (
    Gpu,
    HardwareProbe,
    HardwareSnapshot,
    ollama_models_dir,
    parse_cpuinfo,
    parse_meminfo,
    parse_nvidia_smi,
)

MIB = 1024**2
NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _boom(*_a, **_k):
    raise RuntimeError("boom")


def test_parse_nvidia_smi_one_gpu():
    assert parse_nvidia_smi("NVIDIA GeForce RTX 5080, 16303, 14021\n") == (
        Gpu(name="NVIDIA GeForce RTX 5080", vram_total_bytes=16303 * MIB,
            vram_free_bytes=14021 * MIB),
    )


def test_parse_nvidia_smi_two_gpus_and_sums():
    gpus = parse_nvidia_smi("A, 8000, 6000\nB, 12000, 1000\n")
    assert gpus is not None and len(gpus) == 2
    snap = HardwareSnapshot(
        gpus=gpus, ram_total_bytes=None, ram_available_bytes=None, cpu_model=None,
        cpu_cores=None, disk_path=None, disk_free_bytes=None, scanned_at=NOW,
    )
    assert snap.vram_free_bytes == 7000 * MIB
    assert snap.vram_total_bytes == 20000 * MIB


def test_parse_nvidia_smi_missing_or_malformed_is_none():
    assert parse_nvidia_smi(None) is None
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("[N/A], x, y") is None
    assert parse_nvidia_smi("A, 8000, 6000\nbad line\n") is None


def test_parse_meminfo():
    text = "MemTotal:       32768000 kB\nMemFree: 1 kB\nMemAvailable:   20000000 kB\n"
    assert parse_meminfo(text) == (32768000 * 1024, 20000000 * 1024)
    assert parse_meminfo(None) == (None, None)


def test_parse_cpuinfo_first_model_name():
    text = ("processor\t: 0\nmodel name\t: AMD Ryzen 7 3700X\n\n"
            "processor\t: 1\nmodel name\t: Other\n")
    assert parse_cpuinfo(text) == "AMD Ryzen 7 3700X"
    assert parse_cpuinfo("processor : 0\n") is None
    assert parse_cpuinfo(None) is None


def test_ollama_models_dir_prefers_env_then_home_then_system(monkeypatch):
    import os
    home = os.path.expanduser("~/.ollama/models")
    system = "/usr/share/ollama/.ollama/models"
    everything = lambda p: True  # noqa: E731
    assert ollama_models_dir({"OLLAMA_MODELS": "/m"}, everything) == "/m"
    assert ollama_models_dir({}, everything) == home
    assert ollama_models_dir({}, lambda p: p == system) == system
    assert ollama_models_dir({"OLLAMA_MODELS": "/m"}, lambda p: p == system) == system
    assert ollama_models_dir({}, lambda p: False) is None


def test_scan_with_nothing_detected_reports_none_never_raises():
    probe = HardwareProbe(
        run_nvidia_smi=_boom, read_text=_boom, disk_free=_boom, cpu_count=_boom,
        env={}, exists=lambda p: False, clock=lambda: NOW,
    )
    snap = probe.scan()
    assert snap.gpus is None
    assert snap.ram_total_bytes is None and snap.ram_available_bytes is None
    assert snap.cpu_model is None and snap.cpu_cores is None
    assert snap.disk_path is None and snap.disk_free_bytes is None
    assert snap.vram_total_bytes is None and snap.vram_free_bytes is None
    assert snap.scanned_at == NOW
    assert probe.last() is snap


def test_last_is_none_before_scan():
    assert HardwareProbe(run_nvidia_smi=lambda: None, read_text=lambda p: None,
                         env={}, exists=lambda p: False).last() is None


def test_scan_fills_disk_from_models_dir():
    probe = HardwareProbe(
        run_nvidia_smi=lambda: None, read_text=lambda p: None,
        disk_free=lambda p: 123, env={"OLLAMA_MODELS": "/m"},
        exists=lambda p: p == "/m", clock=lambda: NOW,
    )
    snap = probe.scan()
    assert snap.disk_path == "/m" and snap.disk_free_bytes == 123


def test_models_dir_override_skips_search():
    seen = []
    probe = HardwareProbe(
        run_nvidia_smi=lambda: None, read_text=lambda p: None,
        disk_free=lambda p: seen.append(p) or 7, env={"OLLAMA_MODELS": "/env"},
        exists=lambda p: True, clock=lambda: NOW, models_dir="/override",
    )
    snap = probe.scan()
    assert snap.disk_path == "/override" and snap.disk_free_bytes == 7
    assert seen == ["/override"]


def test_scan_reads_gpu_ram_cpu():
    files = {
        "/proc/meminfo": "MemTotal: 100 kB\nMemAvailable: 50 kB\n",
        "/proc/cpuinfo": "model name : Foo CPU\n",
    }
    probe = HardwareProbe(
        run_nvidia_smi=lambda: "G, 1000, 500\n", read_text=files.get,
        cpu_count=lambda: 16, env={}, exists=lambda p: False, clock=lambda: NOW,
    )
    snap = probe.scan()
    assert snap.gpus is not None and snap.vram_free_bytes == 500 * MIB
    assert snap.ram_total_bytes == 100 * 1024 and snap.ram_available_bytes == 50 * 1024
    assert snap.cpu_model == "Foo CPU" and snap.cpu_cores == 16
