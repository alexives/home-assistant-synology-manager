#!/usr/bin/env bash
set -euo pipefail

IMAGE="alexives/synology-test:latest"
DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION=$(uuidgen)

echo "Building $IMAGE with VERSION=$VERSION"
docker build --platform linux/amd64 -t "$IMAGE" --build-arg "VERSION=$VERSION" "$DIR"

echo "Pushing $IMAGE"
docker push "$IMAGE"

echo ""
echo "Done. New version: $VERSION"
echo ""
echo "Next steps:"
echo "  1. On Synology, pull the new image (Container Manager > Image > pull, or via Task Scheduler)"
echo "  2. The integration should detect the update (ImageID mismatch)"
echo "  3. Trigger the update from Home Assistant"
