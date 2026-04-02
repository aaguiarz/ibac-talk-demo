#!/usr/bin/env python3
"""CLI frontend for the MCP authorization agent.

Thin shell over authz_flow — handles terminal I/O, readline,
elicitation prompts, and CLI argument parsing.

Logging levels (set via LOG_LEVEL env var or --verbose flag):
  default  — clean agent UI: user prompts, agent responses, permission requests
  verbose  — adds planning details, tool calls, grant info
  debug    — adds raw elicitation types, JSON payloads, MCP internals
"""

from __future__ import annotations
import asyncio
import logging
import os
import readline
import sys
import uuid
from enum import IntEnum
from typing import Any

from anthropic import AsyncAnthropic
from fastmcp import Client
from openfga_sdk import OpenFgaClient
from openfga_sdk.client.models import ClientTuple
from openfga_sdk.exceptions import FgaValidationException, ValidationException

from authz_flow import (
    PermissionDeniedError,
    ResolutionError,
    UnauthorizedToolError,
    cleanup_fga_after_task,
    get_server_script,
    init_fga_client,
    run_authz_pipeline,
    suggest_resource_names,
    PROJECT_ROOT,
)
from utils import load_env

# ---------------------------------------------------------------------------
# CLI-specific state
# ---------------------------------------------------------------------------


class LogLevel(IntEnum):
    DEFAULT = 0
    VERBOSE = 1
    DEBUG = 2


_log_level = LogLevel.DEFAULT
_auto_approve = False
_fga_client: OpenFgaClient | None = None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging(level: LogLevel) -> None:
    """Suppress all library logging unless in debug mode."""
    if level < LogLevel.DEBUG:
        logging.disable(logging.CRITICAL)
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(logging.NullHandler())
        for name in ("fastmcp", "mcp", "httpx", "anthropic", "asyncio"):
            lgr = logging.getLogger(name)
            lgr.handlers.clear()
            lgr.addHandler(logging.NullHandler())
            lgr.propagate = False


def _write(msg: str) -> None:
    """Write to stderr (avoids STDIO transport on stdout)."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def log(msg: str, level: LogLevel = LogLevel.DEFAULT) -> None:
    """Log a message if the current log level is high enough."""
    if level <= _log_level:
        _write(msg)


# ---------------------------------------------------------------------------
# CLI agent loop callbacks
# ---------------------------------------------------------------------------


class CLIAgentLoopCallbacks:
    """Implements AgentLoopCallbacks with CLI log() calls."""

    async def on_text(self, text: str, done: bool) -> None:
        if text:
            log(f"\n{text}" if not done else text)

    async def on_tool_start(self, call_id: str, tool: str, args: dict[str, Any]) -> None:
        log(f"\n  [TOOL CALL] {tool}({args!r})", LogLevel.VERBOSE)

    async def on_tool_end(self, call_id: str, tool: str, result: str | None, error: str | None) -> None:
        if error:
            log(f"  [TOOL ERROR] {error!r}", LogLevel.VERBOSE)
        elif result:
            log(
                f"  [TOOL RESULT] {result[:300]}{'...' if len(result) > 300 else ''}",
                LogLevel.VERBOSE,
            )

    async def on_unauthorized(self, tool: str, error: str) -> None:
        log(f"\n{error}")

    async def on_turn_complete(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Anthropic client (global singleton for CLI)
# ---------------------------------------------------------------------------

anthropic_client: AsyncAnthropic | None = None


def _get_anthropic_client() -> AsyncAnthropic:
    """Return the Anthropic client, creating it on first use."""
    global anthropic_client
    if anthropic_client is None:
        anthropic_client = AsyncAnthropic(
            base_url="https://api.anthropic.com",
            max_retries=3,
        )
    return anthropic_client


# ---------------------------------------------------------------------------
# Elicitation handler — presents server prompts to the user in the terminal
# ---------------------------------------------------------------------------


def _setup_readline() -> None:
    """Seed readline history with default prompts."""
    readline.add_history(
        "Summarize the MCP Dev Talk project and post it to #private-team-channel"
    )


def _tty_prompt(prompt: str, keep_history: bool = True) -> str:
    """Read user input with readline support, falling back to stdin if no TTY."""
    sys.stderr.write(prompt)
    sys.stderr.flush()

    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.strip()

    saved_in = os.dup(0)
    saved_out = os.dup(1)
    os.dup2(tty_fd, 0)
    os.dup2(tty_fd, 1)
    os.close(tty_fd)
    try:
        line = input()
        if not keep_history:
            length = readline.get_current_history_length()
            if length > 0:
                readline.remove_history_item(length - 1)
        return line.strip()
    finally:
        os.dup2(saved_in, 0)
        os.dup2(saved_out, 1)
        os.close(saved_in)
        os.close(saved_out)


async def handle_elicitation(
    message: str, response_type: Any, params: Any, context: Any
) -> dict[str, Any]:
    """Handle server elicitation requests by prompting the user."""
    log("  [ELICITATION] Server requesting user input...", LogLevel.DEBUG)
    _write(f"\n{'=' * 60}")
    _write(f"  {message}")
    _write(f"{'=' * 60}")

    if isinstance(response_type, list):
        for i, option in enumerate(response_type, 1):
            _write(f"  {i}. {option}")
        _write("")
        while True:
            choice = await asyncio.to_thread(_tty_prompt, "  > ", False)
            if not choice:
                continue
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(response_type):
                    return {"value": response_type[idx]}
            except ValueError:
                pass
            for option in response_type:
                if choice.casefold() == option.casefold():
                    return {"value": option}
            _write(f"  Please enter a number (1-{len(response_type)}).")

    if isinstance(response_type, type) and hasattr(
        response_type, "__dataclass_fields__"
    ):
        result: dict[str, str | bool] = {}
        for field_name, field_info in response_type.__dataclass_fields__.items():
            field_type = field_info.type
            options = None
            if hasattr(field_type, "__args__"):
                options = list(field_type.__args__)
            if options:
                for i, opt in enumerate(options, 1):
                    _write(f"  {i}. {opt}")
                _write("")
                while True:
                    value = await asyncio.to_thread(
                        _tty_prompt, f"  {field_name} > ", False
                    )
                    if not value:
                        continue
                    try:
                        idx = int(value) - 1
                        if 0 <= idx < len(options):
                            value = str(options[idx])
                            break
                    except ValueError:
                        pass
                    matched = False
                    for opt in options:
                        if value.casefold() == str(opt).casefold():
                            value = str(opt)
                            matched = True
                            break
                    if matched:
                        break
                    _write(f"  Please enter a number (1-{len(options)}).")
            else:
                value = await asyncio.to_thread(_tty_prompt, f"  {field_name}: ", False)
            if field_info.type is bool:
                result[field_name] = value.lower() in ("yes", "true", "y", "1")
            else:
                result[field_name] = value
        return result

    user_input = await asyncio.to_thread(_tty_prompt, "  > ", False)
    log(f"[DEBUG] Returning fallback: {{'value': {user_input!r}}}", LogLevel.DEBUG)
    return {"value": user_input}


async def handle_elicitation_auto(
    message: str, response_type: Any, params: Any, context: Any
) -> None:
    """Abort in --auto mode — elicitation means the tool wasn't pre-authorized."""
    raise UnauthorizedToolError(
        f"The agent tried to use a tool that was not pre-authorized.\n"
        f"  Server asked: {message}\n"
        f"  The agent was stopped before taking any unauthorized action."
    )


