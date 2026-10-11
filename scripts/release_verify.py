#!/usr/bin/env python3
"""Fail-closed verifier for publishing a DQT GitHub Release from frozen artifacts.

This is governed release infrastructure. A DQT release publishes the exact
wheel, sdist and ``checksums.txt`` that were built once from the frozen public
source snapshot and qualified before any tag existed. Nothing in the release
path builds, repacks or substitutes them. This tool is the single place that
decides whether a staged draft release may be made public, and every check it
performs fails closed: a value it cannot read, parse or match is a refusal,
never a warning.

**Authority.** Expected identities come only from the repository-controlled
release manifest ``release/manifests/<version>.json``. Callers supply *where*
to look (a tag, a directory, a JSON document fetched from the GitHub API),
never *what to expect*: no hash, size or filename is accepted on the command
line, so an operator cannot pair a substitute artifact with a matching
substitute hash.

**Snapshot binding.** The tag must be annotated and resolve to a commit whose
tree is byte-for-byte the frozen public snapshot. That is proven twice, by the
git tree object id and by the canonical content fingerprint
(``sha256`` over ``"<sha256>  <size>  <path>\\n"`` records sorted by path), the
same definition the snapshot was frozen under.

**Scope.** Python standard library only, no network, no installation. The
GitHub API calls that fetch release metadata and asset bytes live in the
workflow; their output is handed to this tool as files and verified here.

Subcommands: ``manifest``, ``context``, ``snapshot-dir``, ``source``, ``body``,
``release``, ``assets`` and ``ci``. Each prints ``OK: ...`` and exits 0, or
prints ``REFUSED: ...`` to stderr and exits 1.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import email.message
import email.parser
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "dqt-release-manifest/1"
SNAPSHOT_ALGORITHM = "sha256-canonical-stream/1"
EXPECTED_REPOSITORY = "asamili/data-quality-toolkit"
EXPECTED_REF = "refs/heads/main"
DISTRIBUTION = "data-quality-toolkit"
MODULE = "data_quality_toolkit"
CONSOLE_SCRIPT = "dqt"
CHECKSUMS_NAME = "checksums.txt"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
BLOB_MODE = "100644"
PRIVATE_PATH_DOMAIN = "dqt-private-path/1:"

_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
VERSION_RE = re.compile(rf"\A{_VERSION}\Z")
TAG_RE = re.compile(rf"\Av{_VERSION}\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
SHA1_RE = re.compile(r"\A[0-9a-f]{40}\Z")
CHECKSUM_LINE_RE = re.compile(r"\A([0-9a-f]{64})  ([A-Za-z0-9._+-]+)\Z")

# Release-status wording that must never reach a published release body: it
# describes a pre-publication state that stops being true once the release
# is public. Matching is case-insensitive and word-bounded.
FORBIDDEN_BODY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bunreleased\b", re.IGNORECASE),
    re.compile(r"\bprivate\s+preparation\b", re.IGNORECASE),
    re.compile(r"\bno\s+tag\b", re.IGNORECASE),
)

# Known private surfaces, from the public-snapshot exclusion contract. Stored
# as sha256(PRIVATE_PATH_DOMAIN + path) so this public file does not itself
# publish private file names. A trailing "/" marks a directory prefix.
PRIVATE_PATH_DIGESTS: frozenset[str] = frozenset(
    {
        "097daafc69ee15ea8d9dd01ef06f15e304ad63c7957a0071a474c343e647fea6",
        "09cf3b8fbfea96cd5c56d6f6517604b3a2e9c85cf50cef5cb54cb86485e7fb12",
        "0c85ad1840504f550fa5ec858e0efae872ff30fd26b1eda9032008d8604a6534",
        "157c48c345788273e6be54d9be009e6c92bdc6460886ecb9f268ca27cd4b306e",
        "17d5d01a87683eacd12bf0da0923e25d0905409cc4753eb56fb0f40ed3f6c20d",
        "1a3359f95cfdbb51b5207cc6660bb67f71c99f098a229d6b29388de1e0b3f326",
        "212f7e921a017dd44871e90cf80b470bcc66952bd3b9ce98f6a539a197e66f4d",
        "21d6ed41eee2c52cc22e92c8ed72c2fa3d960d8a63264d9dc965888a038ecf96",
        "22be29a9d61a11782b68383ae85fb3daa56045eab33e91d1d406bff7698a4c91",
        "25e870985fecd4ec421d49a52f920448a7e2336754073c63f2b5d27e1cac002a",
        "2a68e8827af9f6836a83c71bd754651fc3d97b2bb2c800687e2d3eb7350e9e87",
        "2e730136229accbe02465e6aebf560b91898bcd9e1f09ce8af8448e2afd95c65",
        "41c0b46ee4fcf909645974a7b7379c2be29f38bfd0df8c74c52853f1c61ad175",
        "47b03284e22a82d7a828bc548d7782b2f8e5a859d9f5687a3e66a6d9e5a6562c",
        "4c6d53728a3a394a16bc4a10e3ff0af0ed72155c5c237f967490fe402393f24e",
        "4e63744bf890843abfe1ec97e17f5dc43098f8fda1846cfeb42e0059346db37b",
        "4f44c65fa9643c0a960064a514b7c9a25227db8d4beab9a00805d4d3c4c9dae0",
        "5275247ec1111e57e8c7b695b26d83a8b257599773c512968f1f52f7ea4a6e90",
        "57865926a8e4fc3fee93614e49b0fc142f0ac92601cb9956fbb5ce447d77690e",
        "5b0792d3242d024a18a19b72002f4137622aa738d17b4060385d3d6f623e30e3",
        "634c68fc799e5ef5db179b26a461129ae768fc922696cbd5b74a13a8c263f43e",
        "6e0c6915c5083596776ab0161389ac337000dabf98f403a533c8af3503029c42",
        "6f67271a8419aa16c28b920782f2033c66d714ed7fb241c8deb607a46c9d6a41",
        "6fb1f3827ad6286ac5356aadf2660b6d589662b8707c755a78ba8ecb2cd0b7e6",
        "7c275295f78d0b963b48177a4990835916a558792275c64ba8a37c9535fb54fe",
        "872a8c446e7f328c1a7c5bc16175842c4646ed83279a749334bdca71d3088883",
        "94e15ebf6b45f600ddbaa402e2ef4b47862d5c51e0689c1ab6c636fa1e6fb65c",
        "a651dc924c7bf13049aeb4ff5e09064685b373bd8c88de0c0353087fa3863605",
        "a7edeccd8fd72bba4109256f87cefafcadc5a65eac0d54ad2bbd489c9744e498",
        "ae4ed53ec10bf93b563c10cb91494181f1eaa3008721bf89de0e6530ac30f90e",
        "b883eb9af77edc767f13c40a246f1a9623781a8e6bdaecf3d0e992faad4a9c71",
        "ca81e2946f413aae203afb520f719b40d3993e966513aa5383e66d4cbf9ee35c",
        "cdacf698e8ef972da9d15ad46cbb640488db0d1061ac1121a8f44893e279da87",
        "cf50d4858f8bf1dc98103b8558cf3332eb61a89f8fd237ffd3895bd691e1cb8e",
        "d3e3d2b93be253b376d13a684b5c6da653a435a7b9e0633c1cf874581a9a62bb",
        "d4d228a3622486b43941392f566e17099b33724948b1115a3df31cec40b6ae9f",
        "d9abe90d79cf51299d9e43006a0f30abf61c7a1cdb7b4758e9aea4ac7ccb748d",
        "e4383d64eb34bc28149c8ca374bc33729f1f0c766dc01b9c8da8627bc1531a03",
        "ef2d80f42c7e87291268e4e682ce155dde535f67791bdda6d702348c13c6ce59",
        "f17b02361bbd410eea121bd19c542097caea5aa18fdf4838b1fdb291691398b6",
        "f537f77beec080173ce964f1bb927c04d9311e6eee9d6e9192b9d4cfbd18a3e7",
        "f8967beaf4f1d011a0187beea126a18fcfcd0acb7a92455a573923957ca29735",
    }
)

_MANIFEST_KEYS = {
    "schema",
    "version",
    "tag",
    "requires_python",
    "snapshot",
    "artifacts",
    "release_body",
    "publication_status",
}
_SNAPSHOT_KEYS = {"algorithm", "content_sha256", "file_count", "git_tree_sha1"}
_ARTIFACT_KEYS = {"role", "filename", "size", "sha256"}
_BODY_KEYS = {"source", "section", "sha256"}
_ROLES = ("wheel", "sdist", "checksums")


class ReleaseRefusedError(Exception):
    """A verification failure. The release must not proceed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseRefusedError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Artifact:
    role: str
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    version: str
    tag: str
    requires_python: str
    snapshot_sha256: str
    snapshot_file_count: int
    snapshot_tree: str
    artifacts: tuple[Artifact, ...]
    body_sha256: str

    def artifact(self, role: str) -> Artifact:
        return next(a for a in self.artifacts if a.role == role)

    @property
    def filenames(self) -> set[str]:
        return {a.filename for a in self.artifacts}


