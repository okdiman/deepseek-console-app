"""CRM MCP Server — exposes user and ticket data to the support assistant."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("CRM Server")

_PROJECT_ROOT = Path(__file__).parent.parent
_CRM_DATA_PATH = _PROJECT_ROOT / "data" / "crm_data.json"


def _load_data() -> dict:
    """Load CRM data from JSON file. Returns empty structure on error."""
    try:
        return json.loads(_CRM_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"users": [], "tickets": [], "_error": str(e)}


def _save_data(data: dict) -> Optional[str]:
    """Save CRM data back to JSON file. Returns error message or None on success."""
    try:
        _CRM_DATA_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return None
    except OSError as e:
        return str(e)


@mcp.tool()
def get_ticket(ticket_id: str) -> str:
    """Returns full details of a support ticket by its ID (e.g. 't001').

    ticket_id: Ticket identifier, e.g. 't001', 't042'.
    """
    data = _load_data()
    for ticket in data.get("tickets", []):
        if ticket["id"] == ticket_id:
            user = next(
                (u for u in data.get("users", []) if u["id"] == ticket["user_id"]),
                None,
            )
            result = dict(ticket)
            if user:
                result["user_name"] = user["name"]
                result["user_email"] = user["email"]
                result["user_plan"] = user["plan"]
                result["user_status"] = user["status"]
            return json.dumps(result, indent=2, ensure_ascii=False)
    return f"Ticket '{ticket_id}' not found."


@mcp.tool()
def get_user(user_id: str) -> str:
    """Returns full profile of a user by their ID (e.g. 'u001').

    user_id: User identifier, e.g. 'u001'.
    """
    data = _load_data()
    for user in data.get("users", []):
        if user["id"] == user_id:
            user_tickets = [
                {"id": t["id"], "subject": t["subject"], "status": t["status"]}
                for t in data.get("tickets", [])
                if t["user_id"] == user_id
            ]
            result = dict(user)
            result["tickets"] = user_tickets
            return json.dumps(result, indent=2, ensure_ascii=False)
    return f"User '{user_id}' not found."


@mcp.tool()
def list_open_tickets() -> str:
    """Returns a list of all open and in-progress support tickets with basic info."""
    data = _load_data()
    open_statuses = {"open", "in_progress"}
    tickets = [
        {
            "id": t["id"],
            "user_id": t["user_id"],
            "subject": t["subject"],
            "status": t["status"],
            "priority": t["priority"],
            "category": t["category"],
            "created_at": t["created_at"],
        }
        for t in data.get("tickets", [])
        if t.get("status") in open_statuses
    ]
    if not tickets:
        return "No open tickets."
    return json.dumps(tickets, indent=2, ensure_ascii=False)


@mcp.tool()
def search_tickets(query: str) -> str:
    """Searches tickets by subject, description, or category. Case-insensitive.

    query: Search term to match against ticket subject, description, and category.
    """
    data = _load_data()
    q = query.lower()
    matches = []
    for t in data.get("tickets", []):
        if (
            q in t.get("subject", "").lower()
            or q in t.get("description", "").lower()
            or q in t.get("category", "").lower()
        ):
            matches.append({
                "id": t["id"],
                "user_id": t["user_id"],
                "subject": t["subject"],
                "status": t["status"],
                "priority": t["priority"],
                "category": t["category"],
            })
    if not matches:
        return f"No tickets found matching '{query}'."
    return json.dumps(matches, indent=2, ensure_ascii=False)


@mcp.tool()
def update_ticket_status(ticket_id: str, status: str) -> str:
    """Updates the status of a support ticket.

    ticket_id: Ticket identifier, e.g. 't001'.
    status: New status — one of: 'open', 'in_progress', 'resolved', 'closed'.
    """
    valid_statuses = {"open", "in_progress", "resolved", "closed"}
    if status not in valid_statuses:
        return f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}."

    data = _load_data()
    for ticket in data.get("tickets", []):
        if ticket["id"] == ticket_id:
            old_status = ticket["status"]
            ticket["status"] = status
            from datetime import datetime, timezone
            ticket["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            err = _save_data(data)
            if err:
                return f"Error saving data: {err}"
            return f"Ticket '{ticket_id}' status updated: {old_status} → {status}."
    return f"Ticket '{ticket_id}' not found."


if __name__ == "__main__":
    mcp.run()
