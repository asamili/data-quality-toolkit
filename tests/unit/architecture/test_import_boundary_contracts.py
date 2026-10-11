"""Architecture import-boundary contracts (whole-package layer hardening).

``pyproject.toml`` is the single enforcement mechanism for layer direction in
this repository; these tests are its regression net. They do two things the
linter run itself cannot do:

1. Pin the *shape* of the whole-package contracts, so a later edit cannot quietly narrow
   them back to an enumerated subpackage list or bolt an ignore list onto them.
2. Prove each contract actually rejects a prohibited dependency, by replaying
   the contract shapes read straight out of ``pyproject.toml`` against a
   synthetic fixture package built in ``tmp_path``. No production module is
   mutated, and the fixture never enters the real import graph.

The negative proofs are derived from the shipped configuration rather than from
a hand-copied duplicate, so a contract that is weakened in ``pyproject.toml``
weakens here too and the corresponding proof fails.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
FIXTURE_PACKAGE = "layer_arch_fixture"

DOMAIN_CONTRACT = "Domain must not import adapters, application, lineage, or the public API seam"
SHARED_CONTRACT = "Shared kernel must not import any business module"
UI_LAYERS_CONTRACT = (
    "UI presentation must depend on the ui/services application tier, never the reverse"
)
STREAMLIT_CONTRACT = "Streamlit must not reach below the presentation layer"
BACKEND_CONTRACT = "Backend layers must not import the CLI or UI delivery surfaces"

LAYER_CONTRACTS = (
    DOMAIN_CONTRACT,
    SHARED_CONTRACT,
    UI_LAYERS_CONTRACT,
    STREAMLIT_CONTRACT,
    BACKEND_CONTRACT,
)

# The domain contract exactly as it stood before widening. Kept as the historical
# baseline for one test only: it is what proves the widened rule is a genuine
# strengthening rather than a rename.
LEGACY_DOMAIN_FORBIDDEN = (
    "adapters.loaders",
    "adapters.exporters",
    "adapters.storage",
    "adapters.cli",
    "adapters.ui",
    "application.workflow",
    "api",
)

# Runs the linter the same way CI does, but against a throwaway config.
_LINT_RUNNER = """
import sys
from importlinter.cli import lint_imports
sys.exit(lint_imports(config_filename=sys.argv[1], no_cache=True))
"""


def _load_contracts() -> list[dict[str, Any]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(data["tool"]["importlinter"]["contracts"])


def _session_options() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    options = dict(data["tool"]["importlinter"])
    options.pop("contracts", None)
    return options


def _contract(name: str) -> dict[str, Any]:
    matches = [c for c in _load_contracts() if c.get("name") == name]
    assert len(matches) == 1, f"expected exactly one contract named {name!r}, got {len(matches)}"
    return matches[0]


# --- A. The contracts are declared, and declared in their strengthened shape ---


def test_every_layer_contract_is_declared() -> None:
    declared = {c.get("name") for c in _load_contracts()}
    assert set(LAYER_CONTRACTS) <= declared


def test_external_packages_are_graphed() -> None:
    """The Streamlit contract is meaningless unless external imports are graphed."""
    assert _session_options().get("include_external_packages") is True


@pytest.mark.parametrize("name", LAYER_CONTRACTS)
def test_layer_contract_carries_no_ignore_list(name: str) -> None:
    """None of these rules is held green by an exception."""
    assert _contract(name).get("ignore_imports", []) == []


def test_domain_contract_names_package_roots_not_subpackages() -> None:
    """The enumerated form is what let adapters.reports and lineage slip through."""
    contract = _contract(DOMAIN_CONTRACT)
    assert contract["source_modules"] == ["data_quality_toolkit.domain"]
    assert set(contract["forbidden_modules"]) == {
        "data_quality_toolkit.adapters",
        "data_quality_toolkit.application",
        "data_quality_toolkit.lineage",
        "data_quality_toolkit.api",
    }


def test_shared_kernel_contract_names_package_roots_not_subpackages() -> None:
    contract = _contract(SHARED_CONTRACT)
    assert set(contract["source_modules"]) == {
        "data_quality_toolkit.shared",
        "data_quality_toolkit.utils",
    }
    assert set(contract["forbidden_modules"]) == {
        "data_quality_toolkit.domain",
        "data_quality_toolkit.adapters",
        "data_quality_toolkit.application",
        "data_quality_toolkit.lineage",
        "data_quality_toolkit.api",
    }


def test_ui_layer_order_puts_services_below_presentation() -> None:
    """adapters/ui/services is the application tier and stays the lowest UI layer."""
    contract = _contract(UI_LAYERS_CONTRACT)
    assert contract["type"] == "layers"
    assert contract["layers"] == [
        "data_quality_toolkit.adapters.ui.app",
        "data_quality_toolkit.adapters.ui.pages",
        "data_quality_toolkit.adapters.ui.components",
        "data_quality_toolkit.adapters.ui.services",
    ]


def test_streamlit_contract_covers_the_application_tier_but_not_the_render_surface() -> None:
    contract = _contract(STREAMLIT_CONTRACT)
    sources = set(contract["source_modules"])
    assert contract["forbidden_modules"] == ["streamlit"]
    assert "data_quality_toolkit.adapters.ui.services" in sources
    # The render surface and the CLI's subprocess launcher legitimately use it.
    assert "data_quality_toolkit.adapters.ui.pages" not in sources
    assert "data_quality_toolkit.adapters.ui.app" not in sources
    assert "data_quality_toolkit.adapters.cli" not in sources


def test_backend_contract_forbids_both_delivery_surfaces() -> None:
    contract = _contract(BACKEND_CONTRACT)
    assert set(contract["forbidden_modules"]) == {
        "data_quality_toolkit.adapters.cli",
        "data_quality_toolkit.adapters.ui",
    }
    assert "data_quality_toolkit.application" in contract["source_modules"]
    assert "data_quality_toolkit.api" in contract["source_modules"]


# --- B. Fixture-package machinery for the negative proofs -------------------------


def _rebase(module: str) -> str:
    """Rewrite a real module path onto the throwaway fixture package."""
    if module == "data_quality_toolkit":
        return FIXTURE_PACKAGE
    if module.startswith("data_quality_toolkit."):
        return FIXTURE_PACKAGE + module[len("data_quality_toolkit") :]
    return module  # external package, e.g. streamlit


def _rebased_contract(name: str) -> dict[str, Any]:
    contract = dict(_contract(name))
    for key in ("source_modules", "forbidden_modules", "layers"):
        if key in contract:
            contract[key] = [_rebase(m) for m in contract[key]]
    return contract


def _write_config(directory: Path, contracts: list[dict[str, Any]]) -> Path:
    lines = [
        "[tool.importlinter]",
        f'root_packages = ["{FIXTURE_PACKAGE}"]',
        "include_external_packages = true",
    ]
    for contract in contracts:
        lines.append("")
        lines.append("[[tool.importlinter.contracts]]")
        for key, value in contract.items():
            lines.append(f"{key} = {json.dumps(value)}")
    path = directory / "arch_contracts.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_package(directory: Path, imports: dict[str, list[str]]) -> None:
    """Materialise a package whose only content is the given import edges."""
    modules = set(imports)
    # Every ancestor package has to exist for grimp to walk the tree.
    for module in list(modules):
        parts = module.split(".")
        for depth in range(1, len(parts)):
            modules.add(".".join(parts[:depth]))
    modules.add(FIXTURE_PACKAGE)

    leaves = {m for m in modules if not any(o.startswith(m + ".") for o in modules)}
    for module in sorted(modules):
        parts = module.split(".")
        if module in leaves and module != FIXTURE_PACKAGE:
            path = directory.joinpath(*parts[:-1]) / f"{parts[-1]}.py"
        else:
            path = directory.joinpath(*parts) / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(f"import {target}\n" for target in imports.get(module, []))
        path.write_text(body, encoding="utf-8")


def _lint(tmp_path: Path, imports: dict[str, list[str]], contracts: list[dict[str, Any]]) -> str:
    """Run import-linter over a fixture package and return its report text."""
    root = tmp_path / "pkgroot"
    root.mkdir(exist_ok=True)
    _write_package(root, imports)
    config = _write_config(tmp_path, contracts)
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths from tmp_path
        [sys.executable, "-c", _LINT_RUNNER, str(config)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(tmp_path),
        env={**_clean_env(), "PYTHONPATH": str(root)},
    )
    return completed.stdout + completed.stderr


def _clean_env() -> dict[str, str]:
    """Subprocess environment: no inherited PYTHONPATH, no bytecode, no line wrapping."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["COLUMNS"] = "200"
    env["TERM"] = "dumb"
    return env