def _exact_keys(obj: Any, keys: set[str], where: str) -> Mapping[str, Any]:
    require(isinstance(obj, dict), f"{where}: expected an object")
    actual = set(obj)
    require(actual == keys, f"{where}: keys {sorted(actual)} != expected {sorted(keys)}")
    mapping: Mapping[str, Any] = obj
    return mapping


def _positive_int(value: Any, where: str) -> int:
    ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
    require(ok, f"{where}: expected a positive integer")
    return int(value)


def _hex(value: Any, pattern: re.Pattern[str], where: str) -> str:
    require(isinstance(value, str) and bool(pattern.match(value)), f"{where}: malformed digest")
    return str(value)


def expected_filenames(version: str) -> dict[str, str]:
    return {
        "wheel": f"{MODULE}-{version}-py3-none-any.whl",
        "sdist": f"{MODULE}-{version}.tar.gz",
        "checksums": CHECKSUMS_NAME,
    }


def _parse_artifacts(raw: Any, version: str) -> tuple[Artifact, ...]:
    require(isinstance(raw, list) and len(raw) == len(_ROLES), "artifacts: expected 3 entries")
    names = expected_filenames(version)
    parsed: list[Artifact] = []
    for index, item in enumerate(raw):
        entry = _exact_keys(item, _ARTIFACT_KEYS, f"artifacts[{index}]")
        role = entry["role"]
        require(role in names, f"artifacts[{index}]: unknown role {role!r}")
        require(entry["filename"] == names[role], f"artifacts[{index}]: wrong filename")
        size = _positive_int(entry["size"], f"artifacts[{index}].size")
        digest = _hex(entry["sha256"], SHA256_RE, f"artifacts[{index}].sha256")
        parsed.append(Artifact(role, names[role], size, digest))
    require(len({a.role for a in parsed}) == len(_ROLES), "artifacts: duplicate role")
    require(len({a.filename for a in parsed}) == len(_ROLES), "artifacts: duplicate filename")
    return tuple(parsed)


