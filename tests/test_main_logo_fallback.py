"""Tests for handling missing Streamlit logo assets in ``main``."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(Path(__file__).resolve().parents[1]))


def test_main_imports_with_fallback_icon(monkeypatch):
    """``main`` should import without errors when the logo asset is missing."""

    logo_path = Path("assets/logo.png")
    if not logo_path.exists():
        pytest.skip("Logo asset not present; fallback behaviour is already in effect.")

    backup_path = logo_path.with_name(logo_path.name + ".pytest-backup")
    if backup_path.exists():
        backup_path.unlink()
    logo_path.rename(backup_path)

    import streamlit as st

    captured_icon = {}

    def fake_set_page_config(*args, **kwargs):
        captured_icon["icon"] = kwargs.get("page_icon")

    monkeypatch.setattr(st, "set_page_config", fake_set_page_config)

    try:
        sys.modules.pop("main", None)
        main = importlib.import_module("main")
        assert main.PAGE_ICON == main.FALLBACK_PAGE_ICON
        assert captured_icon.get("icon") == main.FALLBACK_PAGE_ICON
    finally:
        sys.modules.pop("main", None)
        backup_path.rename(logo_path)
