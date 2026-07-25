#!/bin/bash
WORKSPACE_DIR="/home/overwatch886/local_ai_workspace"
VENV_PYTHON="${WORKSPACE_DIR}/venv/bin/python3"
VENV_LITELLM="${WORKSPACE_DIR}/venv/bin/litellm"

echo "🧹 Clearing existing processes on ports 8081, 8082, 8085..."
fuser -k 8081/tcp 2>/dev/null
fuser -k 8082/tcp 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
sleep 1

echo "🚀 Starting Granite Model Server (Port 8081)..."
bash "${WORKSPACE_DIR}/scripts/run-models/run-granite.sh" > /dev/null 2>&1 &

echo "⏳ Waiting for Granite to load on port 8081..."
until curl -s http://127.0.0.1:8081/health > /dev/null; do
    sleep 2
done
echo "✓ Granite Model Server is ONLINE."


echo "🚀 Starting LiteLLM Proxy (Port 8082)..."
"${VENV_LITELLM}" --config "${WORKSPACE_DIR}/litellm/config.yaml" --port 8082 > /dev/null 2>&1 &

echo "⏳ Waiting for LiteLLM to load on port 8082..."
until curl -s http://127.0.0.1:8082/health > /dev/null; do
    sleep 1
done
echo "✓ LiteLLM Proxy is ONLINE."

echo "🚀 Starting Local Orchestrator Server (Port 8085)..."
"${VENV_PYTHON}" "${WORKSPACE_DIR}/scripts/orchestrator_server.py" > "${WORKSPACE_DIR}/orchestrator_server.log" 2>&1 &

echo "⏳ Waiting for Orchestrator Server to load on port 8085..."
until curl -s http://127.0.0.1:8085/ > /dev/null; do
    sleep 1
done
echo "✓ Orchestrator Server is ONLINE at http://localhost:8085"

# Keep the shell task running persistently to prevent child processes from being reaped/killed
tail -f /dev/null