def _parse_snapshot(raw: Any) -> tuple[str, int, str]:
    snap = _exact_keys(raw, _SNAPSHOT_KEYS, "snapshot")
    require(snap["algorithm"] == SNAPSHOT_ALGORITHM, "snapshot.algorithm: unexpected value")
    content = _hex(snap["content_sha256"], SHA256_RE, "snapshot.content_sha256")
    count = _positive_int(snap["file_count"], "snapshot.file_count")
    tree = _hex(snap["git_tree_sha1"], SHA1_RE, "snapshot.git_tree_sha1")
    return content, count, tree


def _parse_body(raw: Any, version: str) -> str:
    body = _exact_keys(raw, _BODY_KEYS, "release_body")
    require(body["source"] == "CHANGELOG.md", "release_body.source: expected CHANGELOG.md")
    require(body["section"] == version, "release_body.section: must equal version")
    return _hex(body["sha256"], SHA256_RE, "release_body.sha256")


def parse_manifest(data: Any) -> Manifest:
    root = _exact_keys(data, _MANIFEST_KEYS, "manifest")
    require(root["schema"] == SCHEMA, "manifest.schema: unexpected value")
    version = root["version"]
    require(isinstance(version, str) and bool(VERSION_RE.match(version)), "manifest.version")
    require(root["tag"] == f"v{version}", "manifest.tag: must be 'v' + version")
    requires_python = root["requires_python"]
    require(isinstance(requires_python, str) and bool(requires_python), "requires_python")
    require(root["publication_status"] == "candidate", "publication_status: expected candidate")
    content, count, tree = _parse_snapshot(root["snapshot"])
    return Manifest(
        version=version,
        tag=root["tag"],
        requires_python=requires_python,
        snapshot_sha256=content,
        snapshot_file_count=count,
        snapshot_tree=tree,
        artifacts=_parse_artifacts(root["artifacts"], version),
        body_sha256=_parse_body(root["release_body"], version),
    )


def load_manifest(path: Path) -> Manifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseRefusedError(f"manifest unreadable: {exc}") from exc
    return parse_manifest(data)


# --------------------------------------------------------------------------- #
# Context (repository, ref, tag)
# --------------------------------------------------------------------------- #


def verify_tag_format(tag: str) -> str:
    require(bool(TAG_RE.match(tag)), "tag: must look like vMAJOR.MINOR.PATCH")
    return tag


def verify_context(manifest: Manifest, repository: str, ref: str, tag: str) -> None:
    require(repository == EXPECTED_REPOSITORY, "repository: publication only from public repo")
    require(ref == EXPECTED_REF, f"ref: publication only from {EXPECTED_REF}")
    verify_tag_format(tag)
    require(tag == manifest.tag, "tag: does not match manifest tag")


