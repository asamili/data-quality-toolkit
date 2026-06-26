"""Tests for the rebuilt Settings / Governance page (truthful, redacted)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.ui.pages.settings_diagnostics import (
    _render_settings_governance,
)


class FakeSt:
    """Minimal Streamlit recorder for the settings page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.clicked: set[str] = set()

    def _rec(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))

    def __getattr__(self, name: str) -> Any:
        def recorder(*a: Any, **k: Any) -> None:
            self._rec(name, *a, **k)

        return recorder

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self.text_values.get(label, str(k.get("value", "")))

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return label in self.clicked

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        parts: list[str] = []
        for _name, args, _kwargs in self.calls:
            for arg in args:
                parts.append(str(arg))
        return " ".join(parts)


def test_render_shows_real_sections_no_placeholders() -> None:
    st = FakeSt()
    _render_settings_governance(st)
    assert st.called("header")
    assert st.called("table")
    assert st.called("json")
    text = st.texts()
    # The placeholder values from the old stub must be gone.
    assert "0.1.0" not in text
    assert "some_setting" not in text
    assert "api_key" not in text


def test_render_does_not_leak_ai_env_tokens() -> None:
    st = FakeSt()
    _render_settings_governance(st)
    text = st.texts()
    assert "DQT_STORYLENS_AI_ENABLED" not in text
    assert "DQT_STORYLENS_MODEL_DIR" not in text


def test_probe_not_run_without_button_click() -> None:
    st = FakeSt()
    _render_settings_governance(st)
    # The probe button exists but, unclicked, no success/error is produced.
    assert st.called("button")
    assert not st.called("success")
    assert not st.called("error")


def test_probe_success_on_writable_dir(tmp_path: Path) -> None:
    st = FakeSt()
    st.text_values["Directory to probe"] = str(tmp_path)
    st.clicked.add("Run writable-directory probe")
    _render_settings_governance(st)
    assert st.called("success")
    assert not st.called("error")


def test_probe_error_on_missing_dir() -> None:
    st = FakeSt()
    st.text_values["Directory to probe"] = "definitely_not_a_real_dir_xyz"
    st.clicked.add("Run writable-directory probe")
    _render_settings_governance(st)
    assert st.called("error")
