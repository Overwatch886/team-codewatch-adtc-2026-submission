#!/bin/bash
WORKSPACE_DIR="/home/overwatch886/local_ai_workspace"
VENV_PYTHON="${WORKSPACE_DIR}/venv/bin/python3"
VENV_LITELLM="${WORKSPACE_DIR}/venv/bin/litellm"

export LD_LIBRARY_PATH="/usr/local/lib/ollama/rocm_v7_2:${LD_LIBRARY_PATH:-}"

echo "🧹 Clearing existing processes on ports 8081, 8082, 8085..."
fuser -k 8081/tcp 2>/dev/null
fuser -k 8082/tcp 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
sleep 1

echo "🚀 Starting Granite 3.1 3B A800M Model Server (Port 8081)..."
RADV_PERFTEST=nosam /home/overwatch886/local_ai_workspace/software/llama.cpp/build/bin/llama-server \
  -m /home/overwatch886/local_ai_workspace/code-persona-adtc-2026-submission/model/granite-3.1-3b-a800m-instruct-IQ4_XS.gguf \
  -c 4096 -b 2048 -ub 512 -t 4 \
  --port 8081 --threads-http 2 --parallel 1 --cache-ram 128 \
  -ctk q8_0 -ctv q8_0 \
  --mmap -ngl 99 --flash-attn on --jinja \
  --alias "granite-3.1-3b-a800m-instruct" \
  --spec-type ngram-mod --spec-ngram-mod-n-match 16 --spec-ngram-mod-n-max 5 --spec-ngram-mod-n-min 1 > /tmp/granite_test.log 2>&1 &

echo "⏳ Waiting for Granite Model Server to load on port 8081..."
until curl -s http://127.0.0.1:8081/health > /dev/null; do
    sleep 2
done
echo "✓ Granite 3.1 3B A800M Model Server is ONLINE."

echo "🚀 Starting Local Orchestrator Server (Port 8085)..."
"${VENV_PYTHON}" "${WORKSPACE_DIR}/scripts/orchestrator_server.py" > "${WORKSPACE_DIR}/orchestrator_server.log" 2>&1 &

echo "⏳ Waiting for Orchestrator Server to load on port 8085..."
until curl -s http://127.0.0.1:8085/ > /dev/null; do
    sleep 1
done
echo "✓ Orchestrator Server is ONLINE at http://localhost:8085"

# Keep the shell task running persistently to prevent child processes from being reaped/killed
tail -f /dev/null