# --------------------------------------------------------------------------- #
# Snapshot fingerprint, git tree id, private-path check
# --------------------------------------------------------------------------- #


def _check_relpath(path: str) -> None:
    parts = PurePosixPath(path).parts
    ok = bool(parts) and not path.startswith("/") and "\\" not in path
    require(ok and ".." not in parts and ".git" not in parts, f"unsafe path {path!r}")


def snapshot_fingerprint(files: Mapping[str, bytes]) -> str:
    """The frozen-snapshot content fingerprint over ``path -> bytes``."""
    stream = "".join(
        f"{sha256_bytes(files[path])}  {len(files[path])}  {path}\n" for path in sorted(files)
    )
    return sha256_bytes(stream.encode("utf-8"))


def _git_object(kind: bytes, payload: bytes) -> bytes:
    header = kind + b" " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload, usedforsecurity=False).digest()


def _tree_id(node: Mapping[str, Any]) -> bytes:
    entries: list[tuple[bytes, bytes]] = []
    for name, child in node.items():
        raw = name.encode("utf-8")
        if isinstance(child, dict):
            entries.append((raw + b"/", b"40000 " + raw + b"\0" + _tree_id(child)))
        else:
            entries.append(
                (raw, BLOB_MODE.encode() + b" " + raw + b"\0" + _git_object(b"blob", child))
            )
    entries.sort(key=lambda item: item[0])
    return _git_object(b"tree", b"".join(entry for _, entry in entries))


def git_tree_sha1(files: Mapping[str, bytes]) -> str:
    """Git tree id of ``files`` with every file a regular 100644 blob."""
    root: dict[str, Any] = {}
    for path, data in files.items():
        _check_relpath(path)
        *dirs, leaf = path.split("/")
        node = root
        for part in dirs:
            node = node.setdefault(part, {})
            require(isinstance(node, dict), f"path collision at {path!r}")
        require(leaf not in node, f"duplicate path {path!r}")
        node[leaf] = data
    return _tree_id(root).hex()


def private_path_hits(paths: Iterable[str], digests: frozenset[str]) -> list[str]:
    """Paths that are, or sit under, a known private surface."""
    hits: list[str] = []
    for path in paths:
        parts = path.split("/")
        candidates = [path] + ["/".join(parts[:i]) + "/" for i in range(1, len(parts))]
        if any(
            sha256_bytes((PRIVATE_PATH_DOMAIN + c).encode("utf-8")) in digests for c in candidates
        ):
            hits.append(path)
    return sorted(hits)


def verify_snapshot_files(
    manifest: Manifest,
    files: Mapping[str, bytes],
    digests: frozenset[str] = PRIVATE_PATH_DIGESTS,
) -> str:
    require(len(files) == manifest.snapshot_file_count, f"snapshot: {len(files)} files")
    fingerprint = snapshot_fingerprint(files)
    require(fingerprint == manifest.snapshot_sha256, "snapshot: content fingerprint mismatch")
    tree = git_tree_sha1(files)
    require(tree == manifest.snapshot_tree, "snapshot: git tree id mismatch")
    hits = private_path_hits(files, digests)
    require(not hits, f"snapshot: known private surface present: {len(hits)} path(s)")
    return tree


