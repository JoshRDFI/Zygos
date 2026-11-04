from __future__ import annotations

import struct

import pytest

from tests.models.gguf_writer import kv, s, write_gguf
from zygos.models.gguf import GgufError, read_header


def test_reads_metadata_and_tensors(tmp_path):
    p = write_gguf(
        tmp_path / "m.gguf",
        [
            ("general.architecture", 8, "llama"),
            ("llama.block_count", 4, 32),
            ("llama.rope.freq_base", 6, 10000.0),
            ("tokenizer.add_bos", 7, True),
            ("small", 9, (4, [1, 2, 3])),
        ],
        [("a", [4, 4], 0, 0), ("c", [2], 0, 128), ("b", [8], 0, 64)],
        data_size=200,
    )
    h = read_header(p)
    assert h.version == 3
    assert h.metadata["general.architecture"] == "llama"
    assert h.metadata["llama.block_count"] == 32
    assert h.metadata["llama.rope.freq_base"] == 10000.0
    assert h.metadata["tokenizer.add_bos"] is True
    assert h.metadata["small"] == [1, 2, 3]
    assert h.file_size == p.stat().st_size
    assert h.data_offset == p.stat().st_size - 200
    by = {t.name: t for t in h.tensors}
    assert by["a"].size_bytes == 64
    assert by["b"].size_bytes == 64
    assert by["c"].size_bytes == 200 - 128
    assert [t.offset for t in h.tensors] == [0, 64, 128]


def test_long_arrays_are_summarised(tmp_path):
    p = write_gguf(
        tmp_path / "m.gguf",
        [
            ("tokens", 9, (8, [f"t{i}" for i in range(1000)])),
            ("ints", 9, (5, list(range(500)))),
            ("after", 4, 7),
        ],
    )
    h = read_header(p)
    assert h.metadata["tokens"] == {"type": "string", "length": 1000}
    assert h.metadata["ints"] == {"type": "int32", "length": 500}
    assert h.metadata["after"] == 7


def test_alignment_from_metadata(tmp_path):
    p = write_gguf(tmp_path / "m.gguf", [("general.alignment", 4, 64)], [("a", [1], 0, 0)], alignment=64, data_size=100)
    h = read_header(p)
    assert h.data_offset % 64 == 0 and h.data_offset == p.stat().st_size - 100


def test_v2_supported(tmp_path):
    p = write_gguf(tmp_path / "m.gguf", [("k", 4, 1)], version=2)
    assert read_header(p).version == 2


def test_bad_magic(tmp_path):
    p = tmp_path / "x.gguf"
    p.write_bytes(b"NOPE" + b"\0" * 64)
    with pytest.raises(GgufError, match="magic"):
        read_header(p)


def test_version_1(tmp_path):
    p = write_gguf(tmp_path / "x.gguf", [], version=1)
    with pytest.raises(GgufError, match="unsupported GGUF version 1"):
        read_header(p)


def test_truncated_in_metadata(tmp_path):
    p = write_gguf(tmp_path / "x.gguf", [("a", 8, "hello world"), ("b", 4, 1)])
    data = p.read_bytes()
    p.write_bytes(data[:40])
    with pytest.raises(GgufError):
        read_header(p)


def test_truncated_in_tensor_infos(tmp_path):
    p = write_gguf(tmp_path / "x.gguf", [("a", 4, 1)], [("t", [4], 0, 0)], data_size=0, alignment=1)
    data = p.read_bytes()
    p.write_bytes(data[:-5])
    with pytest.raises(GgufError):
        read_header(p)


def test_string_length_past_eof(tmp_path):
    out = b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + struct.pack("<Q", 2**40) + b"abc"
    p = tmp_path / "x.gguf"
    p.write_bytes(out)
    with pytest.raises(GgufError):
        read_header(p)


def test_hostile_counts(tmp_path):
    p = tmp_path / "x.gguf"
    p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 2**63, 0))
    with pytest.raises(GgufError):
        read_header(p)
    p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 2**63))
    with pytest.raises(GgufError):
        read_header(p)
    body = s("arr") + struct.pack("<I", 9) + struct.pack("<IQ", 8, 2**62)
    p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + body)
    with pytest.raises(GgufError):
        read_header(p)
    body = s("arr") + struct.pack("<I", 9) + struct.pack("<IQ", 4, 2**62)
    p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + body)
    with pytest.raises(GgufError):
        read_header(p)


def test_unknown_value_type(tmp_path):
    p = tmp_path / "x.gguf"
    p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + s("k") + struct.pack("<I", 99) + b"\0" * 8)
    with pytest.raises(GgufError):
        read_header(p)


def test_missing_file(tmp_path):
    with pytest.raises(GgufError):
        read_header(tmp_path / "nope.gguf")


def test_tensor_offset_past_the_data_is_a_truncated_download(tmp_path):
    from tests.models.gguf_writer import write_gguf
    path = write_gguf(tmp_path / "cut.gguf", [("general.architecture", 8, "qwen3")],
                      [("a", [4], 0, 0), ("b", [4], 0, 512)], data_size=256)
    with pytest.raises(GgufError, match="^file is truncated$"):
        read_header(path)


def test_tensor_offset_inside_the_data_is_fine(tmp_path):
    from tests.models.gguf_writer import write_gguf
    path = write_gguf(tmp_path / "ok.gguf", [("general.architecture", 8, "qwen3")],
                      [("a", [4], 0, 0), ("b", [4], 0, 128)], data_size=256)
    assert [t.size_bytes for t in read_header(path).tensors] == [128, 128]


def test_metadata_string_over_16_mib_is_refused(tmp_path):
    from tests.models.gguf_writer import write_gguf
    path = write_gguf(tmp_path / "big.gguf", [("x", 8, "a" * (16 * 1024**2 + 1))])
    with pytest.raises(GgufError, match="^metadata string too long$"):
        read_header(path)


def test_metadata_string_of_16_mib_is_read(tmp_path):
    from tests.models.gguf_writer import write_gguf
    path = write_gguf(tmp_path / "edge.gguf", [("x", 8, "a" * (16 * 1024**2))])
    assert len(read_header(path).metadata["x"]) == 16 * 1024**2
