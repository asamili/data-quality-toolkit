"""Unit tests for lineage manifest serializer backends and dispatch."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from data_quality_toolkit.lineage.manifest.schemas import Artifact, Dataset, Manifest


def _minimal_manifest() -> Manifest:
    return Manifest(
        schema_version="1.0.0",
        run_id="test-run",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _rich_manifest() -> Manifest:
    return Manifest(
        schema_version="1.0.0",
        run_id="rich-run",
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        datasets=[Dataset(kind="bronze", path="data/raw.csv", content_hash="")],
        artifacts=[Artifact(kind="star", path="dist/star.csv")],
    )


# ---------------------------------------------------------------------------
# PydanticSerializer
# ---------------------------------------------------------------------------


class TestPydanticSerializer:
    def test_roundtrip_default(self) -> None:
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        ser = PydanticSerializer()
        m = _minimal_manifest()
        data = ser.serialize(m)
        assert isinstance(data, bytes)
        result = ser.deserialize(data)
        assert result.run_id == m.run_id
        assert result.schema_version == m.schema_version

    def test_roundtrip_use_orjson_false(self) -> None:
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        ser = PydanticSerializer(use_orjson=False)
        assert ser._use_orjson is False
        result = ser.deserialize(ser.serialize(_minimal_manifest()))
        assert result.run_id == "test-run"

    def test_roundtrip_use_orjson_true_if_present(self) -> None:
        pytest.importorskip("orjson")
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        ser = PydanticSerializer(use_orjson=True)
        assert ser._use_orjson is True
        result = ser.deserialize(ser.serialize(_minimal_manifest()))
        assert result.run_id == "test-run"

    def test_use_orjson_false_when_orjson_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import data_quality_toolkit.lineage.manifest.pydantic_impl as mod
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        monkeypatch.setattr(mod, "orjson", None)
        ser = PydanticSerializer(use_orjson=True)
        assert ser._use_orjson is False

    def test_serialize_produces_valid_json_bytes(self) -> None:
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        data = PydanticSerializer().serialize(_minimal_manifest())
        parsed = json.loads(data)
        assert parsed["run_id"] == "test-run"
        assert "schema_version" in parsed

    def test_datasets_and_artifacts_preserved_in_roundtrip(self) -> None:
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        ser = PydanticSerializer()
        m = _rich_manifest()
        result = ser.deserialize(ser.serialize(m))
        assert len(result.datasets) == 1
        assert result.datasets[0].kind == "bronze"
        assert len(result.artifacts) == 1
        assert result.artifacts[0].kind == "star"

    def test_deserialize_orjson_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        orjson = pytest.importorskip("orjson")
        import data_quality_toolkit.lineage.manifest.pydantic_impl as mod
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        monkeypatch.setattr(mod, "orjson", orjson)
        ser = PydanticSerializer(use_orjson=True)
        data = ser.serialize(_minimal_manifest())
        result = ser.deserialize(data)
        assert result.run_id == "test-run"


# ---------------------------------------------------------------------------
# MsgspecSerializer
# ---------------------------------------------------------------------------


class TestMsgspecSerializer:
    def test_roundtrip(self) -> None:
        pytest.importorskip("msgspec")
        from data_quality_toolkit.lineage.manifest.msgspec_impl import MsgspecSerializer

        ser = MsgspecSerializer()
        m = _minimal_manifest()
        data = ser.serialize(m)
        assert isinstance(data, bytes)
        result = ser.deserialize(data)
        assert result.run_id == m.run_id
        assert result.schema_version == m.schema_version

    def test_serialize_produces_valid_json_bytes(self) -> None:
        pytest.importorskip("msgspec")
        from data_quality_toolkit.lineage.manifest.msgspec_impl import MsgspecSerializer

        data = MsgspecSerializer().serialize(_minimal_manifest())
        parsed = json.loads(data)
        assert parsed["run_id"] == "test-run"

    def test_datasets_preserved_in_roundtrip(self) -> None:
        pytest.importorskip("msgspec")
        from data_quality_toolkit.lineage.manifest.msgspec_impl import MsgspecSerializer

        m = Manifest(
            schema_version="1.0.0",
            run_id="r2",
            created_at=datetime(2025, 6, 1, tzinfo=UTC),
            datasets=[Dataset(kind="silver", path="data/clean.csv", content_hash="")],
        )
        ser = MsgspecSerializer()
        result = ser.deserialize(ser.serialize(m))
        assert result.datasets[0].kind == "silver"


# ---------------------------------------------------------------------------
# ManifestSerializer dispatch
# ---------------------------------------------------------------------------


class TestManifestSerializer:
    def test_dispatch_defaults_to_pydantic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import data_quality_toolkit.lineage.manifest.serializer as ser_mod
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer
        from data_quality_toolkit.lineage.manifest.serializer import ManifestSerializer

        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "serde_impl", "pydantic")
        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "json_writer", "json")
        ms = ManifestSerializer()
        assert isinstance(ms._impl, PydanticSerializer)

    def test_dispatch_msgspec_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("msgspec")
        import data_quality_toolkit.lineage.manifest.serializer as ser_mod
        from data_quality_toolkit.lineage.manifest.msgspec_impl import MsgspecSerializer
        from data_quality_toolkit.lineage.manifest.serializer import ManifestSerializer

        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "serde_impl", "msgspec")
        ms = ManifestSerializer()
        assert isinstance(ms._impl, MsgspecSerializer)

    def test_pydantic_dispatch_uses_orjson_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("orjson")
        import data_quality_toolkit.lineage.manifest.serializer as ser_mod
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer
        from data_quality_toolkit.lineage.manifest.serializer import ManifestSerializer

        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "serde_impl", "pydantic")
        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "json_writer", "orjson")
        ms = ManifestSerializer()
        assert isinstance(ms._impl, PydanticSerializer)
        assert ms._impl._use_orjson is True

    def test_to_json_from_json_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import data_quality_toolkit.lineage.manifest.serializer as ser_mod
        from data_quality_toolkit.lineage.manifest.serializer import ManifestSerializer

        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "serde_impl", "pydantic")
        monkeypatch.setattr(ser_mod.DQT_SETTINGS, "json_writer", "json")
        ms = ManifestSerializer()
        m = _minimal_manifest()
        result = ms.from_json(ms.to_json(m))
        assert result.run_id == m.run_id
        assert result.schema_version == m.schema_version