def read_snapshot_dir(root: Path) -> dict[str, bytes]:
    require(root.is_dir(), f"snapshot root missing: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        _check_relpath(rel)
        require(not path.is_symlink(), f"symlink in snapshot: {rel}")
        if path.is_file():
            files[rel] = path.read_bytes()
    return files


# --------------------------------------------------------------------------- #
# Source: tag -> annotated tag object -> commit C1 -> tree, read from git
# --------------------------------------------------------------------------- #


def _git() -> str:
    exe = shutil.which("git")
    require(exe is not None, "git executable not found on PATH")
    return str(exe)


def run_git(repo: Path, args: Sequence[str], stdin: bytes | None = None) -> bytes:
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, validated words only
        [_git(), "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        check=False,
    )
    require(completed.returncode == 0, f"git {args[0]} failed: {completed.stderr!r}")
    return bytes(completed.stdout)


def _tag_header_name(raw_tag_object: bytes) -> str:
    for line in raw_tag_object.split(b"\n"):
        if not line:
            break
        if line.startswith(b"tag "):
            return line[4:].decode("utf-8")
    raise ReleaseRefusedError("tag object has no 'tag' header")


def _read_tree_blobs(repo: Path, commit: str) -> dict[str, bytes]:
    listing = run_git(repo, ["ls-tree", "-r", "-z", "--full-tree", commit])
    entries: list[tuple[str, str]] = []
    for record in filter(None, listing.split(b"\0")):
        meta, _, path = record.partition(b"\t")
        mode, kind, obj = meta.decode("ascii").split(" ")
        rel = path.decode("utf-8")
        require(mode == BLOB_MODE and kind == "blob", f"non-regular tree entry {rel!r} ({mode})")
        entries.append((rel, obj))
    batch = run_git(repo, ["cat-file", "--batch"], "".join(o + "\n" for _, o in entries).encode())
    files: dict[str, bytes] = {}
    offset = 0
    for rel, obj in entries:
        newline = batch.index(b"\n", offset)
        got, kind, size = batch[offset:newline].decode("ascii").split(" ")
        require(got == obj and kind == "blob", f"cat-file mismatch for {rel!r}")
        start = newline + 1
        files[rel] = batch[start : start + int(size)]
        offset = start + int(size) + 1
    return files


def resolve_tag(repo: Path, tag: str) -> tuple[str, str]:
    """Return (commit, tree) for an annotated ``tag`` whose header names it."""
    verify_tag_format(tag)
    ref = f"refs/tags/{tag}"
    kind = run_git(repo, ["cat-file", "-t", ref]).decode().strip()
    require(kind == "tag", f"{tag}: not an annotated tag (object type {kind!r})")
    header = _tag_header_name(run_git(repo, ["cat-file", "tag", ref]))
    require(header == tag, f"{tag}: tag object names {header!r}")
    commit = run_git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"]).decode().strip()
    tree = run_git(repo, ["rev-parse", "--verify", f"{ref}^{{tree}}"]).decode().strip()
    require(bool(SHA1_RE.match(commit)) and bool(SHA1_RE.match(tree)), f"{tag}: bad ids")
    return commit, tree


def _pyproject_version(data: bytes) -> str:
    try:
        project = tomllib.loads(data.decode("utf-8"))["project"]
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError) as exc:
        raise ReleaseRefusedError(f"pyproject.toml unreadable: {exc}") from exc
    version = project.get("version")
    require(isinstance(version, str), "pyproject.toml: project.version missing")
    return str(version)


def verify_source(manifest: Manifest, repo: Path, tag: str, head: str = "HEAD") -> str:
    """Bind tag -> C1 -> frozen snapshot, and require C1 to be an ancestor of ``head``."""
    require(tag == manifest.tag, "tag: does not match manifest tag")
    commit, tree = resolve_tag(repo, tag)
    require(tree == manifest.snapshot_tree, f"{tag}: tree {tree} != manifest snapshot tree")
    files = _read_tree_blobs(repo, commit)
    verify_snapshot_files(manifest, files)
    require("pyproject.toml" in files, "C1: pyproject.toml missing")
    version = _pyproject_version(files["pyproject.toml"])
    require(version == manifest.version, f"C1: pyproject version {version!r} != manifest")
    ancestor = subprocess.run(  # noqa: S603 - fixed argv, no shell, validated words only
        [_git(), "-C", str(repo), "merge-base", "--is-ancestor", commit, head],
        capture_output=True,
        check=False,
    )
    require(ancestor.returncode == 0, f"C1 {commit} is not an ancestor of {head}")
    return commit


# --------------------------------------------------------------------------- #
# Release body (CHANGELOG section)
# --------------------------------------------------------------------------- #


def canonical_text(text: str) -> str:
    """LF line endings, no leading/trailing blank lines, exactly one final newline."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return normalized + "\n" if normalized else ""


def extract_section(changelog: str, version: str) -> tuple[str, str]:
    """Return (heading, canonical body) of the single ``## [version]`` section."""
    lines = changelog.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    heading = re.compile(rf"\A## \[{re.escape(version)}\](?:[ \t].*)?\Z")
    starts = [i for i, line in enumerate(lines) if heading.match(line)]
    require(len(starts) == 1, f"CHANGELOG: {len(starts)} '## [{version}]' sections")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
    body = canonical_text("\n".join(lines[start + 1 : end]))
    require(body.strip() != "", f"CHANGELOG: '## [{version}]' section is empty")
    return lines[start], body


def forbidden_phrases(text: str) -> list[str]:
    return [p.pattern for p in FORBIDDEN_BODY_PATTERNS if p.search(text)]


def verify_body(manifest: Manifest, changelog: str) -> str:
    heading, body = extract_section(changelog, manifest.version)
    bad = forbidden_phrases(heading + "\n" + body)
    require(not bad, f"release body: stale release-status wording {bad}")
    require(sha256_bytes(body.encode("utf-8")) == manifest.body_sha256, "release body: sha256")
    return body


