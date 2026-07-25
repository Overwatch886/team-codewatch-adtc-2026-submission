#!/bin/bash

# Base Configurations
LLAMA_SERVER_BIN="/home/overwatch886/local_ai_workspace/software/llama.cpp/build/bin/llama-server" # Update if your binary path is elsewhere
MODEL_PATH="/home/overwatch886/local_ai_workspace/models/granite/granite-4.0-h-micro-Q4_K_M.gguf" # Update to exact filename
PORT=8081
#LOG_FILE="/home/overwatch886/local_ai_workspace/logs/granite_zone.log"

# 1. Thread Pinning Optimization (-t 4 leaves 2 physical cores fully free for Linux/Proxy tasks)
THREADS=2

# 2. Context Window Cap
CTX=16384

# 3. Batch Flattener Optimization (-b 256 / -ub 256 drops the CPU thermal/spike load)
BATCH=256

# 4. Speculative N-Gram Engine Acceleration
# This enables the built-in token pattern dictionary cache. 
# When writing code matrices, it guesses repetitive structures instantly.
SPEC_FLAGS="--spec-type ngram-mod --spec-ngram-mod-n-match 24"

# 1. System-Level Optimizations (Run inline before model launch)
source "$(dirname "$0")/prep_system.sh"

# Kill any dangling process left on port 8081 before firing up
fuser -k ${PORT}/tcp >/dev/null 2>&1

# Execute server locked directly inside physical RAM
echo "Spinning up Granite with N-Gram optimization on port ${PORT}..."

RADV_PERFTEST=nosam ${LLAMA_SERVER_BIN} \
  -m "${MODEL_PATH}" \
  -c ${CTX} \
  -b ${BATCH} \
  -ub ${BATCH} \
  -t ${THREADS} \
  --port ${PORT} \
  --threads-http 2 \
  --cache-ram 512 \
  --mlock \
  --mmap \
  -ngl 99
  --flash-attn on \
  -ngl 99 \
  --jinja \
  ${SPEC_FLAGS}
