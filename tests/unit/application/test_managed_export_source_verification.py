"""Managed-source identity verification at the application export boundary.

Proves the trust-boundary correction for the stale-content-identity defect and
the single-owner verification finding:

* the managed export use case re-verifies the *actual* source immediately
  before its bytes are consumed, so a manifest can never assert ``content_id``
  X over different bytes;
* the verification policy lives in the shared kernel, below ``adapters.ui``
  and below ``application``, and is the single owner used by both the UI
  managed frame loader and the application export boundary.

Every managed source built here is laid out inside a confined
``preprocessed/<name>`` tail so the confinement stage is exercised honestly
rather than bypassed.
"""

from __future__ import annotations

import ast
import inspect
import json
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from data_quality_toolkit.application.workflow import pipeline
from data_quality_toolkit.application.workflow.pipeline import (
    run_managed_export_star,
)
from data_quality_toolkit.shared import managed_export_source as shared_module
from data_quality_toolkit.shared.managed_export_source import (
    ManagedSourceVerificationError,
    VerifiedManagedExportSource,
    managed_content_id_from_file,
    verify_managed_export_source,
    verify_managed_source,
)

_CSV_BODY = "id,age\n1,30\n2,40\n"
_RELATIVE_POSIX = "preprocessed/customers.csv"


# --- Fixtures / builders ------------------------------------------------------


def _managed_csv(tmp_path: Path, body: str = _CSV_BODY) -> Path:
    """Write a managed CSV at a confined ``preprocessed/customers.csv`` tail."""
    directory = tmp_path / "preprocessed"
    directory.mkdir(parents=True, exist_ok=True)
    csv = directory / "customers.csv"
    csv.write_text(body, encoding="utf-8")
    return csv


def _source_for(csv: Path, **overrides: object) -> VerifiedManagedExportSource:
    """Mint provenance whose trusted identity matches ``csv`` as it is right now."""
    resolved = csv.resolve()
    st = resolved.stat()
    values: dict[str, object] = {
        "version_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "content_id": managed_content_id_from_file(resolved),
        "root_content_id": "sha256:" + "b" * 64,
        "parent_version_id": None,
        "version_label": "cleaned v2",
        "display_name": resolved.name,
        "relative_posix": _RELATIVE_POSIX,
        "size_bytes": int(st.st_size),
        "modified_ns": int(st.st_mtime_ns),
        "large_file_mode": False,
        "source_path": str(resolved),
    }
    values.update(overrides)
    return VerifiedManagedExportSource(**values)  # type: ignore[arg-type]


def _rewrite(csv: Path, body: str) -> None:
    """Replace the file's bytes in place, leaving the path identity untouched."""
    csv.write_text(body, encoding="utf-8")


def _export_dir_is_empty(output_dir: Path) -> bool:
    return not output_dir.exists() or not any(output_dir.rglob("*"))


# --- CASE A: mutation after provenance is minted ------------------------------


def test_managed_export_refuses_a_source_mutated_after_minting(tmp_path: Path) -> None:
    """The accepted defect: stale content_id stamped over changed bytes."""
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    trusted_content_id = source.content_id
    out = tmp_path / "out"

    _rewrite(csv, "id,age\n1,30\n2,40\n3,99\n4,101\n")

    with pytest.raises(ManagedSourceVerificationError) as excinfo:
        run_managed_export_star(source, output_dir=str(out))

    assert excinfo.value.reason_code == "CONTENT_MISMATCH"
    # No export bytes and no provenance manifest were produced at all.
    assert _export_dir_is_empty(out)
    # And the on-disk bytes really are no longer the trusted identity.
    assert managed_content_id_from_file(csv) != trusted_content_id


