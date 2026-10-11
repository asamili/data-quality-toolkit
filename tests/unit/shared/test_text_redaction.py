"""Tests for the shared path-redaction helper.

The absolute paths below (Windows ``C:\\Users\\...`` and POSIX ``/home/...``) are
used purely as *fixtures*: each test asserts the private directory/username is
stripped from the output, proving the redaction. No real private path is emitted.

Every secret-looking literal here is a synthetic ``DQT_TEST_*`` sentinel invented
for these tests. Nothing is read from the environment, and no real credential
appears in this file.

The ownership section at the bottom pins *ownership*: this module is the single
semantic authority for filesystem-path redaction, and the CLI/UI surfaces are
formatters over it rather than independent implementations.
"""

from __future__ import annotations

from data_quality_toolkit.shared.text_redaction import (
    PATH_REDACTED_DISPLAY,
    redact_message_paths,
    redact_path_to_basename,
    redact_paths,
)

# Synthetic sentinels. None of these is a real credential or a real path.
WIN_PRIVATE_PATH = r"C:\Users\SensitiveUser\private\data.csv"
POSIX_PRIVATE_PATH = "/home/sensitive-user/private/data.csv"
SENTINEL_API_KEY = "DQT_TEST_SECRET_ABC123XYZ"  # noqa: S105 - synthetic fixture
SENTINEL_TOKEN = "DQT_TEST_TOKEN_987654"  # noqa: S105 - synthetic fixture
SENTINEL_PASSWORD = "DQT_TEST_PASSWORD"  # noqa: S105 - synthetic fixture
SENTINEL_DB_SECRET = "DQT_TEST_DB_SECRET"  # noqa: S105 - synthetic fixture


def _cli(text: object) -> str:
    """Redact using the CLI wording (``<path:basename>`` / ``<path>``).

    The annotation on ``redacted`` is load-bearing for the pre-commit type check,
    which sees only the staged files: with the production package off its path
    the import degrades to ``Any`` and returning the call directly widens the
    declared ``-> str``. A ``cast`` cannot be used here -- repository-config mypy
    resolves the real ``-> str`` signature and rejects it as redundant under
    ``warn_redundant_casts`` -- so the value is bound to a typed local instead,
    which both contexts accept.
    """
    redacted: str = redact_paths(text, keep=lambda leaf: f"<path:{leaf}>", drop="<path>")
    return redacted


# --- redact_paths (CLI formatter) -----------------------------------------


def test_windows_absolute_path_to_marker() -> None:
    out = _cli(r"could not load C:\Users\example_user\private\customers.csv now")
    assert "<path:customers.csv>" in out
    assert "C:\\" not in out
    assert "example_user" not in out
    assert "private" not in out
    assert "Users" not in out


def test_quoted_windows_path_keeps_quotes_and_wording() -> None:
    out = _cli(r"file not found: 'C:\Users\example_user\private\customers.csv'")
    assert out == "file not found: '<path:customers.csv>'"


def test_posix_absolute_path_to_marker() -> None:
    out = _cli("file not found: '/home/user/data/customers.csv'")
    assert out == "file not found: '<path:customers.csv>'"
    assert "/home" not in out
    assert "user" not in out


def test_unc_path_to_marker() -> None:
    out = _cli(r"denied \\fileserver\share\reports\model.tmsl.json")
    assert "<path:model.tmsl.json>" in out
    assert "fileserver" not in out
    assert "share" not in out


def test_bare_windows_root_uses_generic_marker() -> None:
    assert _cli(r"root C:\ is not writable") == "root <path> is not writable"


def test_private_repo_root_is_redacted() -> None:
    # Synthetic stand-in for a developer's checkout root: an owner-named
    # directory under a drive letter. Both segments must disappear.
    out = _cli(r"permission denied: C:\example_owner\private_repo_root\dqt_metadata.db")
    assert "<path:dqt_metadata.db>" in out
    assert "example_owner" not in out
    assert "private_repo_root" not in out


def test_plain_message_without_path_is_unchanged() -> None:
    msg = "time data '2020-13-01' does not match format '%Y-%m-%d'"
    assert _cli(msg) == msg


def test_fraction_and_slash_words_are_not_mangled() -> None:
    assert _cli("ratio 0/1 exceeded") == "ratio 0/1 exceeded"
    assert _cli("read/write conflict and/or retry") == "read/write conflict and/or retry"


