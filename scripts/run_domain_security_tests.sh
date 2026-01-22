#!/bin/bash
# Helper script to run domain security tests inside the Docker container

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running domain security tests in Docker container...${NC}"
echo ""

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^api$"; then
    echo -e "${RED}Error: API container 'api' is not running${NC}"
    echo "Please start the containers first with: docker-compose up -d"
    exit 1
fi

# Run the test script inside the container
echo -e "${GREEN}Executing tests...${NC}"
echo ""

docker exec api python /app/backend/core/api/app/services/test_domain_security.py

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
else
    echo -e "${RED}✗ Some tests failed${NC}"
fi

exit $EXIT_CODE
