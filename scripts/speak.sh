#!/bin/bash
# Shell wrapper for Kokoro TTS speak.py
WORKSPACE_DIR="/home/overwatch886/local_ai_workspace"
"${WORKSPACE_DIR}/venv/bin/python3" "${WORKSPACE_DIR}/scripts/speak.py" "$@"
