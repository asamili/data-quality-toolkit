from pathlib import Path

from data_quality_toolkit.shared.settings import load_settings


def test_load_settings_env_file_and_types(tmp_path, monkeypatch):
    # Override a couple of envs at runtime to prove precedence & typing
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "123")
    monkeypatch.setenv("DQT_ALLOW_NETWORK", "false")  # bool parsing
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "out"))
    s = load_settings()

    assert s.max_rows_in_memory == 123
    assert s.dqt_allow_network is False
    assert s.export_base_dir == (tmp_path / "out").resolve()
    # directories auto-created
    assert Path(s.export_base_dir).exists()


def test_defaults_and_literals():
    s = load_settings()
    assert s.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert s.log_format in {"json", "text"}
    assert s.log_format in {"json", "text"}
