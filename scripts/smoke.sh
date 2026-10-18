#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

# Never overwrite user data. This script owns data/ only when the directory did
# not exist before this run.
if [ -e data ]; then
  echo "Refusing to overwrite existing data/. Move it aside before running the smoke test." >&2
  exit 1
fi
mkdir -p data
cp -r examples/data/. data/
chmod -R a+rwX data
C="docker compose -f docker-compose.yml -f docker-compose.ci.yml"
cleanup() {
  $C logs app 2>/dev/null | tail -50 || true
  # Files written by the container belong to its uid (1000); on hosts where the
  # user has another uid (e.g. CI runners) only the container can delete them.
  $C exec -T app sh -c 'rm -rf /data/* /data/.[!.]*' 2>/dev/null || true
  $C down || true
  rm -rf data || true
}
trap cleanup EXIT
$C up -d --build

i=0
until curl -fs http://127.0.0.1:8080/api/health >/dev/null; do
  i=$((i+1)); [ "$i" -ge 90 ] && exit 1; sleep 1
done
ID=$(curl -fs -X POST http://127.0.0.1:8080/api/jobs -H 'Content-Type: application/json' \
  -d '{"jd_text":"Senior Data Scientist at Acme Corp in Paris. Python, SQL, ML."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
i=0
while :; do
  S=$(curl -fs "http://127.0.0.1:8080/api/jobs/$ID/status" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))')
  # Wait for a terminal status; jobs pass through transient states (new, generating, ...).
  case "$S" in cv_ready) break;; failed) echo "job failed"; exit 1;; esac
  i=$((i+1)); [ "$i" -ge 120 ] && { echo "timeout"; exit 1; }; sleep 2
done
ls data/output/*/*.pdf >/dev/null && echo "SMOKE OK"
