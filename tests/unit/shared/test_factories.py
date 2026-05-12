# tests/unit/shared/test_factories.py
from tests.fixtures import factories


def test_make_profile_and_assessment():
    profile = factories.make_profile_result()
    assess = factories.make_assessment_result()

    assert "run_id" in profile
    assert "dataset_id" in assess
    assert assess["score"] <= 1.0
    assert isinstance(profile["columns"], list)
    assert isinstance(profile["columns"], list)
