from __future__ import annotations

import pandas as pd

import data_quality_toolkit.domain.profiling.profiling_orchestrator as orch
from data_quality_toolkit.domain.profiling.core.dataset_profiler import (
    dataset_stats,
    profile_dataset,
)
from data_quality_toolkit.shared.models import ColumnProfile


def test_dataset_stats_alias_matches_profile_dataset():
    df = pd.DataFrame({"a": [1, 2, 3]})
    assert dataset_stats(df) == profile_dataset(df)  # covers alias line


def test_run_profiling_uses_sampling_when_large_df(monkeypatch):
    # Make sample_size small so branch triggers
    monkeypatch.setenv("SAMPLE_SIZE", "2")
    df = pd.DataFrame({"x": list(range(10))})

    used_sample: dict[str, object] = {"flag": False, "size": None}

    def fake_profile_columns(
        df_in: pd.DataFrame, sample: pd.DataFrame | None
    ) -> list[ColumnProfile]:
        used_sample["flag"] = sample is not None
        used_sample["size"] = None if sample is None else len(sample)
        return []  # keep it fast

    # Patch just the column profiler to observe the sample usage
    monkeypatch.setattr(orch, "profile_columns", fake_profile_columns)

    pr = orch.run_profiling(df, dataset_id="sha1:test")
    assert pr["rows"] == 10 and pr["cols"] == 1
    # prove sampling branch executed
    assert used_sample["flag"] is True and used_sample["size"] == 2
