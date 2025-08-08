#!/bin/bash

# Optimized multi-architecture Docker build script
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting optimized multi-architecture Docker build...${NC}"

# Check if buildx is available
if ! docker buildx version > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker buildx is not available. Please install Docker Buildx.${NC}"
    exit 1
fi

# Create a new builder instance if it doesn't exist
BUILDER_NAME="globeco-builder"
if ! docker buildx inspect $BUILDER_NAME > /dev/null 2>&1; then
    echo -e "${YELLOW}Creating new buildx builder: $BUILDER_NAME${NC}"
    docker buildx create --name $BUILDER_NAME --driver docker-container --use
else
    echo -e "${YELLOW}Using existing buildx builder: $BUILDER_NAME${NC}"
    docker buildx use $BUILDER_NAME
fi

# Start the builder if not running
docker buildx inspect --bootstrap

# Set build arguments
IMAGE_NAME="kasbench/globeco-benchmark-coordinator"
TAG="latest"
PLATFORMS="linux/amd64,linux/arm64"

# Build with optimized settings
echo -e "${GREEN}Building for platforms: $PLATFORMS${NC}"

docker buildx build \
    --platform $PLATFORMS \
    --tag $IMAGE_NAME:$TAG \
    --cache-from type=local,src=/tmp/.buildx-cache \
    --cache-to type=local,dest=/tmp/.buildx-cache,mode=max \
    --push \
    --progress=plain \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    .

echo -e "${GREEN}Build completed successfully!${NC}"
echo -e "${YELLOW}Image: $IMAGE_NAME:$TAG${NC}"
echo -e "${YELLOW}Platforms: $PLATFORMS${NC}"
