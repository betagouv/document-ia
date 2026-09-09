#!/usr/bin/env bash
set -euo pipefail

# Prevent glibc memory fragmentation in Scalingo Linux containers
export MALLOC_ARENA_MAX=${MALLOC_ARENA_MAX:-2}

# Limit CPU thread pools for PyTorch, OpenCV, OpenMP to prevent memory inflation
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-1}
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-1}
export OPENCV_FOR_THREADS_NUM=${OPENCV_FOR_THREADS_NUM:-1}


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

export QRDET_WEIGHTS_DIR="$APP_ROOT/.models/qrdet"
if [ -d "$QRDET_WEIGHTS_DIR" ]; then
  echo "[boot] QRDet model directory available at $QRDET_WEIGHTS_DIR"
fi

if [ ! -f "$TESSDATA_DIR/fra.traineddata" ]; then
  echo "[boot] French Tesseract data is missing: $TESSDATA_DIR/fra.traineddata" >&2
  exit 1
fi

exec python -u src/document_ia_worker/main.py
