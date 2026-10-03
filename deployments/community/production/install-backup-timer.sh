#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 /absolute/path/to/private.env /absolute/backup-directory" >&2
  exit 2
fi
env_file=$1
backup_dir=$2
for path in "$PWD" "$env_file" "$backup_dir"; do
  [[ "$path" = /* && "$path" =~ ^[A-Za-z0-9_./-]+$ ]] || {
    echo "Paths must be absolute and contain only letters, digits, _, -, . and /" >&2
    exit 2
  }
done
[[ -f "$env_file" ]] || { echo 'Private env file not found' >&2; exit 2; }
[[ $(stat -c '%u' "$PWD") = 0 && $(stat -c '%u' deployments/community/ops/backup.sh) = 0 ]] || {
  echo 'For a root-run timer, the repository and backup script must be root-owned' >&2
  exit 1
}
for path in "$PWD" deployments/community/ops/backup.sh "$env_file"; do
  mode=$(stat -c '%a' "$path")
  (( (8#$mode & 022) == 0 )) || {
    echo "Repository, script and env file must not be group/world writable" >&2
    exit 1
  }
done
[[ $(stat -c '%u' "$env_file") = 0 ]] || {
  echo 'Private env file must be root-owned' >&2
  exit 1
}
mode=$(stat -c '%a' "$env_file")
(( (8#$mode & 077) == 0 )) || { echo 'Private env file must be mode 0600 or stricter' >&2; exit 1; }
[[ ! -L "$backup_dir" ]] || { echo 'Backup directory must not be a symlink' >&2; exit 1; }
sudo -n install -d -m 700 "$backup_dir"
unit=$(mktemp)
trap 'rm -f -- "$unit"' EXIT
sed -e "s|@REPO_DIR@|$PWD|g" -e "s|@BACKUP_DIR@|$backup_dir|g" \
  -e "s|@ENV_FILE@|$env_file|g" \
  deployments/community/production/synchrohq-backup.service.template > "$unit"
sudo -n install -m 644 "$unit" /etc/systemd/system/synchrohq-backup.service
sudo -n install -m 644 deployments/community/production/synchrohq-backup.timer \
  /etc/systemd/system/synchrohq-backup.timer
sudo -n systemd-analyze verify /etc/systemd/system/synchrohq-backup.service \
  /etc/systemd/system/synchrohq-backup.timer
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now synchrohq-backup.timer
systemctl list-timers synchrohq-backup.timer --no-pager
