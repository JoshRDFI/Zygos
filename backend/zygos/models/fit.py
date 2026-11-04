"""Fit estimation constants (RFC-0013 §3). Task 5 completes this module."""

from __future__ import annotations

ASSUMED_CONTEXT_TOKENS = 4096
RUNTIME_OVERHEAD_BYTES = 512 * 1024**2
KOKORO_CUDA_RESERVE_BYTES = 1_400 * 1024**2
KV_BYTES_PER_ELEMENT = 2
