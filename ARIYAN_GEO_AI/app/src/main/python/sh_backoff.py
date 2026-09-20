"""Opt-in HTTP 429 (rate-limit) handling for the four Copernicus Data Space
statistics sources: NDVI, Thermal, Optical and SAR.

WHY THIS EXISTS. Observed on real hardware: right after a wide-area job,
a single-point investigation got HTTP 429 from
sh.dataspace.copernicus.eu/statistics/v1 on every Thermal, Optical and SAR
check and on some NDVI checks. The four sources record such a failure as
"unavailable" and move on -- honest, but a long wide-area job would then
lose most of its satellite evidence for a problem that clears by itself
within seconds or minutes.

THE PRINCIPLE: NOTHING IN THIS MODULE CHANGES BEHAVIOUR UNLESS A
WIDE-AREA JOB HAS *ARMED* IT. arm() is called by
wide_area_search_mobile.run_wide_area_search_job() at the start of a job
and disarm() in a `finally` block at its end, so the app is back in its
original state whether the job finishes, fails or is stopped. The armed
state lives in a threading.local(), so it applies ONLY to the thread
running the job: a single-point investigation started meanwhile on
another thread behaves exactly as before. On a thread that is not armed
the installed wrapper does nothing but call the original function with
the original arguments.

WHAT AN ARMED THREAD GETS:
  * Retry on 429 with the server's own Retry-After when it sends one,
    otherwise exponential backoff (BASE_DELAY_S, doubling), each wait
    capped at MAX_DELAY_S, at most MAX_RETRIES retries per call.
  * Light pacing: at least MIN_INTERVAL_S between calls, to avoid
    provoking the limit in the first place.
  * A circuit breaker: if a call still gets 429 after every retry, the
    limit is not clearing on its own (e.g. a quota, not a burst), so for
    TRIP_COOLDOWN_S further calls fail IMMEDIATELY, with an honest
    "HTTP 429 ... skipped" message in the source's own error class,
    instead of each burning minutes of retries. After the cooldown one
    single probe call is allowed (no retries); success resumes normal
    operation, another 429 re-arms the cooldown.
  * Counters, returned by disarm(), so the job's result reports what
    actually happened.

Only HTTP 429 is retried. Every other failure (bad credentials, network
error, timeout, malformed response) propagates untouched and immediately.

HOW IT HOOKS IN WITHOUT EDITING THE FOUR SOURCES: each source module
funnels every request through a module-level
_urlopen_with_hard_deadline(req, timeout) and raises its OWN error class
(NDVIFetchError, ThermalFetchError, OpticalFetchError, SARFetchError)
with `raise ... from exc`, so the original urllib HTTPError -- and its
Retry-After header -- is available as `__cause__`. install() replaces
that module-level function, once, with a wrapper (idempotent; safe to
call repeatedly). The wrapper looks the armed state up per call, so it
is inert when disarmed.

HONEST LIMITATIONS: the constants below are reasoned starting values,
not measured against Copernicus' real limits, and pacing is deliberately
small. The Retry-After header is honoured only in its delta-seconds form.
"""

from __future__ import annotations

import importlib
import threading
import time
from typing import Any, Callable, Dict, Optional

MAX_RETRIES = 5
BASE_DELAY_S = 4.0
MAX_DELAY_S = 90.0
TRIP_COOLDOWN_S = 300.0
MIN_INTERVAL_S = 0.25

# (module name, name of that module's own error class)
_TARGETS = (
    ("ndvi_source_mobile", "NDVIFetchError"),
    ("thermal_source_mobile", "ThermalFetchError"),
    ("optical_source_mobile", "OpticalFetchError"),
    ("sar_source_mobile", "SARFetchError"),
)

# Test hooks: tests replace these with a fake clock so nothing really waits.
_sleep: Callable[[float], None] = time.sleep
_now: Callable[[], float] = time.monotonic

_tl = threading.local()
_install_lock = threading.Lock()
_installed: Dict[str, Callable[..., Any]] = {}  # module name -> original function


def _new_state() -> Dict[str, Any]:
    return {
        "tripped": False,
        "tripped_until": 0.0,
        "last_call": 0.0,
        "calls": 0,
        "retries": 0,
        "retry_wait_s": 0.0,
        "trips": 0,
        "skipped": 0,
        "recovered": 0,
    }


def is_armed() -> bool:
    """True only on a thread that has called arm() and not yet disarm()."""
    return getattr(_tl, "state", None) is not None