# --------------------------------------------------------------------------- #
# Draft / published release metadata (GitHub REST JSON)
# --------------------------------------------------------------------------- #


def _flatten_releases(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, dict):
        return [data]
    require(isinstance(data, list), "release JSON: expected object or list")
    flat: list[Mapping[str, Any]] = []
    for item in data:
        flat.extend(_flatten_releases(item) if isinstance(item, list) else [item])
    require(all(isinstance(r, dict) for r in flat), "release JSON: non-object entry")
    return flat


def select_release(data: Any, tag: str) -> Mapping[str, Any]:
    matches = [r for r in _flatten_releases(data) if r.get("tag_name") == tag]
    require(len(matches) == 1, f"release JSON: {len(matches)} releases for {tag}")
    return matches[0]


def _check_asset(asset: Mapping[str, Any], expected: Artifact) -> None:
    name = expected.filename
    require(asset.get("state") == "uploaded", f"asset {name}: state {asset.get('state')!r}")
    require(asset.get("size") == expected.size, f"asset {name}: size {asset.get('size')!r}")
    digest = asset.get("digest")
    if digest is not None:  # Server digest is corroboration only; local sha256 is authoritative.
        require(digest == f"sha256:{expected.sha256}", f"asset {name}: server digest mismatch")
    asset_id = asset.get("id")
    require(isinstance(asset_id, int) and not isinstance(asset_id, bool), f"asset {name}: id")


def verify_release(
    manifest: Manifest,
    release: Mapping[str, Any],
    *,
    draft: bool,
    plan: Mapping[str, int] | None = None,
    check_body: bool = False,
) -> dict[str, int]:
    """Check a release object; return its asset plan ``filename -> asset id``."""
    require(release.get("tag_name") == manifest.tag, "release: wrong tag_name")
    require(release.get("draft") is draft, f"release: draft is {release.get('draft')!r}")
    require(release.get("prerelease") is False, "release: must not be a prerelease")
    raw_assets = release.get("assets")
    require(isinstance(raw_assets, list), "release: assets missing")
    assets: list[Mapping[str, Any]] = raw_assets if isinstance(raw_assets, list) else []
    require(all(isinstance(a, dict) for a in assets), "release: malformed asset entry")
    names = [a.get("name") for a in assets]
    require(len(names) == len(set(names)), "release: duplicate asset names")
    require(set(names) == manifest.filenames, f"release: asset set {sorted(map(str, names))}")
    by_name = {a["name"]: a for a in assets}
    for artifact in manifest.artifacts:
        _check_asset(by_name[artifact.filename], artifact)
    found = {name: int(by_name[name]["id"]) for name in manifest.filenames}
    if plan is not None:
        require(found == dict(plan), "release: assets changed since verification")
    if check_body:
        got = canonical_text(str(release.get("body") or ""))
        require(sha256_bytes(got.encode("utf-8")) == manifest.body_sha256, "release: body")
    return found


# --------------------------------------------------------------------------- #
# Downloaded artifacts
# --------------------------------------------------------------------------- #


def verify_checksums_text(manifest: Manifest, data: bytes) -> None:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReleaseRefusedError("checksums.txt: not ASCII") from exc
    require("\r" not in text, "checksums.txt: CR line endings")
    lines = [line for line in text.split("\n") if line != ""]
    require(text.endswith("\n") and len(lines) == 2, f"checksums.txt: {len(lines)} entries")
    entries: dict[str, str] = {}
    for line in lines:
        match = CHECKSUM_LINE_RE.match(line)
        require(match is not None, f"checksums.txt: malformed line {line!r}")
        assert match is not None
        digest, name = match.groups()
        require(name not in entries, f"checksums.txt: duplicate entry {name}")
        entries[name] = digest
    wanted = {a.filename: a.sha256 for a in manifest.artifacts if a.role != "checksums"}
    require(entries == wanted, "checksums.txt: entries do not match manifest")


def _requires_python_clauses(value: str) -> set[str]:
    return {clause.replace(" ", "") for clause in value.split(",") if clause.strip()}


def _metadata_fields(text: str) -> email.message.Message:
    return email.parser.HeaderParser().parsestr(text)


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _check_metadata(manifest: Manifest, text: str, where: str) -> None:
    fields = _metadata_fields(text)
    require(_canonical_name(str(fields.get("Name", ""))) == DISTRIBUTION, f"{where}: Name")
    require(fields.get("Version") == manifest.version, f"{where}: Version mismatch")
    got = _requires_python_clauses(str(fields.get("Requires-Python", "")))
    require(got == _requires_python_clauses(manifest.requires_python), f"{where}: Requires-Python")


