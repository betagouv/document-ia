#!/usr/bin/env bash
set -e

# Configuration par défaut
AGENT_ID="${AGENT_ID:-test-agent}"
REPO_URL="${REPO_URL:-git@github.com:etalab-ia/document-ia.git}"
BRANCH="${BRANCH:-wip/ia-agent-env}"
IMAGE_NAME="${IMAGE_NAME:-antigravity-nix:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-antigravity-${AGENT_ID}}"

# Assurer l'existence des répertoires et fichiers nécessaires sur l'hôte
mkdir -p "$HOME/.gemini/antigravity-cli" "$HOME/.gemini/config" "$(pwd)/.uv-cache"
touch "$HOME/.gemini/antigravity-cli/antigravity-oauth-token"
touch "$HOME/.gemini/antigravity-cli/settings.json"
touch "$HOME/.gemini/config/mcp_config.json"

# Détection du socket SSH agent
if [[ "$(uname -s)" == "Darwin" ]]; then
    # Docker Desktop sur macOS intercepte automatiquement ce chemin virtuel géré par sa VM
    SSH_AUTH_MOUNT="/run/host-services/ssh-auth.sock"
elif [ -n "$SSH_AUTH_SOCK" ] && [ -S "$SSH_AUTH_SOCK" ]; then
    # Sur Linux natif, on monte directement le socket SSH de l'hôte
    SSH_AUTH_MOUNT="$SSH_AUTH_SOCK"
else
    SSH_AUTH_MOUNT="/run/host-services/ssh-auth.sock"
fi

echo "==> Démarrage du conteneur Antigravity '${CONTAINER_NAME}'..."
echo "    - Branche : ${BRANCH}"
echo "    - Partage Antigravity : ~/.gemini (auth token + config MCP)"
echo "    - Réseau : host.docker.internal activé"

exec docker run -it --rm \
  --name "${CONTAINER_NAME}" \
  --add-host=host.docker.internal:host-gateway \
  -e AGENT_ID="${AGENT_ID}" \
  -e REPO_URL="${REPO_URL}" \
  -e BRANCH="${BRANCH}" \
  -e SSH_AUTH_SOCK=/ssh-agent \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "${SSH_AUTH_MOUNT}:/ssh-agent" \
  -v "$(pwd)/.uv-cache:/root/.cache/uv" \
  -v "$HOME/.gemini/antigravity-cli/antigravity-oauth-token:/root/.gemini/antigravity-cli/antigravity-oauth-token" \
  -v "$HOME/.gemini/antigravity-cli/settings.json:/root/.gemini/antigravity-cli/settings.json" \
  -v "$HOME/.gemini/config:/root/.gemini/config" \
  "${IMAGE_NAME}" "${@:-bash}"
