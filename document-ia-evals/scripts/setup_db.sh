#!/bin/bash
# Simple database setup script

set -e  # Exit on error

echo "🔧 Database Setup Script"
echo "======================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}▶ Starting PostgreSQL...${NC}"
docker compose up -d postgres

echo -e "${BLUE}▶ Waiting for PostgreSQL to be ready...${NC}"
sleep 3

# Wait for PostgreSQL to be ready
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Error: PostgreSQL did not start in time"
        exit 1
    fi
    sleep 1
done

echo -e "${BLUE}▶ Running database migrations...${NC}"
alembic upgrade head

echo -e "${BLUE}▶ Verifying tables...${NC}"
docker compose exec -T postgres psql -U postgres -d experiments_db -c "\dt"

echo ""
echo -e "${GREEN}✓ Database setup complete!${NC}"
echo ""
echo "Connection details:"
echo "  Host: localhost"
echo "  Port: 5435"
echo "  Database: experiments_db"
echo ""
echo "Next: Run 'streamlit run app.py'"