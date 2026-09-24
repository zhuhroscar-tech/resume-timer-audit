# Changelog

All notable changes to `resume-timer-audit` are listed here. Dates use UTC publication dates.

## v0.1.9 — 2026-09-24

- Add this changelog and link it from both READMEs.
- Add repository-contract tests for required files, release-history documentation, CI, CodeQL, and release artifact coverage.

## v0.1.8 — 2026-09-24

- Modernized packaging license metadata to use a SPDX license string and explicit license-file inclusion.
- Added regression coverage to keep future package builds free of setuptools license deprecation warnings.

## v0.1.7 — 2026-09-20

- Fixed a silent false all-clear bug when `systemctl show` failed for an individual timer unit.
- Per-unit metadata failures now mark the audit as unverified instead of fabricating missing/persistent timer state.

## v0.1.6 — 2026-09-19

- Fixed year-boundary parsing for journal timestamps that omit the year.
- Resume events parsed in early January can now correctly roll back to late December of the previous year when appropriate.

## v0.1.5 — 2026-09-13

- Improved release packaging and standalone `.pyz` distribution coverage.

## v0.1.4 — 2026-09-13

- Strengthened CLI/test coverage for read-only systemd timer auditing behavior.

## v0.1.3 — 2026-09-12

- Report unreadable journal access as an unverified warning instead of a false all-clear.

## v0.1.2 — 2026-09-12

- Report `systemctl list-timers` failures honestly instead of treating missing timer data as a clean result.

## v0.1.1 — 2026-09-11

- Initial packaging and documentation maintenance release.

## v0.1.0 — 2026-09-10

- Initial public release of the read-only resume timer clustering diagnostic.
