# resume-timer-audit

[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

A read-only Linux diagnostic for systemd timers that fire together immediately after suspend/resume. It correlates wake events from the journal with timers' most recent trigger times and highlights persistent timers without randomized delay.

![Example timer audit](docs/images/example-output.png)

This is a way to investigate a suspected wake-time workload pile-up, not a scheduler or an automatic fix. Background: [systemd #43350](https://github.com/systemd/systemd/issues/43350).

## Requirements and installation

Requires Python 3.9+, Linux with systemd, and `journalctl` / `systemctl` on PATH. It is not a useful host diagnostic on macOS, Windows, or non-systemd Linux. Runtime Python dependencies are standard-library only.

```bash
git clone https://github.com/zhuhroscar-tech/resume-timer-audit.git
cd resume-timer-audit
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
resume-timer-audit --help
```

Alternatively, use the standalone `.pyz` from [GitHub Releases](https://github.com/zhuhroscar-tech/resume-timer-audit/releases), verifying it against the release's `SHA256SUMS.txt` before execution.

## Run an audit

```bash
resume-timer-audit
resume-timer-audit --json
resume-timer-audit --lookback-days 30
```

The default journal lookback is 14 days. A cluster means at least two persistent timers have their latest trigger within 90 seconds after the same resume event. Exit codes are `0` for informational findings only, `1` for warnings, and `2` for a detected cluster.

System-wide journal access may require membership in `systemd-journal` or elevated privileges. Journal or timer-enumeration failures produce warnings rather than a confirmed all-clear.

## Limits and safety

- Reads logs and unit metadata only; never edits timer units, starts services, changes schedules, or writes its own state files. No network requests or telemetry.
- Uses each timer's **latest trigger**, not a complete history of every firing. A longer lookback cannot recover overwritten trigger metadata.
- Timestamp parsing is best-effort and assumes the current year for short journal timestamps. Locale, timezone, and year boundaries can affect results.
- A cluster indicates timing correlation, not proof of CPU/IO contention or its cause. Review the affected units and workload before manually changing randomized delays or calendar times.

## Development

```bash
pip install -e ".[dev]"
pytest -v
```

The [test suite](tests) covers parsing, clustering, subprocess failures, and CLI behavior. [MIT license](LICENSE).
