# resume-timer-audit

[![CI](https://github.com/zhuhroscar-tech/resume-timer-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/zhuhroscar-tech/resume-timer-audit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/zhuhroscar-tech/resume-timer-audit?include_prereleases&label=release)](https://github.com/zhuhroscar-tech/resume-timer-audit/releases)
![Linux](https://img.shields.io/badge/platform-Linux-111111?logo=linux)

Detects systemd timers that cluster/stall right after a laptop or desktop
resumes from suspend — a real, currently-open upstream gap
([systemd#43350](https://github.com/systemd/systemd/issues/43350)).

## The problem

`Persistent=true` on a systemd timer is meant to catch up a missed run —
and it correctly re-anchors that catch-up after a **reboot**. It does
**not** get the same re-anchor after a **resume from suspend**. The result:
several independent timers (`fstrim.timer`, `logrotate.timer`, backup
timers, etc.), each individually reasonable, can all fire together the
instant a laptop wakes up — instead of being spread out the way
`RandomizedDelaySec=` is meant to achieve. That produces a real, measurable
CPU/IO stall right when someone starts using the machine.

This has been reported with real PSI-based (`/proc/pressure/`)
instrumentation showing 88+ resume events with clustered timer firings
and a measurable stall — and remains open upstream at the time this tool
was written. No existing tool detects this specific signature.

## Simple explanation

On a laptop that sleeps and wakes up a lot, several unrelated background
chores (like disk cleanup or log rotation) can all decide to run at the
exact same moment right after you open the lid — because the "catch up
on missed work" logic that normally spreads tasks out doesn't fully
apply after waking from sleep, only after a full reboot. That pile-up
can cause a noticeable slowdown right when you start using the machine.
This tool checks your computer's sleep/wake history against its
scheduled tasks and tells you exactly when and which tasks are
clustering together. It only reads logs — it never changes any
schedule.

## What it does

`resume-timer-audit` is a **strictly read-only** diagnostic:

1. Reads `journalctl` for suspend/resume boundaries (`systemd-sleep` unit
   events and kernel `PM: suspend exit` markers).
2. Reads `systemctl list-timers --all` / `systemctl show` for each
   persistent timer's last-trigger time and `RandomizedDelaySec=` setting.
3. Cross-references: flags any resume event where 2+ persistent timers
   fired within a 90-second window right after resume (the
   thundering-herd signature), and separately flags persistent timers
   that have no `RandomizedDelaySec=` at all.

It **never** modifies timer units, starts/stops services, or touches
systemd configuration in any way. It only reads.

## Install

Requires Python 3.9+ on Linux (uses `journalctl` and `systemctl`, so this
tool is meaningless on non-systemd systems and on macOS/Windows).

```bash
pip install resume-timer-audit
```

Or run the standalone zipapp with no install:

```bash
curl -LO https://github.com/zhuhroscar-tech/resume-timer-audit/releases/download/v0.1.0/resume-timer-audit.pyz
python3 resume-timer-audit.pyz --version
```

Verify the download against `SHA256SUMS.txt` in the same release before
running it.

## Usage

```bash
resume-timer-audit                    # plain-English report
resume-timer-audit --json             # machine-readable report
resume-timer-audit --lookback-days 30 # scan a longer journalctl history
```

Exit codes: `0` = no findings above info level, `1` = warning(s) only
(e.g. missing `RandomizedDelaySec=`), `2` = a resume-clustering signature
was actually detected.

Example:

```
$ resume-timer-audit
resume-timer-audit: 3 resume event(s), 12 timer(s) inspected

[info] Found 3 resume event(s) in the lookback window.
[info] Inspected 12 timer(s), 5 with Persistent=true.
[warn] 2 persistent timer(s) have no RandomizedDelaySec=, making resume-time
       clustering worse if it occurs: fstrim.timer, logrotate.timer
[FAIL] Thundering-herd signature: 2 persistent timers (fstrim.timer,
       logrotate.timer) fired within 90s of resume at 2026-09-08T08:12:03
       (systemd upstream issue #43350).
```

## If it finds a problem

This tool only diagnoses; it does not modify anything. If it flags a
cluster, the practical mitigations today (until systemd#43350 lands
upstream) are:
- Add `RandomizedDelaySec=` to the affected timer units yourself.
- Stagger `OnCalendar=` times for timers that don't strictly need to run
  at the same wall-clock time.

## Uninstall

```bash
pip uninstall resume-timer-audit
```
(Or simply delete the downloaded `.pyz` file — it writes no state files,
config, or logs of its own anywhere on disk.)

## Privacy / permissions

- No network access, no telemetry, no data leaves your machine.
- No root required for normal read access to `journalctl --user`-visible
  logs and `systemctl show`; system-wide journal access may require being
  in the `systemd-journal` group or running with elevated privileges,
  same as any other `journalctl` use.
- Writes nothing to disk. Reads only journal and systemd unit metadata.

## Linux distro / architecture limits

Requires systemd (the vast majority of current distros). Tested via real
`ubuntu-latest` GitHub Actions runners (Python 3.9 and 3.12). Should work
on any systemd-based distro with `journalctl`/`systemctl` on PATH;
architecture-independent (pure Python, no compiled dependencies).

## Reproducible build / test

```bash
git clone https://github.com/zhuhroscar-tech/resume-timer-audit
cd resume-timer-audit
python3 -m pip install -e .[dev]
python3 -m pytest -v
```

CI (`.github/workflows/ci.yml`) runs the same suite on real Ubuntu
runners across Python 3.9 and 3.12, then builds and smoke-tests both the
wheel/sdist and a standalone `.pyz`.

## License

MIT — see [LICENSE](LICENSE).
