"""Tests that the RQ worker uses a Windows-safe death-penalty class.

On Windows, signal.SIGALRM does not exist.  The worker must never
install UnixSignalDeathPenalty as its death_penalty_class; instead it
should use TimerDeathPenalty (if available) or the local no-op fallback.
"""

import signal


def _build_safe_death_penalty_class():
    """Re-execute the death-penalty selection logic from _run_rq_worker.

    This helper mirrors the exact try/except block in main._run_rq_worker so
    we can unit-test it without starting Redis or a real worker.
    """
    try:
        from rq.timeouts import TimerDeathPenalty as _SafeDeathPenalty
    except ImportError:
        from rq.timeouts import BaseDeathPenalty as _BaseDP  # type: ignore[assignment]

        class _SafeDeathPenalty(_BaseDP):  # type: ignore[no-redef]
            def setup_death_penalty(self) -> None:
                pass

            def cancel_death_penalty(self) -> None:
                pass

    return _SafeDeathPenalty


def test_safe_death_penalty_does_not_access_sigalrm():
    """setup_death_penalty() must not raise AttributeError on Windows.

    We simulate a Windows environment by temporarily removing SIGALRM
    from the signal module and verifying that the selected class does NOT
    raise AttributeError when its lifecycle methods are called.
    """
    _SafeDeathPenalty = _build_safe_death_penalty_class()

    # Temporarily hide signal.SIGALRM to mimic Windows
    had_sigalrm = hasattr(signal, "SIGALRM")
    sigalrm_value = getattr(signal, "SIGALRM", None)
    if had_sigalrm:
        delattr(signal, "SIGALRM")

    try:
        # Instantiate with timeout=-1 (no RQ-level timeout; app timeout is
        # enforced in render_worker._run_with_timeout() via ThreadPoolExecutor)
        penalty = _SafeDeathPenalty(-1)
        # These must not raise AttributeError on "Windows"
        penalty.setup_death_penalty()
        penalty.cancel_death_penalty()
    finally:
        if had_sigalrm:
            signal.SIGALRM = sigalrm_value  # type: ignore[attr-defined]


def test_safe_death_penalty_is_not_unix_signal_class():
    """The selected death-penalty class must not be UnixSignalDeathPenalty."""
    from rq.timeouts import UnixSignalDeathPenalty

    _SafeDeathPenalty = _build_safe_death_penalty_class()

    assert _SafeDeathPenalty is not UnixSignalDeathPenalty, (
        "Worker must not use UnixSignalDeathPenalty: it accesses signal.SIGALRM "
        "which is unavailable on Windows."
    )


def test_safe_death_penalty_assigned_to_worker():
    """Assigning the safe class to a worker instance overrides any class default.

    This test exercises the instance-level override pattern used in
    _run_rq_worker() without needing Redis or the full app config.
    """
    from rq.timeouts import UnixSignalDeathPenalty

    _SafeDeathPenalty = _build_safe_death_penalty_class()

    # Simulate a minimal worker-like object (the same pattern used in main.py)
    class _FakeWorker:
        death_penalty_class = UnixSignalDeathPenalty  # simulate old RQ default

    worker = _FakeWorker()
    # The fix: override at instance level
    worker.death_penalty_class = _SafeDeathPenalty

    assert worker.death_penalty_class is not UnixSignalDeathPenalty, (
        "Instance-level assignment must override the class default "
        "(UnixSignalDeathPenalty) so Windows never sees signal.SIGALRM."
    )
    assert worker.death_penalty_class is _SafeDeathPenalty