def _record_digest(data: bytes) -> str:
    raw = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _verify_record(archive: zipfile.ZipFile, dist_info: str) -> None:
    files = [i.filename for i in archive.infolist() if not i.is_dir()]
    for name in files:
        _check_relpath(name)
    record_name = f"{dist_info}/RECORD"
    rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    listed = [row[0] for row in rows if row]
    require(len(listed) == len(set(listed)), "wheel RECORD: duplicate rows")
    require(set(listed) == set(files), "wheel RECORD: does not list exactly the archive files")
    for row in rows:
        if not row or row[0] == record_name:
            continue
        require(len(row) == 3, f"wheel RECORD: malformed row {row[0]!r}")
        data = archive.read(row[0])
        require(row[1] == _record_digest(data), f"wheel RECORD: hash mismatch {row[0]!r}")
        require(row[2] == str(len(data)), f"wheel RECORD: size mismatch {row[0]!r}")


def verify_wheel(manifest: Manifest, path: Path) -> None:
    dist_info = f"{MODULE}-{manifest.version}.dist-info"
    try:
        with zipfile.ZipFile(path) as archive:
            require(archive.testzip() is None, "wheel: corrupt member")
            _check_metadata(manifest, archive.read(f"{dist_info}/METADATA").decode(), "wheel")
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(archive.read(f"{dist_info}/entry_points.txt").decode())
            target = parser.get("console_scripts", CONSOLE_SCRIPT, fallback="")
            require(target.startswith(f"{MODULE}."), "wheel: dqt console entry point missing")
            _verify_record(archive, dist_info)
    except (zipfile.BadZipFile, KeyError, configparser.Error, UnicodeDecodeError) as exc:
        raise ReleaseRefusedError(f"wheel: unreadable ({exc})") from exc


def _check_sdist_member(member: tarfile.TarInfo, root: str) -> None:
    _check_relpath(member.name)
    require(member.isfile() or member.isdir(), f"sdist: non-regular member {member.name!r}")
    require(member.name == root or member.name.startswith(root + "/"), "sdist: member outside root")


def verify_sdist(manifest: Manifest, path: Path) -> None:
    root = f"{MODULE}-{manifest.version}"
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = archive.getmembers()
            require(bool(members), "sdist: empty archive")
            for member in members:
                _check_sdist_member(member, root)
                if member.isfile():
                    handle = archive.extractfile(member)
                    require(handle is not None, f"sdist: unreadable {member.name!r}")
                    assert handle is not None
                    handle.read()
            names = {m.name for m in members}
            require(f"{root}/pyproject.toml" in names, "sdist: pyproject.toml missing")
            pkg_info = archive.extractfile(f"{root}/PKG-INFO")
            require(pkg_info is not None, "sdist: PKG-INFO missing")
            assert pkg_info is not None
            _check_metadata(manifest, pkg_info.read().decode("utf-8"), "sdist")
    except (tarfile.TarError, KeyError, OSError, EOFError, UnicodeDecodeError) as exc:
        raise ReleaseRefusedError(f"sdist: unreadable ({exc})") from exc


def verify_assets(manifest: Manifest, directory: Path) -> None:
    require(directory.is_dir(), f"asset directory missing: {directory}")
    present = sorted(p.name for p in directory.iterdir())
    require(set(present) == manifest.filenames and len(present) == 3, f"assets: {present}")
    for artifact in manifest.artifacts:
        path = directory / artifact.filename
        require(path.is_file() and not path.is_symlink(), f"{artifact.filename}: not a file")
        require(path.stat().st_size == artifact.size, f"{artifact.filename}: size mismatch")
        require(sha256_file(path) == artifact.sha256, f"{artifact.filename}: sha256 mismatch")
    verify_checksums_text(manifest, (directory / CHECKSUMS_NAME).read_bytes())
    verify_wheel(manifest, directory / manifest.artifact("wheel").filename)
    verify_sdist(manifest, directory / manifest.artifact("sdist").filename)


# --------------------------------------------------------------------------- #
# CI precondition
# --------------------------------------------------------------------------- #


