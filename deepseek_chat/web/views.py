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
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        role_label = "You" if role == "user" else agent_name
        rows.append(
            f"""
            <div class="msg {role}" data-msg-id="{i}">
                <div class="msg-inner">
                    <div class="meta">
                        <span>{role_label}</span>
                        {"<button class='branch-btn' title='Branch from here'><svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='6' y1='3' x2='6' y2='15'></line><circle cx='18' cy='6' r='3'></circle><circle cx='6' cy='18' r='3'></circle><path d='M18 9a9 9 0 0 1-9 9'></path></svg></button>" if role != 'system' else ""}
                    </div>
                    <div class="content"></div>
                </div>
                <script>
                  (function() {{
                    const nodes = document.getElementsByClassName("content");
                    const last = nodes[nodes.length - 1];
                    if (last) {{
                      last._rawText = {json.dumps(content)};
                      last.textContent = last._rawText;
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
