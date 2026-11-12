FROM nixos/nix:latest

RUN echo "experimental-features = nix-command flakes" >> /etc/nix/nix.conf

# 1. Installation des outils système, bibliothèques C/C++ partagées et Python 3.13 via Nix
RUN nix profile install \
    nixpkgs#docker-client \
    nixpkgs#docker-compose \
    nixpkgs#python313 \
    nixpkgs#nodejs \
    nixpkgs#socat \
    nixpkgs#uv \
    nixpkgs#gh \
    nixpkgs#tmux \
    nixpkgs#file \
    nixpkgs#stdenv.cc.cc.lib \
    nixpkgs#libxcb \
    nixpkgs#libGL \
    nixpkgs#glib.out \
    nixpkgs#zlib \
    nixpkgs#gnused \
    nixpkgs#gawk \
    nixpkgs#coreutils \
    nixpkgs#patchelf \
    nixpkgs#tesseract5

# 2. Liens symboliques standard
RUN mkdir -p /bin /usr/local/bin && \
    ln -sf $(which bash) /bin/bash && \
    ln -sf $(which python3.13) /usr/local/bin/python3 && \
    ln -sf $(which python3.13) /usr/local/bin/python

# 3. Installation et patch natif de la CLI agy
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash && \
    GLIBC_LD=$(find /nix/store -name "ld-linux-aarch64.so.1" 2>/dev/null | head -n 1) && \
    GLIBC_DIR=$(dirname "$GLIBC_LD") && \
    patchelf --set-interpreter "$GLIBC_LD" --set-rpath "$GLIBC_DIR" /root/.local/bin/agy && \
    ln -sf /root/.local/bin/agy /usr/local/bin/agy && \
    ln -sf /root/.local/bin/agy /usr/local/bin/antigravity

# 4. Variables d'environnement
ENV UV_PYTHON_PREFERENCE="only-system"
ENV UV_LINK_MODE="copy"
ENV PATH="/root/.nix-profile/bin:/root/.local/bin:/usr/local/bin:$PATH"
ENV LD_LIBRARY_PATH="/root/.nix-profile/lib:/usr/local/lib"

# 5. Répertoires de travail et clés SSH
RUN mkdir -p /root/.gemini/antigravity-cli /root/.gemini/config /root/.agentmemory /workspace /root/.ssh
WORKDIR /workspace

RUN echo "StrictHostKeyChecking accept-new" >> /root/.ssh/config && \
    chmod 600 /root/.ssh/config

COPY .env.agent* /root/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
