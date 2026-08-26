#!/usr/bin/env bash
set -euo pipefail

# The model downloaded during post_compile is bundled in the slug.
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_BUNDLED_PATH="$APP_ROOT/.models/yolov8m-world.pt"
export TESSDATA_PREFIX="$APP_ROOT/.models/tessdata"
TESSDATA_DIR="$TESSDATA_PREFIX"

if [ ! -f "$MODEL_BUNDLED_PATH" ]; then
  echo "[boot] YOLO-World model is missing: $MODEL_BUNDLED_PATH" >&2
  exit 1
fi
export YOLOWORLD_PATH="$MODEL_BUNDLED_PATH"
echo "[boot] YOLO-World model available at $YOLOWORLD_PATH"

if [ ! -f "$TESSDATA_DIR/fra.traineddata" ]; then
  echo "[boot] French Tesseract data is missing: $TESSDATA_DIR/fra.traineddata" >&2
  exit 1
fi

exec python -u src/document_ia_worker/main.py
