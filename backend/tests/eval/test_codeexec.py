import pytest

from zygos.eval.codeexec import CheckOutcome, extract_code, run_checks


def test_extract_fenced_python():
    out = extract_code("Here:\n```python\ndef f():\n    return 1\n```\ndone")
    assert out == "def f():\n    return 1"


def test_extract_untagged_fence():
    assert extract_code("```\ndef f():\n    return 2\n```") == "def f():\n    return 2"


def test_extract_last_of_multiple_fences():
    assert extract_code("```\na = 1\n```\ntext\n```python\nb = 2\n```") == "b = 2"


def test_extract_bare_code():
    assert extract_code("  def f():\n    return 1  ") == "def f():\n    return 1"


@pytest.mark.asyncio
async def test_run_checks_all_pass():
    out = await run_checks("def add(a, b):\n    return a + b",
                           ("assert add(1, 2) == 3", "assert add(0, 0) == 0"))
    assert out == CheckOutcome(passed=2, total=2, error=None)


@pytest.mark.asyncio
async def test_run_checks_partial():
    # add is wrong: add(1,2)=4 (fail); add(1,1)=3 (pass)
    out = await run_checks("def add(a, b):\n    return a + b + 1",
                           ("assert add(1, 2) == 3", "assert add(1, 1) == 3"))
    assert out.passed == 1 and out.total == 2


@pytest.mark.asyncio
async def test_run_checks_syntax_error():
    out = await run_checks("def broken(:\n    pass", ("assert True",))
    assert out.passed == 0 and out.error


@pytest.mark.asyncio
async def test_run_checks_timeout():
    out = await run_checks("def f():\n    while True:\n        pass",
                           ("assert f() is None",), timeout_s=1.0)
    assert out.passed == 0 and out.error == "timeout"


@pytest.mark.asyncio
async def test_run_checks_network_blocked():
    code = "import socket\ndef ping():\n    socket.socket()\n    return True"
    out = await run_checks(code, ("assert ping() is True",))
    assert out.passed == 0


@pytest.mark.asyncio
async def test_run_checks_ignores_spoofed_stdout():
    # Candidate prints a result-shaped line then exits before the checks run;
    # the runner must not trust it (eval integrity).
    code = "print('{\"passed\": 5, \"total\": 5}')\nimport sys\nsys.exit(0)"
    out = await run_checks(code, ("assert True", "assert True"))
    assert out.passed == 0 and out.total == 2
