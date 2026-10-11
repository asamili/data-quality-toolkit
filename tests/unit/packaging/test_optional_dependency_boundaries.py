"""Optional dependency boundary contracts.

Documents the absence-behavior for each optional dep:
- scipy [stats]: detect_drift_frames returns status="unavailable" (no ImportError)
- duckdb [duckdb]: export_monitoring_duckdb raises DuckdbExportError with install hint
- orjson: PydanticSerializer falls back to stdlib json (use_orjson stays False)
- msgspec [serde]: MsgspecSerializer raises MsgspecSerdeError with an install hint

Also pins declaration hygiene: install metadata names only packages that have a
real runtime, tooling, or build role in this repository, and tool configuration
names only live targets at the versions constraints.txt pins.

Streamlit [ui] boundary is covered by tests/unit/cli/test_cli_ui.py.
"""

from __future__ import annotations

import importlib
import re
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _requirement_name(requirement: str) -> str:
    """Return the normalized project name of a PEP 508 requirement string."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    assert match is not None, f"unparseable requirement: {requirement!r}"
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def _release_tuple(version: str) -> tuple[int, ...]:
    """Return a plain ``X.Y[.Z]`` release version as a comparable integer tuple."""
    return tuple(int(part) for part in version.strip().split("."))


def _minimum_version(requirement: str) -> tuple[int, ...]:
    """Return the ``>=`` floor of a requirement string as a comparable tuple."""
    match = re.search(r">=\s*([0-9]+(?:\.[0-9]+)*)", requirement)
    assert match is not None, f"no >= floor in {requirement!r}"
    return _release_tuple(match.group(1))


class TestScipy:
    def test_scipy_absent_import_helper_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import drift as drift_mod

        monkeypatch.setattr(drift_mod, "_import_scipy_stats", lambda: None)
        assert drift_mod._import_scipy_stats() is None

    def test_detect_drift_frames_scipy_absent_returns_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pandas as pd

        from data_quality_toolkit.domain.statistics import drift as drift_mod

        monkeypatch.setattr(drift_mod, "_import_scipy_stats", lambda: None)
        ref = pd.DataFrame({"age": [1, 2, 3, 4, 5]})
        cur = pd.DataFrame({"age": [10, 20, 30, 40, 50]})
        result = drift_mod.detect_drift_frames(ref, cur)
        assert result["status"] == "unavailable"
        assert result["scipy_available"] is False
        assert result["columns"] == []


class TestStatsKernel:
    """Wave-1 statistics kernel degrades (no ImportError) when scipy is absent."""

    def test_core_conversions_return_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import core

        monkeypatch.setattr(core, "import_scipy_stats", lambda: None)
        assert core.confidence_level_to_z(0.95) is None
        assert core.confidence_level_to_t(0.95, df=10) is None

    def test_distribution_wrappers_return_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import distributions as dist

        monkeypatch.setattr(dist, "import_scipy_stats", lambda: None)
        assert dist.normal_cdf(0.0) is None
        assert dist.chi2_cdf(1.0, df=2) is None

    def test_intervals_return_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import intervals

        monkeypatch.setattr(intervals, "import_scipy_stats", lambda: None)
        result = intervals.ci_mean([1.0, 2.0, 3.0])
        assert result["status"] == "unavailable"

    def test_power_returns_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import power

        monkeypatch.setattr(power, "import_scipy_stats", lambda: None)
        result = power.required_n_cohend(delta=0.5)
        assert result["status"] == "unavailable"

    def test_bootstrap_percentile_works_but_bca_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from data_quality_toolkit.domain.statistics import bootstrap

        monkeypatch.setattr(bootstrap, "import_scipy_stats", lambda: None)
        # percentile is pure numpy -> still works
        assert bootstrap.bootstrap_ci([1.0, 2.0, 3.0, 4.0], n_bootstrap=100)["status"] == "ok"
        # BCa needs scipy -> unavailable
        bca = bootstrap.bootstrap_ci([1.0, 2.0, 3.0, 4.0], method="bca", n_bootstrap=100)
        assert bca["status"] == "unavailable"

    def test_inference_returns_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import inference
        from data_quality_toolkit.domain.statistics.contracts import TestKey

        monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
        result = inference.calculate_p_value(TestKey.ONE_T, sample=[1.0, 2.0, 3.0])
        assert result["status"] == "unavailable"

    def test_ab_returns_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import ab
        from data_quality_toolkit.domain.statistics.contracts import VariableType

        monkeypatch.setattr(ab._inference, "import_scipy_stats", lambda: None)
        result = ab.compare_ab(
            [3.0, 4.0, 5.0],
            [1.0, 2.0, 3.0],
            variable_type=VariableType.NUMERIC,
        )
        assert result["status"] == "unavailable"


class TestDuckdb:
    def test_duckdb_absent_raises_duckdb_export_error_with_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from data_quality_toolkit.adapters.exporters.bi.duckdb_exporter import (
            DuckdbExportError,
            _import_duckdb,
        )

        monkeypatch.setitem(__import__("sys").modules, "duckdb", None)
        with pytest.raises(DuckdbExportError) as exc_info:
            _import_duckdb()
        msg = str(exc_info.value)
        assert "duckdb" in msg
        assert "pip install" in msg


class TestOrjson:
    def test_orjson_absent_pydantic_serializer_falls_back_to_stdlib(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import data_quality_toolkit.lineage.manifest.pydantic_impl as mod
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        monkeypatch.setattr(mod, "orjson", None)
        ser = PydanticSerializer(use_orjson=True)
        assert ser._use_orjson is False


class TestMsgspec:
    """msgspec [serde] absence is bounded; genuine breakage stays visible."""

    def test_importing_the_module_does_not_require_msgspec(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The optional dependency is reached only when the serializer is built."""
        import data_quality_toolkit.lineage.manifest.msgspec_impl as mod

        monkeypatch.setitem(sys.modules, "msgspec", None)
        reloaded = importlib.reload(mod)
        assert reloaded.MsgspecSerializer is not None
        assert not hasattr(reloaded, "msgspec")

    def test_msgspec_absent_raises_bounded_error_with_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from data_quality_toolkit.lineage.manifest.msgspec_impl import (
            MsgspecSerdeError,
            _import_msgspec,
        )

        monkeypatch.setitem(sys.modules, "msgspec", None)
        with pytest.raises(MsgspecSerdeError) as exc_info:
            _import_msgspec()
        msg = str(exc_info.value)
        assert "msgspec" in msg
        assert "pip install data-quality-toolkit[serde]" in msg
        assert exc_info.value.hint == msg

    def test_serializer_construction_surfaces_the_bounded_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from data_quality_toolkit.lineage.manifest.msgspec_impl import (
            MsgspecSerdeError,
            MsgspecSerializer,
        )

        monkeypatch.setitem(sys.modules, "msgspec", None)
        with pytest.raises(MsgspecSerdeError):
            MsgspecSerializer()

    def test_bounded_error_is_a_dqt_error_chained_to_the_import_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from data_quality_toolkit.lineage.manifest.msgspec_impl import (
            MsgspecSerdeError,
            _import_msgspec,
        )
        from data_quality_toolkit.shared.exceptions import DQTError

        monkeypatch.setitem(sys.modules, "msgspec", None)
        with pytest.raises(MsgspecSerdeError) as exc_info:
            _import_msgspec()
        assert isinstance(exc_info.value, DQTError)
        assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)

    def test_missing_dependency_inside_msgspec_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A nested missing module is real breakage, not an absent optional dep."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "msgspec":
                raise ModuleNotFoundError(
                    "No module named 'inner_dep_of_msgspec'", name="inner_dep_of_msgspec"
                )
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from data_quality_toolkit.lineage.manifest.msgspec_impl import _import_msgspec

        with pytest.raises(ModuleNotFoundError) as exc_info:
            _import_msgspec()
        assert exc_info.value.name == "inner_dep_of_msgspec"

    def test_non_module_import_error_inside_msgspec_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plain ImportError from an installed msgspec propagates unchanged."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "msgspec":
                raise ImportError("cannot import name 'json' from 'msgspec'")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from data_quality_toolkit.lineage.manifest.msgspec_impl import _import_msgspec

        with pytest.raises(ImportError) as exc_info:
            _import_msgspec()
        assert not isinstance(exc_info.value, ModuleNotFoundError)
        assert "msgspec is not installed" not in str(exc_info.value)


