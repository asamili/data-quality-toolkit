"""Contract tests for ``scripts/release_verify.py`` and the release-publish workflow.

A DQT release publishes the exact artifacts that were frozen and qualified
before any tag existed; ``release_verify.py`` is the fail-closed gate that
decides whether a staged draft may become public. These tests pin both halves
of that contract:

* every accepted identity (manifest, tag, snapshot tree and fingerprint,
  artifact bytes, checksums, archive metadata, release body, CI run) passes
  when it is exact, and
* every tampered or ambiguous variant is refused.

Synthetic artifacts and throwaway git repositories under ``tmp_path`` stand in
for the real release. When ``DQT_RELEASE_DIST_DIR`` / ``DQT_PUBLIC_SNAPSHOT_DIR``
point at the governed frozen artifacts and snapshot, the same checks run
against them too. Nothing here touches a remote or this repository's state.
"""

from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOL_PATH = _REPO_ROOT / "scripts" / "release_verify.py"
_MANIFEST_PATH = _REPO_ROOT / "release" / "manifests" / "2.10.0.json"
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_PUBLISH_WORKFLOW = _WORKFLOWS / "release-publish.yml"
_EXCLUDE_PATH = _REPO_ROOT / ".public-snapshot-exclude"


def _load_tool() -> ModuleType:
    """Import the verifier from ``scripts/`` (not an installed package)."""
    spec = importlib.util.spec_from_file_location("dqt_release_verify", _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rv = _load_tool()

VERSION = "2.10.0"
TAG = "v2.10.0"
WHEEL = f"data_quality_toolkit-{VERSION}-py3-none-any.whl"
SDIST = f"data_quality_toolkit-{VERSION}.tar.gz"
CHECKSUMS = "checksums.txt"
PRIVATE_SENTINEL = "docs/sentinel-private/notes.md"
PRIVATE_DIGESTS = frozenset(
    {hashlib.sha256((rv.PRIVATE_PATH_DOMAIN + "docs/sentinel-private/").encode()).hexdigest()}
)


# --------------------------------------------------------------------------- #
# Synthetic release fixtures
# --------------------------------------------------------------------------- #


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_files(version: str = VERSION) -> dict[str, bytes]:
    return {
        "pyproject.toml": f'[project]\nname = "data-quality-toolkit"\nversion = "{version}"\n'.encode(),
        "README.md": b"# DQT\n",
        "src/data_quality_toolkit/__init__.py": b'__version__ = "2.10.0"\n',
        "src/data_quality_toolkit/adapters/cli/main.py": b"def main() -> int:\n    return 0\n",
    }


def _metadata(version: str = VERSION, requires: str = "<3.13,>=3.12") -> bytes:
    return (
        "Metadata-Version: 2.4\nName: data-quality-toolkit\n"
        f"Version: {version}\nRequires-Python: {requires}\n\nDQT\n"
    ).encode()


def _record_hash(data: bytes) -> str:
    raw = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_wheel(
    version: str = VERSION,
    *,
    metadata: bytes | None = None,
    entry_points: bytes = b"[console_scripts]\ndqt = data_quality_toolkit.adapters.cli.main:main\n",
    tamper_record: bool = False,
) -> bytes:
    dist_info = f"data_quality_toolkit-{version}.dist-info"
    members = {
        "data_quality_toolkit/__init__.py": b'__version__ = "2.10.0"\n',
        "data_quality_toolkit/py.typed": b"",
        f"{dist_info}/METADATA": metadata if metadata is not None else _metadata(version),
        f"{dist_info}/entry_points.txt": entry_points,
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
    }
    rows = [f"{name},{_record_hash(data)},{len(data)}" for name, data in members.items()]
    if tamper_record:
        rows[0] = rows[0].replace("sha256=", "sha256=AAAA", 1)
    rows.append(f"{dist_info}/RECORD,,")
    members[f"{dist_info}/RECORD"] = ("\n".join(rows) + "\n").encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def make_sdist(version: str = VERSION, *, pkg_info: bytes | None = None, root: str = "") -> bytes:
    root = root or f"data_quality_toolkit-{version}"
    members = {
        f"{root}/PKG-INFO": pkg_info if pkg_info is not None else _metadata(version),
        f"{root}/pyproject.toml": _snapshot_files(version)["pyproject.toml"],
        f"{root}/src/data_quality_toolkit/__init__.py": b"",
    }
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


def make_checksums(wheel: bytes, sdist: bytes) -> bytes:
    return f"{_sha(wheel)}  {WHEEL}\n{_sha(sdist)}  {SDIST}\n".encode()


CHANGELOG = f"""# Changelog

## [Unreleased]

No entries yet.

## [{VERSION}]

Release candidate. Distributables and SHA-256 checksums are the assets of the
{TAG} GitHub Release.

### Added

- Things.

## [2.9.6] — earlier

- Older, unreleased history is out of scope.
"""


def body_of(changelog: str = CHANGELOG) -> str:
    return str(rv.extract_section(changelog, VERSION)[1])


def manifest_dict(
    *,
    files: dict[str, bytes] | None = None,
    wheel: bytes | None = None,
    sdist: bytes | None = None,
    checksums: bytes | None = None,
    changelog: str = CHANGELOG,
) -> dict[str, Any]:
    files = files if files is not None else _snapshot_files()
    wheel = wheel if wheel is not None else make_wheel()
    sdist = sdist if sdist is not None else make_sdist()
    checksums = checksums if checksums is not None else make_checksums(wheel, sdist)
    return {
        "schema": "dqt-release-manifest/1",
        "version": VERSION,
        "tag": TAG,
        "requires_python": ">=3.12,<3.13",
        "snapshot": {
            "algorithm": "sha256-canonical-stream/1",
            "content_sha256": rv.snapshot_fingerprint(files),
            "file_count": len(files),
            "git_tree_sha1": rv.git_tree_sha1(files),
        },
        "artifacts": [
            {"role": "wheel", "filename": WHEEL, "size": len(wheel), "sha256": _sha(wheel)},
            {"role": "sdist", "filename": SDIST, "size": len(sdist), "sha256": _sha(sdist)},
            {
                "role": "checksums",
                "filename": CHECKSUMS,
                "size": len(checksums),
                "sha256": _sha(checksums),
            },
        ],
        "release_body": {
            "source": "CHANGELOG.md",
            "section": VERSION,
            "sha256": _sha(body_of(changelog).encode()),
        },
        "publication_status": "candidate",
    }


@pytest.fixture
def release_dir(tmp_path: Path) -> tuple[Path, Any]:
    """A directory holding the three synthetic assets plus their manifest."""
    wheel, sdist = make_wheel(), make_sdist()
    checksums = make_checksums(wheel, sdist)
    directory = tmp_path / "assets"
    directory.mkdir()
    (directory / WHEEL).write_bytes(wheel)
    (directory / SDIST).write_bytes(sdist)
    (directory / CHECKSUMS).write_bytes(checksums)
    return directory, rv.parse_manifest(
        manifest_dict(wheel=wheel, sdist=sdist, checksums=checksums)
    )


def refused(func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    with pytest.raises(rv.ReleaseRefusedError) as info:
        func(*args, **kwargs)
    return str(info.value)


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


def test_valid_manifest_is_accepted() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    assert manifest.tag == TAG and manifest.version == VERSION
    assert manifest.filenames == {WHEEL, SDIST, CHECKSUMS}


def _mutate(path: str, value: Any) -> dict[str, Any]:
    data = manifest_dict()
    *parents, leaf = path.split(".")
    node: Any = data
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    if value is _DELETE:
        del node[leaf]
    else:
        node[int(leaf) if leaf.isdigit() else leaf] = value
    return data


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("schema", "dqt-release-manifest/2"),
        ("version", "2.10.1"),
        ("version", "2.10"),
        ("tag", "v2.10.1"),
        ("tag", "2.10.0"),
        ("publication_status", "published"),
        ("requires_python", ""),
        ("snapshot.algorithm", "sha1"),
        ("snapshot.file_count", 0),
        ("snapshot.file_count", True),
        ("snapshot.git_tree_sha1", "XYZ"),
        ("snapshot.content_sha256", "A" * 64),
        ("artifacts.0.filename", "data_quality_toolkit-2.10.0-py3-none-any.whl.bak"),
        ("artifacts.0.size", -1),
        ("artifacts.0.size", "683514"),
        ("artifacts.0.sha256", "0" * 63),
        ("artifacts.1.role", "wheel"),
        ("artifacts.2.filename", "SHA256SUMS"),
        ("release_body.source", "README.md"),
        ("release_body.section", "2.9.6"),
        ("release_body.sha256", "nothex"),
        ("snapshot.content_sha256", _DELETE),
        ("release_body.sha256", _DELETE),
        ("artifacts.0.sha256", _DELETE),
        ("publication_status", _DELETE),
    ],
)
def test_malformed_manifest_is_refused(path: str, value: Any) -> None:
    refused(rv.parse_manifest, _mutate(path, value))


