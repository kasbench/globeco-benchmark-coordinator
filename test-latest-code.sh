#!/bin/bash

# Test script to verify latest code is being used
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Testing latest code in container...${NC}"

# Build the image
echo -e "${YELLOW}Building image...${NC}"
docker build -t globeco-benchmark-coordinator:test .

# Run a quick test to verify the code
echo -e "${YELLOW}Running container to verify latest code...${NC}"
docker run --rm globeco-benchmark-coordinator:test python -c "
import sys
print('Python path:', sys.path)
print('Locust directory contents:')
import os
for root, dirs, files in os.walk('/app/locust'):
    level = root.replace('/app/locust', '').count(os.sep)
    indent = ' ' * 2 * level
    print(f'{indent}{os.path.basename(root)}/')
    subindent = ' ' * 2 * (level + 1)
    for file in files:
        print(f'{subindent}{file}')
"

echo -e "${GREEN}Test completed!${NC}"
echo -e "${YELLOW}If you see your latest files listed above, the code is being copied correctly.${NC}"