def verify_ci(runs_payload: Any, sha: str) -> Mapping[str, Any]:
    """The newest CI push run for exactly ``sha`` on main must have succeeded."""
    require(bool(SHA1_RE.match(sha)), "ci: malformed commit sha")
    runs = runs_payload.get("workflow_runs") if isinstance(runs_payload, dict) else None
    require(isinstance(runs, list), "ci: workflow_runs missing")
    assert isinstance(runs, list)
    relevant = [
        r
        for r in runs
        if isinstance(r, dict)
        and r.get("head_sha") == sha
        and r.get("event") == "push"
        and r.get("head_branch") == "main"
        and r.get("path") == CI_WORKFLOW_PATH
    ]
    require(bool(relevant), f"ci: no CI push run on main for {sha}")
    newest = max(relevant, key=lambda r: (r.get("run_number", 0), r.get("run_attempt", 0)))
    ok = newest.get("status") == "completed" and newest.get("conclusion") == "success"
    require(ok, f"ci: newest CI run {newest.get('id')} is {newest.get('conclusion')!r}")
    return newest


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseRefusedError(f"{path.name}: unreadable JSON ({exc})") from exc


def _read_plan(path: Path) -> dict[str, int]:
    plan: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        asset_id, name = line.split("\t")
        plan[name] = int(asset_id)
    return plan


def _cmd_manifest(args: argparse.Namespace, manifest: Manifest) -> str:
    return f"manifest {manifest.tag} ({len(manifest.artifacts)} artifacts)"


def _cmd_context(args: argparse.Namespace, manifest: Manifest) -> str:
    verify_context(manifest, args.repository, args.ref, args.tag)
    return f"context {args.repository} {args.ref} {args.tag}"


def _cmd_snapshot_dir(args: argparse.Namespace, manifest: Manifest) -> str:
    tree = verify_snapshot_files(manifest, read_snapshot_dir(args.root))
    return f"snapshot {manifest.snapshot_file_count} files tree {tree}"


def _cmd_source(args: argparse.Namespace, manifest: Manifest) -> str:
    commit = verify_source(manifest, args.repo_dir, args.tag, args.head)
    return f"source {args.tag} -> {commit} tree {manifest.snapshot_tree}"


def _cmd_body(args: argparse.Namespace, manifest: Manifest) -> str:
    body = verify_body(manifest, args.changelog.read_text(encoding="utf-8"))
    if args.write:
        args.write.write_bytes(body.encode("utf-8"))
    return f"release body sha256 {manifest.body_sha256}"


def _cmd_release(args: argparse.Namespace, manifest: Manifest) -> str:
    release = select_release(_load_json(args.release_json), manifest.tag)
    plan = _read_plan(args.expect_plan) if args.expect_plan else None
    found = verify_release(
        manifest, release, draft=args.phase == "draft", plan=plan, check_body=args.check_body
    )
    if args.write_plan:
        rows = "".join(f"{found[a.filename]}\t{a.filename}\n" for a in manifest.artifacts)
        args.write_plan.write_text(rows, encoding="utf-8")
    if args.write_id:
        args.write_id.write_text(str(release.get("id")), encoding="utf-8")
    return f"release {manifest.tag} {args.phase} id {release.get('id')}"


def _cmd_assets(args: argparse.Namespace, manifest: Manifest) -> str:
    verify_assets(manifest, args.dir)
    return f"assets {sorted(manifest.filenames)}"


def _cmd_ci(args: argparse.Namespace, manifest: Manifest) -> str:
    run = verify_ci(_load_json(args.runs_json), args.sha)
    return f"ci run {run.get('id')} success for {args.sha}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else "")
    parser.add_argument("--manifest", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest").set_defaults(func=_cmd_manifest)
    p = sub.add_parser("context")
    p.add_argument("--repository", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--tag", required=True)
    p.set_defaults(func=_cmd_context)
    p = sub.add_parser("snapshot-dir")
    p.add_argument("--root", type=Path, required=True)
    p.set_defaults(func=_cmd_snapshot_dir)
    p = sub.add_parser("source")
    p.add_argument("--repo-dir", type=Path, default=Path("."))
    p.add_argument("--tag", required=True)
    p.add_argument("--head", default="HEAD")
    p.set_defaults(func=_cmd_source)
    p = sub.add_parser("body")
    p.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    p.add_argument("--write", type=Path)
    p.set_defaults(func=_cmd_body)
    p = sub.add_parser("release")
    p.add_argument("--release-json", type=Path, required=True)
    p.add_argument("--phase", choices=("draft", "published"), required=True)
    p.add_argument("--expect-plan", type=Path)
    p.add_argument("--check-body", action="store_true")
    p.add_argument("--write-plan", type=Path)
    p.add_argument("--write-id", type=Path)
    p.set_defaults(func=_cmd_release)
    p = sub.add_parser("assets")
    p.add_argument("--dir", type=Path, required=True)
    p.set_defaults(func=_cmd_assets)
    p = sub.add_parser("ci")
    p.add_argument("--runs-json", type=Path, required=True)
    p.add_argument("--sha", required=True)
    p.set_defaults(func=_cmd_ci)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        message = args.func(args, manifest)
    except ReleaseRefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
