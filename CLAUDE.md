# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Task-scoped authorization system for AI agents using MCP (Model Context Protocol) and OpenFGA. The agent plans permissions, discovers resources, gets authorization, then executes — all through MCP primitives. The orchestrator writes task-scoped grants directly to OpenFGA before execution. The agent has **no write access** to the FGA store — any unanticipated permissions at runtime are handled by the middleware's inline elicitation (system-initiated, user-approved). OpenFGA enforces grants at three scopes: **once** (single task), **session** (via inline elicitation), and **always** (via inline elicitation).

## Common Commands

```bash
make prerequisites    # Install prerequisite tools (uv, docker, fga, jq, node) via Homebrew
make install          # uv sync — creates .venv + installs all deps and dev tools
make check            # All static checks + unit tests (syntax, lint, typecheck, security, tests)
make test             # Unit tests only (no external services)
make test-integration # Integration tests — tests/test_permission_openfga.py (loads .env; needs local OpenFGA + model)
make test-e2e         # End-to-end tests — tests/test_e2e_openfga.py (loads .env; needs OpenFGA + live Slack/Linear APIs)
make openfga          # Start OpenFGA via Docker Compose (detached)
make openfga-stop     # Stop OpenFGA container
make openfga-setup    # Start OpenFGA + create store + write model + save FGA_STORE_ID to .env
make fga-reset        # Create a store + write authorization/model.fga + save FGA_STORE_ID to .env
make test-fga         # OpenFGA model tests against authorization/model.fga.yaml
make test-all         # Unit + FGA model + integration + e2e tests
make lint             # Ruff linter
make format           # Auto-format with ruff
make typecheck        # mypy (best-effort, no strict)
make security         # Bandit security scanner
make audit            # pip-audit — check deps for known CVEs
make dead-code        # Vulture — find unused code

# Run a single test
uv run pytest tests/test_agent.py::test_function_name -v

# Run the agent
make run              # Interactive (approve planned permissions, then inline fallback for surprises)
make run-auto ARG="Summarize the MCP Dev Talk project"  # Autonomous (direct FGA writes)
make run-verbose      # Interactive with verbose logging
make run-debug        # Interactive with debug logging
```

## Architecture

```
src/agent.py (CLI) / web/backend/flow_runner.py (Web)
  │  Thin shells — handle I/O and error presentation
  │  MCP (stdio)
  ▼
src/authz_flow.py:run_authz_pipeline()
  │  Shared pipeline: plan → discover → resolve → authorize → execute → cleanup
  │  MCP (stdio)
  ▼
src/mcp_server.py (MCP Server / proxy)
  │  Wraps remote Slack/Linear tools + stub send_email
  │  Middleware chain: [OpenFGAPermissionMiddleware]
  ▼
src/task_authz/middleware.py (FastMCP middleware)
  │  Intercepts every tool call → checks FGA → resolves resource names → elicits or denies
  │  HTTPS
  ▼
OpenFGA (localhost:8080) — authorization tuples
Remote MCP servers (Slack, Linear) — proxied tool execution
```

### Key Data Flow

The full pipeline lives in `src/authz_flow.py:run_authz_pipeline()`. Both CLI and web call this single function.

1. **Permission planning**: `plan_with_namespaces()` uses Claude with forced `tool_choice` to extract action permissions as structured JSON. The backend deterministically derives which discovery tools to run from namespace metadata — the LLM only identifies *actions*, not discovery.
2. **Discovery authorization**: The orchestrator writes task-scoped FGA tuples for discovery tools (`tool:list_slack_channels`, etc.) directly to OpenFGA before running them. Discovery tools are **not exempt** — they go through the same FGA check as action tools.
3. **Resource discovery**: Discovery tools (e.g., `list_slack_channels`) return standardized `[{"id": "...", "name": "..."}]` JSON. The middleware's `_update_registry_if_list_tool()` helper parses results and populates the resource registry after any successful call (whether granted, elicited, or exempt).
4. **Name-to-ID mapping**: `remap_action_permissions()` resolves display names (e.g., `#general`) to canonical IDs (e.g., `C5XMACTML`). Unresolved names raise `ResolutionError` (fail-closed).
5. **Authorization**: The orchestrator writes task-scoped FGA tuples for action tools directly to OpenFGA (same path for both interactive and autonomous modes). During execution, if the agent calls a tool it lacks permission for, the middleware's inline elicitation prompts the user for scope.
6. **Execution**: Middleware checks `check(task:{id}, can_call, tool:{name})` or `check(task:{id}, can_call, tool_resource:{name}/{resource})` against FGA. One check resolves all three scopes via relationship traversal.
7. **Cleanup**: `cleanup_fga_after_task()` deletes all task-scoped grants (both discovery and action) after execution.