# ---------------------------------------------------------------------------
# CLI-specific resolution helper
# ---------------------------------------------------------------------------


class CLIPermissionApprover:
    """Prompts the user to approve planned permissions in the terminal."""

    async def approve(self, permissions: list[str], phase: str) -> bool:
        _write(f"\n{'=' * 60}")
        _write(f"  The agent needs these permissions ({phase}):\n")
        for perm in permissions:
            tool_name, resource = perm.split(":", 1) if ":" in perm else (perm, "*")
            if resource == "*":
                _write(f"    - {tool_name}")
            else:
                _write(f"    - {tool_name} on {resource}")
        _write(f"\n{'=' * 60}")
        _write("  1. Approve")
        _write("  2. Deny")
        _write("")
        while True:
            choice = await asyncio.to_thread(_tty_prompt, "  > ", False)
            if choice in ("1", "approve", "y", "yes"):
                return True
            if choice in ("2", "deny", "n", "no"):
                _write("  Permission denied.")
                return False


def _log_resolution_error(exc: ResolutionError) -> None:
    """Log suggestions for unresolved action permissions."""
    log(
        "  Could not resolve: " + ", ".join(exc.unresolved),
        LogLevel.VERBOSE,
    )
    suggestions: dict[str, list[str]] = {}
    known_display_names = list(exc.name_to_id.keys())
    for perm in exc.unresolved:
        _tool_name, resource = perm.split(":", 1) if ":" in perm else (perm, "")
        matches = suggest_resource_names(resource, known_display_names)
        if matches:
            suggestions[resource] = matches

    if suggestions:
        lines = [
            "I couldn't safely figure out one of the names in your request, so I stopped here before doing anything else.",
        ]
        for resource, matches in suggestions.items():
            lines.append(f'\nI couldn\'t find an exact match for "{resource}".')
            lines.append("Did you mean:")
            for match in matches:
                lines.append(f"- {match}")
        lines.append("\nPlease try again using the exact name.")
        log("\n".join(lines))
    else:
        log(
            "I couldn't safely figure out one of the names in your request, "
            "so I stopped here before doing anything else. Please try again "
            "using the exact name.",
        )


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _parse_args() -> tuple[LogLevel, bool, str]:
    """Parse CLI arguments, return (log_level, auto_approve, user_prompt)."""
    args = sys.argv[1:]
    log_level = LogLevel.DEFAULT

    if "--verbose" in args:
        log_level = LogLevel.VERBOSE
        args.remove("--verbose")
    elif "--debug" in args:
        log_level = LogLevel.DEBUG
        args.remove("--debug")
    else:
        env_level = os.environ.get("LOG_LEVEL", "").lower()
        if env_level == "verbose":
            log_level = LogLevel.VERBOSE
        elif env_level == "debug":
            log_level = LogLevel.DEBUG

    auto_approve = "--auto" in args
    if auto_approve:
        args.remove("--auto")

    user_prompt = " ".join(args) if args else ""
    return log_level, auto_approve, user_prompt


