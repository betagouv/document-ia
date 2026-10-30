#!/usr/bin/env bash
# Scan gitleaks des commits sortants, exécuté par le hook pre-push de pre-commit.
#
# pre-commit transmet la plage de commits poussés via des variables
# d'environnement (PRE_COMMIT_FROM_REF / PRE_COMMIT_TO_REF). Au moment du
# push, l'index est vide : le hook pre-commit de gitleaks (scan --staged)
# ne verrait rien. Ce script scanne donc uniquement les commits sortants.
#
# Échec (code de sortie non nul) => push bloqué.

set -euo pipefail

CONFIG=".gitleaks.toml"
BASELINE=".gitleaks-baseline.json"

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "erreur : gitleaks est introuvable dans le PATH." >&2
  echo "Installez gitleaks v8.30.1 : https://github.com/gitleaks/gitleaks/releases" >&2
  exit 1
fi

if [ -n "${PRE_COMMIT_FROM_REF:-}" ] && [ -n "${PRE_COMMIT_TO_REF:-}" ]; then
  # Cas standard : mise à jour d'une branche distante existante.
  RANGE="${PRE_COMMIT_FROM_REF}..${PRE_COMMIT_TO_REF}"
else
  # Première poussée d'une branche dont l'historique n'est pas encore sur
  # le distant : tout ce qui n'est pas déjà présent sur le remote
  # (la branche poussée, pas nécessairement HEAD).
  BRANCH="${PRE_COMMIT_LOCAL_BRANCH:-HEAD}"
  REMOTE="${PRE_COMMIT_REMOTE_NAME:-origin}"
  RANGE="${BRANCH} --not --remotes=${REMOTE}"
fi

gitleaks git \
  --log-opts="${RANGE}" \
  --config "${CONFIG}" \
  --baseline-path "${BASELINE}" \
  --redact --verbose
