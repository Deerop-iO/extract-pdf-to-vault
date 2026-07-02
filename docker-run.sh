#!/usr/bin/env bash
# Runs a p2v pipeline command inside the Docker container.
# Mounts the current directory as /vault so the PDF, config, and vault output
# are all accessible without copying files into the container.
#
# Run this script from your PROJECT folder (where pipeline.config.json lives).
#
# Usage:
#   ./docker-run.sh extract "my-book.pdf" --out .p2v --config pipeline.config.json
#   ./docker-run.sh build   ".p2v/my-book.manifest.json" --vault "./my-vault"
#   ./docker-run.sh verify  --vault "./my-vault" --config verify.config.json
#
# Note: vault paths in pipeline.config.json must be relative paths that stay
# inside this folder (e.g. "./my-vault"), not "../something" which would escape
# the mount and fail.
set -e
docker run --rm \
  -v "$(pwd):/vault" \
  -w /vault \
  p2v "$@"
