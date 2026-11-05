#!/usr/bin/env bash
# Build the handover bundle for another organization, into deploy/dist/.
#
#   deploy/make-bundle.sh                # source bundle (they build the images)
#   deploy/make-bundle.sh --with-images  # + prebuilt images, for servers
#                                        #   without internet (needs Docker here)
#
# The bundle is made from the last commit, so commit your changes first.
# Your own deploy/.env (secrets) is never included.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(git describe --tags --always)"
OUT="deploy/dist"
NAME="politicalpredictor-$VERSION"
mkdir -p "$OUT"

if [ -n "$(git status --porcelain -- predictor frontend deploy Dockerfile requirements.txt)" ]; then
  echo "warning: uncommitted changes are NOT in the bundle (it is built from HEAD)." >&2
fi

# Only what the system needs to run: no recordings, PDFs or research notes.
git archive --format=zip --prefix="$NAME/" -o "$OUT/$NAME.zip" HEAD -- \
  Dockerfile .dockerignore requirements.txt README.md SECURITY.md \
  predictor baseline_speeches sample_speeches sample_speeches_ar \
  "VICS Code/VICS Code/QI" "VICS Code/VICS Code/QP" \
  frontend deploy \
  ':(exclude)*.pyc' ':(exclude)*.pdf' ':(exclude)**/.DS_Store'
echo "source bundle: $OUT/$NAME.zip"

if [ "${1:-}" = "--with-images" ]; then
  # POSTGRES_PASSWORD is only needed to run, not to build.
  (cd deploy && export VERSION="$VERSION" POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-unused}" \
    && docker compose build \
    && docker compose --profile local-ai pull db ollama)
  docker save -o "$OUT/$NAME-images.tar" \
    "politicalpredictor-api:$VERSION" "politicalpredictor-web:$VERSION" \
    postgres:16-alpine ollama/ollama:latest
  echo "images:        $OUT/$NAME-images.tar"
  echo "Tell them to put VERSION=$VERSION in .env (see INSTALL.md, offline install)."
fi
