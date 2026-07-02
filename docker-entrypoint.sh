#!/bin/sh
# Entrypoint for the p2v Docker image.
# Maps short subcommand names to absolute script paths inside the container
# so callers never need to know where scripts live.
#
# Usage (via docker-run.sh):
#   ./docker-run.sh extract  "my-book.pdf" --out .p2v --config pipeline.config.json
#   ./docker-run.sh build    ".p2v/my-book.manifest.json" --vault "./my-vault"
#   ./docker-run.sh verify   --vault "./my-vault" --config verify.config.json
#   ./docker-run.sh enrich   ".p2v/my-book.manifest.json" --vault "./my-vault"
#   ./docker-run.sh repair   <args>
set -e
case "$1" in
  extract) shift; exec python /app/scripts/extract.py      "$@" ;;
  build)   shift; exec python /app/scripts/build_vault.py  "$@" ;;
  verify)  shift; exec python /app/scripts/verify_vault.py "$@" ;;
  enrich)  shift; exec python /app/scripts/apply_enrichment.py "$@" ;;
  repair)  shift; exec python /app/scripts/apply_repair.py "$@" ;;
  *)              exec python "$@" ;;
esac
