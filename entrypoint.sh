#!/bin/bash
set -e

export PATH="/root/.nix-profile/bin:/usr/local/bin:/root/.local/bin:${PATH}"
export UV_PYTHON_PREFERENCE="only-system"
export UV_LINK_MODE="copy"

INSTANCE_ID=${AGENT_ID:-"agent-$(date +%s)"}
export COMPOSE_PROJECT_NAME="stack_${INSTANCE_ID}"
TARGET_BRANCH=${BRANCH:-"wip/ia-agent-env"}

echo "==> [${INSTANCE_ID}] Initialisation de l'espace de travail..."

# 1. Clonage du dépôt si le workspace est vide
if [ ! -d "/workspace/.git" ]; then
    if [ -n "${REPO_URL}" ]; then
        echo "==> Clonage de la branche '${TARGET_BRANCH}'..."
        git clone -b "${TARGET_BRANCH}" "${REPO_URL}" /workspace
    else
        echo "==> Attention: /workspace/.git n'existe pas et REPO_URL est vide."
    fi
fi

cd /workspace

# 2. Déploiement du .env depuis l'image (ou depuis le repo s'il existe)
if [ -f "/root/.env.agent" ]; then
    echo "==> [${INSTANCE_ID}] Déploiement de /root/.env.agent vers /workspace/.env..."
    cp /root/.env.agent /workspace/.env
elif [ -f "/workspace/.env.agent" ]; then
    echo "==> [${INSTANCE_ID}] Déploiement depuis /workspace/.env.agent..."
    cp /workspace/.env.agent /workspace/.env
elif [ ! -f "/workspace/.env" ] && [ -f "/workspace/env.example" ]; then
    echo "==> [${INSTANCE_ID}] Déploiement initial depuis /workspace/env.example..."
    cp /workspace/env.example /workspace/.env
fi

# 3. Ajustement automatique des paramètres réseau pour l'environnement agent conteneurisé
if [ -f "/workspace/.env" ]; then
    # Dans le réseau Docker interne, PostgreSQL écoute sur son port par défaut 5432
    sed -i -E 's/^POSTGRES_PORT=.*/POSTGRES_PORT=5432/' /workspace/.env
    # S'assurer que les hôtes pointent sur les noms de services Docker Compose
    sed -i -E 's/^POSTGRES_HOST=.*/POSTGRES_HOST=postgres/' /workspace/.env
    sed -i -E 's/^REDIS_HOST=.*/REDIS_HOST=redis/' /workspace/.env
    sed -i -E 's/^S3_ENDPOINT_URL=.*/S3_ENDPOINT_URL=http:\/\/minio:9000/' /workspace/.env

    echo "==> [${INSTANCE_ID}] Chargement des variables d'environnement..."
    set -a
    . /workspace/.env
    set +a
else
    echo "==> [${INSTANCE_ID}] ERREUR : Aucun fichier .env disponible !"
fi

# Exports explicites prioritaires
export POSTGRES_PORT=5432
export POSTGRES_HOST=postgres
export REDIS_HOST=redis
export S3_ENDPOINT_URL="http://minio:9000"
export LD_LIBRARY_PATH="/root/.nix-profile/lib:/usr/local/lib:${LD_LIBRARY_PATH}"
export UV_PYTHON_PREFERENCE="only-system"
export UV_LINK_MODE="copy"

# Persister les variables dans /root/.bashrc pour toutes les sous-sessions shell interactives
cat <<'EOF' > /root/.bashrc
# Agent Sandbox Environment
export LD_LIBRARY_PATH="/root/.nix-profile/lib:/usr/local/lib:$LD_LIBRARY_PATH"
export PATH="/root/.nix-profile/bin:/usr/local/bin:/root/.local/bin:$PATH"
export UV_PYTHON_PREFERENCE="only-system"
export UV_LINK_MODE="copy"

if [ -f "/workspace/.env" ]; then
    set -a
    . /workspace/.env
    set +a
fi
export POSTGRES_PORT=5432
export POSTGRES_HOST=postgres
export REDIS_HOST=redis
export S3_ENDPOINT_URL="http://minio:9000"
EOF

# Relais transparent vers les services MCP tournant sur l'hôte (ex: agent-memory sur le port 3111)
if command -v socat >/dev/null 2>&1; then
    echo "==> [${INSTANCE_ID}] Configuration du relais MCP localhost:3111 -> host.docker.internal:3111..."
    socat TCP-LISTEN:3111,fork,reuseaddr TCP:host.docker.internal:3111 >/dev/null 2>&1 &
fi

# 4. Lancement de Docker Compose avec --env-file explicite
COMPOSE_FILE=""
if [ -f "docker-compose-agent.yaml" ]; then
    COMPOSE_FILE="docker-compose-agent.yaml"
elif [ -f "docker-compose-agent.yml" ]; then
    COMPOSE_FILE="docker-compose-agent.yml"
elif [ -f "docker-compose.yml" ]; then
    COMPOSE_FILE="docker-compose.yml"
fi

if [ -n "$COMPOSE_FILE" ]; then
    echo "==> [${INSTANCE_ID}] Lancement de la stack ($COMPOSE_FILE)..."
    docker compose --env-file .env -f "$COMPOSE_FILE" up -d
