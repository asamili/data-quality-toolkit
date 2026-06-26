"""Unit tests for StoryLens AI adapter settings reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.application.explanation.ai_adapter.settings import (
    compute_availability,
    read_ai_enabled,
    resolve_model_dir,
)


class TestReadAiEnabled:
    def test_default_off_when_env_unset(self) -> None:
        assert read_ai_enabled({}) is False

    def test_default_off_when_key_absent(self) -> None:
        assert read_ai_enabled({"UNRELATED": "1"}) is False

    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"])
    def test_truthy_values_enable_flag(self, val: str) -> None:
        assert read_ai_enabled({"DQT_STORYLENS_AI_ENABLED": val}) is True

    @pytest.mark.parametrize(
        "val",
        ["0", "false", "False", "FALSE", "no", "off", "", "garbage", "2", "enable"],
    )
    def test_falsy_values_keep_flag_off(self, val: str) -> None:
        assert read_ai_enabled({"DQT_STORYLENS_AI_ENABLED": val}) is False

    def test_whitespace_trimmed_before_comparison(self) -> None:
        assert read_ai_enabled({"DQT_STORYLENS_AI_ENABLED": "  1  "}) is True

    def test_env_not_mutated(self) -> None:
        env: dict[str, str] = {}
        read_ai_enabled(env)
        assert env == {}


class TestResolveModelDir:
    def test_none_when_key_absent(self) -> None:
        assert resolve_model_dir({}) is None

    def test_none_when_empty_string(self) -> None:
        assert resolve_model_dir({"DQT_STORYLENS_MODEL_DIR": ""}) is None

    def test_none_when_whitespace_only(self) -> None:
        assert resolve_model_dir({"DQT_STORYLENS_MODEL_DIR": "   "}) is None

    def test_none_when_path_does_not_exist(self) -> None:
        result = resolve_model_dir({"DQT_STORYLENS_MODEL_DIR": "/nonexistent/path/abc123"})
        assert result is None

    def test_returns_path_when_dir_exists(self, tmp_path: Path) -> None:
        result = resolve_model_dir({"DQT_STORYLENS_MODEL_DIR": str(tmp_path)})
        assert result == tmp_path

    def test_does_not_create_missing_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        resolve_model_dir({"DQT_STORYLENS_MODEL_DIR": str(missing)})
        assert not missing.exists()

    def test_env_not_mutated(self) -> None:
        env: dict[str, str] = {}
        resolve_model_dir(env)
        assert env == {}


class TestComputeAvailability:
    def test_disabled_by_default(self) -> None:
        av = compute_availability({})
        assert av.enabled is False

    def test_disabled_reason_is_set(self) -> None:
        av = compute_availability({})
        assert av.reason

    def test_disabled_model_dir_is_none(self) -> None:
        av = compute_availability({})
        assert av.model_dir is None

    def test_disabled_when_no_model_dir(self) -> None:
        av = compute_availability({"DQT_STORYLENS_AI_ENABLED": "1"})
        assert av.enabled is False

    def test_disabled_reason_no_model_dir(self) -> None:
        av = compute_availability({"DQT_STORYLENS_AI_ENABLED": "1"})
        assert av.reason

    def test_enabled_when_flag_and_dir_exist(self, tmp_path: Path) -> None:
        av = compute_availability(
            {"DQT_STORYLENS_AI_ENABLED": "1", "DQT_STORYLENS_MODEL_DIR": str(tmp_path)}
        )
        assert av.enabled is True
        assert av.model_dir == tmp_path

    def test_reason_does_not_contain_concrete_path(self) -> None:
        av = compute_availability({"DQT_STORYLENS_AI_ENABLED": "1"})
        assert "/nonexistent" not in av.reason
        assert "C:\\" not in av.reason

    def test_availability_is_frozen(self) -> None:
        av = compute_availability({})
        with pytest.raises((AttributeError, TypeError)):
            av.enabled = True  # type: ignore[misc]

    def test_enabled_reason_does_not_contain_model_dir_path(self, tmp_path: Path) -> None:
        av = compute_availability(
            {"DQT_STORYLENS_AI_ENABLED": "1", "DQT_STORYLENS_MODEL_DIR": str(tmp_path)}
        )
        assert av.enabled is True
        assert str(tmp_path) not in av.reason
