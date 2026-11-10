#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/model_benchmark.py" \
  --mode gpu \
  --questions-file "$SCRIPT_DIR/benchmark_questions_50.txt" \
  --require-answer-llm \
  --embedding-container model-serving-bge-m3-1 \
  --rerank-container qwen3-reranker-4b \
  "$@"