def test_manifest_extra_key_and_extra_artifact_are_refused() -> None:
    data = manifest_dict()
    data["source_head"] = "0" * 40
    refused(rv.parse_manifest, data)
    data = manifest_dict()
    data["artifacts"].append(copy.deepcopy(data["artifacts"][0]))
    refused(rv.parse_manifest, data)
    data = manifest_dict()
    data["artifacts"][1] = copy.deepcopy(data["artifacts"][0])
    refused(rv.parse_manifest, data)


# --------------------------------------------------------------------------- #
# Context: repository, ref, tag
# --------------------------------------------------------------------------- #


def test_valid_context_is_accepted() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    rv.verify_context(manifest, "asamili/data-quality-toolkit", "refs/heads/main", TAG)


@pytest.mark.parametrize(
    ("repository", "ref", "tag"),
    [
        ("example/fork-of-dqt", "refs/heads/main", TAG),
        ("asamili/data-quality-toolkit", "refs/heads/release", TAG),
        ("asamili/data-quality-toolkit", "refs/tags/v2.10.0", TAG),
        ("asamili/data-quality-toolkit", "refs/heads/main", "v2.10.1"),
        ("asamili/data-quality-toolkit", "refs/heads/main", "2.10.0"),
        ("asamili/data-quality-toolkit", "refs/heads/main", "v2.10.0; rm -rf /"),
        ("asamili/data-quality-toolkit", "refs/heads/main", "v2.10.0\n"),
        ("asamili/data-quality-toolkit", "refs/heads/main", "v02.10.0"),
    ],
)
def test_wrong_repository_branch_or_tag_is_refused(repository: str, ref: str, tag: str) -> None:
    manifest = rv.parse_manifest(manifest_dict())
    refused(rv.verify_context, manifest, repository, ref, tag)