### Discovery Tool Convention

Discovery tools follow the `list_<resource_type>` naming convention (e.g., `list_slack_channels`, `list_linear_projects`). Each returns a standardized `[{"id": "...", "name": "..."}]` JSON array. The middleware uses a single universal parser (`_parse_standard_resources`) — no per-server parsers needed.

`ResourceType` defines each type of resource: `name`, optional `list_tool` for discovery, and `tool_resources` mapping tool names to their resource argument (e.g., `{"slack_send_message": "channel_id"}`). Resource types without a `list_tool` (e.g., email) support authorization without discovery.

### OpenFGA Model (`authorization/model.fga`)

Hierarchy: `user → agent_user ← agent`, then `agent_user → session → task`. In autonomous mode, the orchestrator also binds the task directly to `agent_user` so checks can run without a session-mediated path. The task is the subject of every authorization check. Three grant scopes (`can_call_task`, `can_call_session`, `can_call_agent_user`) are unioned into a single `can_call` relation. `tool_resource` resolves wildcard grants from its `parent_tool` via contextual tuples (ephemeral, never persisted to the store).

### Middleware Meta-Tools

The middleware currently registers one read-only meta-tool (not proxied to remote servers):
- `get_resource_metadata` — **exempt** (bootstrap: needed before any planning). Returns resource type configs (namespaces, discovery tools, tool→arg mappings).

`src/task_authz/meta_tools.py` also contains a `list_permissions` helper implementation, but `register_meta_tools()` does not currently expose it on the server.

Only `get_resource_metadata` is exempt from FGA checks. Discovery tools (`list_slack_channels`, `list_linear_projects`, etc.) require task-scoped grants — the orchestrator writes these before running discovery.

The agent has **no write access** to the FGA store. All grant writes happen either in the orchestrator (pre-execution, task-scoped) or in the middleware's inline elicitation flow (system-initiated, user-approved).

## Configuration

- `.env`: `ANTHROPIC_API_KEY`, `FGA_STORE_ID`, `FGA_API_URL`, `MCP_SSL_VERIFY`, optional `MCP_SSL_CA_BUNDLE`, `ANTHROPIC_MODEL` (default: `claude-haiku-4-5`), `MCP_TOOL_TIMEOUT_SECONDS`, `FGA_USER_ID`, `FGA_AGENT_ID`
- `.mcp_credentials.json`: Remote server URLs and OAuth tokens for Slack, Linear, Notion

### OpenFGA test setup

For integration or e2e tests:

1. Run `make openfga-setup` (starts OpenFGA via Docker Compose, creates store + model, saves `FGA_STORE_ID` to `.env`)
2. Run `make test-integration` or `make test-e2e`
3. When done: `make openfga-stop`

Or step by step:
1. Start OpenFGA with `make openfga`
2. Create the store and model with `make fga-reset`
3. Run `make test-integration` or `make test-e2e`

The `make run*`, `make test-integration`, and `make test-e2e` targets load `.env` automatically. Only source `.env` manually for ad-hoc shell commands.

## Project Layout

```
mcpdev-demo/
  src/                            ← source code (on PYTHONPATH via pyproject.toml)
    agent.py                      ← CLI frontend (thin shell: terminal I/O, readline, approval prompts, error presentation)
    authz_flow.py                 ← shared authorization pipeline + building blocks (plan, discover, authorize, execute)
    mcp_server.py                 ← MCP server (proxies Slack/Linear with authorization middleware)
    mcp_remote.py                 ← remote MCP server connection helper
    utils.py                      ← shared utilities (FGA write opts, text extraction, .env loader)
    test_remote_server.py         ← in-process test MCP server for integration tests
    servers/
      slack.py
      linear.py
      email.py
    task_authz/
      config.py                   ← ResourceType, SCOPE_CHOICES, authz_namespace decorator
      middleware.py                ← OpenFGAPermissionMiddleware
      meta_tools.py               ← read-only meta-tool registration + optional list_permissions helper
      resolution.py               ← resource name resolution
  tests/                          ← test files
    test_agent.py                 ← unit: plan parsing, name mapping, agent loop, prompt injection
    test_authz_flow_extras.py     ← unit: FGA tuple computation, namespace mapping, grant lifecycle
    test_config.py                ← unit: authz_namespace decorator, ResourceType
    test_discovery_phase.py       ← unit: run_discovery_phase orchestration
    test_linear.py                ← unit: Linear project discovery parsing
    test_mcp_remote.py            ← unit: config loading, server lookup, client creation
    test_meta_tools.py            ← unit: _parse_fga_object
    test_middleware_unit.py        ← unit: FGA object building, grant tuples, state locking
    test_resolution.py            ← unit: resource parsing, name→ID resolution, suggestions
    test_slack_parser.py          ← unit: Slack channel parsing (JSON + regex fallback)
    test_utils.py                 ← unit: text extraction, env loading, ID sanitization
    test_permission_openfga.py    ← integration: full FGA lifecycle (needs OpenFGA)
    test_e2e_openfga.py           ← e2e: live Slack/Linear APIs (needs OpenFGA + credentials)
  web/
    backend/
      app.py                      ← FastAPI setup (CORS, WebSocket router, permissions API)
      flow_runner.py              ← web flow orchestration with event emission
      permissions.py              ← demo tuple/model inspection and mutation endpoints
      ws.py                       ← WebSocket endpoint for regular/intention_discovery/autonomous flows
    frontend/
      src/
        App.tsx                   ← flow tabs plus Manage Permissions tab
  authorization/                  ← OpenFGA model
  .env                            ← environment config (project root)
  .mcp_credentials.json           ← MCP server credentials (project root)
  Makefile
  pyproject.toml
  CLAUDE.md
```

