from zygos.memory.retrieve import rrf_fuse


def test_normalizes_top_to_one():
    out = rrf_fuse([("a", 9.9)], [("a", 0.1)], k=5)
    assert out[0] == ("a", 1.0)


def test_disjoint_arms_keep_both():
    out = dict(rrf_fuse([("a", 1.0)], [("b", 1.0)], k=5))
    assert set(out) == {"a", "b"}
    assert max(out.values()) == 1.0


def test_agreement_outranks_single_arm():
    # c appears top of BOTH arms; a/b appear in one arm each -> c wins.
    lexical = [("c", 1.0), ("a", 0.5)]
    semantic = [("c", 1.0), ("b", 0.5)]
    out = rrf_fuse(lexical, semantic, k=10)
    assert out[0][0] == "c"
    assert out[0][1] == 1.0


def test_empty_arms_return_empty():
    assert rrf_fuse([], [], k=5) == []


def test_respects_k():
    lexical = [(c, 1.0) for c in "abcde"]
    assert len(rrf_fuse(lexical, [], k=3)) == 3
