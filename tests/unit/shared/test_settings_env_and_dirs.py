import os

from data_quality_toolkit.shared.settings import load_settings


def test_load_settings_respects_env_and_creates_dirs(monkeypatch, tmp_path):
    # point export dirs to tmp and override sizing envs
    monkeypatch.setenv("SAMPLE_SIZE", "123")
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "456")
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "pbi_param"))

    s = load_settings()

    # env overrides applied
    assert s.sample_size == 123
    assert s.max_rows_in_memory == 456

    # paths are expanded + resolved and created on disk
    assert s.export_base_dir.exists() and s.export_base_dir.is_dir()
    assert s.pbi_base_folder_parameter.exists() and s.pbi_base_folder_parameter.is_dir()

    # sanity defaults still present
    assert s.log_format in {"json", "text"}
    # clean up env side effects for other tests
    for k in ("SAMPLE_SIZE", "MAX_ROWS_IN_MEMORY", "EXPORT_BASE_DIR", "PBI_BASE_FOLDER_PARAMETER"):
        os.environ.pop(k, None)