## Testing

Unit tests (no external services — run with `make test`):
- `test_agent.py` — plan parsing, handle_prompt pipeline integration, agent loop, prompt injection abort
- `test_authz_flow_extras.py` — FGA tuple computation, namespace mapping, grant lifecycle
- `test_config.py` — `authz_namespace` decorator, `ResourceType` dataclass
- `test_discovery_phase.py` — `run_discovery_phase` orchestration
- `test_linear.py` — Linear project discovery parsing (JSON + regex fallback)
- `test_mcp_remote.py` — config loading, server lookup, client creation
- `test_meta_tools.py` — `_parse_fga_object` parsing
- `test_middleware_unit.py` — FGA object building, grant tuples, state locking, task cleanup
- `test_resolution.py` — resource parsing, name→ID resolution, suggestions
- `test_slack_parser.py` — Slack channel parsing (JSON + regex fallback)
- `test_utils.py` — `extract_text`, `.env` loading, and FGA ID sanitization helpers

OpenFGA model tests (need `fga` CLI — run with `make test-fga`):
- `authorization/model.fga.yaml` — model assertions against `authorization/model.fga`

Integration tests (need local OpenFGA — run with `make test-integration`):
- `test_permission_openfga.py` — full FGA lifecycle: session init, grants, checks, scope isolation, deny flows, prompt injection blocking

End-to-end tests (need OpenFGA + live APIs — run with `make test-e2e`):
- `test_e2e_openfga.py` — tests against live Slack and Linear APIs

## Security Design

- **Fail-closed**: Unresolved resource names rejected with suggestions via `difflib.get_close_matches()`
- **Plan validation**: Unknown tools stripped before execution
- **Structured output**: Forced `tool_choice` prevents free-text injection in planner
- **Least-privilege discovery**: Discovery tools require task-scoped grants — agents start with minimal permissions. Only `get_resource_metadata` is exempt from FGA checks.
- **Task isolation**: Grants scoped to single `task_id` (both discovery and action), cleaned up on completion
- **Agent confined**: The agent has no write access to the FGA store — cannot expand its own permissions. All grants written by the orchestrator (pre-execution) or middleware (inline elicitation)
- **Prompt injection defense**: Even if the LLM is tricked, the middleware blocks unauthorized calls; autonomous mode raises `UnauthorizedToolError` and stops immediately
- **Identity**: `FGA_USER_ID` and `FGA_AGENT_ID` are read from env vars by both the middleware and the orchestrator so they always agree on `agent_user_id`. In production, these would come from an access token (user) and client credentials (agent) instead of env vars

### Code Standards

- Python ≥ 3.12 with full type annotations
- Follow existing patterns and maintain consistency
- **Prioritize readable, understandable code** - clarity over cleverness
- Avoid obfuscated or confusing patterns, even if they're shorter
- Each feature needs corresponding tests

### Module Exports

- **Be intentional about re-exports** — don't blindly re-export everything to parent namespaces
- Core types that define a module's purpose should be exported (e.g., `Middleware` from `fastmcp.server.middleware`)
- Specialized features can live in submodules (e.g., `fastmcp.server.middleware.dynamic`)

## After Every Change

Run these checks after each code change:

```bash
make check             # All static checks + unit tests (syntax, lint, typecheck, security, tests)
make test-integration  # Integration tests — needs local OpenFGA + FGA_STORE_ID
```

`make check` must always pass. `make test-integration` should pass when OpenFGA is available.
If any check fails, fix the issue before moving on. Do not batch up changes and check later.

## Critical Patterns

- Never use bare `except` — be specific with exception types
