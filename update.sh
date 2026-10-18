#!/bin/sh
cd "$(dirname "$0")" || exit 1
docker compose pull && docker compose up -d
