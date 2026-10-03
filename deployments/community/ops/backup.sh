#!/usr/bin/env bash
set -euo pipefail

# Run from a SynchroHQ checkout with the Community pilot Compose files.
# Writers are briefly stopped so PostgreSQL and MinIO describe one state.
cd "$(dirname "$0")/../../.."
backup_dir=${1:?Usage: backup.sh /private/backup-directory [--env-file /private/production.env]}
if [[ $# -ne 1 && $# -ne 3 ]]; then
  echo 'Usage: backup.sh /private/backup-directory [--env-file /private/production.env]' >&2
  exit 2
fi
install -d -m 700 "$backup_dir"
backup_dir=$(realpath -e "$backup_dir")
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
if [[ $# -eq 3 ]]; then
  [[ "$2" = --env-file && "$3" = /* && -f "$3" ]] || exit 2
  compose=(sudo docker compose --env-file "$3" -f compose.yaml -f compose.production.yaml)
else
  compose=(sudo docker compose -f compose.yaml -f compose.pilot.yaml)
fi
db_user=$("${compose[@]}" exec -T postgres printenv POSTGRES_USER)
db_name=$("${compose[@]}" exec -T postgres printenv POSTGRES_DB)
db_tmp="$backup_dir/db-$stamp.dump.partial"
objects_tmp="$backup_dir/minio-$stamp.tar.gz.partial"
backend_running=0
minio_running=0
test -z "$("${compose[@]}" ps -q backend)" || backend_running=1
test -z "$("${compose[@]}" ps -q minio)" || minio_running=1

cleanup() {
  result=$?
  trap - EXIT
  rm -f -- "$db_tmp" "$objects_tmp"
  if [ "$result" -ne 0 ]; then
    rm -f -- "$backup_dir/db-$stamp.dump" \
      "$backup_dir/minio-$stamp.tar.gz" "$backup_dir/sha256-$stamp.txt"
  fi
  if [ "$minio_running" = 1 ]; then
    "${compose[@]}" start minio >/dev/null || result=1
  fi
  if [ "$backend_running" = 1 ]; then
    "${compose[@]}" start backend >/dev/null || result=1
  fi
  exit "$result"
}
trap cleanup EXIT

if [ "$backend_running" = 1 ]; then
  "${compose[@]}" stop backend >/dev/null
fi
if [ "$minio_running" = 1 ]; then
  "${compose[@]}" stop minio >/dev/null
fi
"${compose[@]}" exec -T postgres pg_dump -U "$db_user" -d "$db_name" -Fc > "$db_tmp"
minio_container=$("${compose[@]}" ps -a -q minio)
volume=$(sudo docker inspect "$minio_container" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')
test -n "$volume"
sudo tar -C "$volume" -czf - . > "$objects_tmp"
mv "$db_tmp" "$backup_dir/db-$stamp.dump"
mv "$objects_tmp" "$backup_dir/minio-$stamp.tar.gz"
(cd "$backup_dir" && sha256sum "db-$stamp.dump" "minio-$stamp.tar.gz" \
  > "sha256-$stamp.txt")
chmod 600 "$backup_dir"/*"$stamp"*
printf 'Backup: %s\n' "$stamp"