# --------------------------------------------------------------------------- #
# Snapshot fingerprint, tree id and private-path check
# --------------------------------------------------------------------------- #


def test_fingerprint_follows_canonical_record_format() -> None:
    files = {"b.txt": b"bb", "a/x.py": b"x"}
    stream = f"{_sha(b'x')}  1  a/x.py\n" f"{_sha(b'bb')}  2  b.txt\n"
    assert rv.snapshot_fingerprint(files) == _sha(stream.encode())


def test_git_tree_id_matches_git(tmp_path: Path) -> None:
    files = _snapshot_files()
    repo = _init_repo(tmp_path / "repo", files)
    assert rv.git_tree_sha1(files) == _git(repo, "write-tree")


def test_valid_snapshot_is_accepted() -> None:
    files = _snapshot_files()
    manifest = rv.parse_manifest(manifest_dict(files=files))
    assert rv.verify_snapshot_files(manifest, files, PRIVATE_DIGESTS) == rv.git_tree_sha1(files)


def test_snapshot_tamper_is_refused() -> None:
    files = _snapshot_files()
    manifest = rv.parse_manifest(manifest_dict(files=files))
    extra = dict(files, **{"NEW.md": b"x"})
    assert "files" in refused(rv.verify_snapshot_files, manifest, extra, PRIVATE_DIGESTS)
    changed = dict(files, **{"README.md": b"# DQT!\n"})
    assert "fingerprint" in refused(rv.verify_snapshot_files, manifest, changed, PRIVATE_DIGESTS)


def test_wrong_tree_or_fingerprint_in_manifest_is_refused() -> None:
    files = _snapshot_files()
    data = manifest_dict(files=files)
    data["snapshot"]["git_tree_sha1"] = "0" * 40
    msg = refused(rv.verify_snapshot_files, rv.parse_manifest(data), files, PRIVATE_DIGESTS)
    assert "tree" in msg
    data = manifest_dict(files=files)
    data["snapshot"]["content_sha256"] = "0" * 64
    msg = refused(rv.verify_snapshot_files, rv.parse_manifest(data), files, PRIVATE_DIGESTS)
    assert "fingerprint" in msg
    data = manifest_dict(files=files)
    data["snapshot"]["file_count"] = len(files) + 1
    assert "files" in refused(
        rv.verify_snapshot_files, rv.parse_manifest(data), files, PRIVATE_DIGESTS
    )


def test_known_private_path_is_detected_and_refused() -> None:
    assert rv.private_path_hits(_snapshot_files(), PRIVATE_DIGESTS) == []
    files = dict(_snapshot_files(), **{PRIVATE_SENTINEL: b"secret\n"})
    assert rv.private_path_hits(files, PRIVATE_DIGESTS) == [PRIVATE_SENTINEL]
    manifest = rv.parse_manifest(manifest_dict(files=files))
    assert "private" in refused(rv.verify_snapshot_files, manifest, files, PRIVATE_DIGESTS)


def test_private_digests_cover_the_exclusion_contract() -> None:
    if not _EXCLUDE_PATH.is_file():
        pytest.skip("exclusion contract is not part of the public tree")
    entries = set()
    for line in _EXCLUDE_PATH.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.endswith("/**") and not re.search(r"[*?\[]", entry[:-3]):
            entries.add(entry[:-2])
        elif not re.search(r"[*?\[]", entry):
            entries.add(entry)
    expected = {hashlib.sha256((rv.PRIVATE_PATH_DOMAIN + e).encode()).hexdigest() for e in entries}
    assert rv.PRIVATE_PATH_DIGESTS == expected