def test_url_is_not_corrupted() -> None:
    msg = "webhook failed for https://host.example/api/v1/notify (timeout)"
    assert _cli(msg) == msg


def test_falsy_input_returns_empty_string() -> None:
    assert _cli(None) == ""
    assert _cli("") == ""


def test_bare_basename_reference_survives() -> None:
    # A bare filename (no directory) is already safe; nothing to redact.
    assert _cli("could not open report.csv") == "could not open report.csv"


# --- redact_message_paths (UI format, parity) -----------------------------


def test_ui_format_reduces_to_bare_basename() -> None:
    out = redact_message_paths(r"file not found: 'C:\Users\example_user\private\customers.csv'")
    assert out == "file not found: 'customers.csv'"


def test_ui_format_bare_root_uses_path_redacted_marker() -> None:
    assert (
        redact_message_paths(r"root C:\ is not writable") == "root [path redacted] is not writable"
    )


def test_ui_format_falsy_returns_empty() -> None:
    assert redact_message_paths(None) == ""
    assert redact_message_paths("") == ""


# --- redact_path_to_basename (value form of the same leaf policy) ----------


def test_value_form_strips_windows_directories() -> None:
    out = redact_path_to_basename(WIN_PRIVATE_PATH)
    assert out == "data.csv"
    assert "SensitiveUser" not in out
    assert "private" not in out


def test_value_form_strips_posix_directories() -> None:
    out = redact_path_to_basename(POSIX_PRIVATE_PATH)
    assert out == "data.csv"
    assert "sensitive-user" not in out


def test_value_form_strips_unc_host_and_share() -> None:
    out = redact_path_to_basename(r"\\fileserver\share\reports\model.tmsl.json")
    assert out == "model.tmsl.json"
    assert "fileserver" not in out
    assert "share" not in out


def test_value_form_keeps_relative_and_bare_names() -> None:
    assert redact_path_to_basename("relative/path/report.json") == "report.json"
    assert redact_path_to_basename("plain.csv") == "plain.csv"


def test_value_form_tolerates_trailing_separator() -> None:
    """A directory written with a trailing separator still yields its leaf."""
    assert redact_path_to_basename("\\".join(WIN_PRIVATE_PATH.split("\\")[:-1]) + "\\") == "private"
    assert redact_path_to_basename("/home/sensitive-user/private/") == "private"


def test_value_form_safe_fallback_on_rootless_input() -> None:
    """No safe leaf -> empty string, never a partial host path."""
    assert redact_path_to_basename(None) == ""
    assert redact_path_to_basename("") == ""
    assert redact_path_to_basename("   ") == ""
    assert redact_path_to_basename("/") == ""
    # A bare drive is suppressed rather than shown as "C:".
    assert redact_path_to_basename("C:\\") == ""
    assert redact_path_to_basename("C:") == ""


def test_value_form_accepts_non_string_objects() -> None:
    from pathlib import PurePosixPath

    assert redact_path_to_basename(PurePosixPath(POSIX_PRIVATE_PATH)) == "data.csv"


def test_value_form_never_raises_on_hostile_object() -> None:
    """A broken ``__str__`` fails closed (empty), it does not surface a payload."""

    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    assert redact_path_to_basename(Hostile()) == ""


def test_value_form_is_idempotent() -> None:
    for value in (WIN_PRIVATE_PATH, POSIX_PRIVATE_PATH, "plain.csv", "C:\\", ""):
        once = redact_path_to_basename(value)
        assert redact_path_to_basename(once) == once


# --- synthetic adversarial matrix over the message form --------------------


def test_secret_bearing_path_segment_is_removed() -> None:
    """A sentinel hidden in a *directory* name goes with the directory."""
    msg = "load failed for C:\\Users\\SensitiveUser\\.config\\" + SENTINEL_API_KEY + "\\data.csv"
    out = redact_message_paths(msg)
    assert out == "load failed for data.csv"
    assert SENTINEL_API_KEY not in out
    assert "SensitiveUser" not in out


def test_secret_bearing_posix_path_segment_is_removed() -> None:
    out = redact_message_paths(f"/home/sensitive-user/{SENTINEL_API_KEY}/report.json")
    assert out == "report.json"
    assert SENTINEL_API_KEY not in out


