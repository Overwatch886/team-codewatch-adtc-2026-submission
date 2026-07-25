#!/bin/bash

# Base Configurations
LLAMA_SERVER_BIN="/home/overwatch886/local_ai_workspace/llama.cpp/llama-server"

# Core Vision Model & Projector Paths
MODEL_PATH="/home/overwatch886/local_ai_workspace/models/lnn/vision/LFM2.5-VL-1.6B-Q4_0.gguf"
PROJ_PATH="/home/overwatch886/local_ai_workspace/models/lnn/vision/mmproj-LFM2.5-VL-1.6b-Q8_0.gguf"

PORT=8081
LOG_FILE="/home/overwatch886/local_ai_workspace/logs/vision_zone.log"

# System Optimization Boundaries
THREADS=6
CTX=2048
BATCH=256 # Vision matrix evaluations are heavy, keep this low!

# Wipe out whatever is currently using our model port
# 1. System-Level Optimizations (Run inline before model launch)
source "$(dirname "$0")/prep_system.sh"

fuser -k ${PORT}/tcp >/dev/null 2>&1

echo "Spinning up Multimodal Vision Engine on port ${PORT}..."

# Notice the explicit execution of the multimodal projector path
exec env RADV_PERFTEST=nosam ${LLAMA_SERVER_BIN} \
  -m "${MODEL_PATH}" \
  --mmproj "${PROJ_PATH}" \
  -c ${CTX} \
  -b ${BATCH} \
  -ub ${BATCH} \
  -t ${THREADS} \
  --port ${PORT} \
  --mlock \
  --flash-attn on \
  -ngl 99 > "${LOG_FILE}" 2>&1 & \
  -ctk q8_0 \
  -ctv q8_0
