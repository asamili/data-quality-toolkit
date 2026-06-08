import pandas as pd
import pytest

from data_quality_toolkit.adapters.loaders.file.csv_loader import CsvLoader


@pytest.fixture
def sample_csv(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    p = d / "test.csv"
    df = pd.DataFrame({"a": range(100), "b": range(100)})
    df.to_csv(p, index=False)
    return p


def test_load_chunks_yields_expected_chunks(sample_csv):
    loader = CsvLoader()
    chunks = list(loader.load_chunks(str(sample_csv), chunksize=20))
    assert len(chunks) == 5
    assert all(len(c) == 20 for c in chunks)
    total_rows = sum(len(c) for c in chunks)
    assert total_rows == 100


def test_load_chunks_validation():
    loader = CsvLoader()
    with pytest.raises(ValueError, match="chunksize must be a positive integer"):
        list(loader.load_chunks("dummy.csv", chunksize=0))
    with pytest.raises(ValueError, match="chunksize must be a positive integer"):
        list(loader.load_chunks("dummy.csv", chunksize=-1))


def test_load_compatible_with_load_chunks(sample_csv):
    loader = CsvLoader()
    df, meta = loader.load(str(sample_csv))
    assert len(df) == 100
    assert meta["rows"] == 100


def test_load_chunks_function_interface():
    # Verify top-level function load_chunks can be implemented
    # Note: load_chunks isn't exported as a top-level function yet, just CsvLoader
    pass
