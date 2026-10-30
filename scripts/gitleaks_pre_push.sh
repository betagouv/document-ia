#!/usr/bin/env bash
# Scan Gitleaks des commits sortants d'une référence poussée.
#
# Le script natif scripts/pre-push transmet chaque ligne du protocole Git :
# <ref locale> <SHA local> <ref distante> <SHA distant> <remote>
# Il appelle ensuite les hooks pre-commit avec les deux SHA. Les tests manuels
# peuvent aussi fournir PRE_COMMIT_FROM_REF / PRE_COMMIT_TO_REF ou, à défaut,
# PRE_COMMIT_LOCAL_BRANCH et PRE_COMMIT_REMOTE_NAME.
#
# Échec (code de sortie non nul) => push bloqué.

set -euo pipefail

CONFIG=".gitleaks.toml"
BASELINE=".gitleaks-baseline.json"
ZERO_SHA="0000000000000000000000000000000000000000"

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "erreur : gitleaks est introuvable dans le PATH." >&2
  echo "Installez gitleaks v8.30.1 : https://github.com/gitleaks/gitleaks/releases" >&2
  exit 1
fi

if [ "$#" -eq 5 ]; then
  LOCAL_REF="$1"
  LOCAL_SHA="$2"
  REMOTE_SHA="$4"
  REMOTE="$5"
elif [ "$#" -eq 0 ]; then
  LOCAL_REF="${PRE_COMMIT_LOCAL_BRANCH:-HEAD}"
  LOCAL_SHA="${PRE_COMMIT_TO_REF:-}"
  REMOTE_SHA="${PRE_COMMIT_FROM_REF:-}"
  REMOTE="${PRE_COMMIT_REMOTE_NAME:-origin}"
else
  echo "usage : $0 [<ref locale> <SHA local> <ref distante> <SHA distant> <remote>]" >&2
  exit 1
fi

if [ -z "$LOCAL_SHA" ] || [ "$LOCAL_SHA" = "$ZERO_SHA" ]; then
  # Une suppression de référence ne publie aucun nouveau commit.
  exit 0
fi

if [ -n "$REMOTE_SHA" ] && [ "$REMOTE_SHA" != "$ZERO_SHA" ]; then
  RANGE="${REMOTE_SHA}..${LOCAL_SHA}"
else
  # Nouvelle branche ou nouveau tag : scanner les commits absents de toutes
  # les branches distantes. Utiliser --remotes exclurait les ancêtres d'autres
  # tags déjà publiés.
  RANGE="${LOCAL_REF} --not --remotes=${REMOTE}"
fi

gitleaks git \
  --log-opts="${RANGE}" \
  --config "${CONFIG}" \
  --baseline-path "${BASELINE}" \
  --redact --verbose
