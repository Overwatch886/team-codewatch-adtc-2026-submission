#!/usr/bin/env bash
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$WORKSPACE_DIR/venv/bin/activate"

if [ -f "$WORKSPACE_DIR/run_4gb_bounded_server.sh" ]; then
    exec "$WORKSPACE_DIR/run_4gb_bounded_server.sh"
else
    echo "Error: run_4gb_bounded_server.sh not found!"
    exit 1
fi
