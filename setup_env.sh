#!/bin/bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi
echo "✅ Environment configuré"
