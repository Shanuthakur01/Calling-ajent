"""
Multi-page navigation structure regression tests.

1. test_dashboard_root_renders     — / page has sidebar, KPIs, place-call form
2. test_calls_page_renders         — /calls page has sidebar, table, no cost column
3. test_agent_page_renders         — /agent page has sidebar, prompt editor
4. test_sidebar_present_on_all     — sidebar + themeToggle on every page
5. test_theme_toggle_button_exists — theme button and label text present
6. test_existing_api_still_works   — /api/calls backend regression
"""

import json
import pytest
from dashboard import render_dashboard, render_calls, render_agent


# ---------------------------------------------------------------------------
# 1. Dashboard page
# ---------------------------------------------------------------------------

def test_dashboard_root_renders():
    html = render_dashboard()
    assert "IJF Calling Agent" in html
    assert "Place New Call" in html
    assert 'data-route="/"' in html
    assert "ijf-sidebar" in html
    assert "themeToggle" in html


# ---------------------------------------------------------------------------
# 2. Call History page
# ---------------------------------------------------------------------------

def test_calls_page_renders():
    html = render_calls()
    assert "Call History" in html
    assert 'data-route="/calls"' in html
    assert "ijf-sidebar" in html
    assert "<th>Cost</th>" not in html
    assert "<th>COST</th>" not in html
    assert "fmtCost" not in html


# ---------------------------------------------------------------------------
# 3. Agent Setup page
# ---------------------------------------------------------------------------

def test_agent_page_renders():
    html = render_agent()
    assert "Agent" in html
    assert "prompt" in html.lower()
    assert 'data-route="/agent"' in html
    assert "ijf-sidebar" in html


# ---------------------------------------------------------------------------
# 4. Sidebar present on all pages
# ---------------------------------------------------------------------------

def test_sidebar_present_on_all():
    for fn, path in [
        (render_dashboard, "/"),
        (render_calls,     "/calls"),
        (render_agent,     "/agent"),
    ]:
        html = fn()
        assert 'class="ijf-sidebar"' in html,  f"Sidebar missing on {path}"
        assert "themeToggle" in html,           f"Theme toggle missing on {path}"
        assert 'data-route="/"' in html,        f"Nav item / missing on {path}"
        assert 'data-route="/calls"' in html,   f"Nav item /calls missing on {path}"
        assert 'data-route="/agent"' in html,   f"Nav item /agent missing on {path}"


# ---------------------------------------------------------------------------
# 5. Theme toggle
# ---------------------------------------------------------------------------

def test_theme_toggle_button_exists():
    html = render_dashboard()
    assert "themeToggle" in html
    assert "Light mode" in html or "Dark mode" in html
    assert "data-theme" in html or "localStorage" in html


# ---------------------------------------------------------------------------
# 6. Backend /api/calls still works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_api_still_works():
    import main as _main
    resp = await _main.api_calls()
    data = json.loads(resp.body)
    assert "calls" in data
