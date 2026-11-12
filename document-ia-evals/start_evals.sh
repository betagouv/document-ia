#!/usr/bin/env bash
set -euo pipefail

echo "==> Running database migrations (Alembic)..."
alembic upgrade head

echo "==> Generating Streamlit OIDC secrets configuration..."
python -m document_ia_evals.utils.auth_secrets || true

PORT="${PORT:-8501}"
echo "==> Starting Streamlit application on port ${PORT}..."
exec streamlit run src/document_ia_evals/app.py \
  --server.port="${PORT}" \
  --server.address="0.0.0.0"
