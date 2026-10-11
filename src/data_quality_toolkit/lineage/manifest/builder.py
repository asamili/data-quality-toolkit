# src/data_quality_toolkit/lineage/manifest/builder.py
"""Build and write manifest files."""

from __future__ import annotations

import io
import json
import logging
import os
import pathlib
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

from data_quality_toolkit.lineage.manifest.collector import collect
from data_quality_toolkit.lineage.manifest.schemas import (
    Artifact,
    Dataset,
    GateFailure,
    Gates,
    Manifest,
    StepSummary,
    Summary,
)
from data_quality_toolkit.shared.exceptions import DQTError
from data_quality_toolkit.shared.settings import settings

logger = logging.getLogger(__name__)

# Cross-version UTC tzinfo; prefer Py3.11+ `datetime.UTC`, fallback to `timezone.utc`
try:  # Python 3.11+
    from datetime import UTC
except Exception:  # pragma: no cover
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017


# Optional orjson with strict typing and no mypy conflicts
class _OrjsonLike(Protocol):
    def dumps(self, __obj: Any, option: int = ...) -> bytes: ...


orjson: _OrjsonLike | None
try:
    import orjson as _real_orjson  # noqa: F401

    orjson = cast(_OrjsonLike, _real_orjson)
except Exception:  # pragma: no cover
    orjson = None


def _parse_gate_event(ev: dict, idx: int) -> tuple[bool, GateFailure | None]:
    """Return (is_error_failed, GateFailure|None) for a single gates.jsonl event."""
    sev_raw = str(ev.get("severity", "")).lower()
    st = str(ev.get("status", "")).lower()
    phase = _coerce_phase(str(ev.get("gate", "")))
    severity = _coerce_severity(sev_raw)

    # Only record failures for error+failed
    if severity == "error" and st == "failed":
        if phase is None:
            logger.warning("unknown gate phase %r; skipping failure record", ev.get("gate"))
            return True, None
        ts = _parse_iso_utc(str(ev.get("timestamp", ""))) or datetime.now(UTC)
        try:
            failure = GateFailure(
                phase=phase,
                code=str(ev.get("code", "")),
                severity=severity,  # Literal['warn','error']
                details=cast(dict[str, Any], ev.get("details", {})),
                timestamp=ts,
            )
            return True, failure
        except Exception as e:
            logger.warning("invalid gate failure at line %d: %s", idx, e)
            return True, None

    return False, None


