import types

from data_quality_toolkit.assessment import issue_detector as mod


def test_detect_issues_stub_returns_empty_list_and_is_pure():
    profile_in = {"rows": 10}
    before = profile_in.copy()
    out = mod.detect_issues(profile_in)
    assert out == []
    # sanity: function shouldn't mutate the input
    assert profile_in == before
    # and module has the expected interface
    assert isinstance(mod, types.ModuleType)
