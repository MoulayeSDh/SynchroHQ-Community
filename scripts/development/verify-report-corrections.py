"""PostgreSQL correction gate, restricted to the synthetic development tenant."""

import copy
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
import rfc8785
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.forms.models import Form
from app.modules.reports.models import Report, ReportRevision


def main() -> None:
    assert get_settings().app_env == "development", "Development only"
    credentials = json.loads(Path("/app/.local/forms-demo.json").read_text())
    with SessionLocal() as session:
        form = session.get(Form, uuid.UUID(credentials["form_id"]))
        assert form is not None
        revision = session.scalar(
            select(ReportRevision)
            .join(Report, Report.id == ReportRevision.report_id)
            .where(Report.tenant_id == form.tenant_id)
            .order_by(ReportRevision.server_received_at.desc())
        )
        assert revision is not None
        template = copy.deepcopy(revision.payload)
    headers = {"Authorization": "Bearer " + credentials["token"]}
    with httpx.Client(base_url="http://localhost:8000", headers=headers, timeout=30) as api:

        def post(path, data=None, params=None):
            response = api.post(path, json=data, params=params)
            response.raise_for_status()
            return response.json()

        version = template["snapshot"]["form_version_id"]
        context = post("/api/reports/contexts/" + version)
        grant = post("/api/sync/grants/" + version)

        def prepare(payload, context, grant):
            now = datetime.now(UTC).isoformat()
            payload.update(
                revision_id=str(uuid.uuid4()),
                draft_id=str(uuid.uuid4()),
                created_at=now,
                finalized_at=now,
                confirmed_at=now,
                snapshot=context["snapshot"],
                attachments=[],
            )
            payload["answers"].pop("attachments", None)
            post(
                "/api/sync/drafts",
                {
                    "operation_id": str(uuid.uuid4()),
                    "draft_id": payload["draft_id"],
                    "device_id": payload["device_id"],
                    "form_version_id": version,
                    "base_version": 0,
                    "client_updated_at": now,
                    "answers": payload["answers"],
                    "sync_grant": grant,
                },
            )
            canonical = rfc8785.dumps(payload)
            return {
                "operation_id": str(uuid.uuid4()),
                "canonical_payload": canonical.decode(),
                "payload_hash": hashlib.sha256(canonical).hexdigest(),
                "context_token": context["context_token"],
            }

        first = copy.deepcopy(template)
        first.update(report_id=str(uuid.uuid4()), revision_number=1)
        first.pop("correction", None)
        body = prepare(first, context, grant["sync_grant"])
        post("/api/reports/confirmations", body)
        change = post(
            "/api/reports/" + first["report_id"] + "/correction-requests",
            {
                "operation_id": str(uuid.uuid4()),
                "revision_id": first["revision_id"],
                "text": "Concurrent correction gate",
            },
        )
        context = post(
            "/api/reports/contexts/" + version, params={"correction_request_id": change["id"]}
        )
        second = copy.deepcopy(first)
        second.update(
            revision_number=2,
            correction={
                "base_revision_id": first["revision_id"],
                "correction_request_id": change["id"],
            },
        )
        second["answers"]["executive_summary"] = "Correction reçue avec concurrence PostgreSQL."
        body = prepare(second, context, context["sync_grant"])

        def send(_):
            response = httpx.post(
                "http://localhost:8000/api/reports/confirmations",
                headers=headers,
                json=body,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(send, range(2)))
        assert receipts[0] == receipts[1]
        viewed = api.get("/api/reports/" + first["report_id"]).json()
        assert len(viewed["revisions"]) == 2
        assert viewed["revisions"][0]["payload"] == first
        assert viewed["current_revision_id"] == second["revision_id"]
        assert viewed["corrections"][0]["state"] == "RESOLVED"
    with SessionLocal() as session:
        checks = [
            ("reports", "id", first["report_id"], "current_revision_id"),
            ("report_revisions", "id", first["revision_id"], "payload_hash"),
            ("correction_requests", "id", change["id"], "text"),
            ("correction_resolutions", "request_id", change["id"], "revision_id"),
            ("report_workflow_operations", "id", change["operation_id"], "receipt"),
        ]
        for table, key, value, column in checks:
            rejected = False
            try:
                with session.begin_nested():
                    session.execute(
                        text(f"UPDATE {table} SET {column}={column} WHERE {key}=:id"), {"id": value}
                    )
            except DBAPIError as exc:
                assert any(word in str(exc).lower() for word in ("immutable", "correction"))
                rejected = True
            assert rejected, table
        session.rollback()
    print(
        "PostgreSQL: concurrent correction has one effect; "
        "two revisions intact; five mutation guards passed."
    )


if __name__ == "__main__":
    main()