class TestSerdeExtraMetadata:
    """The optional serializer/writer backends are installable from metadata."""

    @staticmethod
    def _pyproject() -> dict:
        return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_serde_extra_declares_msgspec_and_orjson(self) -> None:
        extras = self._pyproject()["project"]["optional-dependencies"]
        assert "serde" in extras, "no [serde] extra declares the optional serde backends"
        names = [req.split(">")[0].split("=")[0].split("[")[0].strip() for req in extras["serde"]]
        assert "msgspec" in names
        assert "orjson" in names

    def test_serde_backends_are_never_mandatory(self) -> None:
        required = self._pyproject()["project"]["dependencies"]
        names = [req.split(">")[0].split("=")[0].split("[")[0].strip() for req in required]
        assert "msgspec" not in names
        assert "orjson" not in names

    def test_constraints_pin_the_serde_backends(self) -> None:
        text = (REPO_ROOT / "constraints.txt").read_text(encoding="utf-8")
        pins = [line.strip() for line in text.splitlines() if "==" in line]
        assert any(pin.startswith("msgspec==") for pin in pins)
        assert any(pin.startswith("orjson==") for pin in pins)

    def test_settings_values_selecting_the_backends_remain_valid(self) -> None:
        """SERDE_IMPL/JSON_WRITER still accept the values the extra installs for."""
        from data_quality_toolkit.shared.settings import Settings

        fields = Settings.model_fields
        assert "msgspec" in str(fields["serde_impl"].annotation)
        assert "orjson" in str(fields["json_writer"].annotation)


