#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8501}"

echo "Démarrage de Streamlit Playground sur le port ${PORT}..."

streamlit run src/document_ia_playground/app.py \
  --server.port="${PORT}" \
  --server.address=0.0.0.0