def test_snapshot_dir_reader_refuses_git_metadata(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    refused(rv.read_snapshot_dir, tmp_path)


# --------------------------------------------------------------------------- #
# Source: annotated tag -> C1 -> snapshot, C1 ancestor of C2
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> str:
    exe = shutil.which("git")
    assert exe is not None, "git is required for the tag/source tests"
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(repo / "unused-global-config")
    env.update(
        GIT_AUTHOR_NAME="Release Test",
        GIT_AUTHOR_EMAIL="release-test@example.invalid",
        GIT_COMMITTER_NAME="Release Test",
        GIT_COMMITTER_EMAIL="release-test@example.invalid",
    )
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [exe, "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return completed.stdout.strip()


def _write_tree(repo: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _init_repo(repo: Path, files: dict[str, bytes]) -> Path:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")
    _write_tree(repo, files)
    _git(repo, "add", "-A")
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "-q", "--no-verify", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def c1_c2_repo(tmp_path: Path) -> tuple[Path, Any]:
    """C1 = exact snapshot (annotated tag), C2 = control plane on top of it."""
    files = _snapshot_files()
    repo = _init_repo(tmp_path / "repo", files)
    _commit(repo, "C1 snapshot")
    _git(repo, "tag", "-a", TAG, "-m", "DQT 2.10.0")
    _write_tree(repo, {"release/manifests/2.10.0.json": b"{}\n"})
    _git(repo, "add", "-A")
    _commit(repo, "C2 control plane")
    return repo, rv.parse_manifest(manifest_dict(files=files))


def test_valid_c1_c2_model_is_accepted(c1_c2_repo: tuple[Path, Any]) -> None:
    repo, manifest = c1_c2_repo
    c1 = _git(repo, "rev-parse", f"{TAG}^{{commit}}")
    assert rv.verify_source(manifest, repo, TAG) == c1
    assert _git(repo, "rev-parse", "HEAD") != c1


def test_lightweight_tag_is_refused(c1_c2_repo: tuple[Path, Any]) -> None:
    repo, manifest = c1_c2_repo
    _git(repo, "tag", "-d", TAG)
    _git(repo, "tag", TAG, "HEAD~1")
    assert "annotated" in refused(rv.verify_source, manifest, repo, TAG)


def test_missing_tag_is_refused(c1_c2_repo: tuple[Path, Any]) -> None:
    repo, manifest = c1_c2_repo
    _git(repo, "tag", "-d", TAG)
    refused(rv.verify_source, manifest, repo, TAG)


def test_tag_on_wrong_tree_is_refused(c1_c2_repo: tuple[Path, Any]) -> None:
    repo, manifest = c1_c2_repo
    _git(repo, "tag", "-d", TAG)
    _git(repo, "tag", "-a", TAG, "-m", "points at C2", "HEAD")
    assert "tree" in refused(rv.verify_source, manifest, repo, TAG)


def test_tag_object_naming_another_tag_is_refused(c1_c2_repo: tuple[Path, Any]) -> None:
    repo, manifest = c1_c2_repo
    _git(repo, "tag", "-a", "v2.10.1", "-m", "other", "HEAD~1")
    _git(repo, "tag", "-d", TAG)
    _git(repo, "update-ref", f"refs/tags/{TAG}", _git(repo, "rev-parse", "refs/tags/v2.10.1"))
    assert "names" in refused(rv.verify_source, manifest, repo, TAG)


def test_c1_not_ancestor_of_control_plane_is_refused(c1_c2_repo: tuple[Path, Any]) -> None:
    repo, manifest = c1_c2_repo
    _git(repo, "checkout", "-q", "--orphan", "elsewhere")
    _commit(repo, "unrelated root")
    assert "ancestor" in refused(rv.verify_source, manifest, repo, TAG)


def test_wrong_pyproject_version_is_refused(tmp_path: Path) -> None:
    files = _snapshot_files(version="2.10.1")
    repo = _init_repo(tmp_path / "repo", files)
    _commit(repo, "C1")
    _git(repo, "tag", "-a", TAG, "-m", "tag")
    manifest = rv.parse_manifest(manifest_dict(files=files))
    assert "pyproject" in refused(rv.verify_source, manifest, repo, TAG)


def test_private_path_in_tagged_tree_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    files = dict(_snapshot_files(), **{PRIVATE_SENTINEL: b"secret\n"})
    repo = _init_repo(tmp_path / "repo", files)
    _commit(repo, "C1")
    _git(repo, "tag", "-a", TAG, "-m", "tag")
    monkeypatch.setattr(rv, "PRIVATE_PATH_DIGESTS", PRIVATE_DIGESTS)
    monkeypatch.setattr(
        rv, "verify_snapshot_files", _bind_digests(rv.verify_snapshot_files, PRIVATE_DIGESTS)
    )
    manifest = rv.parse_manifest(manifest_dict(files=files))
    assert "private" in refused(rv.verify_source, manifest, repo, TAG)


def _bind_digests(func: Callable[..., Any], digests: frozenset[str]) -> Callable[..., Any]:
    def bound(manifest: Any, files: Any, _digests: Any = None) -> Any:
        return func(manifest, files, digests)

    return bound


# --------------------------------------------------------------------------- #
# Artifacts, checksums, archive structure
# --------------------------------------------------------------------------- #


def test_valid_asset_directory_is_accepted(release_dir: tuple[Path, Any]) -> None:
    directory, manifest = release_dir
    rv.verify_assets(manifest, directory)


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        (WHEEL, lambda b: b + b"\0"),
        (WHEEL, lambda b: b[:-1] + bytes([b[-1] ^ 1])),
        (SDIST, lambda b: b + b"\0"),
        (SDIST, lambda b: b[:-1] + bytes([b[-1] ^ 1])),
        (CHECKSUMS, lambda b: b.replace(b"\n", b"\n\n", 1)),
    ],
    ids=["wheel-size", "wheel-hash", "sdist-size", "sdist-hash", "checksums-hash"],
)
def test_tampered_asset_bytes_are_refused(
    release_dir: tuple[Path, Any], name: str, mutate: Callable[[bytes], bytes]
) -> None:
    directory, manifest = release_dir
    path = directory / name
    path.write_bytes(mutate(path.read_bytes()))
    msg = refused(rv.verify_assets, manifest, directory)
    assert name in msg and ("size" in msg or "sha256" in msg)


def test_missing_extra_or_renamed_asset_is_refused(release_dir: tuple[Path, Any]) -> None:
    directory, manifest = release_dir
    (directory / "extra.txt").write_bytes(b"x")
    assert "assets" in refused(rv.verify_assets, manifest, directory)
    (directory / "extra.txt").unlink()
    (directory / WHEEL).rename(directory / (WHEEL + ".renamed"))
    assert "assets" in refused(rv.verify_assets, manifest, directory)
    (directory / (WHEEL + ".renamed")).unlink()
    assert "assets" in refused(rv.verify_assets, manifest, directory)


def _checksums_manifest(text: bytes) -> Any:
    wheel, sdist = make_wheel(), make_sdist()
    return rv.parse_manifest(manifest_dict(wheel=wheel, sdist=sdist, checksums=text))


def test_valid_checksums_file_is_accepted() -> None:
    text = make_checksums(make_wheel(), make_sdist())
    rv.verify_checksums_text(_checksums_manifest(text), text)


@pytest.mark.parametrize(
    "transform",
    [
        lambda w, s: f"{w}  {WHEEL}\n".encode(),
        lambda w, s: f"{w}  {WHEEL}\n{s}  {SDIST}\n{w}  extra.whl\n".encode(),
        lambda w, s: f"{w}  {WHEEL}\n{w}  {WHEEL}\n".encode(),
        lambda w, s: f"{w} {WHEEL}\n{s}  {SDIST}\n".encode(),
        lambda w, s: f"{w.upper()}  {WHEEL}\n{s}  {SDIST}\n".encode(),
        lambda w, s: f"{w}  {WHEEL}\r\n{s}  {SDIST}\r\n".encode(),
        lambda w, s: f"{w}  {WHEEL}\n{s}  {SDIST}".encode(),
        lambda w, s: f"{s}  {WHEEL}\n{w}  {SDIST}\n".encode(),
        lambda w, s: f"{w}  other.whl\n{s}  {SDIST}\n".encode(),
    ],
    ids=[
        "missing",
        "third",
        "duplicate",
        "one-space",
        "uppercase",
        "crlf",
        "no-newline",
        "swapped",
        "renamed",
    ],
)
def test_malformed_checksums_are_refused(transform: Callable[[str, str], bytes]) -> None:
    wheel, sdist = make_wheel(), make_sdist()
    text = transform(_sha(wheel), _sha(sdist))
    manifest = rv.parse_manifest(manifest_dict(wheel=wheel, sdist=sdist, checksums=text))
    refused(rv.verify_checksums_text, manifest, text)


def _verify_archive(tmp_path: Path, name: str, data: bytes) -> str | None:
    path = tmp_path / name
    path.write_bytes(data)
    manifest = rv.parse_manifest(manifest_dict())
    verify = rv.verify_wheel if name == WHEEL else rv.verify_sdist
    try:
        verify(manifest, path)
    except rv.ReleaseRefusedError as exc:
        return str(exc)
    return None


def test_valid_wheel_and_sdist_metadata_are_accepted(tmp_path: Path) -> None:
    assert _verify_archive(tmp_path, WHEEL, make_wheel()) is None
    assert _verify_archive(tmp_path, SDIST, make_sdist()) is None


@pytest.mark.parametrize(
    "wheel",
    [
        make_wheel(metadata=_metadata("2.10.1")),
        make_wheel(metadata=_metadata(requires=">=3.11")),
        make_wheel(entry_points=b"[console_scripts]\nother = x:y\n"),
        make_wheel(tamper_record=True),
        make_wheel(version="2.10.1"),
        b"not a zip",
    ],
    ids=["metadata-version", "requires-python", "no-entry-point", "record", "dist-info", "corrupt"],
)
def test_bad_wheel_is_refused(tmp_path: Path, wheel: bytes) -> None:
    assert _verify_archive(tmp_path, WHEEL, wheel) is not None


@pytest.mark.parametrize(
    "sdist",
    [
        make_sdist(pkg_info=_metadata("2.10.1")),
        make_sdist(pkg_info=_metadata(requires=">=3.11")),
        make_sdist(root="other-2.10.0"),
        b"not a tarball",
    ],
    ids=["pkg-info-version", "requires-python", "root", "corrupt"],
)
def test_bad_sdist_is_refused(tmp_path: Path, sdist: bytes) -> None:
    assert _verify_archive(tmp_path, SDIST, sdist) is not None


# --------------------------------------------------------------------------- #
# Release body
# --------------------------------------------------------------------------- #


def test_release_body_extraction_semantics() -> None:
    heading, body = rv.extract_section(CHANGELOG.replace("\n", "\r\n"), VERSION)
    assert heading == f"## [{VERSION}]"
    assert body.startswith("Release candidate.") and body.endswith("- Things.\n")
    assert "## [" not in body and "Unreleased" not in body
    manifest = rv.parse_manifest(manifest_dict())
    assert rv.verify_body(manifest, CHANGELOG) == body


@pytest.mark.parametrize(
    ("changelog", "needle"),
    [
        (CHANGELOG.replace(f"## [{VERSION}]", "## [2.10.1]"), "0 '## ["),
        (CHANGELOG + f"\n## [{VERSION}]\n\nagain\n", "2 '## ["),
        (CHANGELOG.replace("Release candidate.", "Status: unreleased."), "stale"),
        (CHANGELOG.replace("Release candidate.", "A private preparation baseline."), "stale"),
        (CHANGELOG.replace("Release candidate.", "No tag has been pushed."), "stale"),
        (CHANGELOG.replace(f"## [{VERSION}]", f"## [{VERSION}] — (Unreleased)"), "stale"),
        (CHANGELOG.replace("Release candidate.", "Release candidate!"), "sha256"),
    ],
    ids=["missing", "duplicate", "unreleased", "private-preparation", "no-tag", "heading", "hash"],
)
def test_bad_release_body_is_refused(changelog: str, needle: str) -> None:
    manifest = rv.parse_manifest(manifest_dict())
    assert needle in refused(rv.verify_body, manifest, changelog)


def test_empty_release_body_is_refused() -> None:
    empty = CHANGELOG.split(f"## [{VERSION}]")[0] + f"## [{VERSION}]\n\n## [2.9.6]\n"
    assert "empty" in refused(rv.extract_section, empty, VERSION)


@pytest.mark.parametrize(
    "text",
    [
        "Released after review; tagging happens later.",
        "Private keys are never logged.",
        "No tagging is required for local runs.",
        "Handles notag columns.",
    ],
)
def test_forbidden_phrase_check_is_not_overbroad(text: str) -> None:
    assert rv.forbidden_phrases(text) == []


# --------------------------------------------------------------------------- #
# Draft / published release metadata
# --------------------------------------------------------------------------- #


def release_json(manifest: Any, *, draft: bool = True, body: str | None = None) -> dict[str, Any]:
    assets = [
        {"id": 100 + i, "name": a.filename, "size": a.size, "state": "uploaded", "digest": None}
        for i, a in enumerate(manifest.artifacts)
    ]
    return {
        "id": 7,
        "tag_name": TAG,
        "draft": draft,
        "prerelease": False,
        "assets": assets,
        "body": body if body is not None else body_of(),
    }


def test_valid_draft_release_is_accepted_and_planned() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    plan = rv.verify_release(manifest, release_json(manifest), draft=True)
    assert set(plan) == {WHEEL, SDIST, CHECKSUMS}
    rv.verify_release(manifest, release_json(manifest), draft=True, plan=plan, check_body=True)
    rv.verify_release(manifest, release_json(manifest, draft=False), draft=False, plan=plan)


def test_server_digest_is_compared_when_present() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    data = release_json(manifest)
    for asset, artifact in zip(data["assets"], manifest.artifacts):
        asset["digest"] = f"sha256:{artifact.sha256}"
    rv.verify_release(manifest, data, draft=True)
    data["assets"][0]["digest"] = "sha256:" + "0" * 64
    assert "digest" in refused(rv.verify_release, manifest, data, draft=True)


def _drop_asset(d: dict[str, Any]) -> None:
    d["assets"].pop()


def _extra_asset(d: dict[str, Any]) -> None:
    d["assets"].append(dict(d["assets"][0], id=999, name="extra.zip"))


def _duplicate_asset(d: dict[str, Any]) -> None:
    d["assets"][2] = dict(d["assets"][0], id=998)


def _rename_asset(d: dict[str, Any]) -> None:
    d["assets"][0]["name"] = WHEEL.replace("2.10.0", "2.10.1")


def _resize_asset(d: dict[str, Any]) -> None:
    d["assets"][1]["size"] += 1


def _pending_asset(d: dict[str, Any]) -> None:
    d["assets"][1]["state"] = "starter"


def _published(d: dict[str, Any]) -> None:
    d["draft"] = False


def _prerelease(d: dict[str, Any]) -> None:
    d["prerelease"] = True


def _wrong_tag(d: dict[str, Any]) -> None:
    d["tag_name"] = "v2.10.1"


@pytest.mark.parametrize(
    "tamper",
    [
        _drop_asset,
        _extra_asset,
        _duplicate_asset,
        _rename_asset,
        _resize_asset,
        _pending_asset,
        _published,
        _prerelease,
        _wrong_tag,
    ],
)
def test_bad_draft_release_is_refused(tamper: Callable[[dict[str, Any]], None]) -> None:
    manifest = rv.parse_manifest(manifest_dict())
    data = release_json(manifest)
    tamper(data)
    refused(rv.verify_release, manifest, data, draft=True)


def test_swapped_asset_after_verification_is_refused() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    plan = rv.verify_release(manifest, release_json(manifest), draft=True)
    swapped = release_json(manifest)
    swapped["assets"][0]["id"] = 555
    assert "changed" in refused(rv.verify_release, manifest, swapped, draft=True, plan=plan)


def test_wrong_release_body_on_draft_is_refused() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    data = release_json(manifest, body="Something else\n")
    assert "body" in refused(rv.verify_release, manifest, data, draft=True, check_body=True)


def test_release_selection_requires_exactly_one_match() -> None:
    manifest = rv.parse_manifest(manifest_dict())
    one = release_json(manifest)
    other = dict(one, id=8, tag_name="v2.9.0", draft=False)
    assert rv.select_release([[other], [one]], TAG)["id"] == 7
    refused(rv.select_release, [other], TAG)
    refused(rv.select_release, [one, dict(one, id=9)], TAG)


# --------------------------------------------------------------------------- #
# CI precondition
# --------------------------------------------------------------------------- #

SHA = "1" * 40


def _run(**overrides: Any) -> dict[str, Any]:
    run = {
        "id": 1,
        "head_sha": SHA,
        "event": "push",
        "head_branch": "main",
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
        "run_number": 10,
        "run_attempt": 1,
    }
    run.update(overrides)
    return run


def test_ci_success_on_exact_sha_is_accepted() -> None:
    rv.verify_ci({"workflow_runs": [_run()]}, SHA)
    retried = [_run(conclusion="failure"), _run(id=2, run_attempt=2)]
    assert rv.verify_ci({"workflow_runs": retried}, SHA)["id"] == 2


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [_run(head_sha="2" * 40)],
        [_run(event="pull_request")],
        [_run(head_branch="feature")],
        [_run(path=".github/workflows/other.yml")],
        [_run(conclusion="failure")],
        [_run(status="in_progress", conclusion=None)],
        [_run(), _run(id=3, run_number=11, conclusion="failure")],
    ],
    ids=["none", "other-sha", "pr", "branch", "workflow", "failed", "running", "newest-failed"],
)
def test_ci_precondition_failures_are_refused(runs: list[dict[str, Any]]) -> None:
    refused(rv.verify_ci, {"workflow_runs": runs}, SHA)


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def test_cli_reports_ok_and_refusal(tmp_path: Path, capsys: Any) -> None:
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(manifest_dict()), encoding="utf-8")
    args = ["--manifest", str(manifest_path), "context", "--repository"]
    assert (
        rv.main([*args, "asamili/data-quality-toolkit", "--ref", "refs/heads/main", "--tag", TAG])
        == 0
    )
    assert capsys.readouterr().out.startswith("OK:")
    assert rv.main([*args, "example/fork", "--ref", "refs/heads/main", "--tag", TAG]) == 1
    assert "REFUSED" in capsys.readouterr().err


