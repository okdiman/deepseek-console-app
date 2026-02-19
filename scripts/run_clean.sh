#!/bin/sh
set -e
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
find "$PROJECT_ROOT" -name "__pycache__" -type d -exec rm -rf {} +
python -B "$PROJECT_ROOT/main.py"
