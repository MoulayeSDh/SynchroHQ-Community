#!/usr/bin/env bash
set -euo pipefail

# Restore into a disposable database and directory; never touch live volumes.
cd "$(dirname "$0")/../../.."
backup_dir=${1:?Usage: restore-check.sh /private/backup-directory TIMESTAMP}
backup_dir=$(realpath -e "$backup_dir")
stamp=${2:?Usage: restore-check.sh /private/backup-directory TIMESTAMP [--env-file /private/production.env]}
[[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || { echo 'Invalid backup timestamp' >&2; exit 2; }
if [[ $# -ne 2 && $# -ne 4 ]]; then
  echo 'Usage: restore-check.sh /private/backup-directory TIMESTAMP [--env-file /private/production.env]' >&2
  exit 2
fi
db_file="$backup_dir/db-$stamp.dump"
objects_file="$backup_dir/minio-$stamp.tar.gz"
test -f "$db_file" && test -f "$objects_file"
(cd "$backup_dir" && sha256sum -c "sha256-$stamp.txt")
if [[ $# -eq 4 ]]; then
  [[ "$3" = --env-file && "$4" = /* && -f "$4" ]] || exit 2
  compose=(sudo docker compose --env-file "$4" -f compose.yaml -f compose.production.yaml)
else
  compose=(sudo docker compose -f compose.yaml -f compose.pilot.yaml)
fi
db_user=$("${compose[@]}" exec -T postgres printenv POSTGRES_USER)
db_name="synchrohq_restore_$RANDOM"
scratch=$(mktemp -d)
created=0
cleanup() {
  if [ "$created" = 1 ]; then
    "${compose[@]}" exec -T postgres dropdb -U "$db_user" --if-exists "$db_name" >/dev/null
  fi
  rm -rf -- "$scratch"
}
trap cleanup EXIT
"${compose[@]}" exec -T postgres createdb -U "$db_user" "$db_name"
created=1
cat "$db_file" | "${compose[@]}" exec -T postgres pg_restore -U "$db_user" -d "$db_name" --no-owner --no-privileges
"${compose[@]}" exec -T postgres psql -U "$db_user" -d "$db_name" -Atc \
  "select 'tenants=' || count(*) from tenants; select 'users=' || count(*) from users; select extname || '=' || count(*) from pg_extension where extname in ('postgis', 'vector') group by extname order by extname;"
tar -xzf "$objects_file" -C "$scratch"
printf 'Object archive extracted: %s files\n' "$(find "$scratch" -type f | wc -l)"
