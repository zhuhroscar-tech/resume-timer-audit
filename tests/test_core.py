from datetime import datetime, timedelta

from resume_timer_audit.core import (
    ClusterFinding,
    ResumeEvent,
    TimerUnit,
    _parse_journal_timestamp,
    _parse_systemd_duration,
    _parse_systemd_timestamp,
    evaluate,
    find_clusters,
)


def test_parse_journal_timestamp():
    line = "Sep 10 08:30:01 host systemd-sleep[123]: System returned from suspend"
    ts = _parse_journal_timestamp(line, 2026)
    assert ts is not None
    assert ts.month == 9 and ts.day == 10 and ts.hour == 8 and ts.minute == 30


def test_parse_journal_timestamp_no_match():
    assert _parse_journal_timestamp("not a journal line", 2026) is None


def test_parse_systemd_duration_various_units():
    assert _parse_systemd_duration("10min") == 600
    assert _parse_systemd_duration("1h") == 3600
    assert _parse_systemd_duration("30s") == 30
    assert _parse_systemd_duration("0") is None
    assert _parse_systemd_duration("n/a") is None
    assert _parse_systemd_duration("") is None


def test_parse_systemd_duration_combined():
    assert _parse_systemd_duration("1h 30min") == 5400


def test_parse_systemd_timestamp():
    ts = _parse_systemd_timestamp("Wed 2026-09-10 08:30:00 UTC")
    assert ts is not None
    assert ts.year == 2026 and ts.month == 9 and ts.day == 10


def test_parse_systemd_timestamp_na():
    assert _parse_systemd_timestamp("n/a") is None
    assert _parse_systemd_timestamp(None) is None


def _timer(name, persistent=True, last_trigger=None, randomized_delay_sec=None):
    return TimerUnit(
        name=name,
        persistent=persistent,
        randomized_delay_sec=randomized_delay_sec,
        last_trigger=last_trigger,
        next_elapse=None,
    )


def test_find_clusters_detects_thundering_herd():
    resume_time = datetime(2026, 9, 10, 8, 0, 0)
    resume = ResumeEvent(resume_time, "journalctl: systemd-sleep")

    timers = [
        _timer("fstrim.timer", last_trigger=resume_time + timedelta(seconds=5)),
        _timer("logrotate.timer", last_trigger=resume_time + timedelta(seconds=20)),
        _timer("unrelated.timer", last_trigger=resume_time + timedelta(hours=5)),
    ]

    clusters = find_clusters([resume], timers)
    assert len(clusters) == 1
    assert set(clusters[0].timers) == {"fstrim.timer", "logrotate.timer"}


def test_find_clusters_no_cluster_when_single_timer():
    resume_time = datetime(2026, 9, 10, 8, 0, 0)
    resume = ResumeEvent(resume_time, "journalctl: systemd-sleep")
    timers = [_timer("fstrim.timer", last_trigger=resume_time + timedelta(seconds=5))]
    assert find_clusters([resume], timers) == []


def test_find_clusters_ignores_non_persistent():
    resume_time = datetime(2026, 9, 10, 8, 0, 0)
    resume = ResumeEvent(resume_time, "journalctl: systemd-sleep")
    timers = [
        _timer("a.timer", persistent=False, last_trigger=resume_time + timedelta(seconds=5)),
        _timer("b.timer", persistent=False, last_trigger=resume_time + timedelta(seconds=10)),
    ]
    assert find_clusters([resume], timers) == []


def test_find_clusters_ignores_timers_without_last_trigger():
    resume_time = datetime(2026, 9, 10, 8, 0, 0)
    resume = ResumeEvent(resume_time, "journalctl: systemd-sleep")
    timers = [_timer("a.timer", last_trigger=None), _timer("b.timer", last_trigger=None)]
    assert find_clusters([resume], timers) == []


def test_evaluate_reports_fail_on_cluster():
    resume_time = datetime(2026, 9, 10, 8, 0, 0)
    resume = ResumeEvent(resume_time, "journalctl: systemd-sleep")
    timers = [
        _timer("fstrim.timer", last_trigger=resume_time + timedelta(seconds=5)),
        _timer("logrotate.timer", last_trigger=resume_time + timedelta(seconds=20)),
    ]
    report = evaluate([resume], timers)
    assert report.worst_level() == "fail"
    assert report.resume_events_seen == 1
    assert report.timers_inspected == 2


def test_evaluate_no_events_is_info():
    report = evaluate([], [])
    assert report.worst_level() == "info"
    assert report.resume_events_seen == 0


def test_evaluate_warns_on_missing_randomized_delay():
    timers = [_timer("a.timer", randomized_delay_sec=None), _timer("b.timer", randomized_delay_sec=600)]
    report = evaluate([], timers)
    levels = [f.level for f in report.findings]
    assert "warn" in levels


def test_evaluate_warns_when_list_timers_failed():
    # Before this fix, a failed `systemctl list-timers` (missing binary,
    # non-systemd host) produced timers=[] which evaluate() could not tell
    # apart from "genuinely zero timers on this host" -- silently reporting
    # a clean "0 timers inspected, no clustering" result.
    report = evaluate([], [], list_timers_ok=False)
    levels = [f.level for f in report.findings]
    assert "warn" in levels
    assert any("could not enumerate" in f.message.lower() for f in report.findings)


def test_evaluate_default_list_timers_ok_true_is_backward_compatible():
    report = evaluate([], [])
    assert not any("could not enumerate" in f.message.lower() for f in report.findings)


def test_get_timer_units_returns_ok_false_on_systemctl_failure(monkeypatch):
    import resume_timer_audit.core as core_mod

    def fake_run_checked(cmd):
        return ("", False)

    monkeypatch.setattr(core_mod, "_run_checked", fake_run_checked)
    units, ok = core_mod.get_timer_units()
    assert units == []
    assert ok is False


def test_report_to_dict_roundtrip():
    resume_time = datetime(2026, 9, 10, 8, 0, 0)
    resume = ResumeEvent(resume_time, "journalctl: systemd-sleep")
    timers = [
        _timer("a.timer", last_trigger=resume_time + timedelta(seconds=1)),
        _timer("b.timer", last_trigger=resume_time + timedelta(seconds=2)),
    ]
    report = evaluate([resume], timers)
    d = report.to_dict()
    assert d["resume_events_seen"] == 1
    assert d["timers_inspected"] == 2
    assert len(d["clusters"]) == 1
    assert isinstance(d["clusters"][0]["timers"], list)


def test_cluster_finding_to_dict():
    cf = ClusterFinding(resume_time=datetime(2026, 1, 1, 0, 0, 0), timers=["a.timer", "b.timer"])
    d = cf.to_dict()
    assert d["timers"] == ["a.timer", "b.timer"]
    assert d["window_seconds"] == 90
