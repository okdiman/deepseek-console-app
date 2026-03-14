import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DEEPSEEK_DATA_DIR", "data"))
