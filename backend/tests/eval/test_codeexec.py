from zygos.eval.codeexec import extract_code


def test_extract_fenced_python():
    out = extract_code("Here:\n```python\ndef f():\n    return 1\n```\ndone")
    assert out == "def f():\n    return 1"


def test_extract_untagged_fence():
    assert extract_code("```\ndef f():\n    return 2\n```") == "def f():\n    return 2"


def test_extract_last_of_multiple_fences():
    assert extract_code("```\na = 1\n```\ntext\n```python\nb = 2\n```") == "b = 2"


def test_extract_bare_code():
    assert extract_code("  def f():\n    return 1  ") == "def f():\n    return 1"