class TestDependencyDeclarationHygiene:
    """Only dependencies with a real runtime, tooling, or build role are declared.

    Each removed name had no import, fixture, marker, ini option, command-line
    flag, or build invocation anywhere in the repository. Re-adding one should
    arrive together with the code that uses it.
    """

    REMOVED_RUNTIME = ("jsonschema", "packaging", "typing-extensions")
    REMOVED_PYTEST_PLUGINS = ("pytest-xdist", "pytest-mock", "pytest-asyncio", "pytest-timeout")

    @staticmethod
    def _pyproject() -> dict:
        return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def _extras(self) -> dict[str, list[str]]:
        extras: dict[str, list[str]] = self._pyproject()["project"]["optional-dependencies"]
        return extras

    def test_unused_runtime_dependencies_are_not_mandatory(self) -> None:
        required = {_requirement_name(req) for req in self._pyproject()["project"]["dependencies"]}
        for name in self.REMOVED_RUNTIME:
            assert name not in required

    def test_unused_pytest_plugins_are_not_declared_by_any_extra(self) -> None:
        for extra, requirements in self._extras().items():
            names = {_requirement_name(req) for req in requirements}
            for plugin in self.REMOVED_PYTEST_PLUGINS:
                assert plugin not in names, f"[{extra}] still declares {plugin}"

    def test_sphinx_docs_extra_is_not_declared(self) -> None:
        assert "docs" not in self._extras()

    def test_viz_extra_declares_only_the_matplotlib_plot_backend(self) -> None:
        # Graphviz DOT output is plain text written by domain/semantics/graph_export.py;
        # the graphviz Python package is never imported.
        assert {_requirement_name(req) for req in self._extras()["viz"]} == {"matplotlib"}

    def test_every_extra_is_a_non_empty_list_of_requirements(self) -> None:
        for extra, requirements in self._extras().items():
            assert requirements, f"[{extra}] is empty"
            for req in requirements:
                assert _requirement_name(req)

    def test_serde_extra_is_unchanged(self) -> None:
        assert self._extras()["serde"] == ["msgspec>=0.20.0", "orjson>=3.11.7"]

    def test_console_entry_point_is_unchanged(self) -> None:
        scripts = self._pyproject()["project"]["scripts"]
        assert scripts == {"dqt": "data_quality_toolkit.adapters.cli.main:main"}

    def test_constraints_do_not_pin_removed_packages(self) -> None:
        text = (REPO_ROOT / "constraints.txt").read_text(encoding="utf-8")
        pinned = {_requirement_name(line) for line in text.splitlines() if "==" in line}
        for name in (*self.REMOVED_RUNTIME, *self.REMOVED_PYTEST_PLUGINS):
            assert name not in pinned

    def test_build_backend_requires_only_setuptools(self) -> None:
        """setuptools>=70.1 ships bdist_wheel itself, and `build` is a frontend."""
        build_system = self._pyproject()["build-system"]
        assert build_system["build-backend"] == "setuptools.build_meta"
        assert [_requirement_name(req) for req in build_system["requires"]] == ["setuptools"]

    def test_workflows_install_the_build_frontend_before_invoking_it(self) -> None:
        """`build` is not a backend requirement, so each caller installs it itself.

        No workflow is required to build: releases publish frozen, pre-built
        artifacts. The rule binds only the workflows that do invoke the frontend.
        """
        for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            if "python -m build" not in text:
                continue
            before = text.split("python -m build", 1)[0]
            assert re.search(r"pip install [^\n]*\bbuild\b", before), workflow.name

    def test_diagnostics_probes_only_declared_optional_dependencies(self) -> None:
        from data_quality_toolkit.adapters.ui.services.diagnostics import (
            collect_capability_snapshot,
        )

        declared = {_requirement_name(req) for reqs in self._extras().values() for req in reqs}
        probed = set(collect_capability_snapshot())
        assert "graphviz" not in probed
        assert probed <= declared