async def handle_prompt(
    mcp_client: Client,
    planner_tools: list[Any],
    agent_tools: list[Any],
    user_prompt: str,
    task_id: str,
) -> None:
    """Handle a single user prompt: plan -> discover -> authorize -> execute."""
    fga_tuples: list[ClientTuple] = []

    try:
        fga_tuples = await run_authz_pipeline(
            mcp_client, planner_tools, agent_tools, user_prompt, task_id,
            _get_anthropic_client(), CLIAgentLoopCallbacks(),
            autonomous=_auto_approve,
            fga_client=_fga_client,
            approver=None if _auto_approve else CLIPermissionApprover(),
        )
    except PermissionDeniedError:
        return
    except ResolutionError as exc:
        _log_resolution_error(exc)
    except RuntimeError as exc:
        log(f"\nError: {exc}")
    finally:
        try:
            await cleanup_fga_after_task(_fga_client, task_id, fga_tuples)
        except (ValidationException, FgaValidationException, RuntimeError, OSError) as exc:
            log(f"  Cleanup failed: {exc!r}", LogLevel.DEFAULT)


async def main() -> None:
    global _log_level, _auto_approve, _fga_client

    load_env(os.path.join(PROJECT_ROOT, ".env"))
    os.environ.pop("ANTHROPIC_BASE_URL", None)
    os.environ.pop("ANTHROPIC_HOST", None)

    _log_level, _auto_approve, user_prompt = _parse_args()

    if _auto_approve and not user_prompt:
        _write("Error: --auto requires a prompt argument.")
        _write("Usage: python agent.py --auto \"Your prompt here\"")
        sys.exit(1)

    _configure_logging(_log_level)

    _fga_client = init_fga_client()
    if _fga_client is None:
        _write("Error: OpenFGA configuration required (set FGA_STORE_ID in .env and ensure OpenFGA is running).")
        sys.exit(1)

    server_script = get_server_script()
    if _auto_approve:
        log(
            "Auto mode: writing FGA tuples directly (no user prompts)", LogLevel.VERBOSE
        )

    async def handle_server_log(params: Any) -> None:
        if _log_level >= LogLevel.DEBUG:
            level = getattr(params, "level", "info").upper()
            data = params.data if hasattr(params, "data") else str(params)
            msg = data.get("msg", str(data)) if isinstance(data, dict) else str(data)
            _write(f"  [{level}] {msg}")

    if _log_level >= LogLevel.DEBUG:
        os.environ["MCP_SERVER_DEBUG"] = "1"
        os.environ["FASTMCP_LOG_LEVEL"] = "DEBUG"
        os.environ.pop("FASTMCP_SHOW_SERVER_BANNER", None)
    else:
        os.environ.pop("MCP_SERVER_DEBUG", None)
        os.environ["FASTMCP_LOG_LEVEL"] = "ERROR"
        os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "false"

    elicitation = handle_elicitation_auto if _auto_approve else handle_elicitation

    mcp_client = Client(
        server_script,
        elicitation_handler=elicitation,
        log_handler=handle_server_log,
    )

    try:
        async with mcp_client:
            _configure_logging(_log_level)
            tools = await mcp_client.list_tools()
            internal_tools = {
                "register_resource_alias",
                "get_resource_metadata",
            }
            agent_tools = [t for t in tools if t.name not in internal_tools]
            planner_tools = agent_tools
            log(
                f"Connected to MCP server ({len(tools)} tools available)",
                LogLevel.VERBOSE,
            )
            log(f"Tools: {[t.name for t in tools]}", LogLevel.DEBUG)

            _setup_readline()

            while True:
                if not user_prompt:
                    try:
                        user_prompt = await asyncio.to_thread(_tty_prompt, "\n> ")
                    except (EOFError, KeyboardInterrupt):
                        log("\nGoodbye.")
                        break
                    if not user_prompt:
                        continue

                if user_prompt.lower() in ("exit", "quit", "q"):
                    log("\nGoodbye.")
                    break

                task_id = str(uuid.uuid4())
                log(f"\n{user_prompt}\n")
                log(f"Task ID: {task_id}", LogLevel.VERBOSE)

                try:
                    await handle_prompt(
                        mcp_client, planner_tools, agent_tools, user_prompt, task_id
                    )
                except asyncio.CancelledError:
                    log("\nCancelled.")
                    break

                if _auto_approve:
                    break

                user_prompt = ""
    except KeyboardInterrupt:
        log("\nGoodbye.")
    finally:
        if _fga_client:
            await _fga_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _write("\nGoodbye.")
