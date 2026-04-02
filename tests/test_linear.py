"""Unit tests for servers.linear — parse_linear_projects."""

from __future__ import annotations

from servers.linear import parse_linear_projects


def test_parse_valid_json_array() -> None:
    text = '[{"id": "p1", "name": "Website"}, {"id": "p2", "name": "API"}]'
    result = parse_linear_projects(text)
    assert result == [{"id": "p1", "name": "Website"}, {"id": "p2", "name": "API"}]


def test_parse_json_object_with_projects_key() -> None:
    text = '{"projects": [{"id": "p1", "name": "Website"}]}'
    result = parse_linear_projects(text)
    assert result == [{"id": "p1", "name": "Website"}]


def test_parse_json_object_with_nodes_key() -> None:
    text = '{"nodes": [{"id": "p1", "name": "Website"}]}'
    result = parse_linear_projects(text)
    assert result == [{"id": "p1", "name": "Website"}]


def test_parse_skips_items_missing_id() -> None:
    text = '[{"name": "no-id"}, {"id": "p1", "name": "ok"}]'
    result = parse_linear_projects(text)
    assert result == [{"id": "p1", "name": "ok"}]


def test_parse_skips_non_dict_items() -> None:
    text = '["not-a-dict", {"id": "p1", "name": "ok"}]'
    result = parse_linear_projects(text)
    assert result == [{"id": "p1", "name": "ok"}]


def test_parse_falls_back_to_regex_on_invalid_json() -> None:
    text = 'id: "abc123" name: "My Project"'
    result = parse_linear_projects(text)
    assert len(result) == 1
    assert result[0]["id"] == "abc123"
    assert result[0]["name"] == "My Project"


def test_parse_returns_empty_for_garbage_input() -> None:
    result = parse_linear_projects("completely random text no patterns")
    assert result == []


def test_parse_empty_string() -> None:
    result = parse_linear_projects("")
    assert result == []


def test_parse_empty_json_array() -> None:
    result = parse_linear_projects("[]")
    assert result == []


def test_parse_regex_multiple_entries() -> None:
    text = """
    id: "p1" name: "Project A"
    id: "p2" name: "Project B"
    """
    result = parse_linear_projects(text)
    assert len(result) == 2
    assert result[0] == {"id": "p1", "name": "Project A"}
    assert result[1] == {"id": "p2", "name": "Project B"}
