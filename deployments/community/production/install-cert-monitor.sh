#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 CERT_NAME /absolute/path/to/fullchain.pem" >&2
  exit 2
fi
name=$1
chain=$2
[[ "$name" =~ ^[A-Za-z0-9.-]+$ && "$chain" =~ ^/[A-Za-z0-9_./-]+$ ]] || {
  echo "Invalid certificate name or path" >&2
  exit 2
}
[[ -r "$chain" ]] || { echo "Certificate not readable: $chain" >&2; exit 1; }
install -m 755 deployments/community/production/check-certificate.sh \
  /usr/local/sbin/synchrohq-cert-check
unit=$(mktemp)
trap 'rm -f -- "$unit"' EXIT
sed -e "s|@CERT_NAME@|$name|g" -e "s|@CERT_CHAIN@|$chain|g" \
  deployments/community/production/synchrohq-cert-check.service.template > "$unit"
install -m 644 "$unit" /etc/systemd/system/synchrohq-cert-check.service
install -m 644 deployments/community/production/synchrohq-cert-check.timer \
  /etc/systemd/system/synchrohq-cert-check.timer
systemd-analyze verify /etc/systemd/system/synchrohq-cert-check.service \
  /etc/systemd/system/synchrohq-cert-check.timer
systemctl daemon-reload
systemctl enable --now synchrohq-cert-check.timer
systemctl start synchrohq-cert-check.service
systemctl show synchrohq-cert-check.service -p Result -p ExecMainStatus
