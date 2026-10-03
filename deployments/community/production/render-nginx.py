#!/usr/bin/env python3
"""Render a host-specific Nginx site; installation and certificate issuance are separate."""

import argparse
import ipaddress
import re
from pathlib import Path


def public_host(value: str) -> str:
    try:
        ipaddress.IPv4Address(value)
        return value
    except ipaddress.AddressValueError:
        pass
    if len(value) > 253 or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
        value,
    ):
        raise argparse.ArgumentTypeError("Expected an IPv4 address or DNS hostname")
    return value


def existing_certificate(value: str) -> Path:
    path = Path(value)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or not path.is_file():
        raise argparse.ArgumentTypeError("Certificate path must be an existing safe absolute file")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, type=public_host)
    parser.add_argument("--stage", choices=("acme", "https"), required=True)
    parser.add_argument("--fullchain", type=existing_certificate)
    parser.add_argument("--key", type=existing_certificate)
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.web_port <= 65535:
        parser.error("--web-port must be between 1 and 65535")
    if not args.output.is_absolute():
        parser.error("--output must be absolute")
    if args.stage == "https" and (args.fullchain is None or args.key is None):
        parser.error("HTTPS stage requires --fullchain and --key")

    template_name = "nginx.conf.template" if args.stage == "https" else "nginx-acme.conf.template"
    template = Path(__file__).with_name(template_name).read_text()
    rendered = (
        template.replace("@PUBLIC_HOST@", args.host)
        .replace("@CERT_FULLCHAIN@", str(args.fullchain or ""))
        .replace("@CERT_KEY@", str(args.key or ""))
        .replace("@WEB_PORT@", str(args.web_port))
    )
    args.output.write_text(rendered)
    print(args.output)


if __name__ == "__main__":
    main()
