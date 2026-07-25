#!/usr/bin/env bash
# download_models.sh - Download supporting models for ASR, TTS, Router, and RAG.
#
# Rules:
#   - Must be idempotent (safe to run multiple times).
#   - Must download without any credentials (public URL only).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(dirname "$HERE")"
MODELS_DIR="$WORKSPACE_DIR/models"

# 1. Directories
mkdir -p "$MODELS_DIR/audio/kokoro"
mkdir -p "$MODELS_DIR/gliner2_quantized"
mkdir -p "$WORKSPACE_DIR/answerai-colbert-small-v1"

# Helper download function
download_file() {
    local url="$1"
    local dest="$2"
    if [[ -f "$dest" ]]; then
        echo "File already exists: $dest — skipping."
        return 0
    fi
    echo "Downloading $url → $dest..."
    if command -v curl > /dev/null 2>&1; then
        curl -L --fail --progress-bar -o "$dest.partial" "$url"
    elif command -v wget > /dev/null 2>&1; then
        wget -q --show-progress -O "$dest.partial" "$url"
    else
        echo "Error: neither curl nor wget found" >&2
        return 1
    fi
    mv "$dest.partial" "$dest"
}

# 2. Nemotron ASR
download_file \
    "https://huggingface.co/cstr/nemotron-3.5-asr-streaming-0.6b-GGUF/resolve/main/nemotron-3.5-asr-streaming-0.6b-q5_k.gguf" \
    "$MODELS_DIR/audio/nemotron-3.5-asr-streaming-0.6b-q5_k.gguf"

# 3. Parakeet ASR
download_file \
    "https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/main/tdt-0.6b-v2-q5_k.gguf" \
    "$MODELS_DIR/audio/tdt-0.6b-v2-q5_k.gguf"

# 4. Kokoro TTS (FP32 model — optimized for AVX2 execution on Zen 2/Zen 3 CPUs without VNNI)
download_file \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" \
    "$MODELS_DIR/audio/kokoro/kokoro-v1.0.onnx"

download_file \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" \
    "$MODELS_DIR/audio/kokoro/voices-v1.0.bin"

# 5. GLiner ONNX
GLINER_FILES=(
    "classifier_head.onnx"
    "encoder.onnx"
    "gliner4j_config.json"
    "scoring_head.onnx"
    "span_rep.onnx"
    "tokenizer.json"
    "tokenizer_config.json"
)
for file in "${GLINER_FILES[@]}"; do
    download_file \
        "https://huggingface.co/gravitee-io/gliner4j-gliner2-base-v1/resolve/main/$file" \
        "$MODELS_DIR/gliner2_quantized/$file"
done

# 6. ColBERT ONNX
COLBERT_FILES=(
    "config.json"
    "model_int8.onnx"
    "special_tokens_map.json"
    "tokenizer.json"
    "tokenizer_config.json"
    "vocab.txt"
)
for file in "${COLBERT_FILES[@]}"; do
    download_file \
        "https://huggingface.co/AnswerDotAI/answerai-colbert-small-v1/resolve/main/$file" \
        "$WORKSPACE_DIR/answerai-colbert-small-v1/$file"
done

echo "🎉 All supporting models downloaded successfully!"
