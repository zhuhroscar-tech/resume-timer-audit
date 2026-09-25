"""Repository-level contract checks for release quality.

These tests guard documentation and workflow promises that are easy to drift
when a small diagnostic repo gets maintenance releases.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _project_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.MULTILINE)
    assert match, "pyproject.toml must declare [project].version"
    return match.group(1)


def test_required_project_files_are_present():
    required_paths = [
        "LICENSE",
        "README.md",
        "README.zh-CN.md",
        "CHANGELOG.md",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
    ]

    for relative_path in required_paths:
        path = _REPO_ROOT / relative_path
        assert path.is_file(), f"Missing required repository file: {relative_path}"
        assert path.read_text(encoding="utf-8").strip(), f"Required file is empty: {relative_path}"


def test_readmes_link_release_history_license_and_downloads():
    for relative_path in ("README.md", "README.zh-CN.md"):
        text = _read(relative_path)
        assert "CHANGELOG.md" in text
        assert "LICENSE" in text
        assert "https://github.com/zhuhroscar-tech/resume-timer-audit/releases" in text
        assert "SHA256SUMS.txt" in text


def test_changelog_tracks_current_version_and_prior_bugfixes():
    changelog = _read("CHANGELOG.md")
    version = _project_version()

    assert f"## v{version}" in changelog
    for prior_version in ("v0.1.8", "v0.1.7", "v0.1.6", "v0.1.3", "v0.1.2", "v0.1.0"):
        assert f"## {prior_version}" in changelog
    assert "systemctl show" in changelog
    assert "year-boundary" in changelog
    assert "unreadable journal" in changelog


def test_ci_workflow_covers_tests_build_pyz_and_release_assets():
    ci = _read(".github/workflows/ci.yml")

    assert "branches: [main]" in ci
    assert 'tags: ["v*"]' in ci
    assert "python -m pytest" in ci
    assert "python -m build" in ci
    assert "python -m zipapp" in ci
    assert "resume-timer-audit.pyz" in ci
    assert "SHA256SUMS.txt" in ci
    assert "actions/upload-artifact@v4" in ci


def test_package_metadata_links_to_project_resources():
    pyproject = _read("pyproject.toml")

    assert '[project.urls]' in pyproject
    assert 'Homepage = "https://github.com/zhuhroscar-tech/resume-timer-audit"' in pyproject
    assert 'Issues = "https://github.com/zhuhroscar-tech/resume-timer-audit/issues"' in pyproject
    assert 'Changelog = "https://github.com/zhuhroscar-tech/resume-timer-audit/blob/main/CHANGELOG.md"' in pyproject


def test_codeql_workflow_scans_python():
    codeql = _read(".github/workflows/codeql.yml")

    assert "github/codeql-action/init@v3" in codeql
    assert "github/codeql-action/analyze@v3" in codeql
    assert "languages: python" in codeql
