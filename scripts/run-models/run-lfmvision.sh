#!/bin/bash

# Base Configurations
LLAMA_SERVER_BIN="/home/overwatch886/local_ai_workspace/software/llama.cpp/build/bin/llama-server" # Path to your built llama-server binary
MODEL_PATH="/home/overwatch886/local_ai_workspace/models/lnn/vision/LFM2.5-VL-1.6B-Q4_0.gguf"
PROJ_PATH="/home/overwatch886/local_ai_workspace/models/lnn/vision/mmproj-LFM2.5-VL-1.6b-Q8_0.gguf"
PORT=8083
LOG_FILE="/home/overwatch886/local_ai_workspace/logs/lfm_vision_zone.log"

# 1. Thread Pinning Optimization (-t 4 leaves 2 physical cores fully free for Linux/Proxy tasks)
THREADS=6

# 2. Context Window Cap
CTX=6800

# 3. Batch Flattener Optimization (-b 256 / -ub 256 drops the CPU thermal/spike load)
BATCH=256

# Create the logs directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

# 1. System-Level Optimizations (Run inline before model launch)
source "$(dirname "$0")/prep_system.sh"

# Kill any dangling process left on this port before firing up
fuser -k ${PORT}/tcp >/dev/null 2>&1

# Execute server locked directly inside physical RAM with logging backgrounded properly
echo "Spinning up LFM vision model on port ${PORT}..."

exec env RADV_PERFTEST=nosam MALLOC_ARENA_MAX=1 MALLOC_TRIM_THRESHOLD_=-1 ${LLAMA_SERVER_BIN} \
  -m "${MODEL_PATH}" \
  --mmproj "${PROJ_PATH}" \
  -c ${CTX} \
  -b ${BATCH} \
  -ub ${BATCH} \
  -t ${THREADS} \
  --port ${PORT} \
  --threads-http 2 \
  --parallel 1 \
  --cache-ram 512 \
  --mlock \
  --jinja \
  --flash-attn on \
  -ngl 99
  
