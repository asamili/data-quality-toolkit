# src/data_quality_toolkit/adapters/cli/commands/__init__.py
"""CLI command modules.

Each module owns one or more ``dqt`` subcommands. A module exposes:

* one or more ``register*(subparsers)`` functions that wire its argparse
  subparser(s), and
* the ``cmd_*`` handler(s) those subparsers dispatch to.

Handlers resolve test-monkeypatched names (proxies and shared helpers such as
``run_drift`` / ``_safe_text``) through the ``adapters.cli.main`` module at call
time, so existing tests that patch ``cli.main.<name>`` keep working after the
split.
"""
