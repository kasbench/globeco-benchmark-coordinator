#!/bin/bash

# Build script that forces fresh build to ensure latest source code
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Building fresh image with latest source code...${NC}"

# Build without cache to ensure latest code
docker build --no-cache -t globeco-benchmark-coordinator:latest .

echo -e "${GREEN}Fresh build completed!${NC}"
echo -e "${YELLOW}Image: globeco-benchmark-coordinator:latest${NC}"
echo -e "${YELLOW}This build includes the latest source code changes.${NC}"
