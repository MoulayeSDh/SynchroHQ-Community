#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."
if [[ $# -ne 3 ]]; then
  echo "Usage: $0 /absolute/path/to/private.env /private/backup-directory TIMESTAMP" >&2
  exit 2
fi
env_file=$1
backup_dir=$2
stamp=$3
[[ "$env_file" = /* && -f "$env_file" && "$backup_dir" = /* && -d "$backup_dir" ]] || exit 2
[[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || exit 2
db_file="$backup_dir/db-$stamp.dump"
objects_file="$backup_dir/minio-$stamp.tar.gz"
manifest="$backup_dir/sha256-$stamp.txt"
[[ -f "$db_file" && -f "$objects_file" && -f "$manifest" ]] || exit 2
(cd "$backup_dir" && sha256sum -c "$(basename "$manifest")")
python3 - "$objects_file" <<'PY'
import pathlib
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as archive:
    for member in archive:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
            raise SystemExit(f"Unsafe object archive member: {member.name}")
PY

compose=(sudo docker compose --env-file "$env_file" -f compose.yaml -f compose.production.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" config --format json | python3 \
  deployments/community/production/preflight-compose.py
if [[ -n "$("${compose[@]}" ps -a -q postgres)" ||
      -n "$("${compose[@]}" ps -a -q minio)" ]]; then
  echo 'Target Compose installation already exists; use a new empty project' >&2
  exit 1
fi
"${compose[@]}" up -d --wait --build postgres
db_user=$("${compose[@]}" exec -T postgres printenv POSTGRES_USER)
db_name=$("${compose[@]}" exec -T postgres printenv POSTGRES_DB)
app_tables=$("${compose[@]}" exec -T postgres psql -U "$db_user" -d "$db_name" \
  -Atc "select count(*) from pg_tables where schemaname='public' and tablename <> 'spatial_ref_sys'")
[[ "$app_tables" = 0 ]] || {
  echo 'Target database is not empty; refusing to replace existing data' >&2
  exit 1
}
"${compose[@]}" build minio
"${compose[@]}" create --no-recreate minio >/dev/null
minio_container=$("${compose[@]}" ps -a -q minio)
volume=$(sudo docker inspect "$minio_container" \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')
[[ -n "$volume" && -d "$volume" ]] || {
  echo 'Target object volume is missing' >&2
  exit 1
}
volume_contents=$(sudo find "$volume" -mindepth 1 -print -quit)
[[ -z "$volume_contents" ]] || {
  echo 'Target object volume is not empty; refusing to replace existing data' >&2
  exit 1
}

# The PostGIS image initializes the default database with tiger/topology.
# Recreate only this verified-empty database from template0 so pg_restore can
# create the schemas and extensions from the archive without name collisions.
"${compose[@]}" exec -T postgres dropdb -U "$db_user" \
  --maintenance-db=postgres "$db_name"
"${compose[@]}" exec -T postgres createdb -U "$db_user" \
  --maintenance-db=postgres --template=template0 "$db_name"
cat "$db_file" | "${compose[@]}" exec -T postgres pg_restore -U "$db_user" \
  -d "$db_name" --no-owner --no-privileges
sudo tar -C "$volume" -xzf "$objects_file"
"${compose[@]}" up -d --build minio backend frontend
"${compose[@]}" exec -T backend alembic upgrade head
"${compose[@]}" exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
echo "Restored backup $stamp on this new host. Verify login and data before opening public access."
