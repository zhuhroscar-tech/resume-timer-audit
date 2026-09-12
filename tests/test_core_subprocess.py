"""Regression tests for the previously-untested subprocess-driven parsing
paths in core.py: run()'s error handling, journalctl-based resume-event
discovery, systemctl-based timer enumeration, the raw-microseconds fallback
in _parse_systemd_duration, and the collect_and_evaluate() wiring.

Before this file, core.py sat at 59% coverage with these real, risky
(subprocess + text-parsing) code paths completely unexercised.
"""
import subprocess
from datetime import datetime

import resume_timer_audit.core as core
from resume_timer_audit.core import (
    Report,
    TimerUnit,
    _parse_journal_timestamp,
    _parse_systemd_duration,
    _parse_systemd_timestamp,
    collect_and_evaluate,
    get_resume_events,
    get_timer_units,
    run,
)


# -- run() -------------------------------------------------------------


def test_run_returns_stdout_on_success(monkeypatch):
    class FakeResult:
        stdout = "hello\n"
        returncode = 0

    def fake_run(cmd, capture_output, text, timeout, check):
        assert cmd == ["echo", "hi"]
        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run(["echo", "hi"]) == "hello\n"


def test_run_returns_empty_string_when_stdout_is_none(monkeypatch):
    class FakeResult:
        stdout = None
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())
    assert run(["whatever"]) == ""


def test_run_swallows_oserror(monkeypatch):
    def raise_oserror(*a, **k):
        raise OSError("command not found")

    monkeypatch.setattr(subprocess, "run", raise_oserror)
    assert run(["nonexistent-binary"]) == ""


def test_run_swallows_subprocess_error(monkeypatch):
    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="journalctl", timeout=30)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert run(["journalctl"]) == ""


# -- get_resume_events() -------------------------------------------------


def test_get_resume_events_parses_systemd_sleep_and_kernel_markers(monkeypatch):
    """Two independent markers for the same physical resume (systemd-sleep
    'Stopped' line and a kernel 'PM: suspend exit' line, five seconds apart)
    must be de-duplicated into one ResumeEvent, and a second, unrelated
    kernel event outside the 5s window must survive as its own event."""

    def fake_run_checked(cmd, *a, **k):
        if "systemd-suspend.service" in cmd:
            return (
                "Sep 10 08:30:00 host systemd-sleep[1]: Stopped System Suspend\n"
                "not a matching line at all\n",
                True,
            )
        if "-g" in cmd and "PM: suspend exit" in cmd:
            return (
                "Sep 10 08:30:03 host kernel: PM: suspend exit\n"
                "Sep 10 09:45:10 host kernel: PM: suspend exit\n",
                True,
            )
        return ("", True)

    monkeypatch.setattr(core, "_run_checked", fake_run_checked)
    events, ok = get_resume_events(lookback_days=7)

    assert ok is True
    assert len(events) == 2
    assert events[0].source == "journalctl: systemd-sleep"
    assert events[0].timestamp.hour == 8 and events[0].timestamp.minute == 30
    assert events[1].source == "journalctl: kernel PM suspend exit"
    assert events[1].timestamp.hour == 9


def test_get_resume_events_empty_when_no_journal_output(monkeypatch):
    monkeypatch.setattr(core, "_run_checked", lambda cmd, *a, **k: ("", True))
    events, ok = get_resume_events()
    assert events == []
    assert ok is True


def test_get_resume_events_ignores_unparseable_lines(monkeypatch):
    monkeypatch.setattr(
        core, "_run_checked", lambda cmd, *a, **k: ("totally malformed line with no timestamp\n", True)
    )
    events, ok = get_resume_events()
    assert events == []
    assert ok is True


def test_get_resume_events_returns_ok_false_when_either_journalctl_call_fails(monkeypatch):
    """Regression: if journalctl fails (permission denied -- caller not in
    the 'systemd-journal' group -- or the binary is missing), an empty
    events list must be reported as unverified (ok=False), never silently
    collapsed into "no resume events found" -- the same false-all-clear
    class of bug get_timer_units already guards against via list_timers_ok."""

    def fake_run_checked(cmd, *a, **k):
        if "systemd-suspend.service" in cmd:
            return ("", False)  # journalctl failed for the systemd-sleep query
        return ("", True)  # kernel query succeeded, found nothing

    monkeypatch.setattr(core, "_run_checked", fake_run_checked)
    events, ok = get_resume_events()
    assert events == []
    assert ok is False


def test_get_resume_events_ok_true_only_when_both_calls_succeed(monkeypatch):
    def fake_run_checked(cmd, *a, **k):
        if "-g" in cmd and "PM: suspend exit" in cmd:
            return ("", False)  # kernel query fails even though sleep query worked
        return ("", True)

    monkeypatch.setattr(core, "_run_checked", fake_run_checked)
    events, ok = get_resume_events()
    assert events == []
    assert ok is False


# -- get_timer_units() ---------------------------------------------------


