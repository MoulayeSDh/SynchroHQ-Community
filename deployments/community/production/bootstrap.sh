#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."
if [[ $# -ne 7 ]]; then
  echo "Usage: $0 /absolute/path/to/private.env TENANT_CODE TENANT_NAME ADMIN_EMAIL ADMIN_NAME ROOT_TERRITORY_NAME ORGANIZATION_NAME" >&2
  exit 2
fi
env_file=$1
[[ "$env_file" = /* && -f "$env_file" ]] || { echo 'Private env file not found' >&2; exit 2; }
[[ -t 0 && -t 1 ]] || { echo 'Interactive terminal required for the admin password' >&2; exit 1; }
exec sudo docker compose --env-file "$env_file" -f compose.yaml \
  -f compose.production.yaml exec backend python -m app.modules.identity.bootstrap \
  --tenant-code "$2" --tenant-name "$3" --admin-identifier "$4" \
  --admin-name "$5" --root-territory-name "$6" --organization-name "$7"