fi

# 5. Détection des conteneurs et connexion de l'agent au réseau Compose
MINIO_CONTAINER_ID=$(docker compose -f "$COMPOSE_FILE" ps -q minio 2>/dev/null || docker ps -qf "name=${COMPOSE_PROJECT_NAME}-minio-1")
POSTGRES_CONTAINER_ID=$(docker compose -f "$COMPOSE_FILE" ps -q postgres 2>/dev/null || docker ps -qf "name=${COMPOSE_PROJECT_NAME}-postgres-1")
AGENT_CONTAINER_ID=$(cat /etc/hostname)

if [ -n "$MINIO_CONTAINER_ID" ]; then
    COMPOSE_NETWORK=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$MINIO_CONTAINER_ID" 2>/dev/null | head -n 1)
    if [ -n "$COMPOSE_NETWORK" ] && [ -n "$AGENT_CONTAINER_ID" ]; then
        echo "==> [${INSTANCE_ID}] Connexion de l'agent ($AGENT_CONTAINER_ID) au réseau : $COMPOSE_NETWORK..."
        docker network connect "$COMPOSE_NETWORK" "$AGENT_CONTAINER_ID" 2>/dev/null || true
    fi
fi

# 6. Attente de la disponibilité des services
if [ -n "$POSTGRES_CONTAINER_ID" ]; then
    echo "==> [${INSTANCE_ID}] Attente de disponibilité de PostgreSQL..."
    WAIT_COUNT=0
    until docker exec "$POSTGRES_CONTAINER_ID" pg_isready -U "${POSTGRES_USER:-postgres}" >/dev/null 2>&1; do
        sleep 1
        WAIT_COUNT=$((WAIT_COUNT + 1))
        if [ $WAIT_COUNT -gt 30 ]; then
            echo "==> [${INSTANCE_ID}] Attention: PostgreSQL n'a pas répondu après 30s."
            break
        fi
    done
fi

echo "==> [${INSTANCE_ID}] Attente de disponibilité de MinIO..."
WAIT_COUNT=0
until curl -s -f http://minio:9000/minio/health/live >/dev/null 2>&1; do
    sleep 1
    WAIT_COUNT=$((WAIT_COUNT + 1))
    if [ $WAIT_COUNT -gt 30 ]; then
        echo "==> [${INSTANCE_ID}] Attention: MinIO n'a pas répondu après 30s."
        break
    fi
done

# 7. Initialisation du bucket S3
if [ -f "scripts/init-s3-bucket.py" ]; then
    echo "==> [${INSTANCE_ID}] Initialisation du bucket S3 (scripts/init-s3-bucket.py)..."
    export S3_ENDPOINT_URL="http://minio:9000"
    export PYTHONPATH="/workspace:${PYTHONPATH}"
    uv run --with boto3 --with python-dotenv python scripts/init-s3-bucket.py
fi

# 8. Application des migrations de base de données (Alembic)
if [ -d "document-ia-api" ] && [ -f "document-ia-api/alembic.ini" ]; then
    echo "==> [${INSTANCE_ID}] Application des migrations Alembic (document-ia-api)..."
    (cd document-ia-api && uv run alembic upgrade head) || echo "==> [${INSTANCE_ID}] Attention: problème lors des migrations Alembic."
fi

# 9. Synchronisation multi-projets pour le monorepo
echo "==> [${INSTANCE_ID}] Synchronisation des sous-projets UV..."

SUBPROJECTS="document-ia-schemas document-ia-infra document-ia-api document-ia-worker document-ia-auto-scaler document-ia-evals"

for SUBPROJECT in $SUBPROJECTS; do
    SUBPROJECT_PATH="/workspace/$SUBPROJECT"
    
    if [ -d "$SUBPROJECT_PATH" ]; then
        if [ -f "$SUBPROJECT_PATH/pyproject.toml" ] || [ -f "$SUBPROJECT_PATH/requirements.txt" ]; then
            echo "--> [${INSTANCE_ID}] Synchronisation de $SUBPROJECT..."
            (cd "$SUBPROJECT_PATH" && uv sync)
        else
            echo "--> [${INSTANCE_ID}] $SUBPROJECT : aucun pyproject.toml ou requirements.txt trouvé, passage."
        fi
    else
        echo "--> [${INSTANCE_ID}] Dossier $SUBPROJECT non présent dans ce commit, passage."
    fi
done

cd /workspace

echo "==> [${INSTANCE_ID}] Environnement prêt !"

# Si aucun argument n'est fourni ou si seul 'bash' est demandé, lancer agy automatiquement tout en permettant de basculer sur bash à la sortie
if [ $# -eq 0 ] || { [ "$1" = "bash" ] && [ $# -eq 1 ]; } || { [ "$1" = "/bin/bash" ] && [ $# -eq 1 ]; }; then
    echo "==> [${INSTANCE_ID}] Lancement automatique de Antigravity (agy)..."
    agy --dangerously-skip-permissions || true
    echo "==> [${INSTANCE_ID}] Session agy terminée, bascule sur bash..."
    exec /bin/bash
else
    exec "$@"
fi
