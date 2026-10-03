"""Phase 5 PostgreSQL gate, restricted to the synthetic development tenant."""

import copy
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
import rfc8785
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.forms.models import Form
from app.modules.reports.models import Report, ReportAttachment, ReportOperation, ReportRevision


def main() -> None:
    if get_settings().app_env != "development":
        raise SystemExit("Development only")
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
        assert revision is not None, "Run the report browser gate first"
        file = session.scalar(
            select(ReportAttachment).where(ReportAttachment.revision_id == revision.id)
        )
        assert file is not None
        official = copy.deepcopy(revision.payload)
        checks = [
            ("reports", "id", revision.report_id, "current_revision_id"),
            ("report_revisions", "id", revision.id, "payload"),
            ("confirmation_proofs", "revision_id", revision.id, "payload_hash"),
            ("report_attachments", "revision_id", revision.id, "sha256"),
            ("report_operations", "revision_id", revision.id, "receipt"),
            ("report_audit_events", "revision_id", revision.id, "code"),
            ("collection_drafts", "id", revision.source_draft_id, "answers"),
            ("draft_attachments", "id", file.attachment_id, "sha256"),
        ]
        for table, key, value, column in checks:
            rejected = False
            try:
                with session.begin_nested():
                    session.execute(
                        text(f"UPDATE {table} SET {column}={column} WHERE {key}=:value"),
                        {"value": value},
                    )
            except DBAPIError as exc:
                assert any(
                    word in str(exc).lower() for word in ("immutable", "confirmed", "already")
                )
                rejected = True
            assert rejected, f"Immutability missing on {table}"
        session.rollback()
    headers = {"Authorization": "Bearer " + credentials["token"]}
    with httpx.Client(base_url="http://localhost:8000", headers=headers, timeout=30) as api:
        version_id = official["snapshot"]["form_version_id"]
        context = api.post("/api/reports/contexts/" + version_id)
        context.raise_for_status()
        grant = api.post("/api/sync/grants/" + version_id)
        grant.raise_for_status()
        now = datetime.now(UTC).isoformat()
        official.update(
            report_id=str(uuid.uuid4()),
            revision_id=str(uuid.uuid4()),
            draft_id=str(uuid.uuid4()),
            created_at=now,
            finalized_at=now,
            confirmed_at=now,
            snapshot=context.json()["snapshot"],
            attachments=[],
        )
        official["answers"].pop("attachments", None)
        source = {
            "operation_id": str(uuid.uuid4()),
            "draft_id": official["draft_id"],
            "device_id": official["device_id"],
            "form_version_id": version_id,
            "base_version": 0,
            "client_updated_at": now,
            "answers": official["answers"],
            "sync_grant": grant.json()["sync_grant"],
        }
        sent = api.post("/api/sync/drafts", json=source)
        sent.raise_for_status()
        canonical = rfc8785.dumps(official)
        operation_id = str(uuid.uuid4())
        request = {
            "operation_id": operation_id,
            "canonical_payload": canonical.decode(),
            "payload_hash": hashlib.sha256(canonical).hexdigest(),
            "context_token": context.json()["context_token"],
        }

        def send(_: int) -> dict:
            response = api.post("/api/reports/confirmations", json=request)
            response.raise_for_status()
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(send, range(2)))
        assert receipts[0] == receipts[1]
    with SessionLocal() as session:
        report_id = uuid.UUID(official["report_id"])
        assert (
            session.scalar(select(func.count()).select_from(Report).where(Report.id == report_id))
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReportRevision)
                .where(ReportRevision.report_id == report_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReportOperation)
                .where(ReportOperation.id == uuid.UUID(operation_id))
            )
            == 1
        )
    print(
        "PASS: all 8 PostgreSQL immutability guards reject changes."
    )
    print(
        "PASS: simultaneous confirmations create one effect and identical receipts."
    )


if __name__ == "__main__":
    main()
