#!/bin/sh
set -e

INSTANCE_ID=${AGENT_ID:-"agent-$(date +%s)"}
export COMPOSE_PROJECT_NAME="stack_${INSTANCE_ID}"
TARGET_BRANCH=${BRANCH:-"wip/ia-agent-env"}

echo "==> [${INSTANCE_ID}] Initialisation de l'espace de travail..."

# 1. Clonage du dépôt sur develop si le workspace est vide
if [ ! -d "/workspace/.git" ]; then
    echo "==> Clonage de la branche '${TARGET_BRANCH}'..."
    git clone -b "${TARGET_BRANCH}" "${REPO_URL}" /workspace
fi

cd /workspace

# 2. Déploiement du .env depuis l'image (ou depuis le repo s'il existe)
if [ -f "/root/.env.agent" ]; then
    echo "==> [${INSTANCE_ID}] Déploiement de /root/.env.agent vers /workspace/.env..."
    cp /root/.env.agent /workspace/.env
elif [ -f "/workspace/.env.agent" ]; then
    echo "==> [${INSTANCE_ID}] Déploiement depuis /workspace/.env.agent..."
    cp /workspace/.env.agent /workspace/.env
fi

# 3. Chargement et export des variables dans l'environnement du shell
if [ -f "/workspace/.env" ]; then
    echo "==> [${INSTANCE_ID}] Chargement des variables d'environnement..."
    set -a
    . /workspace/.env
    set +a
else
    echo "==> [${INSTANCE_ID}] ERREUR : Aucun fichier .env disponible !"
fi

# 4. Lancement de Docker Compose avec --env-file explicite
if [ -f "docker-compose-agent.yaml" ]; then
    echo "==> [${INSTANCE_ID}] Lancement de la stack (docker-compose-agent.yaml)..."
    docker compose --env-file .env -f docker-compose-agent.yaml up -d
elif [ -f "docker-compose-agent.yml" ]; then
    echo "==> [${INSTANCE_ID}] Lancement de la stack (docker-compose-agent.yml)..."
    docker compose --env-file .env -f docker-compose-agent.yml up -d
elif [ -f "docker-compose.yml" ]; then
    echo "==> [${INSTANCE_ID}] Lancement de la stack (fallback docker-compose.yml)..."
    docker compose --env-file .env up -d
fi

# 5. Détection du conteneur MinIO et de son réseau réel
MINIO_CONTAINER="${COMPOSE_PROJECT_NAME}-minio-1"

echo "==> [${INSTANCE_ID}] Attente du démarrage de MinIO..."
until docker inspect -f '{{.State.Health.Status}}' "$MINIO_CONTAINER" 2>/dev/null | grep -q "healthy"; do
    sleep 2
done

# Récupération automatique du réseau Docker attribué à MinIO par Compose
COMPOSE_NETWORK=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$MINIO_CONTAINER")
AGENT_CONTAINER_ID=$(cat /etc/hostname)

echo "==> [${INSTANCE_ID}] Connexion de l'agent ($AGENT_CONTAINER_ID) au réseau : $COMPOSE_NETWORK..."
docker network connect "$COMPOSE_NETWORK" "$AGENT_CONTAINER_ID" 2>/dev/null || true

# 6. Initialisation du bucket S3 avec votre script Python
if [ -f "scripts/init-s3-bucket.py" ]; then
    echo "==> [${INSTANCE_ID}] Attente de disponibilité de MinIO..."
    MINIO_CONTAINER="${COMPOSE_PROJECT_NAME}-minio-1"

    # Attente du statut healthy
    until docker inspect -f '{{.State.Health.Status}}' "$MINIO_CONTAINER" 2>/dev/null | grep -q "healthy"; do
        sleep 2
    done

    MINIO_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$MINIO_CONTAINER")
    echo "==> [${INSTANCE_ID}] MinIO actif sur http://${MINIO_IP}:9000. Lancement de scripts/init-s3-bucket.py..."

    export S3_ENDPOINT_URL="http://${MINIO_IP}:9000"
    export PYTHONPATH="/workspace:${PYTHONPATH}"

    uv run --with boto3 --with python-dotenv python scripts/init-s3-bucket.py
fi

# 7. Synchronisation multi-projets pour le monorepo
echo "==> [${INSTANCE_ID}] Synchronisation des sous-projets UV..."

SUBPROJECTS="document-ia-api document-ia-evals document-ia-schemas document-ia-auto-scaler document-ia-infra document-ia-worker"

for SUBPROJECT in $SUBPROJECTS; do
    SUBPROJECT_PATH="/workspace/$SUBPROJECT"
    
    if [ -d "$SUBPROJECT_PATH" ]; then
        if [ -f "$SUBPROJECT_PATH/pyproject.toml" ] || [ -f "$SUBPROJECT_PATH/requirements.txt" ]; then
            echo "--> [${INSTANCE_ID}] Synchronisation de $SUBPROJECT..."
            cd "$SUBPROJECT_PATH"
            
            # Utilise explicitement Python 3.13 fourni par Nix / le système
            uv sync
        else
            echo "--> [${INSTANCE_ID}] $SUBPROJECT : aucun pyproject.toml ou requirements.txt trouvé, passage."
        fi
    else
        echo "--> [${INSTANCE_ID}] Dossier $SUBPROJECT non présent dans ce commit, passage."
    fi
done

# Retour à la racine du workspace
cd /workspace

# 8. Synchronisation de l'environnement virtuel avec uv
if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
    echo "==> [${INSTANCE_ID}] Synchronisation de l'environnement avec uv..."
    uv venv .venv
    export VIRTUAL_ENV="/workspace/.venv"
    export PATH="/workspace/.venv/bin:$PATH"

    if [ -f "uv.lock" ]; then
        uv sync
    elif [ -f "requirements.txt" ]; then
        uv pip install -r requirements.txt
    fi
fi

echo "==> [${INSTANCE_ID}] Environnement prêt !"
exec "$@"
