#!/usr/bin/env bash
set -euo pipefail

CADDY_VERSION="2.10.2"

# --- Download Caddy si pas déjà présent ---
if [ ! -f ./binaries/caddy ]; then
  mkdir -p ./binaries
  mkdir -p /tmp/caddy

  echo "Téléchargement de Caddy v${CADDY_VERSION}..."
  curl -L "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" -o /tmp/caddy/caddy.tar.gz

  echo "Extraction de Caddy..."
  tar -xzf /tmp/caddy/caddy.tar.gz -C /tmp/caddy/

  echo "Installation de Caddy dans ./binaries/"
  mv /tmp/caddy/caddy ./binaries/caddy
  chmod +x ./binaries/caddy

  echo "Nettoyage des fichiers temporaires..."
  rm -rf /tmp/caddy

  echo "Caddy v${CADDY_VERSION} installé avec succès !"
fi

ALLOWED_REMOTE_IP_LINES=""
for ip in $ALLOWED_IPS_ENV; do
  ALLOWED_REMOTE_IP_LINES+="        remote_ip ${ip}\\n"
done

if [ ! -f ./Caddyfile.template ]; then
  echo "ERREUR: Caddyfile.template introuvable."
  exit 1
fi

printf "Génération du Caddyfile avec IPs autorisées: %s\n" "$ALLOWED_IPS_ENV"
TEMPLATE_CONTENT=$(cat ./Caddyfile.template)
FINAL_CONTENT=${TEMPLATE_CONTENT/__ALLOWED_REMOTE_IP_LINES__/${ALLOWED_REMOTE_IP_LINES}}
printf "%b" "$FINAL_CONTENT" > ./Caddyfile

# --- Démarre Streamlit sur un port interne ---
streamlit run app.py \
  --server.port=8501 \
  --server.address=0.0.0.0 &

STREAMLIT_PID=$!

# Optionnel : attendre un peu que Streamlit démarre
sleep 5

# --- Démarre Caddy en avant-plan sur $PORT (processus "web") ---
./binaries/caddy run --config ./Caddyfile --adapter caddyfile &
CADDY_PID=$!

# Gestion propre des signaux (stop tout si Scalingo redémarre le conteneur)
term() {
  kill -TERM "$STREAMLIT_PID" "$CADDY_PID" 2>/dev/null || true
  wait "$CADDY_PID"
}
trap term TERM INT

wait "$CADDY_PID"
