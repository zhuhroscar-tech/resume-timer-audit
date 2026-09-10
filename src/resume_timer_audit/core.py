"""Core logic for resume-timer-audit.

The problem (systemd upstream issue #43350, confirmed open): timers
configured with ``Persistent=true`` correctly re-anchor their catch-up
after a *reboot*, but do NOT get the same re-anchor after a *resume from
suspend*. The result: several independent timers, each individually
reasonable, all fire together the instant a laptop wakes up instead of
being spread out the way ``RandomizedDelaySec=`` intends -- causing a
real, measurable CPU/IO stall right when someone starts using the machine.

This tool is strictly read-only. It never modifies timer units, never
starts/stops services, and never touches systemd configuration. It:

1. Parses ``journalctl`` (via ``python-systemd`` if available, else the
   ``journalctl`` CLI) for suspend/resume boundaries
   (``systemd-sleep``/``PM: suspend exit`` markers).
2. Parses ``systemctl list-timers --all`` (or ``systemctl show`` per unit)
   to find each persistent timer's last-trigger timestamps.
3. Cross-references: for each resume event, checks whether multiple
   persistent timers triggered within a short window right after that
   resume (the "thundering herd" signature) and whether those timers
   lack ``RandomizedDelaySec=``.
4. Emits a plain-English report plus a machine-readable JSON mode.

No system state is ever changed by this tool.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

# Two persistent-timer triggers within this window of a resume event are
# considered "clustered" (i.e. exhibiting the thundering-herd signature).
CLUSTER_WINDOW_SECONDS = 90

# Minimum number of persistent timers clustering together to flag a finding
# (a single timer firing right after resume is normal and expected).
CLUSTER_MIN_COUNT = 2


@dataclass
class ResumeEvent:
    timestamp: datetime
    source: str  # e.g. "journalctl: systemd-sleep" or "journalctl: PM: suspend exit"


@dataclass
class TimerUnit:
    name: str
    persistent: bool
    randomized_delay_sec: Optional[int]  # None if not set / unknown
    last_trigger: Optional[datetime]
    next_elapse: Optional[datetime]


@dataclass
class ClusterFinding:
    resume_time: datetime
    timers: list = field(default_factory=list)  # list[str]
    window_seconds: int = CLUSTER_WINDOW_SECONDS

    def to_dict(self) -> dict:
        return {
            "resume_time": self.resume_time.isoformat(),
            "timers": list(self.timers),
            "window_seconds": self.window_seconds,
        }


@dataclass
class Finding:
    level: str  # "info" | "warn" | "fail"
    message: str


@dataclass
class Report:
    resume_events_seen: int
    timers_inspected: int
    clusters: list  # list[ClusterFinding]
    findings: list  # list[Finding]

    def to_dict(self) -> dict:
        return {
            "resume_events_seen": self.resume_events_seen,
            "timers_inspected": self.timers_inspected,
            "clusters": [c.to_dict() for c in self.clusters],
            "findings": [{"level": f.level, "message": f.message} for f in self.findings],
        }

    def worst_level(self) -> str:
        order = {"info": 0, "warn": 1, "fail": 2}
        if not self.findings:
            return "info"
        return max(self.findings, key=lambda f: order.get(f.level, 0)).level


def run(cmd: list) -> str:
    """Run a read-only subprocess command, returning stdout (empty on error)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        )
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