def _read_gates(session_dir: Path) -> Gates:
    """Read gates.jsonl and return an aggregated Gates object."""
    gates_path = session_dir / "meta" / "gates.jsonl"
    if not gates_path.exists():
        return Gates(status="skipped", failures=[])

    any_error_failed = False
    failures: list[GateFailure] = []

    for idx, raw in enumerate(gates_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception as e:
            logger.warning("gates.jsonl parse error at line %d: %s", idx, e)
            continue

        is_failed, failure = _parse_gate_event(ev, idx)
        any_error_failed |= is_failed
        if failure:
            failures.append(failure)

    return Gates(status=("failed" if any_error_failed else "passed"), failures=failures)


def _atomic_write_json(path: pathlib.Path, payload: dict) -> None:
    """Write JSON atomically to avoid corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if settings.json_writer == "orjson" and orjson is not None:
        # 2 | 256 == OPT_INDENT_2 | OPT_SORT_KEYS
        data = orjson.dumps(payload, option=2 | 256)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(path.parent)) as tmp_bin:
            tmp_bin.write(data)
            tmp_bin.flush()
            os.fsync(tmp_bin.fileno())
        os.replace(tmp_bin.name, path)
    else:
        buf = io.StringIO()
        json.dump(payload, buf, indent=2, sort_keys=True, default=str)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=str(path.parent)
        ) as tmp_txt:
            tmp_txt.write(buf.getvalue())
            tmp_txt.flush()
            os.fsync(tmp_txt.fileno())
        os.replace(tmp_txt.name, path)


# Read-only protocol so attribute types are covariant for structural typing
class _HasKindPath(Protocol):
    @property
    def kind(self) -> object: ...

    @property
    def path(self) -> object: ...


def _sorted_datasets(datasets: Sequence[_HasKindPath]) -> list[_HasKindPath]:
    """Sort by kind, then path (stringified to support enums/Paths)."""
    return sorted(datasets, key=lambda x: (str(x.kind), str(x.path)))


def _sorted_artifacts(artifacts: Sequence[_HasKindPath]) -> list[_HasKindPath]:
    """Sort by kind, then path (stringified to support enums/Paths)."""
    return sorted(artifacts, key=lambda x: (str(x.kind), str(x.path)))


def _parse_iso_utc(ts: str) -> datetime | None:
    """Parse ISO8601 timestamps with optional trailing 'Z' into aware datetimes."""
    s = ts.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


PhaseT = Literal["pre", "post", "publish"]
SeverityT = Literal["warn", "error"]


def _coerce_phase(value: str) -> PhaseT | None:
    v = value.strip().lower()
    if v in ("pre", "post", "publish"):
        return cast(PhaseT, v)
    return None


def _coerce_severity(value: str) -> SeverityT | None:
    v = value.strip().lower()
    if v in ("warn", "warning"):  # normalize "warning" → "warn"
        return "warn"
    if v == "error":
        return "error"
    return None


def resolve_manifest_path(session_dir: Path | str) -> Path:
    """Return where :func:`build_and_write` writes the manifest for *session_dir*.

    The filename is the configured ``MANIFEST_FILE`` (default ``artifacts.json``),
    so callers that report the written manifest never assume a literal name.
    """
    return Path(session_dir) / settings.manifest_file


def build_and_write(
    run_id: str,
    session_dir: pathlib.Path,
    datasets: list[Dataset],
    artifacts: list[Artifact],
    steps_summary: StepSummary | None = None,
    rows_in: int = 0,
    rows_out: int = 0,
    bytes_total: int = 0,
    health: float | None = None,
    gates: Gates | None = None,
) -> Manifest:
    """Build manifest and write to artifacts.json."""
    if bytes_total == 0:
        bytes_total = sum(getattr(d, "bytes", 0) for d in datasets) + sum(
            getattr(a, "bytes", 0) for a in artifacts
        )

    manifest = Manifest(
        schema_version=settings.lineage_schema_version,
        run_id=run_id,
        created_at=datetime.now(UTC),
        datasets=cast(list[Dataset], _sorted_datasets(datasets)),
        artifacts=cast(list[Artifact], _sorted_artifacts(artifacts)),
        summary=Summary(
            steps=steps_summary or StepSummary(),
            rows_in=rows_in,
            rows_out=rows_out,
            bytes_total=bytes_total,
            health=health,
        ),
        gates=gates or Gates(status="skipped", failures=[]),
    )

    manifest_path = resolve_manifest_path(session_dir)
    _atomic_write_json(manifest_path, json.loads(manifest.model_dump_json(by_alias=True)))
    return manifest


class ManifestRebuildRefusedError(DQTError, ValueError):
    """Raised when a rebuild would discard evidence the existing manifest records.

    Also a ``ValueError`` so existing callers report it as a bounded failure: the
    CLI's ``ValueError`` handler prints one redacted ``Error:`` line and exits 1,
    and the UI rebuild actions render any exception instead of their success text.
    """


# Evidence categories a manifest can record, in stable reporting order. Derived
# summary fields (health, rows, bytes) are deliberately not categories: a rebuild
# never recomputes them, so counting them as evidence would refuse every rebuild.
_EVIDENCE_LABELS: Final[dict[str, str]] = {
    "datasets": "dataset entries",
    "artifacts": "artifact entries",
    "provenance": "artifact provenance metadata",
    "gates": "gate results",
}


def _evidence(
    datasets: Sequence[Dataset], artifacts: Sequence[Artifact], gates: Gates
) -> frozenset[str]:
    """Return the evidence categories present in manifest content."""
    found: set[str] = set()
    if datasets:
        found.add("datasets")
    if artifacts:
        found.add("artifacts")
    if any(artifact.meta for artifact in artifacts):
        found.add("provenance")
    if gates.status != "skipped" or gates.failures:
        found.add("gates")
    return frozenset(found)


def _existing_evidence(manifest_path: Path) -> frozenset[str]:
    """Return the evidence categories recorded by the manifest already on disk.

    A missing file records nothing, so first-time creation is unaffected. Content
    that is not a valid manifest records nothing the schema can vouch for, so a
    rebuild can still replace (repair) it. Any other read failure propagates.
    """
    try:
        data = manifest_path.read_bytes()
    except FileNotFoundError:
        return frozenset()
    try:
        existing = Manifest.model_validate_json(data)
    except ValueError:
        return frozenset()
    return _evidence(existing.datasets, existing.artifacts, existing.gates)


def _refuse_evidence_loss(manifest_path: Path, proposed: frozenset[str]) -> None:
    """Refuse, before any write, a rebuild that drops a whole evidence category.

    Counts may change freely; only a category the existing manifest records and
    the rebuilt content lacks entirely is treated as a destructive downgrade.
    """
    missing = _existing_evidence(manifest_path) - proposed
    lost = [key for key in _EVIDENCE_LABELS if key in missing]
    if not lost:
        return
    labels = ", ".join(_EVIDENCE_LABELS[key] for key in lost)
    raise ManifestRebuildRefusedError(
        f"Manifest rebuild refused: the existing manifest records {labels}, but the "
        "rebuild found none in this session. The existing manifest was left unchanged.",
        hint=(
            "Rebuild reads the session's recorded lineage (meta/lineage.jsonl) and gate "
            "log (meta/gates.jsonl). Re-run the workflow that produced the manifest to "
            "regenerate it."
        ),
        metadata={"lost_evidence": lost},
    )


def build_manifest(run_id: str, sessions_root: Path | str) -> Manifest:
    """Public entrypoint: build a manifest for <run_id> using lineage + FS.

    Raises :class:`ManifestRebuildRefusedError`, before anything is written, when
    the existing manifest records an evidence category the rebuild lacks entirely.
    """
    session_dir = Path(sessions_root) / run_id

    # 1) collect from lineage + filesystem (normalized to sessions/<run_id>/...)
    datasets, artifacts = collect(session_dir)

    # 2) compute totals
    bytes_total = sum(getattr(d, "bytes", 0) for d in datasets) + sum(
        getattr(a, "bytes", 0) for a in artifacts
    )

    # 3) minimal defaults; you can enrich later from telemetry
    steps_summary = StepSummary()
    rows_in = rows_out = 0

    # 4) gates (if present). If not, default to "skipped"
    gates = _read_gates(session_dir)

    # 5) refuse before writing if this rebuild would discard recorded evidence
    _refuse_evidence_loss(
        session_dir / settings.manifest_file, _evidence(datasets, artifacts, gates)
    )

    return build_and_write(
        run_id=run_id,
        session_dir=session_dir,
        datasets=datasets,
        artifacts=artifacts,
        steps_summary=steps_summary,
        rows_in=rows_in,
        rows_out=rows_out,
        bytes_total=bytes_total,
        gates=gates,
    )
