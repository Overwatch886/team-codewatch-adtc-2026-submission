#!/usr/bin/env bash
# download_models.sh — Download all supporting models for LowaCode AI Tutor.
#
# NOTE: The competition benchmark model is handled separately by download_model.sh.
#       This script downloads everything else the system needs to run fully:
#         • Granite 4.1 3B  (Socratic / Auto mode LLM)
#         • Qwen 2.5 Coder 3B  (Ship Fast coding LLM)
#         • ColBERT ONNX  (semantic search / RAG)
#         • Kokoro TTS  (text-to-speech, optional)
#         • Parakeet TDT ASR  (speech-to-text, optional)
#
# Rules:
#   - Idempotent (safe to run multiple times).
#   - No credentials needed — all public URLs.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[download_models]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
skip()    { echo -e "${YELLOW}[→ skip]${NC} $*"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$HERE/model"

mkdir -p "$MODEL_DIR/granite"
mkdir -p "$MODEL_DIR/qwen"
mkdir -p "$MODEL_DIR/audio/kokoro"
mkdir -p "$HERE/answerai-colbert-small-v1"

# ── Helper: direct URL download ────────────────────────────────────────────────
download_file() {
    local url="$1" dest="$2"
    if [[ -f "$dest" ]]; then skip "$(basename "$dest") already exists."; return 0; fi
    info "Downloading $(basename "$dest")…"
    if command -v curl > /dev/null 2>&1; then
        curl -L --fail --progress-bar -o "$dest.partial" "$url"
    elif command -v wget > /dev/null 2>&1; then
        wget -q --show-progress -O "$dest.partial" "$url"
    else
        echo "Error: neither curl nor wget found" >&2; return 1
    fi
    mv "$dest.partial" "$dest"
    success "$(basename "$dest") done."
}

# ── Helper: HuggingFace download (cli preferred, URL fallback) ─────────────────
hf_download() {
    local repo="$1" file="$2" dest="$3"
    if [[ -f "$dest" ]]; then skip "$(basename "$dest") already exists."; return 0; fi
    info "Downloading $(basename "$dest") from HuggingFace (${repo})…"
    HF_CLI=""
    for c in "$HERE/venv/bin/hf" "$HERE/venv/bin/huggingface-cli" "$HOME/.local/bin/hf" "$HOME/.local/bin/huggingface-cli" \
              "$(command -v hf 2>/dev/null || true)" "$(command -v huggingface-cli 2>/dev/null || true)"; do
        [[ -x "$c" ]] && { HF_CLI="$c"; break; }
    done
    if [[ -n "$HF_CLI" ]]; then
        "$HF_CLI" download "$repo" "$file" \
            --local-dir "$(dirname "$dest")" --local-dir-use-symlinks False
    else
        download_file "https://huggingface.co/${repo}/resolve/main/${file}" "$dest"
    fi
    success "$(basename "$dest") ready."
}

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        LowaCode AI Tutor — Model Downloader         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# [1/5] Granite 4.1 3B Q4_K_M — Socratic Tutor / Auto mode
info "[1/5] Granite 4.1 3B (Socratic Tutor / Auto mode)"
hf_download \
    "ibm-granite/granite-4.1-3b-GGUF" \
    "granite-4.1-3b-Q4_K_M.gguf" \
    "$MODEL_DIR/granite/granite-4.1-3b-Q4_K_M.gguf"

# [2/5] Qwen 2.5 Coder 3B Q4_K_M — Ship Fast coding mode
info "[2/5] Qwen 2.5 Coder 3B (Ship Fast / coding mode)"
hf_download \
    "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF" \
    "qwen2.5-coder-3b-instruct-q4_k_m.gguf" \
    "$MODEL_DIR/qwen/qwen2.5-coder-3b-instruct-q4_k_m.gguf"

# [3/5] ColBERT ONNX — semantic RAG search
info "[3/5] ColBERT ONNX (answerai-colbert-small-v1)"
for f in config.json model_int8.onnx special_tokens_map.json \
          tokenizer.json tokenizer_config.json vocab.txt; do
    download_file \
        "https://huggingface.co/AnswerDotAI/answerai-colbert-small-v1/resolve/main/$f" \
        "$HERE/answerai-colbert-small-v1/$f"
done

# [4/5] Kokoro TTS — text-to-speech (optional)
info "[4/5] Kokoro TTS v1.0"
download_file \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" \
    "$MODEL_DIR/audio/kokoro/kokoro-v1.0.onnx"
download_file \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" \
    "$MODEL_DIR/audio/kokoro/voices-v1.0.bin"

# [5/5] Parakeet TDT — speech-to-text (optional)
info "[5/5] Parakeet TDT ASR"
download_file \
    "https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/main/tdt-0.6b-v2-q5_k.gguf" \
    "$MODEL_DIR/audio/tdt-0.6b-v2-q5_k.gguf"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  🎉  All supporting models downloaded!              ║"
echo "║                                                      ║"
echo "║  Next steps:                                         ║"
echo "║    1. ./download_model.sh   (competition model)     ║"
echo "║    2. ./install_linux.sh    (or install_wsl.sh)     ║"
echo "║    3. ./start.sh            (launch server)         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
