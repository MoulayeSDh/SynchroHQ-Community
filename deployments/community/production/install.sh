#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."
usage() { echo "Usage: $0 /absolute/path/to/private.env" >&2; exit 2; }
[[ $# -eq 1 ]] || usage
env_file=$1
[[ "$env_file" = /* && -f "$env_file" ]] || usage

# Secrets must not be readable by other users on the installation host.
mode=$(stat -c '%a' "$env_file")
(( (8#$mode & 077) == 0 )) || {
  echo "Private environment file must not be group/world readable" >&2
  exit 1
}
command -v docker >/dev/null
sudo -n docker compose version >/dev/null
compose=(sudo docker compose --env-file "$env_file" -f compose.yaml -f compose.production.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" config --format json | python3 \
  deployments/community/production/preflight-compose.py
existing_postgres=$("${compose[@]}" ps -a -q postgres)
if [[ -n "$existing_postgres" ]]; then
  existing_image=$(sudo docker inspect "$existing_postgres" --format '{{.Config.Image}}')
  if [[ "$existing_image" = synchrohq/postgis-pgvector:* ]]; then
    echo 'Existing Enterprise database: use the private Enterprise deployment procedure' >&2
    exit 1
  fi
fi
"${compose[@]}" up -d --build postgres minio backend frontend
"${compose[@]}" exec -T backend alembic upgrade head

"${compose[@]}" exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
echo 'SynchroHQ services and migrations are ready. Run bootstrap.sh on a new installation.'
