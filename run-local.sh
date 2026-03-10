#!/bin/bash

# Genie2 Local Development Runner
# Runs all services without Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Starting Genie2 in local mode...${NC}"

# Check for .env
if [ ! -f ".env" ]; then
    echo "Error: .env file not found. Copy .env.example and fill in your keys."
    exit 1
fi

# Export env vars
export $(grep -v '^#' .env | xargs)
export DATABASE_PATH="$SCRIPT_DIR/genie.db"

# Function to cleanup on exit
cleanup() {
    echo -e "\n${BLUE}Shutting down...${NC}"
    kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT

# Start Master Agent (port 8001)
echo -e "${GREEN}Starting Master Agent on :8001${NC}"
cd agents
python -m master.main &
MASTER_PID=$!
cd ..

# Wait for master to be ready
sleep 2

# Start Customer Service Agent (port 8002)
echo -e "${GREEN}Starting Customer Service Agent on :8002${NC}"
cd agents
python -m customer_service.main &
CS_PID=$!
cd ..

# Wait for agents to be ready
sleep 2

# Start Gateway (port 3000)
echo -e "${GREEN}Starting SMS Gateway on :3000${NC}"
cd gateway
npm run dev &
GATEWAY_PID=$!
cd ..

echo -e "\n${GREEN}All services running!${NC}"
echo "  Gateway:          http://localhost:3000"
echo "  Master Agent:     http://localhost:8001"
echo "  Customer Service: http://localhost:8002"
echo ""
echo "Test with:"
echo "  curl http://localhost:3000/health"
echo "  curl http://localhost:8001/health"
echo "  curl http://localhost:8002/health"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for any process to exit
wait
