"""``hermes subagent`` model and reasoning parser.

Wired from ``hermes_cli/main.py``.  Provides the shell-facing entry point
for subagent model selection:

    hermes subagent                       # status
    hermes subagent model                 # interactive picker
    hermes subagent model <model>         # validated direct selection
    hermes subagent model reset           # inherit parent
    hermes subagent model --reset         # inherit parent (flag form)
    hermes subagent reasoning high        # fixed child reasoning effort
    hermes subagent reasoning reset       # inherit parent reasoning
"""

from __future__ import annotations

import sys
from typing import Callable


def build_subagent_parser(subparsers, *, cmd_subagent: Callable) -> None:
    """Attach the ``subagent`` subcommand to ``subparsers``."""
    subagent_parser = subparsers.add_parser(
        "subagent",
        help="Inspect or configure the subagent model and reasoning",
        description=(
            "Show the current subagent model selection.  When no override "
            "is configured, subagents inherit the parent model."
        ),
    )
    subparsers_sub = subagent_parser.add_subparsers(dest="subagent_command")

    # subagent (no subcommand) → status
    subagent_parser.set_defaults(func=cmd_subagent)

    # subagent model → status / select / reset
    model_parser = subparsers_sub.add_parser(
        "model",
        help="Select or reset the subagent model",
        description=(
            "Pin all subagents to a specific model, or reset to inherit "
            "the parent model. With no model argument, opens the complete "
            "`hermes model` provider setup flow, including login and custom "
            "endpoint creation. Shared provider additions are retained while "
            "the active primary model remains unchanged. The delegation "
            "provider/model is read on every child spawn — no restart needed."
        ),
    )
    model_parser.add_argument(
        "model",
        nargs="?",
        help="Model to pin, or 'reset' to inherit the parent model",
    )
    model_parser.add_argument(
        "--provider",
        default=None,
        help="Provider to route subagents through (e.g. 'openrouter', 'nous')",
    )
    model_parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove the subagent model/provider override (inherit parent)",
    )
    model_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh provider model catalogs before opening the full setup picker",
    )
    model_parser.set_defaults(func=cmd_subagent)

    reasoning_parser = subparsers_sub.add_parser(
        "reasoning",
        help="Inspect, set, or reset subagent reasoning effort",
        description=(
            "Set the reasoning effort used by newly spawned subagents. "
            "Without an override, children inherit the parent agent's "
            "reasoning configuration. Changes are read on every child spawn."
        ),
    )
    reasoning_parser.add_argument(
        "effort",
        nargs="?",
        help="none|minimal|low|medium|high|xhigh|max|ultra, or 'reset'",
    )
    reasoning_parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove the subagent reasoning override (inherit parent)",
    )
    reasoning_parser.set_defaults(func=cmd_subagent)


def cmd_subagent(args):
    """Inspect or configure the subagent model and reasoning."""
    from hermes_cli.main import _require_tty
    from hermes_cli.subagent_model import (
        get_subagent_model_status,
        get_subagent_reasoning_status,
        reset_subagent_model,
        reset_subagent_reasoning_effort,
        select_subagent_model_interactively,
        set_subagent_model,
        set_subagent_reasoning_effort,
    )

    sub = getattr(args, "subagent_command", None)
    if sub in {None, ""}:
        _print_subagent_status(get_subagent_model_status())
        _print_subagent_reasoning_status(get_subagent_reasoning_status())
        return

    if sub == "model":
        model_arg = getattr(args, "model", None)
        positional_reset = (
            isinstance(model_arg, str) and model_arg.strip().lower() == "reset"
        )
        if getattr(args, "reset", False) or positional_reset:
            _print_subagent_status(reset_subagent_model(), action="Reset")
            return
        if model_arg:
            try:
                status = set_subagent_model(
                    model_arg,
                    provider=getattr(args, "provider", None) or None,
                )
            except ValueError as exc:
                print(f"  ✗ {exc}", file=sys.stderr)
                return 2
            _print_subagent_status(status, action="Pinned")
            return
        _require_tty("subagent model")
        status = select_subagent_model_interactively(
            refresh=bool(getattr(args, "refresh", False)),
            initial_provider=getattr(args, "provider", None) or None,
        )
        if status is None:
            print("  Subagent model selection cancelled.")
            return
        _print_subagent_status(status, action="Selected")
        return

    if sub == "reasoning":
        effort_arg = getattr(args, "effort", None)
        positional_reset = (
            isinstance(effort_arg, str)
            and effort_arg.strip().lower() in {"clear", "default", "inherit", "reset"}
        )
        if getattr(args, "reset", False) or positional_reset:
            _print_subagent_reasoning_status(
                reset_subagent_reasoning_effort(), action="Reset"
            )
            return
        if effort_arg:
            try:
                status = set_subagent_reasoning_effort(effort_arg)
            except ValueError as exc:
                print(f"  ✗ {exc}", file=sys.stderr)
                return 2
            _print_subagent_reasoning_status(status, action="Set")
            return
        _print_subagent_reasoning_status(get_subagent_reasoning_status())
        return

    print(
        "usage: hermes subagent "
        "[model [<model>|--reset|--refresh] | reasoning [<effort>|--reset]]"
    )



def _print_subagent_status(status, action=None):
    if status.inherits_parent:
        label = "inherits parent"
    elif status.model:
        label = status.model
        if status.provider:
            label = f"{label} (provider: {status.provider})"
    else:
        label = f"provider default (provider: {status.provider})"
    prefix = f"{action} " if action else ""
    print(f"  {prefix}subagent model: {label}")



def _print_subagent_reasoning_status(status, action=None):
    label = "inherits parent" if status.inherits_parent else (status.effort or "(none)")
    prefix = f"{action} " if action else ""
    print(f"  {prefix}subagent reasoning: {label}")
