# Community VM pilot

This configuration installs the Community stack for a technical VM check. It keeps PostgreSQL and object storage inside Docker and binds the web/API ports to the VM's loopback interface. It does not expose SynchroHQ to the public Internet.

## Requirements

- Ubuntu 24.04 (amd64)
- Docker Engine with the Compose plugin (Compose 2.24.4 or newer)
- A fresh checkout of this repository

Install Docker using the [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). From the repository root, create a private `.env` with unique values for `POSTGRES_PASSWORD`, `S3_SECRET_KEY`, and `AUTH_JWT_SECRET`; set `S3_ACCESS_KEY` to a non-default identifier. Keep `.env` mode `0600` and never commit it.

The commands below use `sudo` because the pilot VM user is not a member of the Docker group. If Docker is configured for your account, omit `sudo`.

```sh
sudo docker compose -f compose.yaml -f compose.pilot.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.pilot.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.pilot.yaml exec -T backend alembic upgrade head
curl --fail http://127.0.0.1:8001/api/health
curl --fail http://127.0.0.1:3000/
```

The checked-in `compose.yaml` is for local development. Always include `compose.pilot.yaml` on the VM. Verify the effective port bindings before starting. The pilot override disables demo login and sets `APP_ENV=production`.

After applying the 9B migration, initialize a *new, empty* database exactly once. This command prompts for the password twice; never pass a password in shell arguments or an environment variable. Run it from an interactive terminal so `getpass` can read without echoing:

```sh
sudo docker compose -f compose.yaml -f compose.pilot.yaml exec backend \
  python -m app.modules.identity.bootstrap \
  --tenant-code DCORP_INVEST --tenant-name "D-Corp Invest" \
  --admin-identifier admin@dcorpinvest.com --admin-name "D-Corp Invest Admin" \
  --root-territory-name "SynchroHQ Pilot" --organization-name "D-Corp Invest"
```

The bootstrap refuses a second run and refuses any database that already contains users, tenants, territories or organizations. Change the example identifiers and names for another installation. It creates only the tenant, a technical root scope, an operator organization, and its administrator; it does not create institutional fixtures, forms, or reports. Log in with that identifier and password through the application; the first administrator has the existing Community permissions across the new tenant's root scope and descendants. Session tokens expire after one hour and sign-out revokes the current server session while online. No demo account is enabled in production.

For a fresh installation, follow [the production runbook](production/README.md) for TLS, backups, and the remaining acceptance gates. A public login page alone is not evidence that the installation is production-ready.
