"""Brute-force cosine search over active-model vectors (RFC-0006 §3).

numpy is imported HERE ONLY. The `embeddings` extra that provides numpy is the
same one that provides an embedder, so 'no numpy' and 'no embedder' collapse to
the identical degrade-to-FTS path. vectors.py stays stdlib for the extra-free
primitive.

Stability: Experimental.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from zygos.memory.store import MemoryStore


class VectorSearch:
    def __init__(self, store: MemoryStore, *, model: str) -> None:
        self._store = store
        self._model = model

    def search(self, qvec: Sequence[float], *, k: int) -> list[tuple[str, float]]:
        rows = self._store.all_embeddings(self._model)
        if not rows:
            return []
        q = np.asarray(qvec, dtype=np.float32)
        dim = int(q.shape[0])
        ids: list[str] = []
        mats: list[np.ndarray] = []
        for record_id, blob in rows:
            if len(blob) != dim * 4:  # defensive: skip a row whose dim disagrees
                continue
            ids.append(record_id)
            mats.append(np.frombuffer(blob, dtype=np.float32))
        if not ids:
            return []
        matrix = np.vstack(mats)  # (n, dim)
        qn = q / (float(np.linalg.norm(q)) or 1.0)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix_n = matrix / np.where(norms == 0.0, 1.0, norms)
        sims = matrix_n @ qn  # (n,)
        order = np.argsort(-sims)[:k]
        return [(ids[i], float(sims[i])) for i in order]
