from __future__ import annotations

import os
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .state import get_default_agent_name, get_session

# Set up Jinja2 templates directory
TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_PATH)


def render_messages(messages: List[Dict[str, str]], agent_name: str) -> str:
    """
    Render chat messages as HTML blocks for the template.
    """
    import json

    rows = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        role_label = "You" if role == "user" else agent_name
        rows.append(
            f"""
            <div class="msg {role}">
                <div class="meta">{role_label}</div>
                <div class="content"></div>
                <script>
                  (function() {{
                    const nodes = document.getElementsByClassName("content");
                    const last = nodes[nodes.length - 1];
                    if (last) {{
                      last.textContent = {json.dumps(content)};
                    }}
                  }})();
                </script>
            </div>
            """
        )
    return "\n".join(rows)


def render_index(request: Optional[Request] = None) -> str:
    """
    Render the index page using Jinja2 template.
    """
    from .state import get_agent_registry, get_default_agent_id
    
    session = get_session()
    agent_name = get_default_agent_name()
    rendered_messages = render_messages(session.messages(), agent_name)
    agents = get_agent_registry()
    default_agent_id = get_default_agent_id()
    # If request is not provided, create a dummy one for template rendering
    if request is None:
        from starlette.datastructures import URL, Headers, QueryParams
        from starlette.requests import Request as StarletteRequest

        request = StarletteRequest(
            scope={
                "type": "http",
                "headers": Headers({}),
                "query_string": b"",
                "server": ("127.0.0.1", 8000),
                "client": ("127.0.0.1", 12345),
                "method": "GET",
                "path": "/",
                "raw_path": b"/",
                "scheme": "http",
                "root_path": "",
                "query_params": QueryParams(""),
                "url": URL("http://127.0.0.1/"),
            }
        )
    return templates.get_template("index.html").render(
        request=request,
        rendered_messages=rendered_messages,
        agents=agents,
        default_agent_id=default_agent_id,
        agent_name=agent_name,
    )
