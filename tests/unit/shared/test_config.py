"""Tests for shared/config.py — minimal dqt.yaml loader."""

from __future__ import annotations

import pytest

from data_quality_toolkit.shared.config import (
    CONFIG_FILENAME,
    SUPPORTED_KEYS,
    load_dqt_config,
)
from data_quality_toolkit.shared.exceptions import ConfigError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path, content: str):
    p = tmp_path / CONFIG_FILENAME
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Absent / empty
# ---------------------------------------------------------------------------


def test_absent_file_returns_empty(tmp_path):
    result = load_dqt_config(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_empty_file_returns_empty(tmp_path):
    p = _write(tmp_path, "")
    assert load_dqt_config(p) == {}


def test_null_only_file_returns_empty(tmp_path):
    p = _write(tmp_path, "null\n")
    assert load_dqt_config(p) == {}


# ---------------------------------------------------------------------------
# Valid config
# ---------------------------------------------------------------------------


def test_null_threshold_parsed_as_float(tmp_path):
    p = _write(tmp_path, "null_threshold: 0.3\n")
    result = load_dqt_config(p)
    assert result == {"null_threshold": 0.3}
    assert isinstance(result["null_threshold"], float)


def test_fail_under_parsed_as_float(tmp_path):
    p = _write(tmp_path, "fail_under: 0.75\n")
    result = load_dqt_config(p)
    assert result == {"fail_under": 0.75}


def test_outdir_parsed_as_str(tmp_path):
    p = _write(tmp_path, "outdir: ./output\n")
    result = load_dqt_config(p)
    assert result == {"outdir": "./output"}
    assert isinstance(result["outdir"], str)


def test_integer_numeric_coerced_to_float(tmp_path):
    p = _write(tmp_path, "null_threshold: 1\n")
    result = load_dqt_config(p)
    assert result["null_threshold"] == 1.0
    assert isinstance(result["null_threshold"], float)


def test_all_three_keys_together(tmp_path):
    p = _write(tmp_path, "null_threshold: 0.2\nfail_under: 0.8\noutdir: ./dist\n")
    result = load_dqt_config(p)
    assert result == {"null_threshold": 0.2, "fail_under": 0.8, "outdir": "./dist"}


def test_supported_keys_frozenset_contents():
    assert SUPPORTED_KEYS == frozenset({"null_threshold", "fail_under", "outdir"})


# ---------------------------------------------------------------------------
# Malformed YAML
# ---------------------------------------------------------------------------


def test_malformed_yaml_raises_config_error(tmp_path):
    p = _write(tmp_path, "key: [\n")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_dqt_config(p)


# ---------------------------------------------------------------------------
# Non-mapping content
# ---------------------------------------------------------------------------


def test_list_root_raises_config_error(tmp_path):
    p = _write(tmp_path, "- item1\n- item2\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_dqt_config(p)


def test_scalar_root_raises_config_error(tmp_path):
    p = _write(tmp_path, "just_a_string\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_dqt_config(p)


# ---------------------------------------------------------------------------
# Unknown keys (fail-loud)
# ---------------------------------------------------------------------------


def test_unknown_key_raises_config_error(tmp_path):
    p = _write(tmp_path, "unknown_option: 1\n")
    with pytest.raises(ConfigError, match="unknown_option"):
        load_dqt_config(p)


def test_unknown_key_message_names_supported_keys(tmp_path):
    p = _write(tmp_path, "bad_key: 1\n")
    with pytest.raises(ConfigError, match="Supported keys"):
        load_dqt_config(p)


def test_multiple_unknown_keys_all_named(tmp_path):
    p = _write(tmp_path, "aaa: 1\nbbb: 2\n")
    with pytest.raises(ConfigError, match="aaa") as exc_info:
        load_dqt_config(p)
    assert "bbb" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Wrong-typed values
# ---------------------------------------------------------------------------


def test_string_for_null_threshold_raises(tmp_path):
    p = _write(tmp_path, "null_threshold: high\n")
    with pytest.raises(ConfigError, match="null_threshold"):
        load_dqt_config(p)


def test_bool_for_null_threshold_raises(tmp_path):
    p = _write(tmp_path, "null_threshold: true\n")
    with pytest.raises(ConfigError, match="null_threshold"):
        load_dqt_config(p)


def test_bool_for_fail_under_raises(tmp_path):
    p = _write(tmp_path, "fail_under: false\n")
    with pytest.raises(ConfigError, match="fail_under"):
        load_dqt_config(p)


def test_int_for_outdir_raises(tmp_path):
    p = _write(tmp_path, "outdir: 42\n")
    with pytest.raises(ConfigError, match="outdir"):
        load_dqt_config(p)


def test_list_for_outdir_raises(tmp_path):
    p = _write(tmp_path, "outdir:\n  - a\n  - b\n")
    with pytest.raises(ConfigError, match="outdir"):
        load_dqt_config(p)
