"""Tests: API sample_size path does not mutate os.environ["SAMPLE_SIZE"]."""

from __future__ import annotations

import os

from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_csv(tmp_path, rows: int = 10) -> str:
    f = tmp_path / "data.csv"
    lines = ["id"] + [str(i) for i in range(rows)]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(f)


# ---------------------------------------------------------------------------
# No env mutation via load_csv explicit param
# ---------------------------------------------------------------------------


def test_explicit_sample_size_does_not_set_env(tmp_path, monkeypatch):
    """Passing sample_size explicitly must not write to os.environ["SAMPLE_SIZE"]."""
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=20)

    load_csv(csv_path, sample_size=5)

    assert os.environ.get("SAMPLE_SIZE") is None


def test_explicit_sample_size_limits_rows(tmp_path, monkeypatch):
    """Explicit sample_size is honoured even when SAMPLE_SIZE env is absent."""
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=20)

    df, meta = load_csv(csv_path, sample_size=5)

    assert len(df) == 5
    assert meta["sample_applied"] is True
    assert meta["sample_size"] == 5


def test_explicit_sample_size_beats_larger_env(tmp_path, monkeypatch):
    """Explicit sample_size=3 wins over SAMPLE_SIZE=1000 in env."""
    monkeypatch.setenv("SAMPLE_SIZE", "1000")
    csv_path = _make_csv(tmp_path, rows=20)

    df, meta = load_csv(csv_path, sample_size=3)

    assert len(df) == 3
    assert meta["sample_applied"] is True


def test_explicit_sample_size_beats_smaller_env(tmp_path, monkeypatch):
    """Explicit sample_size=10 wins over SAMPLE_SIZE=2 in env (loads more rows)."""
    monkeypatch.setenv("SAMPLE_SIZE", "2")
    csv_path = _make_csv(tmp_path, rows=20)

    df, meta = load_csv(csv_path, sample_size=10)

    assert len(df) == 10
    assert meta["sample_applied"] is True


def test_env_fallback_still_works_when_no_explicit(tmp_path, monkeypatch):
    """SAMPLE_SIZE env is still honoured when no explicit sample_size is provided."""
    monkeypatch.setenv("SAMPLE_SIZE", "3")
    csv_path = _make_csv(tmp_path, rows=20)

    df, meta = load_csv(csv_path)

    assert len(df) == 3
    assert meta["sample_applied"] is True


def test_no_env_no_explicit_loads_full_file(tmp_path, monkeypatch):
    """Without env and without explicit param, full file is loaded."""
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=10)

    df, meta = load_csv(csv_path)

    assert len(df) == 10
    assert meta["sample_applied"] is False


def test_explicit_zero_treated_as_no_sampling(tmp_path, monkeypatch):
    """sample_size=0 is treated as 'no limit' (same as None), not as empty sample."""
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=10)

    df, meta = load_csv(csv_path, sample_size=0)

    assert len(df) == 10
    assert meta["sample_applied"] is False


# ---------------------------------------------------------------------------
# Public API — no env mutation
# ---------------------------------------------------------------------------


def test_profile_csv_sample_size_does_not_set_env(tmp_path, monkeypatch):
    """profile_csv(sample_size=N) must not write SAMPLE_SIZE to os.environ."""
    from data_quality_toolkit.api import profile_csv

    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=20)

    profile_csv(csv_path, sample_size=5)

    assert os.environ.get("SAMPLE_SIZE") is None


def test_assess_csv_sample_size_does_not_set_env(tmp_path, monkeypatch):
    """assess_csv(sample_size=N) must not write SAMPLE_SIZE to os.environ."""
    from data_quality_toolkit.api import assess_csv

    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=20)

    assess_csv(csv_path, sample_size=5)

    assert os.environ.get("SAMPLE_SIZE") is None


def test_assess_csv_explicit_sample_limits_rows(tmp_path, monkeypatch):
    """assess_csv with explicit sample_size loads at most sample_size rows."""
    from data_quality_toolkit.api import assess_csv

    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    csv_path = _make_csv(tmp_path, rows=20)

    out = assess_csv(csv_path, sample_size=5)

    assert out["meta"]["rows"] == 5