def test_managed_export_refuses_source_minted_through_the_gateway(tmp_path: Path) -> None:
    """Same defect, minted through the admitted UI gateway path end to end."""
    from data_quality_toolkit.adapters.ui.services.managed_export_gateway import (
        build_verified_managed_export_source,
    )
    from data_quality_toolkit.adapters.ui.services.managed_trust import (
        commit_trust_root,
        ensure_session_capability,
        make_source_locator,
    )

    csv = _managed_csv(tmp_path)
    resolved = csv.resolve()
    st = resolved.stat()
    state: dict[str, object] = {}
    capability = ensure_session_capability(state)
    commit_trust_root(
        state,
        capability,
        version_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id=managed_content_id_from_file(resolved),
        root_content_id="sha256:" + "b" * 64,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name=resolved.name,
            relative_posix=_RELATIVE_POSIX,
            absolute_path=str(resolved),
        ),
        size_bytes=int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
        large_file_mode=False,
    )
    source = build_verified_managed_export_source(state)
    out = tmp_path / "out"

    _rewrite(csv, "id,age\n7,71\n8,81\n9,91\n")

    with pytest.raises(ManagedSourceVerificationError):
        run_managed_export_star(source, output_dir=str(out))

    assert _export_dir_is_empty(out)


def test_managed_verification_never_falls_back_to_unmanaged_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verification failure is terminal: the unmanaged exporter is never reached."""
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    calls: list[object] = []

    def _spy(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append(args)
        return {"export_paths": {}}

    monkeypatch.setattr(pipeline, "run_export_star", _spy)
    _rewrite(csv, "id,age\n5,50\n6,60\n7,70\n")

    with pytest.raises(ManagedSourceVerificationError):
        run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    assert calls == []


# --- CASE B: same-size content mutation ---------------------------------------


def test_same_size_content_mutation_is_detected(tmp_path: Path) -> None:
    """Size-only (and size+stat-only) verification is provably insufficient.

    The trusted ``size_bytes`` and ``modified_ns`` are taken *after* the
    mutation, so both stat checks pass and only exact content identity can
    refuse the export. This is deterministic on every host: it depends on no
    timestamp preservation and no nanosecond granularity assumption.
    """
    csv = _managed_csv(tmp_path)
    original_content_id = managed_content_id_from_file(csv)
    mutated = _CSV_BODY.replace("30", "99")
    assert len(mutated) == len(_CSV_BODY)

    _rewrite(csv, mutated)
    st = csv.resolve().stat()
    source = _source_for(
        csv,
        content_id=original_content_id,
        size_bytes=int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
    )
    out = tmp_path / "out"

    with pytest.raises(ManagedSourceVerificationError) as excinfo:
        run_managed_export_star(source, output_dir=str(out))

    assert excinfo.value.reason_code == "CONTENT_MISMATCH"
    assert _export_dir_is_empty(out)


# --- CASE C: replacement / confinement ----------------------------------------


def test_source_outside_its_trusted_relative_tail_is_refused(tmp_path: Path) -> None:
    """A source refiled outside its managed tail is refused as unconfined."""
    directory = tmp_path / "elsewhere"
    directory.mkdir()
    csv = directory / "customers.csv"
    csv.write_text(_CSV_BODY, encoding="utf-8")
    source = _source_for(csv)  # still claims preprocessed/customers.csv
    out = tmp_path / "out"

    with pytest.raises(ManagedSourceVerificationError) as excinfo:
        run_managed_export_star(source, output_dir=str(out))

    assert excinfo.value.reason_code == "SOURCE_NOT_CONFINED"
    assert _export_dir_is_empty(out)


def test_removed_source_is_refused(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    out = tmp_path / "out"

    csv.unlink()

    with pytest.raises(ManagedSourceVerificationError) as excinfo:
        run_managed_export_star(source, output_dir=str(out))

    assert excinfo.value.reason_code == "SOURCE_MISSING"
    assert _export_dir_is_empty(out)


# --- Existing behavior: an unchanged managed export still succeeds -------------


def test_unchanged_managed_export_still_succeeds(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)

    result = run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    assert result["managed_source"]["content_id"] == source.content_id
    assert "manifest" in result["export_paths"]
    for path in result["export_paths"].values():
        assert Path(path).exists()


def test_unchanged_managed_manifest_records_the_verified_content_id(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)

    result = run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    manifest = Path(result["export_paths"]["manifest"]).read_text(encoding="utf-8")
    assert source.content_id in manifest
    assert source.version_id in manifest
    # The manifest carries no machine-side path in any separator form: the source
    # is recorded by file name only, and nothing in it names the test's host root.
    parsed = json.loads(manifest)
    assert [dataset["path"] for dataset in parsed["datasets"]] == ["customers.csv"]
    for form in {
        source.source_path,
        Path(source.source_path).as_posix(),
        source.source_path.replace("\\", "/"),
        str(tmp_path),
        tmp_path.as_posix(),
        json.dumps(str(tmp_path))[1:-1],
    }:
        assert form not in manifest
    for value in _string_values(parsed):
        windows = PureWindowsPath(value)
        assert not PurePosixPath(value).is_absolute(), value
        assert not (windows.drive or windows.root), value


def _string_values(node: object) -> list[str]:
    """Every string a parsed JSON document contains."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [value for item in node.values() for value in _string_values(item)]
    if isinstance(node, list):
        return [value for item in node for value in _string_values(item)]
    return []


