"""Tests for shared/config.py — minimal dqt.yaml loader."""

from __future__ import annotations

import pytest

from data_quality_toolkit.shared.config import (
    CONFIG_FILENAME,
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
# Valid config (v1.9 flat)
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


# ---------------------------------------------------------------------------
# Valid config (v2.0 nested)
# ---------------------------------------------------------------------------


def test_valid_dataset_section(tmp_path):
    p = _write(tmp_path, "dataset:\n  fail_under: 0.9\n  score_field: quality_score\n")
    result = load_dqt_config(p)
    assert result["dataset"] == {"fail_under": 0.9, "score_field": "quality_score"}


def test_valid_columns_section(tmp_path):
    content = """
columns:
  id:
    required: true
    critical: true
    null_threshold: 0.0
    unique: true
    weight: 2.0
  price:
    dtype: float
    outlier_threshold: 0.05
    weight: 1.5
  category:
    accepted_values: ["A", "B"]
    high_cardinality_threshold: 0.8
"""
    p = _write(tmp_path, content)
    result = load_dqt_config(p)
    cols = result["columns"]
    assert cols["id"] == {
        "required": True,
        "critical": True,
        "null_threshold": 0.0,
        "unique": True,
        "weight": 2.0,
    }
    assert cols["price"] == {"dtype": "float", "outlier_threshold": 0.05, "weight": 1.5}
    assert cols["category"] == {"accepted_values": ["A", "B"], "high_cardinality_threshold": 0.8}


# ---------------------------------------------------------------------------
# Validation: Numeric Ranges
# ---------------------------------------------------------------------------


def test_threshold_out_of_range_raises(tmp_path):
    p = _write(tmp_path, "null_threshold: 1.1\n")
    with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
        load_dqt_config(p)


def test_dataset_fail_under_out_of_range_raises(tmp_path):
    p = _write(tmp_path, "dataset:\n  fail_under: -0.1\n")
    with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
        load_dqt_config(p)


def test_weight_zero_or_negative_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  id:\n    weight: 0\n")
    with pytest.raises(ConfigError, match="must be greater than 0"):
        load_dqt_config(p)


# ---------------------------------------------------------------------------
# Validation: Types
# ---------------------------------------------------------------------------


def test_invalid_bool_type_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  id:\n    required: yes_please\n")
    with pytest.raises(ConfigError, match="must be a boolean"):
        load_dqt_config(p)


def test_invalid_list_type_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  id:\n    accepted_values: A\n")
    with pytest.raises(ConfigError, match="must be a list"):
        load_dqt_config(p)


def test_invalid_string_type_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  id:\n    dtype: 123\n")
    with pytest.raises(ConfigError, match="must be a string"):
        load_dqt_config(p)


# ---------------------------------------------------------------------------
# Unknown Keys
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_raises(tmp_path):
    p = _write(tmp_path, "unknown_top: 1\n")
    with pytest.raises(ConfigError, match="unknown_top"):
        load_dqt_config(p)


def test_unknown_dataset_key_raises(tmp_path):
    p = _write(tmp_path, "dataset:\n  unknown_sub: 1\n")
    with pytest.raises(ConfigError, match="unknown_sub"):
        load_dqt_config(p)


def test_unknown_column_rule_key_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  id:\n    unknown_rule: 1\n")
    with pytest.raises(ConfigError, match="unknown_rule"):
        load_dqt_config(p)


# ---------------------------------------------------------------------------
# Malformed / Non-mapping
# ---------------------------------------------------------------------------


def test_malformed_yaml_raises_config_error(tmp_path):
    p = _write(tmp_path, "key: [\n")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_dqt_config(p)


def test_list_root_raises_config_error(tmp_path):
    p = _write(tmp_path, "- item1\n- item2\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_dqt_config(p)


def test_column_rules_not_mapping_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  id: not_a_mapping\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_dqt_config(p)


# ---------------------------------------------------------------------------
# Column-level fail_under
# ---------------------------------------------------------------------------


def test_column_fail_under_parsed_as_float(tmp_path):
    p = _write(tmp_path, "columns:\n  revenue:\n    fail_under: 0.95\n")
    result = load_dqt_config(p)
    assert result["columns"]["revenue"]["fail_under"] == pytest.approx(0.95)
    assert isinstance(result["columns"]["revenue"]["fail_under"], float)


def test_column_fail_under_zero_accepted(tmp_path):
    p = _write(tmp_path, "columns:\n  col:\n    fail_under: 0.0\n")
    result = load_dqt_config(p)
    assert result["columns"]["col"]["fail_under"] == pytest.approx(0.0)


def test_column_fail_under_one_accepted(tmp_path):
    p = _write(tmp_path, "columns:\n  col:\n    fail_under: 1.0\n")
    result = load_dqt_config(p)
    assert result["columns"]["col"]["fail_under"] == pytest.approx(1.0)


def test_column_fail_under_out_of_range_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  col:\n    fail_under: 1.1\n")
    with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
        load_dqt_config(p)


def test_column_fail_under_negative_raises(tmp_path):
    p = _write(tmp_path, "columns:\n  col:\n    fail_under: -0.1\n")
    with pytest.raises(ConfigError, match="must be between 0.0 and 1.0"):
        load_dqt_config(p)
