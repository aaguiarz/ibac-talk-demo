from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from utils import extract_text, load_env, sanitize_fga_id


def test_extract_text_with_text_content() -> None:
    content_item = SimpleNamespace(text="hello world")
    result = SimpleNamespace(content=[content_item])
    assert extract_text(result) == "hello world"


def test_extract_text_str_passthrough() -> None:
    assert extract_text("plain string") == "plain string"


def test_extract_text_mixed_content() -> None:
    text_item = SimpleNamespace(text="hello ")
    other_item = 42
    result = SimpleNamespace(content=[text_item, other_item])
    assert extract_text(result) == "hello 42"


def test_extract_text_empty() -> None:
    result = SimpleNamespace(content=[])
    assert extract_text(result) == ""


def test_sanitize_fga_id_passthrough() -> None:
    assert sanitize_fga_id("hello-world_1.0") == "hello-world_1.0"


def test_sanitize_fga_id_replaces_special_chars() -> None:
    assert sanitize_fga_id("user:name/path space") == "user_name_path_space"


def test_sanitize_fga_id_preserves_dash_underscore_dot() -> None:
    assert sanitize_fga_id("a-b_c.d") == "a-b_c.d"


def test_load_env_loads_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as file_handle:
        file_handle.write("TEST_LOAD_ENV_KEY=hello123\n")
        file_handle.flush()
        path = file_handle.name
    try:
        os.environ.pop("TEST_LOAD_ENV_KEY", None)
        load_env(path)
        assert os.environ.get("TEST_LOAD_ENV_KEY") == "hello123"
    finally:
        os.environ.pop("TEST_LOAD_ENV_KEY", None)
        os.unlink(path)


def test_load_env_does_not_override_existing_env_var() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as file_handle:
        file_handle.write("TEST_LOAD_ENV_OVERRIDE=new_value\n")
        file_handle.flush()
        path = file_handle.name
    try:
        os.environ["TEST_LOAD_ENV_OVERRIDE"] = "old_value"
        load_env(path)
        assert os.environ.get("TEST_LOAD_ENV_OVERRIDE") == "old_value"
    finally:
        os.environ.pop("TEST_LOAD_ENV_OVERRIDE", None)
        os.unlink(path)


def test_load_env_skips_comments_and_blanks() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as file_handle:
        file_handle.write("# comment\n\nVALID_KEY_LOAD_ENV=value\n")
        file_handle.flush()
        path = file_handle.name
    try:
        os.environ.pop("VALID_KEY_LOAD_ENV", None)
        load_env(path)
        assert os.environ.get("VALID_KEY_LOAD_ENV") == "value"
    finally:
        os.environ.pop("VALID_KEY_LOAD_ENV", None)
        os.unlink(path)