def test_nested_exception_text_with_two_sentinels_is_scrubbed() -> None:
    msg = (
        "export failed: OSError(2, 'no such file: "
        f"/home/sensitive-user/{SENTINEL_API_KEY}/x.csv') while writing "
        "C:\\Users\\SensitiveUser\\" + SENTINEL_TOKEN + "\\y.json"
    )
    out = redact_message_paths(msg)
    assert out == "export failed: OSError(2, 'no such file: x.csv') while writing y.json"
    assert SENTINEL_API_KEY not in out
    assert SENTINEL_TOKEN not in out
    assert "sensitive-user" not in out
    assert "SensitiveUser" not in out


def test_message_form_is_idempotent() -> None:
    for msg in (
        "could not load C:\\Users\\SensitiveUser\\" + SENTINEL_API_KEY + "\\data.csv",
        f"missing {POSIX_PRIVATE_PATH}",
        "root C:\\ is not writable",
        "time data '2020-13-01' does not match format '%Y-%m-%d'",
    ):
        once = redact_message_paths(msg)
        assert redact_message_paths(once) == once


def test_message_form_scope_is_paths_not_free_text_secrets() -> None:
    """Documents the policy boundary this module owns.

    URL/query/userinfo secrets are *not* this module's job -- they are owned by
    ``adapters.notifications.webhook.redact_url``, which is asserted separately
    below. Pinning the boundary here stops a future edit from assuming this
    helper already covers them.
    """
    for msg in (
        f"auth failed: Bearer {SENTINEL_TOKEN}",
        f"conn: Server=test;Password={SENTINEL_DB_SECRET}",
        f"password={SENTINEL_PASSWORD}",
    ):
        assert redact_message_paths(msg) == msg


def test_url_secrets_have_exactly_one_owner() -> None:
    """The token/userinfo guarantee exists, and lives in a single helper."""
    from data_quality_toolkit.adapters.notifications.webhook import redact_url

    assert redact_url(f"https://host.example/hook?token={SENTINEL_TOKEN}") == (
        "https://host.example/hook"
    )
    assert redact_url(f"https://user:{SENTINEL_PASSWORD}@host.example/hook") == (
        "https://host.example/hook"
    )
    assert redact_url(f"https://host.example/hook#{SENTINEL_API_KEY}") == (
        "https://host.example/hook"
    )
    assert redact_url("not a url") == "<redacted-url>"


# --- single-owner regression net -------------------------------------------


def test_ui_services_reexport_the_shared_value_form() -> None:
    """Neither UI service may reimplement the basename rule."""
    from data_quality_toolkit.adapters.ui.services import artifacts, monitoring

    assert artifacts.redact_path_to_basename is redact_path_to_basename
    assert monitoring.redact_path_to_basename is redact_path_to_basename


def test_ui_error_component_reexports_the_shared_message_form() -> None:
    from data_quality_toolkit.adapters.ui.components import errors

    assert errors.redact_message_paths is redact_message_paths


def test_source_hub_reuses_the_shared_redaction_marker() -> None:
    """The display marker is defined once, not mirrored by hand."""
    from data_quality_toolkit.adapters.ui.components import source_hub

    assert source_hub.PATH_REDACTED_DISPLAY is PATH_REDACTED_DISPLAY


def test_cli_and_ui_share_the_protection_not_the_prose() -> None:
    """Surface parity: same guarantee, deliberately different wording."""
    import data_quality_toolkit.adapters.cli.main as cli

    msg = f"could not open {WIN_PRIVATE_PATH}"
    cli_out = cli._redact_cli_paths(msg)
    ui_out = redact_message_paths(msg)

    for out in (cli_out, ui_out):
        assert "SensitiveUser" not in out
        assert "private" not in out
        assert "C:" not in out
        assert "data.csv" in out
    # Wording differs by surface; the protection does not.
    assert cli_out != ui_out
    assert cli_out == "could not open <path:data.csv>"
    assert ui_out == "could not open data.csv"


# --- R7A3B2-R1: absolute paths containing whitespace -----------------------

WIN_SPACED_PATH = r"C:\Users\example user\private runtime\drift.db"
POSIX_SPACED_PATH = "/home/example user/private runtime/drift.db"
_SPACED_FRAGMENTS = ("example user", "private runtime", "Users", "C:\\", "/home")


def _assert_no_spaced_fragment(out: str) -> None:
    for fragment in _SPACED_FRAGMENTS:
        assert fragment not in out


