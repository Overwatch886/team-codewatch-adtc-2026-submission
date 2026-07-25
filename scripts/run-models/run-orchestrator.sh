#!/bin/bash

# --- Configurations ---
LLAMA_DIR="$HOME/local_ai_workspace/software/llama.cpp"
MODEL_PATH="$HOME/local_ai_workspace/models/lnn/LFM2.5-350M-Q4_K_M.gguf"
PORT=8080
THREADS=6
CTX_SIZE=16000

echo -e "\e[34m[Orchestrator] \e[0m Initializing 350M Core Engine..."

# --- 1. Sanity Check: Ensure Model Exists ---
if [ ! -f "$MODEL_PATH" ]; then
    echo -e "\e[31m[ERROR] \e[0m Model file not found at: $MODEL_PATH"
    echo "Please verify your path or filename and try again."
    exit 1
fi

# --- 2. Port Guard: Clear Port 8080 ---
if lsof -i :$PORT > /dev/null 2>&1; then
    echo -e "\e[33m[Orchestrator] \e[0m Port $PORT is busy. Clearing old instances..."
    # 1. System-Level Optimizations (Run inline before model launch)
source "$(dirname "$0")/prep_system.sh"

fuser -k $PORT/tcp 2>/dev/null
    sleep 0.5
fi

# --- 3. Jump to Directory and Execute ---
cd "$LLAMA_DIR" || { echo -e "\e[31m[ERROR] \e[0m Could not change directory to $LLAMA_DIR"; exit 1; }

echo -e "\e[32m[Orchestrator] \e[0m Launching llama-server on port $PORT ($THREADS Threads)..."
echo "----------------------------------------------------------------"

RADV_PERFTEST=nosam ./build/bin/llama-server \
    -m "$MODEL_PATH" \
    --port "$PORT" \
    -t "$THREADS" \
    --flash-attn on \
    --no-context-shift \
    -ngl 99 \
    --mlock \
    --ctx-size "$CTX_SIZE"
    -ctk q8_0 \
    -ctv q8_0
