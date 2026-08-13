#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODEL_SLUG_DIR="$APP_ROOT/.models"
MODEL_SLUG_PATH="$MODEL_SLUG_DIR/yolov8m-world.pt"
TESSDATA_DIR="$MODEL_SLUG_DIR/tessdata"
FRA_TRAINEDDATA_PATH="$TESSDATA_DIR/fra.traineddata"

echo "[post_compile] copy lib to vendor folder"
cd "$APP_ROOT"
mkdir -p vendor
cp -r "$APP_ROOT/../document-ia-infra" vendor/

echo "[post_compile] install local lib"
uv pip install -e vendor/document-ia-infra

mkdir -p "$MODEL_SLUG_DIR" "$TESSDATA_DIR"

if [ ! -f "$MODEL_SLUG_PATH" ]; then
  echo "[post_compile] Downloading YOLO-World model to $MODEL_SLUG_PATH"
  uv run python -c "from ultralytics import YOLOWorld; YOLOWorld('$MODEL_SLUG_PATH')"
fi

echo "[post_compile] YOLO-World model bundled at $MODEL_SLUG_PATH"

if [ ! -f "$FRA_TRAINEDDATA_PATH" ]; then
  echo "[post_compile] Downloading French Tesseract data to $FRA_TRAINEDDATA_PATH"
  curl -fL --retry 3 -o "$FRA_TRAINEDDATA_PATH" \
    https://github.com/tesseract-ocr/tessdata_fast/raw/main/fra.traineddata
  chmod 0644 "$FRA_TRAINEDDATA_PATH"
fi

echo "[post_compile] French Tesseract data bundled at $FRA_TRAINEDDATA_PATH"