def stats() -> Optional[Dict[str, Any]]:
    """Counters for the CURRENT thread's armed session, or None."""
    st = getattr(_tl, "state", None)
    if st is None:
        return None
    return {
        "calls": st["calls"],
        "retries": st["retries"],
        "retry_wait_s": round(st["retry_wait_s"], 1),
        "trips": st["trips"],
        "skipped_while_paused": st["skipped"],
        "recovered_after_pause": st["recovered"],
    }


def arm() -> None:
    """Arm 429 handling for the calling thread and make sure the source
    modules are wrapped. Call disarm() in a `finally` block."""
    install()
    _tl.state = _new_state()


def disarm() -> Optional[Dict[str, Any]]:
    """Disarm the calling thread; returns its final counters (or None if
    it was not armed). After this the thread behaves exactly as it did
    before arm()."""
    summary = stats()
    _tl.state = None
    return summary


def install() -> None:
    """Wrap each source module's _urlopen_with_hard_deadline exactly once.
    Idempotent. A missing module or a module whose shape has changed is
    skipped, never fatal (that source simply keeps its original
    behaviour)."""
    with _install_lock:
        for mod_name, cls_name in _TARGETS:
            if mod_name in _installed:
                continue
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue
            orig = getattr(mod, "_urlopen_with_hard_deadline", None)
            err_cls = getattr(mod, cls_name, None)
            if orig is None or err_cls is None:
                continue
            setattr(mod, "_urlopen_with_hard_deadline", _make_wrapper(orig, err_cls))
            _installed[mod_name] = orig


def uninstall() -> None:
    """Put the original functions back. The app never needs this (the
    wrappers are inert when disarmed); it exists for tests and for anyone
    who wants the literal original function objects restored."""
    with _install_lock:
        for mod_name, orig in list(_installed.items()):
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue
            setattr(mod, "_urlopen_with_hard_deadline", orig)
            del _installed[mod_name]


def _make_wrapper(orig: Callable[..., Any], err_cls: type) -> Callable[..., Any]:
    def wrapped(req, timeout):
        st = getattr(_tl, "state", None)
        if st is None:
            return orig(req, timeout)  # disarmed thread: EXACTLY the original
        return _armed_call(orig, err_cls, st, req, timeout)

    wrapped.__name__ = getattr(orig, "__name__", "_urlopen_with_hard_deadline")
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def _is_429(exc: BaseException) -> bool:
    if str(exc).startswith("HTTP 429"):
        return True
    return getattr(exc.__cause__, "code", None) == 429


def _retry_after_s(exc: BaseException) -> Optional[float]:
    headers = getattr(exc.__cause__, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None  # HTTP-date form: not honoured, fall back to backoff
    return value if value >= 0 else None


def _delay_for(exc: BaseException, retries_so_far: int) -> float:
    hinted = _retry_after_s(exc)
    if hinted is not None:
        return min(max(hinted, 1.0), MAX_DELAY_S)
    return min(BASE_DELAY_S * (2 ** retries_so_far), MAX_DELAY_S)


def _pace(st: Dict[str, Any]) -> None:
    wait = st["last_call"] + MIN_INTERVAL_S - _now()
    if wait > 0:
        _sleep(wait)
    st["last_call"] = _now()


def _armed_call(orig, err_cls, st, req, timeout):
    st["calls"] += 1
    probing = False
    if st["tripped"]:
        remaining = st["tripped_until"] - _now()
        if remaining > 0:
            st["skipped"] += 1
            raise err_cls(
                f"HTTP 429 from {req.full_url}: Copernicus rate limit "
                f"persisted through {MAX_RETRIES} retries; calls to it are "
                f"paused for another {remaining:.0f} s and this call was "
                "skipped without contacting the server (the job re-probes "
                "automatically)."
            )
        probing = True  # cooldown over: one single attempt, no retries

    retries = 0
    while True:
        _pace(st)
        try:
            result = orig(req, timeout)
        except err_cls as exc:
            if not _is_429(exc):
                raise
            if probing:
                st["tripped_until"] = _now() + TRIP_COOLDOWN_S
                st["trips"] += 1
                raise
            if retries >= MAX_RETRIES:
                st["tripped"] = True
                st["tripped_until"] = _now() + TRIP_COOLDOWN_S
                st["trips"] += 1
                raise
            delay = _delay_for(exc, retries)
            retries += 1
            st["retries"] += 1
            st["retry_wait_s"] += delay
            _sleep(delay)
            continue
        if probing:
            st["tripped"] = False
            st["recovered"] += 1
        return result
