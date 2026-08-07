#!/bin/bash
# ==============================================================================
# Hard 4 GB System RAM Memory Limiter Launcher
# ==============================================================================
# - Activates the project virtual environment
# - Sets memory-bounded llama-server and ColBERT parameters
# - Enforces 4 GB system RAM ceiling using Linux systemd cgroups (if available)
#   → Typical operation: ~3.14 GB | Vision peak: ~3.8 GB (resident model stays loaded)
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
# RAM Budget: 4 GB total
#   Python Server + FastAPI:    ~120 MB
#   ColBERT (mmap'd):           ~250 MB
#   Resident LLM (Granite 4.1): ~2.09 GB
#   KV Cache (4096 ctx):        ~280 MB
#   Buffer:                     ~400 MB
#   ─────────────────────────────────────
#   Typical peak:               ~3.14 GB  ✓
#
#   Vision calls (LFM2.5-VL 695MB + mmproj 583MB = ~1.28 GB):
#   Resident model stays loaded → brief peak of ~3.8 GB (under 4 GB ceiling).

export LLAMA_CTX_SIZE_GRANITE="10240"
export LLAMA_CTX_SIZE_QWEN="10240"
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
echo "🛡️  Launching Local Orchestrator under HARD 4 GB RAM Cap"
echo "========================================================"
echo "  LLAMA_CTX_SIZE   = 10240 (Fast Ship Qwen) | 4096 (Granite)"
echo "  LLAMA_CACHE_RAM  = ${LLAMA_CACHE_RAM} MB"
echo "  COLBERT_THREADS  = ${COLBERT_THREADS}"
echo "========================================================"


if command -v systemd-run &> /dev/null; then
    echo "[Memory Enforcement] Using Linux systemd-run MemoryMax=4G (vision-safe ceiling)..."
    exec systemd-run --scope --user -p MemoryMax=4G -p MemoryHigh=3.7G \
        "$VENV_DIR/bin/python3" scripts/orchestrator_server.py
else
    echo "[Memory Enforcement] Using environment bounds only (systemd not available)."
    exec python3 scripts/orchestrator_server.py
fi
