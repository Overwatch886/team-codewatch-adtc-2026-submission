#!/bin/bash

# Base Configurations
LLAMA_SERVER_BIN="/home/overwatch886/local_ai_workspace/software/llama.cpp/build/bin/llama-server" # Path to your built llama-server binary
MODEL_PATH="/home/overwatch886/local_ai_workspace/models/qwen/Qwen3-4B-Thinking-2507-Q4_K_M.gguf" # Exact GGUF filename
PORT=8081
LOG_FILE="/home/overwatch886/local_ai_workspace/logs/qwen_zone.log"

# 1. Thread Pinning Optimization (-t 4 leaves 2 physical cores fully free for Linux/Proxy tasks)
THREADS=2

# 2. Context Window Cap
CTX=6800

# 3. Batch Flattener Optimization (-b 256 / -ub 256 drops the CPU thermal/spike load)
BATCH=256

# 4. Speculative N-Gram Engine Acceleration
# This enables the built-in token pattern dictionary cache. 
# When writing code matrices, it guesses repetitive structures instantly.
SPEC_FLAGS="--spec-type ngram-mod --spec-ngram-mod-n-match 24"

# Create the logs directory if it doesn't exist

# 1. System-Level Optimizations (Run inline before model launch)
source "$(dirname "$0")/prep_system.sh"

# Kill any dangling process left on port 8081 before firing up
fuser -k ${PORT}/tcp >/dev/null 2>&1

# Execute server locked directly inside physical RAM with logging backgrounded properly
echo "Spinning up Qwen with N-Gram optimization on port ${PORT}..."

exec env RADV_PERFTEST=nosam MALLOC_ARENA_MAX=1 MALLOC_TRIM_THRESHOLD_=-1 ${LLAMA_SERVER_BIN} \
  -m "${MODEL_PATH}" \
  -c ${CTX} \
  -b ${BATCH} \
  -ub ${BATCH} \
  -t ${THREADS} \
  --port ${PORT} \
  --threads-http 2 \
  --parallel 1 \
  --cache-ram 512 \
  --mlock \
  --mmap \
  --flash-attn on \
  -ngl 99 \
  --jinja \
  ${SPEC_FLAGS}
  