def test_windows_spaced_directories_are_fully_redacted() -> None:
    out = _cli(f"Failed to write workbook to {WIN_SPACED_PATH} (disk error)")
    assert out == "Failed to write workbook to <path:drift.db> (disk error)"
    _assert_no_spaced_fragment(out)


def test_windows_spaced_filename_keeps_trailing_prose() -> None:
    out = _cli(
        r"Failed to write workbook to C:\Users\example user\out file.xlsx: permission denied"
    )
    assert out == "Failed to write workbook to <path:out file.xlsx>: permission denied"
    _assert_no_spaced_fragment(out)


def test_spaced_path_does_not_swallow_trailing_error_text() -> None:
    """A space-bearing path stops at its file extension, not at the sentence end."""
    out = _cli(r"Failed to open C:\Users\example user\drift db.sqlite after 3 retries")
    assert out == "Failed to open <path:drift db.sqlite> after 3 retries"
    _assert_no_spaced_fragment(out)


def test_spaced_trailing_component_without_extension_still_drops_directories() -> None:
    """No extension to anchor on: the match stops early, directories still go."""
    out = _cli(r"missing C:\Users\example user\my report here")
    assert out == "missing <path:my> report here"
    _assert_no_spaced_fragment(out)


def test_repr_escaped_windows_spaced_path_is_redacted() -> None:
    out = _cli("[Errno 13] Permission denied: 'C:\\\\Users\\\\example user\\\\drift.db'")
    assert out == "[Errno 13] Permission denied: '<path:drift.db>'"
    _assert_no_spaced_fragment(out)


def test_unc_path_with_spaces_is_redacted() -> None:
    out = _cli(r"denied \\fileserver\team share\monthly reports\model.tmsl.json")
    assert out == "denied <path:model.tmsl.json>"
    assert "fileserver" not in out
    assert "team share" not in out
    assert "monthly reports" not in out


def test_posix_spaced_directories_are_fully_redacted() -> None:
    out = _cli(f"missing {POSIX_SPACED_PATH} now")
    assert out == "missing <path:drift.db> now"
    _assert_no_spaced_fragment(out)


def test_posix_spaced_filename_keeps_trailing_prose() -> None:
    out = _cli("missing /home/example user/report file.csv: no such file")
    assert out == "missing <path:report file.csv>: no such file"
    _assert_no_spaced_fragment(out)


def test_ui_form_redacts_spaced_paths_with_its_own_wording() -> None:
    assert redact_message_paths(f"cannot read {WIN_SPACED_PATH}") == "cannot read drift.db"
    assert redact_message_paths(f"cannot read {POSIX_SPACED_PATH}") == "cannot read drift.db"


def test_trailing_colon_now_keeps_the_basename() -> None:
    """A colon closes the trailing component instead of being consumed with it."""
    out = _cli(r"could not open C:\example_owner\runtime\drift.db: [Errno 13] denied")
    assert out == "could not open <path:drift.db>: [Errno 13] denied"
    assert "example_owner" not in out


def test_colon_inside_a_directory_component_is_still_part_of_the_path() -> None:
    out = _cli("read failed for /data/run:2026-01-01/report.csv")
    assert out == "read failed for <path:report.csv>"
    assert "run:2026-01-01" not in out


def test_spaced_prose_and_colons_are_not_read_as_paths() -> None:
    for msg in (
        "Unknown chart 'pie'. Supported: drift-rate, psi-by-column, top-drifted, all.",
        "webhook returned HTTP 500 for https://hooks.example.com/x",
        "Output path must end with .xlsx, got: out.csv",
        "could not open report.csv",
        "time data '2020-13-01' does not match format '%Y-%m-%d'",
    ):
        assert _cli(msg) == msg
        assert redact_message_paths(msg) == msg


def test_already_redacted_spaced_output_is_stable() -> None:
    for msg in (
        f"cannot read {WIN_SPACED_PATH}",
        f"cannot read {POSIX_SPACED_PATH}",
        r"Failed to write workbook to C:\Users\example user\out file.xlsx: denied",
        "Output path is an existing directory: [path redacted]",
        "Output file already exists; pass --force to overwrite: <path:drift.db>",
    ):
        once = _cli(msg)
        assert _cli(once) == once
        ui_once = redact_message_paths(msg)
        assert redact_message_paths(ui_once) == ui_once
