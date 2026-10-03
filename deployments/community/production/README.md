# Reproducible SynchroHQ deployment (Ubuntu 24.04)

This is the host-independent Community installation path. It requires no
Enterprise repository, AI provider, or customer fixture. Use a pinned Git
commit for each installation.

## 1. Prepare a new host

Install Docker Engine with Compose 2.24.4 or newer, Python 3, Nginx, and a
certificate manager from their official packages. Provide a hostname or static
IPv4 address and allow inbound 80/443 in the host and cloud firewalls. Clone the
repository under a root-owned path such as `/opt/SynchroHQ`. Verify that the
checkout has no local modifications and record `git rev-parse HEAD`.

Create `/etc/synchrohq/production.env` with owner root and mode `0600`, using
[`production.env.example`](production.env.example) as a *list of names*, not
as production values. Set at least:

```dotenv
POSTGRES_DB=synchrohq
POSTGRES_USER=synchrohq
POSTGRES_PASSWORD=<unique private value>
S3_ACCESS_KEY=<unique private value>
S3_SECRET_KEY=<unique private value>
AUTH_JWT_SECRET=<unique private value, at least 32 characters>
PUBLIC_ORIGIN=https://your-host.example
```

Store real values in a secret manager and enter them on the host without putting
them in command arguments, shell history, Git, or logs. The site certificate and
private key are also host-specific. This runbook does not copy them to GitHub.

## 2. Install Community and bootstrap

From the repository root on a **new, empty** host:

```sh
sudo bash deployments/community/production/install.sh /etc/synchrohq/production.env
sudo bash deployments/community/production/bootstrap.sh \
  /etc/synchrohq/production.env TENANT_CODE 'Tenant name' \
  admin@example.org 'Administrator name' 'Root territory' 'Operator organization'
```

The bootstrap prompts twice for the first administrator password in the
terminal. It refuses a second initial bootstrap. No demo account, report, form,
or institutional fixture is created. `install.sh` applies Community migrations
and checks the backend health endpoint. Container ports for PostgreSQL and
MinIO are unpublished; backend and frontend bind only to loopback. Check the
effective Compose configuration before permitting public traffic:

```sh
sudo docker compose --env-file /etc/synchrohq/production.env \
  -f compose.yaml -f compose.production.yaml config --quiet
```

The installer provisions Community only. Enterprise extensions have their own
private installation procedure and must not be required by this checkout.

## 3. Configure HTTPS

Prepare the HTTP challenge endpoint first. Example for a DNS name:

```sh
sudo install -d -m 755 /var/www/synchrohq-acme
sudo python3 deployments/community/production/render-nginx.py \
  --stage acme --host your-host.example \
  --output /etc/nginx/sites-available/synchrohq
sudo ln -s /etc/nginx/sites-available/synchrohq \
  /etc/nginx/sites-enabled/synchrohq
sudo nginx -t && sudo systemctl reload nginx
```

Obtain a valid certificate for the chosen DNS name or IP with the certificate
manager. Its account registration and terms acceptance are interactive operator
steps. Once the certificate files exist, render and activate HTTPS:

```sh
sudo python3 deployments/community/production/render-nginx.py \
  --stage https --host your-host.example \
  --fullchain /etc/letsencrypt/live/your-host.example/fullchain.pem \
  --key /etc/letsencrypt/live/your-host.example/privkey.pem \
  --output /etc/nginx/sites-available/synchrohq
sudo install -m 644 deployments/community/ops/nginx-rate-limit.conf \
  /etc/nginx/conf.d/synchrohq-rate-limit.conf
sudo install -m 644 deployments/community/ops/nginx-proxy.conf \
  /etc/nginx/snippets/synchrohq-proxy.conf
sudo nginx -t && sudo systemctl reload nginx
```

Install `reload-nginx.sh` as the certificate manager's deploy hook if using
Certbot (under `/etc/letsencrypt/renewal-hooks/deploy/`), then verify a dry run.
Keep Certbot's own renewal timer enabled. Install an independent twice-daily
expiration guard that attempts renewal within 36 hours of expiry and fails the
systemd service if less than 24 hours remain:

```sh
sudo bash deployments/community/production/install-cert-monitor.sh \
  your-host.example /etc/letsencrypt/live/your-host.example/fullchain.pem
systemctl list-timers synchrohq-cert-check.timer --no-pager
systemctl show synchrohq-cert-check.service -p Result -p ExecMainStatus
```

Connect your host monitoring to a failed `synchrohq-cert-check.service` and
alert an operator; a local journal entry alone is not an external alert. A
successful dry run plus an active guard is sufficient for deployment validation;
there is no need to wait for the next real certificate expiry.

## 4. Backups and verification

The root-owned checkout can install the generic daily systemd timer:

```sh
sudo bash deployments/community/production/install-backup-timer.sh \
  /etc/synchrohq/production.env /var/backups/synchrohq
sudo systemctl start synchrohq-backup.service
systemctl show synchrohq-backup.service -p Result -p ExecMainStatus
```

The backup pauses Community writers and MinIO. It
stores a PostgreSQL dump, MinIO archive, and SHA-256 manifest. Keep the backup
directory private, monitor its size, and copy each archive off the host through
an approved encrypted backup channel. A same-host backup alone is not disaster
recovery. Run `deployments/community/ops/restore-check.sh` with `--env-file`
against a disposable database for a non-destructive check.

The decisive recovery drill is on a **second clean machine**. Start with the
same pinned repository commit, a suitable private environment file, and an
off-host copy of the backup. Before running `install.sh` or bootstrapping on
that target, execute:

```sh
sudo bash deployments/community/production/restore-new-host.sh \
  /etc/synchrohq/production.env /private/backup-directory 20261003T093636Z
```

The restore script refuses a database containing application tables or a
nonempty object volume. It verifies the archive hashes, restores PostgreSQL
and MinIO, starts services, and applies any later Community migrations. Confirm
the restored tenant, admin login, reports/attachments, permissions, and HTTPS
before permitting public traffic. Do not run it on a live installation.

The manually dispatched [clean-host recovery workflow](../../../.github/workflows/recovery-drill.yml)
performs this drill with synthetic data on two separate fresh GitHub Actions
runners. Its artifact
contains no client data or VM secrets. A customer installation still needs an
off-host backup and an operator-verified restore on its own infrastructure.

## Acceptance boundary

Record the commit, image versions, migration revision, backup timestamp and
hash, HTTPS certificate, health checks, authenticated sign-in/sign-out,
authorization isolation, and the clean-host restore result. Without those
checks, this package is a reproducible deployment candidate rather than a
verified Ready to Deploy release. The first real LLM/embedding provider test
is separate from Community availability.