def test_cli_has_no_hash_url_or_artifact_path_overrides() -> None:
    text = _TOOL_PATH.read_text(encoding="utf-8")
    flags = set(re.findall(r'add_argument\("(--[a-z-]+)"', text))
    assert flags == {
        "--manifest",
        "--repository",
        "--ref",
        "--tag",
        "--root",
        "--repo-dir",
        "--head",
        "--changelog",
        "--write",
        "--release-json",
        "--phase",
        "--expect-plan",
        "--check-body",
        "--write-plan",
        "--write-id",
        "--dir",
        "--runs-json",
        "--sha",
    }
    assert not any(re.search(r"sha256|url|size|filename", f) for f in flags - {"--sha"})


# --------------------------------------------------------------------------- #
# Committed manifest and workflows
# --------------------------------------------------------------------------- #


# The frozen 2.10.0 distributables. Unlike the snapshot identity, these do not
# depend on the tree that carries the manifest, so they are pinned here.
FROZEN_ARTIFACTS = {
    (WHEEL, 683716, "f835d2a4af6057152ef8328079b3f47c4b25192de5a6dba144edbe12b5080cab"),
    (SDIST, 578051, "47511e6c543b9973580dad0a5d3e78b7b975c42494d718851040e807a84ffe28"),
    (CHECKSUMS, 212, "7944af7abf40918af0361f3ddcc2d0f89670f39e7f5bd28998e093b750937d3b"),
}


