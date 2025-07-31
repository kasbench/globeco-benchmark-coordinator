#!/bin/bash

# Build script for multi-architecture Docker image
# Usage: ./build.sh [version]

set -e

IMAGE_NAME="kasbench/globeco-benchmark-coordinator"
VERSION=${1:-latest}

echo "Building multi-architecture Docker image..."
echo "Image: $IMAGE_NAME:$VERSION"
echo "Architectures: linux/amd64, linux/arm64"

# Build and push multi-architecture image
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag "$IMAGE_NAME:$VERSION" \
    --tag "$IMAGE_NAME:latest" \
    --push \
    .

echo "Build completed successfully!"
echo "Image: $IMAGE_NAME:$VERSION"
echo "Available architectures: linux/amd64, linux/arm64" 