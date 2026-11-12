#!/usr/bin/env bash
set -e

# Configuration par défaut
AGENT_ID="${AGENT_ID:-test-agent}"
REPO_URL="${REPO_URL:-git@github.com:etalab-ia/document-ia.git}"
BRANCH="${BRANCH:-wip/ia-agent-env}"
IMAGE_NAME="${IMAGE_NAME:-antigravity-nix:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-antigravity-${AGENT_ID}}"

# Répertoire dédié de persistance Antigravity pour ce conteneur
AGENT_DATA_DIR="${HOME}/.gemini/agent-containers/${AGENT_ID}/antigravity-cli"
mkdir -p "${AGENT_DATA_DIR}/cache" "$HOME/.gemini/config" "$HOME/.agentmemory" "$(pwd)/.uv-cache"
touch "$HOME/.gemini/config/mcp_config.json"

# Synchronisation du token OAuth depuis l'hôte
if [ -f "$HOME/.gemini/antigravity-cli/antigravity-oauth-token" ]; then
    cp -f "$HOME/.gemini/antigravity-cli/antigravity-oauth-token" "${AGENT_DATA_DIR}/antigravity-oauth-token"
    chmod 600 "${AGENT_DATA_DIR}/antigravity-oauth-token"
fi

# Initialisation de settings.json depuis l'hôte si inexistant ou mis à jour
if [ -f "$HOME/.gemini/antigravity-cli/settings.json" ]; then
    if [ ! -f "${AGENT_DATA_DIR}/settings.json" ] || [ "$HOME/.gemini/antigravity-cli/settings.json" -nt "${AGENT_DATA_DIR}/settings.json" ]; then
        cp -f "$HOME/.gemini/antigravity-cli/settings.json" "${AGENT_DATA_DIR}/settings.json"
    fi
fi

# Pré-remplir l'état d'onboarding pour éviter l'assistant interactif (choix du thème/style de terminal)
if [ ! -f "${AGENT_DATA_DIR}/cache/onboarding.json" ]; then
    if [ -f "$HOME/.gemini/antigravity-cli/cache/onboarding.json" ]; then
        cp -f "$HOME/.gemini/antigravity-cli/cache/onboarding.json" "${AGENT_DATA_DIR}/cache/onboarding.json"
    else
        echo '{"consumerOnboardingComplete":true,"enterpriseOnboardingComplete":false,"onboardingComplete":true}' > "${AGENT_DATA_DIR}/cache/onboarding.json"
    fi
fi

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
echo "    - Données Antigravity : ${AGENT_DATA_DIR}"
echo "    - Partage configuration : ~/.gemini/config (MCP)"
echo "    - Partage mémoire : ~/.agentmemory (agentmemory standalone)"
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
  -v "${AGENT_DATA_DIR}:/root/.gemini/antigravity-cli" \
  -v "$HOME/.gemini/config:/root/.gemini/config" \
  -v "$HOME/.agentmemory:/root/.agentmemory" \
  "${IMAGE_NAME}" "${@:-bash}"
