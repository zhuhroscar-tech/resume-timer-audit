import json

import pytest

from resume_timer_audit.cli import main
from resume_timer_audit.core import Finding, Report


def _fake_report(level="info"):
    findings = [Finding(level, "example message")]
    return Report(resume_events_seen=1, timers_inspected=2, clusters=[], findings=findings)


def test_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "resume-timer-audit" in out


def test_text_output(monkeypatch, capsys):
    monkeypatch.setattr("resume_timer_audit.cli.collect_and_evaluate", lambda lookback_days: _fake_report("info"))
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "resume-timer-audit:" in out
    assert "[info]" in out


def test_json_output(monkeypatch, capsys):
    monkeypatch.setattr("resume_timer_audit.cli.collect_and_evaluate", lambda lookback_days: _fake_report("warn"))
    rc = main(["--json"])
    out = capsys.readouterr().out
    assert rc == 1
    parsed = json.loads(out)
    assert parsed["resume_events_seen"] == 1
    assert parsed["timers_inspected"] == 2


def test_fail_exit_code(monkeypatch):
    monkeypatch.setattr("resume_timer_audit.cli.collect_and_evaluate", lambda lookback_days: _fake_report("fail"))
    rc = main([])
    assert rc == 2


def test_lookback_days_passed_through(monkeypatch):
    seen = {}

    def fake(lookback_days):
        seen["lookback_days"] = lookback_days
        return _fake_report("info")

    monkeypatch.setattr("resume_timer_audit.cli.collect_and_evaluate", fake)
    main(["--lookback-days", "30"])
    assert seen["lookback_days"] == 30
