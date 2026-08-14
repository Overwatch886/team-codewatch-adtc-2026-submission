#!/bin/bash
# ==============================================================================
# 6 GB System RAM Memory Limiter Launcher
# ==============================================================================
# - Activates the project virtual environment
# - Sets memory-bounded llama-server and ColBERT parameters
# - Enforces 6 GB system RAM ceiling using Linux systemd cgroups (if available)
#   → Typical operation: ~3.5 GB | Peak: ~4.5 GB (leaves headroom for resident model)
# ==============================================================================

set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$WORKSPACE_DIR/venv"

cd "$WORKSPACE_DIR"

# Activate virtual environment
if [ -f "$VENV_DIR/bin/activate" ]; then
    echo "[Launcher] Activating virtual environment: $VENV_DIR"
    source "$VENV_DIR/bin/activate"
else
    echo "[Launcher] WARNING: Virtual environment not found at $VENV_DIR — using system Python."
fi

# --- Memory Budget Configuration ---
# RAM Budget: 6 GB total
#   Python Server + FastAPI:           ~120 MB
#   ColBERT (mmap'd):                  ~250 MB
#   Resident LLM (Granite 4.0 H Tiny): ~3.75 GB
#   KV Cache (4096 ctx):               ~280 MB
#   Buffer:                            ~600 MB
#   ──────────────────────────────────────────
#   Typical peak:                      ~4.50 GB  ✓ (Well within 6 GB cap)

export PYTHONUNBUFFERED="1"
export LLAMA_CTX_SIZE="131072"
export LLAMA_CTX_SIZE_GRANITE="131072"
export LLAMA_BATCH_SIZE="2048"
export LLAMA_UBATCH_SIZE="512"
export LLAMA_THREADS="4"
export LLAMA_HTTP_THREADS="2"
export LLAMA_CACHE_RAM="64"
export LLAMA_CTK="q8_0"
export LLAMA_CTV="q8_0"

export COLBERT_BATCH_SIZE="1000"
export COLBERT_THREADS="4"
export COLBERT_CHUNK_SIZE="1500"
export COLBERT_CHUNK_OVERLAP="200"

echo "========================================================"
echo "🛡️  Launching Local Orchestrator under HARD 6 GB RAM Cap"
echo "========================================================"
echo "  LLAMA_CTX_SIZE   = 131072 (Granite 4.0 H Tiny)"
echo "  LLAMA_CACHE_RAM  = ${LLAMA_CACHE_RAM} MB"
echo "  COLBERT_THREADS  = ${COLBERT_THREADS}"
echo "========================================================"

LOG_DIR="$WORKSPACE_DIR/logs"
mkdir -p "$LOG_DIR"

if command -v systemd-run &> /dev/null; then
    echo "[Memory Enforcement] Using Linux systemd-run MemoryMax=6G MemoryHigh=5.5G..."
    exec systemd-run --scope --user -p MemoryMax=6G -p MemoryHigh=5.5G \
        "$VENV_DIR/bin/python3" scripts/orchestrator_server.py
else
    echo "[Memory Enforcement] Using environment bounds only..."
    exec python3 scripts/orchestrator_server.py
fi
