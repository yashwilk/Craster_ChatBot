#!/bin/bash
set -e

echo "Starting with these environment variables:"
echo "APP_ENV: ${APP_ENV:-development}"

# Load env file if present (system env vars take precedence over file values)
if [ -f ".env.${APP_ENV}" ]; then
    echo "Loading environment from .env.${APP_ENV}"
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$line" ]] && continue
        key=$(echo "$line" | cut -d '=' -f 1)
        if [[ -z "${!key}" ]]; then
            export "$line"
        fi
    done < ".env.${APP_ENV}"
elif [ -f ".env" ]; then
    echo "Loading environment from .env"
fi

# Fail fast if required secrets are missing
required_vars=("JWT_SECRET_KEY" "OPENAI_API_KEY")
missing_vars=()
for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        missing_vars+=("$var")
    fi
done
if [[ ${#missing_vars[@]} -gt 0 ]]; then
    echo "ERROR: missing required environment variables:"
    for var in "${missing_vars[@]}"; do echo "  - $var"; done
    exit 1
fi

echo "Environment: ${APP_ENV:-development}"
echo "Debug Mode: ${DEBUG:-false}"

# NOTE: migrations are NOT run automatically here — run them explicitly via
# `make docker-migrate` once the stack is up. Auto-migrating on every
# container start is unsafe with multiple replicas (concurrent migration
# races) — this mirrors the original template's design.

exec "$@"