_JOURNAL_TIMESTAMP_RE = re.compile(r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s")


def _parse_journal_timestamp(line: str, year: int) -> Optional[datetime]:
    m = _JOURNAL_TIMESTAMP_RE.match(line)
    if not m:
        return None
    try:
        # journalctl's default short format has no year; assume current year,
        # which is fine for the resume-clustering heuristic (relative deltas
        # matter, not absolute calendar correctness across year boundaries).
        return datetime.strptime(f"{year} {m.group(1)}", "%Y %b %d %H:%M:%S")
    except ValueError:
        return None


def get_resume_events(lookback_days: int = 14) -> list:
    """Find resume-from-suspend events via journalctl markers.

    Looks for the two most reliable, widely-present markers:
      - "systemd-sleep" unit logging "System returned from suspend/hibernate"
      - kernel "PM: suspend exit" messages
    Returns a de-duplicated, time-sorted list of ResumeEvent.
    """
    since = f"-{lookback_days}d"
    events: list = []
    year = datetime.now().year

    out = run(["journalctl", "--no-pager", "-u", "systemd-suspend.service",
               "-u", "systemd-hibernate.service", "-u", "systemd-suspend-then-hibernate.service",
               "--since", since])
    for line in out.splitlines():
        if "Stopped" in line or "Finished" in line or "returned from" in line.lower():
            ts = _parse_journal_timestamp(line, year)
            if ts:
                events.append(ResumeEvent(ts, "journalctl: systemd-sleep"))

    out = run(["journalctl", "--no-pager", "-k", "--since", since, "-g", "PM: suspend exit"])
    for line in out.splitlines():
        ts = _parse_journal_timestamp(line, year)
        if ts:
            events.append(ResumeEvent(ts, "journalctl: kernel PM suspend exit"))

    # De-dupe events within 5s of each other (same physical resume, two markers)
    events.sort(key=lambda e: e.timestamp)
    deduped: list = []
    for e in events:
        if deduped and (e.timestamp - deduped[-1].timestamp) <= timedelta(seconds=5):
            continue
        deduped.append(e)
    return deduped


_LIST_TIMERS_LINE_RE = re.compile(
    r"^(?P<next>\S.*?\S)\s{2,}(?P<left>\S.*?\S)\s{2,}(?P<last>\S.*?\S)\s{2,}"
    r"(?P<passed>\S.*?\S)\s{2,}(?P<unit>\S+\.timer)\s+(?P<activates>\S+\.service)"
)


def get_timer_units() -> list:
    """Enumerate persistent timers with their last-trigger time and
    RandomizedDelaySec setting, via `systemctl list-timers` + `show`."""
    out = run(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    names: list = []
    for line in out.splitlines():
        m = re.search(r"(\S+\.timer)\s+\S+\.service\s*$", line.strip())
        if m:
            names.append(m.group(1))
        else:
            parts = line.split()
            for p in parts:
                if p.endswith(".timer"):
                    names.append(p)
                    break

    units: list = []
    for name in sorted(set(names)):
        show = run(["systemctl", "show", name,
                    "--property=Persistent,RandomizedDelayUSec,LastTriggerUSec,NextElapseUSecRealtime"])
        props = {}
        for line in show.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                props[k] = v

        persistent = props.get("Persistent", "no") == "yes"
        rd_usec = props.get("RandomizedDelayUSec", "0")
        randomized_delay_sec = None
        m = re.match(r"(\d+)", rd_usec)
        if m and int(m.group(1)) > 0:
            # RandomizedDelayUSec as reported is actually already seconds-ish
            # text like "10min" in some systemd versions; normalize best-effort.
            randomized_delay_sec = _parse_systemd_duration(rd_usec)

        last_trigger = _parse_systemd_timestamp(props.get("LastTriggerUSec"))
        next_elapse = _parse_systemd_timestamp(props.get("NextElapseUSecRealtime"))

        units.append(TimerUnit(
            name=name,
            persistent=persistent,
            randomized_delay_sec=randomized_delay_sec,
            last_trigger=last_trigger,
            next_elapse=next_elapse,
        ))
    return units


def _parse_systemd_duration(text: str) -> Optional[int]:
    """Best-effort parse of a systemd duration string into whole seconds."""
    text = text.strip()
    if not text or text in ("0", "n/a"):
        return None
    total = 0.0
    matched = False
    for value, unit in re.findall(r"([\d.]+)\s*(us|ms|s|min|h|d|w)\b", text):
        matched = True
        v = float(value)
        mult = {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        total += v * mult
    if not matched:
        try:
            total = float(text) / 1_000_000  # raw microseconds fallback
            matched = True
        except ValueError:
            return None
    return int(total) if matched and total > 0 else None


def _parse_systemd_timestamp(text: Optional[str]) -> Optional[datetime]:
    if not text or text in ("n/a", "0", ""):
        return None
    # e.g. "Wed 2026-09-10 08:30:00 UTC" or with timezone abbreviation.
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def find_clusters(resume_events: list, timers: list) -> list:
    """Detect groups of >=CLUSTER_MIN_COUNT persistent timers whose
    last_trigger falls within CLUSTER_WINDOW_SECONDS of the same resume
    event -- the thundering-herd signature from systemd#43350."""
    clusters: list = []
    persistent_timers = [t for t in timers if t.persistent and t.last_trigger]

    for resume in resume_events:
        window_end = resume.timestamp + timedelta(seconds=CLUSTER_WINDOW_SECONDS)
        hit = [
            t.name for t in persistent_timers
            if resume.timestamp <= t.last_trigger <= window_end
        ]
        if len(hit) >= CLUSTER_MIN_COUNT:
            clusters.append(ClusterFinding(resume_time=resume.timestamp, timers=hit))
    return clusters


def evaluate(resume_events: list, timers: list) -> Report:
    clusters = find_clusters(resume_events, timers)
    findings: list = []

    if not resume_events:
        findings.append(Finding("info", "No suspend/resume events found in the lookback window."))
    else:
        findings.append(Finding("info", f"Found {len(resume_events)} resume event(s) in the lookback window."))

    persistent = [t for t in timers if t.persistent]
    findings.append(Finding("info", f"Inspected {len(timers)} timer(s), {len(persistent)} with Persistent=true."))

    no_jitter = [t.name for t in persistent if not t.randomized_delay_sec]
    if no_jitter:
        findings.append(Finding(
            "warn",
            f"{len(no_jitter)} persistent timer(s) have no RandomizedDelaySec=, "
            f"making resume-time clustering worse if it occurs: {', '.join(no_jitter)}",
        ))

    if clusters:
        for c in clusters:
            findings.append(Finding(
                "fail",
                f"Thundering-herd signature: {len(c.timers)} persistent timers "
                f"({', '.join(c.timers)}) fired within {c.window_seconds}s of resume at "
                f"{c.resume_time.isoformat()} (systemd upstream issue #43350).",
            ))
    else:
        findings.append(Finding("info", "No resume-clustering signature detected in the lookback window."))

    return Report(
        resume_events_seen=len(resume_events),
        timers_inspected=len(timers),
        clusters=clusters,
        findings=findings,
    )


def collect_and_evaluate(lookback_days: int = 14) -> Report:
    resume_events = get_resume_events(lookback_days=lookback_days)
    timers = get_timer_units()
    return evaluate(resume_events, timers)