# --- Shared verifier: direct unit coverage (§19) ------------------------------


def _verify(source: VerifiedManagedExportSource, *, exact: bool = True) -> str | None:
    return verify_managed_source(
        source_path=source.source_path,
        relative_posix=source.relative_posix,
        size_bytes=source.size_bytes,
        modified_ns=source.modified_ns,
        content_id=source.content_id if exact else None,
    )


def test_verifier_passes_an_unchanged_valid_source(tmp_path: Path) -> None:
    source = _source_for(_managed_csv(tmp_path))

    assert _verify(source) is None


def test_verifier_refuses_a_missing_source(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    csv.unlink()

    assert _verify(source) == "SOURCE_MISSING"


def test_verifier_refuses_a_non_regular_source(tmp_path: Path) -> None:
    """A file replaced by a directory at the same path is not a managed source."""
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    csv.unlink()
    csv.mkdir()

    assert _verify(source) == "SOURCE_MISSING"


def test_verifier_refuses_a_size_mismatch(tmp_path: Path) -> None:
    source = _source_for(_managed_csv(tmp_path), size_bytes=1)

    assert _verify(source) == "CONTENT_MISMATCH"


def test_verifier_refuses_a_stat_identity_mismatch(tmp_path: Path) -> None:
    source = _source_for(_managed_csv(tmp_path), modified_ns=1)

    assert _verify(source) == "CONTENT_MISMATCH"


def test_verifier_refuses_an_exact_content_id_mismatch(tmp_path: Path) -> None:
    source = _source_for(_managed_csv(tmp_path), content_id="sha256:" + "a" * 64)

    assert _verify(source) == "CONTENT_MISMATCH"


def test_verifier_refuses_a_same_size_content_mismatch(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    original = managed_content_id_from_file(csv)
    mutated = _CSV_BODY.replace("30", "99")
    assert len(mutated) == len(_CSV_BODY)
    _rewrite(csv, mutated)
    st = csv.resolve().stat()
    source = _source_for(
        csv,
        content_id=original,
        size_bytes=int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
    )

    assert _verify(source) == "CONTENT_MISMATCH"


def test_verifier_refuses_an_unconfined_source(tmp_path: Path) -> None:
    directory = tmp_path / "elsewhere"
    directory.mkdir()
    csv = directory / "customers.csv"
    csv.write_text(_CSV_BODY, encoding="utf-8")

    assert _verify(_source_for(csv)) == "SOURCE_NOT_CONFINED"


def test_verifier_without_content_id_skips_exact_verification(tmp_path: Path) -> None:
    """The frame-load posture: path/stat only, so no full-file hash is paid.

    This is the behavior the managed frame loader relies on, and the precise
    reason the export path must opt into exact content verification.
    """
    csv = _managed_csv(tmp_path)
    original = managed_content_id_from_file(csv)
    mutated = _CSV_BODY.replace("30", "99")
    _rewrite(csv, mutated)
    st = csv.resolve().stat()
    source = _source_for(
        csv,
        content_id=original,
        size_bytes=int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
    )

    assert _verify(source, exact=False) is None
    assert _verify(source, exact=True) == "CONTENT_MISMATCH"


def test_verifier_never_mutates_the_filesystem(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    st_before = csv.stat()

    assert _verify(source) is None

    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    assert csv.stat().st_size == st_before.st_size
    assert csv.stat().st_mtime_ns == st_before.st_mtime_ns


# --- Privacy ------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason_code",
    ["SOURCE_MISSING", "SOURCE_REPLACED", "SOURCE_NOT_CONFINED", "CONTENT_MISMATCH"],
)
def test_refusal_messages_are_path_free(reason_code: str) -> None:
    error = ManagedSourceVerificationError(reason_code)

    text = f"{error} {error!r}"
    assert "C:\\" not in text
    assert ":\\" not in text
    assert "/" not in text
    assert error.reason_code == reason_code


def test_export_refusal_never_exposes_the_absolute_source_path(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)
    _rewrite(csv, "id,age\n1,30\n2,40\n3,50\n")

    with pytest.raises(ManagedSourceVerificationError) as excinfo:
        run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    rendered = f"{excinfo.value} {excinfo.value!r} {excinfo.value.args}"
    assert source.source_path not in rendered
    assert str(tmp_path) not in rendered
    assert source.content_id not in rendered
    assert "customers.csv" not in rendered


def test_verified_source_repr_still_excludes_the_source_path(tmp_path: Path) -> None:
    source = _source_for(_managed_csv(tmp_path))

    assert source.source_path not in repr(source)


# --- Identity algorithm: one definition, not two ------------------------------


def test_shared_content_id_matches_the_canonical_lifecycle_algorithm(tmp_path: Path) -> None:
    """The shared verifier uses the repository's canonical content identity.

    ``dataset_versions.content_id_from_file`` is the lifecycle owner of
    ``content_id``; the shared verifier must compute exactly the same value,
    never a second competing identity.
    """
    from data_quality_toolkit.adapters.ui.services.dataset_versions import (
        content_id_from_file,
    )

    for body in ("", _CSV_BODY, "x" * (3 * 1024 * 1024 + 7)):
        csv = tmp_path / "sample.csv"
        csv.write_text(body, encoding="utf-8")
        assert managed_content_id_from_file(csv) == content_id_from_file(csv)


def test_shared_content_id_is_a_prefixed_sha256(tmp_path: Path) -> None:
    import hashlib

    csv = _managed_csv(tmp_path)
    # Hash the bytes actually on disk: identity is byte-exact, never text-shaped.
    expected = hashlib.sha256(csv.read_bytes()).hexdigest()

    assert managed_content_id_from_file(csv) == f"sha256:{expected}"


# --- Architecture / import direction (§22) ------------------------------------


def _imported_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_shared_verifier_imports_no_business_layer() -> None:
    modules = _imported_modules(shared_module)

    for module in modules:
        assert not module.startswith("data_quality_toolkit.adapters")
        assert not module.startswith("data_quality_toolkit.application")
        assert not module.startswith("data_quality_toolkit.domain")
        assert not module.startswith("streamlit")
    assert not any(m.startswith("data_quality_toolkit.") for m in modules)


def test_application_export_boundary_imports_no_ui_layer() -> None:
    modules = _imported_modules(pipeline)

    assert not any(m.startswith("data_quality_toolkit.adapters.ui") for m in modules)
    assert "data_quality_toolkit.shared.managed_export_source" in modules


def test_managed_frame_loader_delegates_instead_of_duplicating_the_policy() -> None:
    """The loader keeps no second copy of the generic path/stat policy."""
    from data_quality_toolkit.adapters.ui.services import managed_frame_loader

    source = inspect.getsource(managed_frame_loader._revalidate_source)

    assert "verify_managed_source" in source
    # The duplicated stat/confinement implementation is gone from the loader.
    assert "S_ISREG" not in source
    assert "resolve(strict=True)" not in source
    assert "st_mtime_ns" not in source


def test_export_boundary_verifies_before_consuming_bytes() -> None:
    """Verification is the first statement of the managed use case."""
    source = inspect.getsource(run_managed_export_star)
    function = ast.parse(source).body[0]
    assert isinstance(function, ast.FunctionDef)

    # Skip the docstring; verification must be the first executable statement.
    statements = list(function.body)
    if isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant):
        statements = statements[1:]
    first = statements[0]
    assert isinstance(first, ast.Expr)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "verify_managed_export_source"
    # And it precedes the call into the unmanaged exporter.
    assert source.index("verify_managed_export_source(source)") < source.index("run_export_star(")


def test_verify_managed_export_source_raises_rather_than_returning_a_flag(
    tmp_path: Path,
) -> None:
    """A caller cannot proceed to export by ignoring a return value."""
    csv = _managed_csv(tmp_path)
    source = _source_for(csv)

    verify_managed_export_source(source)

    _rewrite(csv, "id,age\n1,30\n2,41\n")
    with pytest.raises(ManagedSourceVerificationError):
        verify_managed_export_source(source)
