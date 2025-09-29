#!/bin/bash

echo "[post_compile] copy lib to vendor folder"
mkdir -p vendor
cp -r ../document-ia-infra vendor/

echo "[post_compile] install local lib"
poetry run pip install -e vendor/document-ia-infra
