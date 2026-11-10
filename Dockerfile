FROM nixos/nix:latest

RUN echo "experimental-features = nix-command flakes" >> /etc/nix/nix.conf

# 1. Installation des outils système ET de Python 3.13 via Nix (compilé pour NixOS)
RUN nix profile install \
    nixpkgs#docker-client \
    nixpkgs#docker-compose \
    nixpkgs#python313 \
    nixpkgs#uv \
    nixpkgs#gh \
    nixpkgs#tmux

# 2. Liens symboliques standard pour les scripts et outils
RUN mkdir -p /bin /usr/local/bin && \
    ln -sf $(which bash) /bin/bash && \
    ln -sf $(which python3.13) /usr/local/bin/python3 && \
    ln -sf $(which python3.13) /usr/local/bin/python

# 3. Forcer uv à utiliser EXCLUSIVEMENT le Python fourni par le système (Nix)
ENV UV_PYTHON_PREFERENCE="only-system"
ENV PATH="/usr/local/bin:/root/.local/bin:$PATH"

# 4. Dossiers de travail et clés SSH
RUN mkdir -p /root/.antigravity /workspace /root/.ssh
WORKDIR /workspace

RUN echo "StrictHostKeyChecking accept-new" >> /root/.ssh/config && \
    chmod 600 /root/.ssh/config

COPY .env.agent /root/.env.agent
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
