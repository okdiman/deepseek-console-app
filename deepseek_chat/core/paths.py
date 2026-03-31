import os
from pathlib import Path

# Resolve to an absolute path anchored to the project root so that subprocesses
# (e.g. MCP servers) that may have a different cwd always write to the same location.
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.getenv("DEEPSEEK_DATA_DIR", str(PROJECT_ROOT / "data")))
