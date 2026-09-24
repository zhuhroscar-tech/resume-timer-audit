"""Regression coverage for packaging metadata drift.

Setuptools now warns on the old table-style ``project.license`` field and
on the legacy MIT Trove classifier when a SPDX license expression is present.
This keeps future releases on the modern metadata path so builds stay clean.
"""
from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _pyproject_text() -> str:
    return _PYPROJECT.read_text(encoding="utf-8")


def test_project_license_uses_spdx_string_not_deprecated_table():
    text = _pyproject_text()

    assert 'license = "MIT"' in text
    assert "license = {" not in text
    assert 'license-files = ["LICENSE"]' in text


def test_build_backend_is_new_enough_for_spdx_license_files():
    text = _pyproject_text()

    match = re.search(r'requires\s*=\s*\[(?P<requires>[^\]]+)\]', text)
    assert match, "build-system.requires is missing"
    assert '"setuptools>=77"' in match.group("requires")


def test_deprecated_license_classifier_is_absent():
    text = _pyproject_text()

    assert "License :: OSI Approved :: MIT License" not in text