def test_get_timer_units_parses_names_and_properties(monkeypatch):
    list_timers_out = (
        "Wed 2026-09-10 09:00:00 UTC  1h left  Wed 2026-09-10 08:00:00 UTC  1h ago  "
        "fstrim.timer          fstrim.service\n"
        "n/a                          n/a      n/a                          n/a     "
        "custom.timer          custom.service\n"
    )

    show_outputs = {
        "fstrim.timer": (
            "Persistent=yes\n"
            "RandomizedDelayUSec=10min\n"
            "LastTriggerUSec=Wed 2026-09-10 08:00:00 UTC\n"
            "NextElapseUSecRealtime=Wed 2026-09-10 09:00:00 UTC\n"
        ),
        "custom.timer": (
            "Persistent=no\n"
            "RandomizedDelayUSec=0\n"
            "LastTriggerUSec=n/a\n"
            "NextElapseUSecRealtime=n/a\n"
        ),
    }

    def fake_run_checked(cmd, *a, **k):
        if cmd[0] == "systemctl" and cmd[1] == "list-timers":
            return (list_timers_out, True)
        if cmd[0] == "systemctl" and cmd[1] == "show":
            name = cmd[2]
            return (show_outputs.get(name, ""), True)
        return ("", True)

    monkeypatch.setattr(core, "_run_checked", fake_run_checked)
    units, ok = get_timer_units()
    assert ok is True

    assert [u.name for u in units] == ["custom.timer", "fstrim.timer"]
    fstrim = next(u for u in units if u.name == "fstrim.timer")
    assert fstrim.persistent is True
    assert fstrim.randomized_delay_sec == 600
    assert fstrim.last_trigger is not None and fstrim.last_trigger.hour == 8

    custom = next(u for u in units if u.name == "custom.timer")
    assert custom.persistent is False
    assert custom.randomized_delay_sec is None
    assert custom.last_trigger is None


def test_get_timer_units_no_timers_found(monkeypatch):
    monkeypatch.setattr(core, "_run_checked", lambda cmd, *a, **k: ("", True))
    units, ok = get_timer_units()
    assert units == []
    assert ok is True


def test_get_timer_units_falls_back_to_bare_dot_timer_token(monkeypatch):
    """Lines that don't match the primary regex (e.g. odd column spacing)
    still get their unit name recovered via the plain-token fallback scan."""

    def fake_run_checked(cmd, *a, **k):
        if cmd[0] == "systemctl" and cmd[1] == "list-timers":
            # No trailing ".service" token -> primary regex can't match,
            # forcing the token-scan fallback branch.
            return ("weird.timer  (no service column here)\n", True)
        return ("Persistent=no\nRandomizedDelayUSec=0\nLastTriggerUSec=n/a\nNextElapseUSecRealtime=n/a\n", True)

    monkeypatch.setattr(core, "_run_checked", fake_run_checked)
    units, ok = get_timer_units()
    assert [u.name for u in units] == ["weird.timer"]
    assert ok is True


def test_get_timer_units_returns_ok_false_when_list_timers_fails(monkeypatch):
    monkeypatch.setattr(core, "_run_checked", lambda cmd, *a, **k: ("", False))
    units, ok = get_timer_units()
    assert units == []
    assert ok is False


# -- misc small edge cases -------------------------------------------------


def test_parse_journal_timestamp_bad_value_raises_value_error_swallowed():
    # Matches the regex shape but with an impossible calendar value, so
    # strptime raises ValueError, which _parse_journal_timestamp must catch.
    line = "Xyz 99 99:99:99 host systemd-sleep[1]: Stopped\n"
    assert _parse_journal_timestamp(line, 2026) is None


def test_parse_systemd_timestamp_bad_value_raises_value_error_swallowed():
    assert _parse_systemd_timestamp("not a real timestamp at all") is None


def test_report_worst_level_defaults_to_info_with_no_findings():
    report = Report(resume_events_seen=0, timers_inspected=0, clusters=[], findings=[])
    assert report.worst_level() == "info"


# -- _parse_systemd_duration raw-microseconds fallback -------------------


def test_parse_systemd_duration_raw_microseconds_fallback():
    # No unit suffix at all -> falls back to treating the text as raw usec.
    assert _parse_systemd_duration("5000000") == 5


def test_parse_systemd_duration_unparseable_returns_none():
    assert _parse_systemd_duration("not-a-duration") is None


# -- collect_and_evaluate() wiring ----------------------------------------


def test_collect_and_evaluate_wires_events_and_timers(monkeypatch):
    resume_time = datetime(2026, 9, 10, 8, 0, 0)

    monkeypatch.setattr(
        core, "get_resume_events", lambda lookback_days=14: (
            [core.ResumeEvent(resume_time, "journalctl: systemd-sleep")],
            True,
        )
    )
    monkeypatch.setattr(
        core, "get_timer_units", lambda: (
            [
                TimerUnit(
                    name="a.timer", persistent=True,
                    randomized_delay_sec=None,
                    last_trigger=resume_time, next_elapse=None,
                ),
                TimerUnit(
                    name="b.timer", persistent=True,
                    randomized_delay_sec=None,
                    last_trigger=resume_time, next_elapse=None,
                ),
            ],
            True,
        )
    )

    report = collect_and_evaluate(lookback_days=3)
    assert report.resume_events_seen == 1
    assert report.timers_inspected == 2
    assert report.worst_level() == "fail"
