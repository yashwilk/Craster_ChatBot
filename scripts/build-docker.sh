#!/bin/bash
set -e

# Build the Docker image for a given environment.
# Usage: ./scripts/build-docker.sh <environment>
#
# NOTE: unlike some setups you may have seen elsewhere, this does NOT pass
# secrets as --build-arg. Docker build-args get cached in image layer
# history, so anything passed that way can leak. Secrets are provided at
# runtime instead (via env_file / -e), never baked into the image.

if [ $# -ne 1 ]; then
    echo "Usage: $0 <environment>"
    echo "Environments: development, staging, production"
    exit 1
fi

ENV=$1
if [[ ! "$ENV" =~ ^(development|staging|production)$ ]]; then
    echo "Invalid environment. Must be one of: development, staging, production"
    exit 1
fi

ENV_FILE=".env.$ENV"
if [ ! -f "$ENV_FILE" ]; then
    echo "Warning: $ENV_FILE not found. Creating from .env.example"
    cp .env.example "$ENV_FILE"
    echo "Please update $ENV_FILE with real values before deploying."
fi

echo "Building Docker image for $ENV environment (no secrets baked in)"
docker build --build-arg APP_ENV="$ENV" -t craster-agent:"$ENV" .
echo "Built craster-agent:$ENV"
