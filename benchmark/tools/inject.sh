#!/bin/bash
set -e
INCIDENT=$1
if [ -z "$INCIDENT" ]; then echo "Usage: $0 <incident_name>"; exit 1; fi

cd "$(dirname "$0")/../shopfront"
git reset --hard baseline
git clean -fd

if [ -f "../incidents/$INCIDENT/inject.patch" ]; then
    patch -p1 < "../incidents/$INCIDENT/inject.patch"
fi

docker compose down -v
docker compose up --build -d
echo "Waiting for services..."
sleep 15
