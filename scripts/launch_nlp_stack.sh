#!/bin/bash
source /home/overwatch886/local_ai_workspace/venv/bin/activate

echo "🚀 Launching Local Embedding Engine Node on Port 8082..."
infinity_emb v2 --model-id BAAI/bge-large-en-v1.5 --port 8082 --device cpu --engine hf &

echo "🚀 Launching Local Similarity Reranker Engine Node on Port 8083..."
infinity_emb v2 --model-id BAAI/bge-reranker-large --port 8083 --device cpu --engine hf &

echo "✨ All background NLP auxiliary data layers are scaling up."
wait
