"""Unit tests for servers.slack — parse_slack_channels regex fallback and edge cases."""

from __future__ import annotations

from servers.slack import parse_slack_channels


# ---------------------------------------------------------------------------
# Regex fallback (JSON parse fails or returns empty)
# ---------------------------------------------------------------------------


def test_regex_fallback_extracts_channel_from_archive_url() -> None:
    text = "Name: general /archives/C5XMACTML some text"
    result = parse_slack_channels(text)
    assert result == [{"id": "C5XMACTML", "name": "#general"}]


def test_regex_fallback_multiple_channels() -> None:
    text = (
        "Name: general /archives/C111\n"
        "Name: random /archives/C222\n"
    )
    result = parse_slack_channels(text)
    assert len(result) == 2
    assert result[0] == {"id": "C111", "name": "#general"}
    assert result[1] == {"id": "C222", "name": "#random"}


def test_regex_fallback_strips_hash_prefix_from_name() -> None:
    text = "Name: #private-team /archives/C333"
    result = parse_slack_channels(text)
    assert result == [{"id": "C333", "name": "#private-team"}]


def test_regex_fallback_case_insensitive_name_prefix() -> None:
    text = "name: dev-ops /archives/C444"
    result = parse_slack_channels(text)
    assert result == [{"id": "C444", "name": "#dev-ops"}]


def test_regex_fallback_escaped_archive_url() -> None:
    """Handles escaped slashes like \\/archives\\/ in stringified JSON."""
    text = r"name: test \/archives\/C555"
    result = parse_slack_channels(text)
    assert result == [{"id": "C555", "name": "#test"}]


def test_regex_fallback_returns_empty_on_no_matches() -> None:
    result = parse_slack_channels("no useful data here")
    assert result == []


def test_regex_fallback_mismatched_counts_uses_zip() -> None:
    """When IDs and names don't pair up, zip truncates to shorter list."""
    text = (
        "Name: first /archives/C111\n"
        "Name: second\n"  # no ID
    )
    result = parse_slack_channels(text)
    # Only one ID found, zip stops at 1
    assert len(result) == 1
    assert result[0] == {"id": "C111", "name": "#first"}


# ---------------------------------------------------------------------------
# JSON edge cases
# ---------------------------------------------------------------------------


def test_json_array_skips_non_dict_items() -> None:
    result = parse_slack_channels('[42, {"id": "C1", "name": "ok"}]')
    assert result == [{"id": "C1", "name": "#ok"}]


def test_json_array_skips_missing_fields() -> None:
    result = parse_slack_channels('[{"id": "C1"}, {"id": "C2", "name": "valid"}]')
    assert result == [{"id": "C2", "name": "#valid"}]


def test_json_with_results_key() -> None:
    result = parse_slack_channels('{"results": [{"id": "C1", "name": "a"}]}')
    assert result == [{"id": "C1", "name": "#a"}]


def test_json_with_items_key() -> None:
    result = parse_slack_channels('{"items": [{"id": "C1", "name": "b"}]}')
    assert result == [{"id": "C1", "name": "#b"}]


def test_empty_json_array_falls_through_to_regex() -> None:
    """Empty JSON array → result is empty → falls through to regex."""
    result = parse_slack_channels("[]")
    assert result == []


def test_json_non_string_id_skipped() -> None:
    result = parse_slack_channels('[{"id": 123, "name": "num-id"}]')
    # id is int, not str → skipped; empty result → falls to regex
    assert result == []
