#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop isn't running. Open Docker Desktop, wait until it says \"Engine running\", then run this again."
  exit 1
fi
mkdir -p data
docker compose pull || true
docker compose up -d || { echo "Could not start Job Hunt Copilot. See docs/TROUBLESHOOTING.md"; exit 1; }
echo "Starting Job Hunt Copilot..."
i=0
until curl -fs http://127.0.0.1:8080/api/health >/dev/null 2>&1; do
  i=$((i+1)); [ "$i" -ge 60 ] && { echo "Taking longer than usual; open http://127.0.0.1:8080 in a minute."; exit 0; }
  sleep 1
done
URL=http://127.0.0.1:8080
command -v open >/dev/null 2>&1 && open "$URL" || { command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL"; } || echo "Open $URL"
