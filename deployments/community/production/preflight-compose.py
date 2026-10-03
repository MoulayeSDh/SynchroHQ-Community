#!/usr/bin/env python3
"""Reject unsafe effective production Compose configuration without printing secrets."""

import json
import sys
from urllib.parse import urlparse


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Production preflight failed: {message}")


services = json.load(sys.stdin)["services"]
backend = services["backend"]["environment"]
minio = services["minio"]["environment"]
postgres = services["postgres"]["environment"]
require(backend["APP_ENV"] == "production", "backend environment")
require(str(backend["DEMO_LOGIN_ENABLED"]).lower() == "false", "demo login")
origin = urlparse(backend["CORS_ORIGINS"])
require(origin.scheme == "https" and bool(origin.netloc) and
        origin.path in ("", "/") and not origin.query and not origin.fragment and
        not origin.username and "," not in backend["CORS_ORIGINS"],
        "single HTTPS public origin")
require(len(backend["AUTH_JWT_SECRET"]) >= 32, "JWT secret length")
require(
    backend["AUTH_JWT_SECRET"] != "development-only-change-me-32-chars",
    "development JWT secret",
)
require(len(postgres["POSTGRES_PASSWORD"]) >= 16, "PostgreSQL password length")
require(postgres["POSTGRES_PASSWORD"] != "synchrohq_dev", "development DB password")
require(len(minio["MINIO_ROOT_PASSWORD"]) >= 16, "object-storage secret length")
require(minio["MINIO_ROOT_PASSWORD"] != "synchrohq_dev_secret", "development object secret")
require(minio["MINIO_ROOT_USER"] != "synchrohq_dev", "development object access key")
require(backend["POSTGRES_PASSWORD"] == postgres["POSTGRES_PASSWORD"] and
        backend["POSTGRES_DB"] == postgres["POSTGRES_DB"] and
        backend["POSTGRES_USER"] == postgres["POSTGRES_USER"],
        "backend/database credentials mismatch")
require(backend["S3_ACCESS_KEY"] == minio["MINIO_ROOT_USER"] and
        backend["S3_SECRET_KEY"] == minio["MINIO_ROOT_PASSWORD"],
        "backend/object-storage credentials mismatch")

for name in ("postgres", "minio"):
    require(not services[name].get("ports"), f"{name} must not publish ports")
for name in ("backend", "frontend"):
    service = services.get(name)
    if service:
        ports = service.get("ports") or []
        require(ports, f"{name} must have an explicit loopback binding")
        require(all(port.get("host_ip") == "127.0.0.1" for port in ports),
                f"{name} must bind loopback only")
print("Production Compose preflight: PASS")
