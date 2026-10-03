#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 CERT_NAME /absolute/path/to/fullchain.pem" >&2
  exit 2
fi
name=$1
chain=$2
[[ "$name" =~ ^[A-Za-z0-9.-]+$ && "$chain" =~ ^/[A-Za-z0-9_./-]+$ ]] || exit 2
[[ -r "$chain" ]] || { echo "Certificate not readable: $chain" >&2; exit 1; }

# Certbot's own timer remains enabled. This independent guard catches a stalled
# renewal early and makes a failing certificate visible to systemd monitoring.
if ! openssl x509 -in "$chain" -noout -checkend 129600 >/dev/null; then
  echo "Certificate $name expires within 36 hours; requesting renewal"
  certbot renew --cert-name "$name" --quiet
  nginx -t
  systemctl reload nginx
fi
openssl x509 -in "$chain" -noout -enddate
if ! openssl x509 -in "$chain" -noout -checkend 86400 >/dev/null; then
  echo "CRITICAL: certificate $name expires within 24 hours" >&2
  exit 1
fi
