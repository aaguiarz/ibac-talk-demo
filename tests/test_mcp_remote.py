"""Unit tests for mcp_remote — config loading and client creation."""

from __future__ import annotations

import json
import os
import tempfile

from mcp_remote import create_remote_client, get_server, load_config


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_reads_valid_json() -> None:
    data = {"servers": {"slack": {"url": "https://slack.example.com", "token": "tok"}}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        result = load_config(path)
        assert result == data
    finally:
        os.unlink(path)


def test_load_config_returns_empty_on_invalid_json() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{invalid json")
        path = f.name
    try:
        assert load_config(path) == {}
    finally:
        os.unlink(path)


def test_load_config_returns_empty_on_missing_file() -> None:
    assert load_config("/tmp/nonexistent_config_12345.json") == {}


# ---------------------------------------------------------------------------
# get_server
# ---------------------------------------------------------------------------


def test_get_server_returns_url_and_token() -> None:
    data = {"servers": {"slack": {"url": "https://slack.example.com", "token": "tok"}}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        result = get_server(path, "slack")
        assert result == {"url": "https://slack.example.com", "token": "tok"}
    finally:
        os.unlink(path)


def test_get_server_returns_none_for_missing_server() -> None:
    data = {"servers": {}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        assert get_server(path, "slack") is None
    finally:
        os.unlink(path)


def test_get_server_returns_none_when_url_missing() -> None:
    data = {"servers": {"slack": {"token": "tok"}}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        assert get_server(path, "slack") is None
    finally:
        os.unlink(path)


def test_get_server_falls_back_to_env_token() -> None:
    data = {"servers": {"slack": {"url": "https://slack.example.com"}}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        env_key = "SLACK_MCP_API_KEY"
        old = os.environ.get(env_key)
        os.environ[env_key] = "env-token"
        try:
            result = get_server(path, "slack")
            assert result == {"url": "https://slack.example.com", "token": "env-token"}
        finally:
            if old is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = old
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# create_remote_client
# ---------------------------------------------------------------------------


def test_create_remote_client_returns_client_for_sse_url() -> None:
    client = create_remote_client("https://example.com/sse", "tok")
    assert client is not None


def test_create_remote_client_returns_client_for_streamable_url() -> None:
    client = create_remote_client("https://example.com/mcp", "tok")
    assert client is not None
