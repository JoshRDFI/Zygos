from __future__ import annotations

import os

import pytest

from tests.models.gguf_writer import write_gguf
from zygos.models.gguf_scan import scan_folder


def mk(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + b"\0" * 20)
    return path


def test_nested_and_sorted(tmp_path):
    mk(tmp_path / "b.gguf")
    mk(tmp_path / "sub" / "deep" / "a.gguf")
    (tmp_path / "notes.txt").write_text("x")
    models = scan_folder(tmp_path)
    assert [m.name for m in models] == ["b", "sub/deep/a"]
    assert models[0].files == (tmp_path / "b.gguf",)
    assert models[0].size_bytes == 24
    assert models[0].mmproj is None


def test_split_set(tmp_path):
    mk(tmp_path / "X-00002-of-00002.gguf")
    mk(tmp_path / "X-00001-of-00002.gguf")
    [m] = scan_folder(tmp_path)
    assert m.name == "X"
    assert [p.name for p in m.files] == ["X-00001-of-00002.gguf", "X-00002-of-00002.gguf"]
    assert m.size_bytes == 48


def test_split_missing_part_still_one_model(tmp_path):
    mk(tmp_path / "Y-00002-of-00003.gguf")
    [m] = scan_folder(tmp_path)
    assert m.name == "Y" and len(m.files) == 1


def test_one_model_one_mmproj_paired(tmp_path):
    mk(tmp_path / "m.gguf")
    mk(tmp_path / "MMPROJ-m.gguf")
    [m] = scan_folder(tmp_path)
    assert m.name == "m"
    assert m.mmproj == tmp_path / "MMPROJ-m.gguf"
    assert m.mmproj_ambiguous == ()


def test_ambiguous_mmproj(tmp_path):
    mk(tmp_path / "a.gguf")
    mk(tmp_path / "b.gguf")
    mk(tmp_path / "mmproj-x.gguf")
    ms = scan_folder(tmp_path)
    assert len(ms) == 2
    for m in ms:
        assert m.mmproj is None
        assert m.mmproj_ambiguous == (tmp_path / "mmproj-x.gguf",)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unreadable_subfolder_skipped(tmp_path):
    mk(tmp_path / "ok.gguf")
    bad = tmp_path / "locked"
    mk(bad / "hidden.gguf")
    bad.chmod(0)
    try:
        assert [m.name for m in scan_folder(tmp_path)] == ["ok"]
    finally:
        bad.chmod(0o700)


def test_missing_root(tmp_path):
    assert scan_folder(tmp_path / "nope") == []
