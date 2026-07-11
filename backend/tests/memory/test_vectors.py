import math

from zygos.memory.vectors import cosine, pack, unpack


def test_pack_unpack_round_trips_as_float32():
    v = [1.0, -0.5, 0.25, 0.0]
    out = unpack(pack(v))
    assert len(out) == 4
    for got, want in zip(out, v):
        assert math.isclose(got, want, rel_tol=1e-6, abs_tol=1e-6)


def test_cosine_identities():
    assert math.isclose(cosine([1.0, 0.0], [1.0, 0.0]), 1.0, abs_tol=1e-9)
    assert math.isclose(cosine([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-9)
    assert math.isclose(cosine([1.0, 2.0], [2.0, 4.0]), 1.0, abs_tol=1e-9)  # parallel
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector -> 0, no divide-by-zero