class TestConfigTargetAndToolPinAlignment:
    """Tool configuration names live targets, and each tool runs at one version.

    CI runs the constrained tools directly and then again through pre-commit, so a
    hook ``rev`` that differs from constraints.txt lets two versions of the same
    tool judge one tree. Configuration that names a missing path silently does
    nothing, which is how a stale target survives a restructure.
    """

    # pre-commit repository -> constraints.txt distribution it must match
    PRE_COMMIT_TOOLS = {
        "https://github.com/psf/black": "black",
        "https://github.com/PyCQA/isort": "isort",
        "https://github.com/astral-sh/ruff-pre-commit": "ruff",
        "https://github.com/pre-commit/mirrors-mypy": "mypy",
    }

    @staticmethod
    def _pyproject() -> dict:
        return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    @staticmethod
    def _pins() -> dict[str, str]:
        text = (REPO_ROOT / "constraints.txt").read_text(encoding="utf-8")
        pins: dict[str, str] = {}
        for line in text.splitlines():
            if "==" in line and not line.lstrip().startswith("#"):
                name, version = line.split("==", 1)
                pins[_requirement_name(name)] = version.strip()
        return pins

    @staticmethod
    def _pre_commit_repos() -> list[dict]:
        text = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        repos: list[dict] = yaml.safe_load(text)["repos"]
        return repos

    def _package_data(self) -> list[str]:
        patterns: list[str] = self._pyproject()["tool"]["setuptools"]["package-data"][
            "data_quality_toolkit"
        ]
        return patterns

    def test_ruff_per_file_ignores_target_existing_paths(self) -> None:
        ignores = self._pyproject()["tool"]["ruff"]["lint"]["per-file-ignores"]
        for pattern in ignores:
            assert any(REPO_ROOT.glob(pattern)), f"per-file-ignore {pattern!r} matches nothing"

    def test_every_package_data_pattern_ships_a_file(self) -> None:
        package = REPO_ROOT / "src" / "data_quality_toolkit"
        for pattern in self._package_data():
            shipped = [path for path in package.glob(pattern) if path.is_file()]
            assert shipped, f"package-data pattern {pattern!r} matches no package file"

    def test_required_package_data_stays_declared(self) -> None:
        patterns = self._package_data()
        assert "adapters/exporters/bi/templates/*" in patterns  # Power BI template assets
        assert "py.typed" in patterns  # PEP 561 marker

    def test_coverage_does_not_omit_a_nonexistent_static_tree(self) -> None:
        omit = self._pyproject()["tool"]["coverage"]["run"]["omit"]
        assert "*/static/*" not in omit
        for kept in ("*/tests/*", "*/__init__.py", "*/templates/*"):
            assert kept in omit

    def test_pre_commit_tool_revs_match_constraints(self) -> None:
        pins = self._pins()
        repos = self._pre_commit_repos()
        revs = {repo["repo"]: str(repo["rev"]) for repo in repos if "rev" in repo}
        for url, tool in self.PRE_COMMIT_TOOLS.items():
            assert url in revs, f"pre-commit no longer configures {url}"
            hook_version = revs[url].removeprefix("v")
            assert hook_version == pins[tool], f"{tool}: hook {revs[url]} vs {pins[tool]}"

    def test_focused_pytest_hook_does_not_undercut_the_project_floor(self) -> None:
        project = next(
            req
            for req in self._pyproject()["project"]["dependencies"]
            if _requirement_name(req) == "pydantic-settings"
        )
        hook = next(
            hook
            for repo in self._pre_commit_repos()
            for hook in repo["hooks"]
            if hook["id"] == "pytest-focused"
        )
        hook_req = next(
            req
            for req in hook["additional_dependencies"]
            if _requirement_name(req) == "pydantic-settings"
        )
        assert _minimum_version(hook_req) >= _minimum_version(project)

    def test_ci_architecture_and_ui_tools_are_pinned(self) -> None:
        """import-linter gates CI and streamlit arrives through the [ui] extra CI installs."""
        pins = self._pins()
        extras = self._pyproject()["project"]["optional-dependencies"]
        for name, extra in (("import-linter", "dev"), ("streamlit", "ui")):
            assert name in pins, f"constraints.txt does not pin {name}"
            declared = next(req for req in extras[extra] if _requirement_name(req) == name)
            assert _release_tuple(pins[name]) >= _minimum_version(declared)

    def test_build_system_requires_is_unchanged(self) -> None:
        assert self._pyproject()["build-system"]["requires"] == ["setuptools>=71.0"]
