"""
Tests for the prompt editor API endpoints.

1. test_get_prompt_returns_content      — GET /api/prompt returns file content + char_count
2. test_get_prompt_missing_file         — GET returns empty response when file absent
3. test_post_prompt_writes_to_disk      — POST /api/prompt writes new content
4. test_post_prompt_rejects_empty       — POST 400 for whitespace-only content; file unchanged
5. test_post_prompt_rejects_over_limit  — POST 400 for content > 10000 chars; file unchanged
6. test_reset_prompt_restores_default   — POST /api/prompt/reset copies default back
7. test_reset_prompt_missing_default    — POST /reset 404 when default file absent
8. test_get_system_prompt_reads_fresh   — hot-reload: get_system_prompt() re-reads disk each call
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _fake_settings(tmp_path):
    return SimpleNamespace(system_prompt_path=str(tmp_path / "system_prompt.txt"))


# ---------------------------------------------------------------------------
# GET /api/prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_prompt_returns_content(tmp_path):
    """GET /api/prompt returns the file's text and correct char_count."""
    import main as _main

    content = "You are a helpful agent."
    (tmp_path / "system_prompt.txt").write_text(content, encoding="utf-8")

    with patch("main.settings", _fake_settings(tmp_path)):
        resp = await _main.get_prompt()

    data = json.loads(resp.body)
    assert data["content"] == content
    assert data["char_count"] == len(content)


@pytest.mark.asyncio
async def test_get_prompt_missing_file(tmp_path):
    """GET /api/prompt returns empty content when system_prompt.txt does not exist."""
    import main as _main

    fake = SimpleNamespace(system_prompt_path=str(tmp_path / "nonexistent.txt"))
    with patch("main.settings", fake):
        resp = await _main.get_prompt()

    data = json.loads(resp.body)
    assert data["content"] == ""
    assert data["char_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_prompt_writes_to_disk(tmp_path):
    """POST /api/prompt overwrites system_prompt.txt and returns ok: True."""
    import main as _main

    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text("old prompt", encoding="utf-8")
    new_content = "You are now a different agent with new behavior."

    with patch("main.settings", _fake_settings(tmp_path)):
        resp = await _main.update_prompt({"content": new_content})

    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["char_count"] == len(new_content)
    assert prompt_file.read_text(encoding="utf-8") == new_content


@pytest.mark.asyncio
async def test_post_prompt_rejects_empty(tmp_path):
    """POST /api/prompt raises HTTPException(400) for whitespace-only content; file unchanged."""
    import main as _main
    from fastapi import HTTPException

    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text("existing prompt", encoding="utf-8")

    with patch("main.settings", _fake_settings(tmp_path)):
        with pytest.raises(HTTPException) as exc_info:
            await _main.update_prompt({"content": "   "})

    assert exc_info.value.status_code == 400
    assert prompt_file.read_text(encoding="utf-8") == "existing prompt"


@pytest.mark.asyncio
async def test_post_prompt_rejects_over_limit(tmp_path):
    """POST /api/prompt raises HTTPException(400) for content > 10000 chars; file unchanged."""
    import main as _main
    from fastapi import HTTPException

    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text("existing prompt", encoding="utf-8")

    with patch("main.settings", _fake_settings(tmp_path)):
        with pytest.raises(HTTPException) as exc_info:
            await _main.update_prompt({"content": "x" * 10001})

    assert exc_info.value.status_code == 400
    assert prompt_file.read_text(encoding="utf-8") == "existing prompt"


# ---------------------------------------------------------------------------
# POST /api/prompt/reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_prompt_restores_default(tmp_path):
    """POST /api/prompt/reset copies system_prompt.default.txt back to system_prompt.txt."""
    import main as _main

    current = tmp_path / "system_prompt.txt"
    default = tmp_path / "system_prompt.default.txt"
    current.write_text("modified prompt", encoding="utf-8")
    default.write_text("original default prompt", encoding="utf-8")

    with patch("main.settings", _fake_settings(tmp_path)):
        resp = await _main.reset_prompt()

    body = json.loads(resp.body)
    assert body["ok"] is True
    assert current.read_text(encoding="utf-8") == "original default prompt"


@pytest.mark.asyncio
async def test_reset_prompt_missing_default(tmp_path):
    """POST /api/prompt/reset raises HTTPException(404) when default file is absent."""
    import main as _main
    from fastapi import HTTPException

    (tmp_path / "system_prompt.txt").write_text("some prompt", encoding="utf-8")

    with patch("main.settings", _fake_settings(tmp_path)):
        with pytest.raises(HTTPException) as exc_info:
            await _main.reset_prompt()

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Hot-reload regression
# ---------------------------------------------------------------------------

def test_get_system_prompt_reads_fresh(tmp_path):
    """get_system_prompt() must re-read disk on every call — not cache the first read."""
    import config

    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text("v1 unique sentinel text", encoding="utf-8")

    fake = SimpleNamespace(system_prompt_path=str(prompt_file))

    with patch("config.settings", fake):
        v1 = config.get_system_prompt()

    assert "v1 unique sentinel text" in v1

    prompt_file.write_text("v2 unique sentinel text", encoding="utf-8")

    with patch("config.settings", fake):
        v2 = config.get_system_prompt()

    assert "v2 unique sentinel text" in v2
    assert v1 != v2, "get_system_prompt() must not cache the first result"
