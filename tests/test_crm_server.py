"""Tests for CRM MCP server tools."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_DATA = {
    "users": [
        {
            "id": "u001",
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "plan": "pro",
            "registered_at": "2024-01-15",
            "status": "active",
        },
        {
            "id": "u002",
            "name": "Bob Smith",
            "email": "bob@startup.io",
            "plan": "free",
            "registered_at": "2024-03-22",
            "status": "active",
        },
    ],
    "tickets": [
        {
            "id": "t001",
            "user_id": "u001",
            "subject": "Authorization error on login",
            "description": "Getting 401 Unauthorized when trying to log in via API.",
            "status": "open",
            "priority": "high",
            "category": "auth",
            "created_at": "2026-03-30T10:15:00Z",
            "updated_at": "2026-03-30T10:15:00Z",
        },
        {
            "id": "t002",
            "user_id": "u002",
            "subject": "How to switch to Ollama?",
            "description": "I want to use a local LLM instead of DeepSeek.",
            "status": "open",
            "priority": "normal",
            "category": "configuration",
            "created_at": "2026-03-31T09:00:00Z",
            "updated_at": "2026-03-31T09:00:00Z",
        },
        {
            "id": "t003",
            "user_id": "u001",
            "subject": "Billing issue",
            "description": "Overcharged on last invoice.",
            "status": "resolved",
            "priority": "normal",
            "category": "billing",
            "created_at": "2026-03-01T10:00:00Z",
            "updated_at": "2026-03-05T12:00:00Z",
        },
    ],
}


@pytest.fixture()
def crm_data_file(tmp_path):
    """Write sample CRM data to a temp file and patch _CRM_DATA_PATH."""
    data_file = tmp_path / "crm_data.json"
    data_file.write_text(json.dumps(_SAMPLE_DATA), encoding="utf-8")
    return data_file


@pytest.fixture(autouse=True)
def patch_crm_path(crm_data_file):
    """Redirect the CRM server's data path to the temp file."""
    import mcp_servers.crm_server as crm
    original = crm._CRM_DATA_PATH
    crm._CRM_DATA_PATH = crm_data_file
    yield
    crm._CRM_DATA_PATH = original


# ---------------------------------------------------------------------------
# get_ticket
# ---------------------------------------------------------------------------

def test_get_ticket_found():
    from mcp_servers.crm_server import get_ticket
    result = json.loads(get_ticket("t001"))
    assert result["id"] == "t001"
    assert result["subject"] == "Authorization error on login"
    assert result["user_name"] == "Alice Johnson"
    assert result["user_plan"] == "pro"


def test_get_ticket_includes_user_data():
    from mcp_servers.crm_server import get_ticket
    result = json.loads(get_ticket("t002"))
    assert result["user_email"] == "bob@startup.io"
    assert result["user_status"] == "active"


def test_get_ticket_not_found():
    from mcp_servers.crm_server import get_ticket
    result = get_ticket("t999")
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# get_user
# ---------------------------------------------------------------------------

def test_get_user_found():
    from mcp_servers.crm_server import get_user
    result = json.loads(get_user("u001"))
    assert result["id"] == "u001"
    assert result["name"] == "Alice Johnson"
    assert result["plan"] == "pro"


def test_get_user_includes_tickets():
    from mcp_servers.crm_server import get_user
    result = json.loads(get_user("u001"))
    ticket_ids = [t["id"] for t in result["tickets"]]
    assert "t001" in ticket_ids
    assert "t003" in ticket_ids
    # t002 belongs to u002, not u001
    assert "t002" not in ticket_ids


def test_get_user_not_found():
    from mcp_servers.crm_server import get_user
    result = get_user("u999")
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# list_open_tickets
# ---------------------------------------------------------------------------

def test_list_open_tickets_returns_only_open():
    from mcp_servers.crm_server import list_open_tickets
    result = json.loads(list_open_tickets())
    statuses = {t["status"] for t in result}
    # resolved tickets must not appear
    assert "resolved" not in statuses
    assert all(s in {"open", "in_progress"} for s in statuses)


def test_list_open_tickets_count():
    from mcp_servers.crm_server import list_open_tickets
    result = json.loads(list_open_tickets())
    # sample data has 2 open tickets (t001, t002); t003 is resolved
    assert len(result) == 2


# ---------------------------------------------------------------------------
# search_tickets
# ---------------------------------------------------------------------------

def test_search_tickets_by_subject():
    from mcp_servers.crm_server import search_tickets
    result = json.loads(search_tickets("authorization"))
    assert len(result) == 1
    assert result[0]["id"] == "t001"


def test_search_tickets_by_category():
    from mcp_servers.crm_server import search_tickets
    result = json.loads(search_tickets("billing"))
    assert len(result) == 1
    assert result[0]["id"] == "t003"


def test_search_tickets_case_insensitive():
    from mcp_servers.crm_server import search_tickets
    result = json.loads(search_tickets("OLLAMA"))
    assert len(result) >= 1


def test_search_tickets_no_match():
    from mcp_servers.crm_server import search_tickets
    result = search_tickets("zzznomatch")
    assert "no tickets found" in result.lower()


# ---------------------------------------------------------------------------
# update_ticket_status
# ---------------------------------------------------------------------------

def test_update_ticket_status_valid(crm_data_file):
    from mcp_servers.crm_server import update_ticket_status
    result = update_ticket_status("t001", "in_progress")
    assert "in_progress" in result

    # Verify persistence
    saved = json.loads(crm_data_file.read_text())
    ticket = next(t for t in saved["tickets"] if t["id"] == "t001")
    assert ticket["status"] == "in_progress"


def test_update_ticket_status_updates_timestamp(crm_data_file):
    from mcp_servers.crm_server import update_ticket_status
    update_ticket_status("t002", "resolved")
    saved = json.loads(crm_data_file.read_text())
    ticket = next(t for t in saved["tickets"] if t["id"] == "t002")
    # updated_at should differ from created_at now
    assert ticket["updated_at"] != "2026-03-31T09:00:00Z"


def test_update_ticket_status_invalid_status():
    from mcp_servers.crm_server import update_ticket_status
    result = update_ticket_status("t001", "flying")
    assert "invalid status" in result.lower()


def test_update_ticket_status_not_found():
    from mcp_servers.crm_server import update_ticket_status
    result = update_ticket_status("t999", "resolved")
    assert "not found" in result.lower()
