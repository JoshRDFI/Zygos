from zygos.services.router import _CircuitBreaker


def _breaker(threshold=2, cooldown=10.0, t=None):
    clock = t if t is not None else {"v": 0.0}
    return _CircuitBreaker(threshold, cooldown, lambda: clock["v"]), clock


def test_closed_admits_without_probe():
    breaker, _ = _breaker()
    assert breaker.admit() == (True, False)
    assert breaker.state == "closed"


def test_open_denies_until_cooldown():
    breaker, clock = _breaker(threshold=1)
    breaker.record_failure("boom", probe=False)  # opens (threshold=1)
    assert breaker.state == "open"
    assert breaker.admit() == (False, False)


def test_half_open_admits_exactly_one_probe():
    breaker, clock = _breaker(threshold=1, cooldown=10.0)
    breaker.record_failure("boom", probe=False)
    clock["v"] = 11.0  # past cooldown
    assert breaker.state == "half_open"
    assert breaker.admit() == (True, True)   # first probe
    assert breaker.admit() == (False, False)  # second denied while probing


def test_probe_success_closes():
    breaker, clock = _breaker(threshold=1, cooldown=10.0)
    breaker.record_failure("boom", probe=False)
    clock["v"] = 11.0
    breaker.admit()
    breaker.record_success(probe=True)
    assert breaker.state == "closed"


def test_probe_failure_reopens_with_fresh_cooldown():
    breaker, clock = _breaker(threshold=1, cooldown=10.0)
    breaker.record_failure("boom", probe=False)
    clock["v"] = 11.0
    breaker.admit()
    breaker.record_failure("again", probe=True)
    assert breaker.state == "open"  # reopened at t=11
    assert breaker.admit() == (False, False)


def test_stale_success_does_not_reset_open_breaker():
    # AC5 at unit level: a non-probe success must not reset an open breaker.
    breaker, clock = _breaker(threshold=1)
    breaker.record_failure("boom", probe=False)  # open
    assert breaker.state == "open"
    breaker.record_success(probe=False)          # stale in-flight success
    assert breaker.state == "open"               # still open