def _committed_manifest() -> Any:
    """The committed manifest, or a skip while it is intentionally absent.

    The manifest records the identity of the frozen public snapshot, so it
    cannot be part of the tree that snapshot is generated from; it is absent
    from that source commit and added once the snapshot identity exists.
    """
    if not _MANIFEST_PATH.is_file():
        pytest.skip("release manifest intentionally absent from the snapshot source commit")
    return rv.load_manifest(_MANIFEST_PATH)


def _frozen_manifest() -> Any:
    """A manifest carrying the pinned artifacts, independent of the committed one."""
    data = manifest_dict(changelog=(_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    data["artifacts"] = [
        {"role": role, "filename": name, "size": size, "sha256": digest}
        for role, (name, size, digest) in zip(
            ("wheel", "sdist", "checksums"), sorted(FROZEN_ARTIFACTS, key=_artifact_order)
        )
    ]
    return rv.parse_manifest(data)


def _artifact_order(item: tuple[str, int, str]) -> int:
    return [WHEEL, SDIST, CHECKSUMS].index(item[0])


def test_repository_release_body_is_publishable() -> None:
    _, body = rv.extract_section((_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), VERSION)
    assert rv.forbidden_phrases(body) == []
    assert (
        rv.verify_body(
            _frozen_manifest(), (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        )
        == body
    )


def test_committed_manifest_is_self_consistent() -> None:
    manifest = _committed_manifest()
    assert manifest.tag == TAG and manifest.version == VERSION
    assert manifest.requires_python == ">=3.12,<3.13"
    assert {(a.filename, a.size, a.sha256) for a in manifest.artifacts} == FROZEN_ARTIFACTS
    rv.verify_body(manifest, (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


def _workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # YAML 1.1 reads the bare key ``on`` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job["steps"])


def test_publish_workflow_trigger_inputs_and_permissions() -> None:
    wf = _workflow(_PUBLISH_WORKFLOW)
    assert set(wf["on"]) == {"workflow_dispatch"}
    assert set(wf["on"]["workflow_dispatch"]["inputs"]) == {"tag"}
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["cancel-in-progress"] is False
    guard, publish = wf["jobs"]["guard"], wf["jobs"]["publish"]
    assert guard["permissions"] == {"contents": "read"}
    assert publish["permissions"] == {"contents": "write", "actions": "read"}
    assert publish["needs"] == "guard" and publish["environment"] == "release"
    guard_script = guard["steps"][0]["run"]
    assert '"asamili/data-quality-toolkit"' in guard_script and '"refs/heads/main"' in guard_script


def test_publish_workflow_checkouts_drop_credentials() -> None:
    wf = _workflow(_PUBLISH_WORKFLOW)
    checkouts = [
        s
        for job in wf["jobs"].values()
        for s in _steps(job)
        if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts and all(s["with"]["persist-credentials"] is False for s in checkouts)


def test_publish_workflow_never_builds_tags_or_creates_releases() -> None:
    text = _PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    runs = "\n".join(
        str(s.get("run", ""))
        for job in _workflow(_PUBLISH_WORKFLOW)["jobs"].values()
        for s in _steps(job)
    )
    forbidden = [
        r"python\s+-m\s+build",
        r"\bpip\s+(install|wheel|download)\b",
        r"\bbdist",
        r"\bsdist\b",
        r"setup\.py",
        r"hatch\s+build",
        r"poetry\s+build",
        r"flit\s+build",
        r"\btwine\b",
        r"gh\s+release\s+(create|upload|edit|delete)",
        r"\bgit\s+(tag|push)\b",
        r"-X\s+(POST|DELETE)",
        r"upload-artifact",
        r"generate-notes",
    ]
    assert [p for p in forbidden if re.search(p, runs)] == []
    assert "${{ inputs" not in runs and "github.event.inputs" not in text


def test_publish_workflow_verifies_everything_before_the_flip() -> None:
    names = [s.get("name", "") for s in _steps(_workflow(_PUBLISH_WORKFLOW)["jobs"]["publish"])]
    order = [
        "Validate context and manifest",
        "Locate the staged draft release",
        "Download the exact draft assets",
        "Verify assets, checksums and archive structure",
        "Verify tag, source commit and frozen snapshot",
        "Verify release body",
        "Require CI success on this exact commit",
        "Re-verify the draft immediately before publication",
        "Publish (draft -> public)",
        "Read back the published release",
    ]
    assert [n for n in names if n in order] == order
    steps = {
        s.get("name"): str(s.get("run", ""))
        for s in _steps(_workflow(_PUBLISH_WORKFLOW)["jobs"]["publish"])
    }
    assert "draft=false" in steps["Publish (draft -> public)"]
    assert sum("draft=false" in r for r in steps.values()) == 1
    assert "$GITHUB_SHA" in steps["Require CI success on this exact commit"]


_RELEASE_PATCH = re.compile(r'\bgh\s+api\s+-X\s+PATCH\s+"repos/\$REPOSITORY/releases/')


def _shell_commands(script: str) -> list[str]:
    """Logical shell commands: backslash continuations joined, comment lines dropped."""
    joined = re.sub(r"\\\n\s*", " ", script)
    return [line.strip() for line in joined.splitlines() if not line.strip().startswith("#")]


def _release_patches(job: dict[str, Any]) -> list[tuple[int, str]]:
    return [
        (index, command)
        for index, step in enumerate(_steps(job))
        for command in _shell_commands(str(step.get("run", "")))
        if _RELEASE_PATCH.search(command)
    ]


def test_publish_workflow_patches_the_release_once_and_keeps_its_tag() -> None:
    # A release PATCH that omits tag_name detaches a draft from its tag, so the
    # only release write is the final flip, and it must name the tag explicitly.
    wf = _workflow(_PUBLISH_WORKFLOW)
    publish = wf["jobs"]["publish"]
    names = [s.get("name", "") for s in _steps(publish)]
    verify = names.index("Re-verify the draft immediately before publication")
    flip = names.index("Publish (draft -> public)")
    assert verify < flip < names.index("Read back the published release")
    patches = _release_patches(publish)
    assert [index for index, _ in patches] == [flip]
    command = patches[0][1]
    assert re.search(r'(?<!\S)-f\s+tag_name="\$TAG"(?!\S)', command)
    assert re.search(r"(?<!\S)-F\s+draft=false(?!\S)", command)
    for job_name, job in wf["jobs"].items():
        if job_name != "publish":
            assert _release_patches(job) == []
    check = str(_steps(publish)[verify].get("run", ""))
    assert all(flag in check for flag in ("--phase draft", "--expect-plan", "--check-body"))
    assert publish["environment"] == "release"


def test_no_workflow_publishes_on_tag_push() -> None:
    assert not (_WORKFLOWS / "release.yml").exists()
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        triggers = _workflow(path)["on"]
        push = triggers.get("push") if isinstance(triggers, dict) else None
        assert not (isinstance(push, dict) and "tags" in push), path.name


def test_ci_runs_bandit_after_pre_commit() -> None:
    steps = _steps(_workflow(_WORKFLOWS / "ci.yml")["jobs"]["lint-type-test"])
    names = [s.get("name") for s in steps]
    bandit = names.index("Bandit (security lint, src)")
    assert bandit == names.index("Pre-commit (repo policy)") + 1
    assert "pre-commit run bandit --hook-stage manual --files" in steps[bandit]["run"]


# --------------------------------------------------------------------------- #
# Governed frozen release (opt-in; the paths are environment-specific)
# --------------------------------------------------------------------------- #


def _env_dir(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"{name} not set")
    return Path(value)


def test_real_frozen_artifacts_pass() -> None:
    rv.verify_assets(_frozen_manifest(), _env_dir("DQT_RELEASE_DIST_DIR"))


def test_real_frozen_snapshot_passes() -> None:
    manifest = _committed_manifest()
    files = rv.read_snapshot_dir(_env_dir("DQT_PUBLIC_SNAPSHOT_DIR"))
    assert rv.verify_snapshot_files(manifest, files) == manifest.snapshot_tree
