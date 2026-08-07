#!/bin/bash

# Load and summarize environment configuration.
# Usage: source ./scripts/set_env.sh [development|staging|production]
# Must be sourced (not executed) so exported vars reach the parent shell.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: This script must be sourced, not executed."
    echo "Usage: source ./scripts/set_env.sh [development|staging|production]"
    exit 1
fi

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'

ENV=${1:-development}
if [[ ! "$ENV" =~ ^(development|staging|production)$ ]]; then
    echo -e "${RED}Error: Invalid environment. Choose development, staging, or production.${NC}"
    return 1
fi

export APP_ENV=$ENV
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.$ENV"

if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}Loading environment from $ENV_FILE${NC}"
    set -a; source "$ENV_FILE"; set +a
else
    echo -e "${YELLOW}Warning: $ENV_FILE not found. Creating from .env.example...${NC}"
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
        set -a; source "$ENV_FILE"; set +a
        echo -e "${GREEN}Created $ENV_FILE — please update it with real values.${NC}"
    else
        echo -e "${RED}Error: .env.example not found.${NC}"
        return 1
    fi
fi

echo -e "\n${GREEN}=== ENVIRONMENT SUMMARY ===${NC}"
echo -e "Environment:    ${YELLOW}$ENV${NC}"
echo -e "Project:        ${YELLOW}${PROJECT_NAME:-Not set}${NC}"
echo -e "DB host:        ${YELLOW}${POSTGRES_HOST:-Not set}${NC}"
echo -e "LLM model:      ${YELLOW}${DEFAULT_LLM_MODEL:-Not set}${NC}"
echo -e "Acumatica URL:  ${YELLOW}${ACUMATICA_BASE_URL:-Not set}${NC}"
echo -e "Debug mode:     ${YELLOW}${DEBUG:-Not set}${NC}"