def _broken_contract_names(report: str, candidates: tuple[str, ...]) -> set[str]:
    """Return which of ``candidates`` the report marks BROKEN.

    Contract names wrap across lines in the linter's output, so the summary line
    is matched on collapsed whitespace rather than read verbatim.
    """
    collapsed = " ".join(report.split())
    return {name for name in candidates if f"{name} BROKEN" in collapsed}


# A dependency graph that respects every contract: presentation depends downward
# on the services tier, backends depend on nothing above them.
COMPLIANT_IMPORTS: dict[str, list[str]] = {
    f"{FIXTURE_PACKAGE}.domain.statistics": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.shared": [],
    f"{FIXTURE_PACKAGE}.utils": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.lineage": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.application.workflow": [f"{FIXTURE_PACKAGE}.domain.statistics"],
    f"{FIXTURE_PACKAGE}.api": [f"{FIXTURE_PACKAGE}.application.workflow"],
    f"{FIXTURE_PACKAGE}.adapters.loaders": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.adapters.exporters": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.adapters.storage": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.adapters.reports": [f"{FIXTURE_PACKAGE}.api"],
    f"{FIXTURE_PACKAGE}.adapters.notifications": [f"{FIXTURE_PACKAGE}.shared"],
    f"{FIXTURE_PACKAGE}.adapters.cli.commands": [f"{FIXTURE_PACKAGE}.api"],
    f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment": [f"{FIXTURE_PACKAGE}.api"],
    f"{FIXTURE_PACKAGE}.adapters.ui.state": [f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment"],
    f"{FIXTURE_PACKAGE}.adapters.ui.components.page_shell": [
        f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment"
    ],
    f"{FIXTURE_PACKAGE}.adapters.ui.pages.data_overview": [
        "streamlit",
        f"{FIXTURE_PACKAGE}.adapters.ui.components.page_shell",
        f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment",
    ],
    f"{FIXTURE_PACKAGE}.adapters.ui.app": [
        "streamlit",
        f"{FIXTURE_PACKAGE}.adapters.ui.pages.data_overview",
    ],
}


def _with(extra: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {module: list(targets) for module, targets in COMPLIANT_IMPORTS.items()}
    for module, targets in extra.items():
        merged.setdefault(module, [])
        merged[module] = merged[module] + list(targets)
    return merged


# --- C. Negative proofs: each contract rejects a representative violation ---------


def test_compliant_fixture_keeps_every_contract(tmp_path: Path) -> None:
    """Control case: the proofs below only mean something if this one is clean."""
    report = _lint(tmp_path, COMPLIANT_IMPORTS, [_rebased_contract(n) for n in LAYER_CONTRACTS])
    assert "Contracts: 5 kept, 0 broken." in report, report


# Each case names every contract the added edge is expected to break. Forbidden
# contracts follow indirect chains, so a single edge can legitimately break more
# than one rule; the expected set is stated in full rather than loosened to a
# membership check, so an over-broad contract shows up as a failure here.
VIOLATIONS: list[tuple[str, set[str], dict[str, list[str]]]] = [
    (
        # adapters.notifications post-dates the legacy enumerated forbidden list.
        "domain-imports-a-late-added-adapter",
        {DOMAIN_CONTRACT},
        {f"{FIXTURE_PACKAGE}.domain.statistics": [f"{FIXTURE_PACKAGE}.adapters.notifications"]},
    ),
    (
        "domain-imports-lineage",
        {DOMAIN_CONTRACT},
        {f"{FIXTURE_PACKAGE}.domain.statistics": [f"{FIXTURE_PACKAGE}.lineage"]},
    ),
    (
        "shared-kernel-imports-lineage",
        {SHARED_CONTRACT},
        {f"{FIXTURE_PACKAGE}.utils": [f"{FIXTURE_PACKAGE}.lineage"]},
    ),
    (
        # Also breaks the Streamlit rule: the services tier now reaches streamlit
        # transitively through the page it imported.
        "services-tier-imports-a-page",
        {UI_LAYERS_CONTRACT, STREAMLIT_CONTRACT},
        {
            f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment": [
                f"{FIXTURE_PACKAGE}.adapters.ui.pages.data_overview"
            ]
        },
    ),
    (
        "services-tier-imports-streamlit",
        {STREAMLIT_CONTRACT},
        {f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment": ["streamlit"]},
    ),
    (
        "domain-imports-streamlit",
        {STREAMLIT_CONTRACT},
        {f"{FIXTURE_PACKAGE}.domain.statistics": ["streamlit"]},
    ),
    (
        "application-imports-the-cli",
        {BACKEND_CONTRACT},
        {f"{FIXTURE_PACKAGE}.application.workflow": [f"{FIXTURE_PACKAGE}.adapters.cli.commands"]},
    ),
    (
        "storage-adapter-imports-the-ui",
        {BACKEND_CONTRACT},
        {
            f"{FIXTURE_PACKAGE}.adapters.storage": [
                f"{FIXTURE_PACKAGE}.adapters.ui.services.assessment"
            ]
        },
    ),
]


@pytest.mark.parametrize(
    ("expected_broken", "extra_imports"),
    [(contracts, extra) for _, contracts, extra in VIOLATIONS],
    ids=[case_id for case_id, _, _ in VIOLATIONS],
)
def test_prohibited_dependency_breaks_its_contract(
    tmp_path: Path, expected_broken: set[str], extra_imports: dict[str, list[str]]
) -> None:
    report = _lint(tmp_path, _with(extra_imports), [_rebased_contract(n) for n in LAYER_CONTRACTS])
    assert _broken_contract_names(report, LAYER_CONTRACTS) == expected_broken, report


def test_legacy_domain_shape_would_have_missed_the_late_added_adapter(tmp_path: Path) -> None:
    """The widening is real: the old enumerated list never named adapters.notifications.

    Same fixture, same violating import, only the contract shape differs.
    """
    legacy = {
        "name": "legacy domain contract (historical shape)",
        "type": "forbidden",
        "source_modules": [f"{FIXTURE_PACKAGE}.domain.statistics"],
        "forbidden_modules": [f"{FIXTURE_PACKAGE}.{m}" for m in LEGACY_DOMAIN_FORBIDDEN],
    }
    violating = _with(
        {f"{FIXTURE_PACKAGE}.domain.statistics": [f"{FIXTURE_PACKAGE}.adapters.notifications"]}
    )

    legacy_report = _lint(tmp_path, violating, [legacy])
    assert "Contracts: 1 kept, 0 broken." in legacy_report, legacy_report

    current_report = _lint(tmp_path, violating, [_rebased_contract(DOMAIN_CONTRACT)])
    assert "Contracts: 0 kept, 1 broken." in current_report, current_report
