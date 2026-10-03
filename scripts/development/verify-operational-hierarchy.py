"""Check PostgreSQL obligation invariants in the synthetic Phase 6B tenant."""

import json
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.hierarchy.models import ExpectedReceipt, ReportReview


def main() -> None:
    if get_settings().app_env != "development":
        raise SystemExit("Development only")
    demo = json.loads(Path("/app/.local/hierarchy-demo.json").read_text())
    assert demo["tenant_id"] == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "synchrohq:phase6b-demo")
    )
    headers = {"Authorization": "Bearer " + demo["actors"]["reviewer"]["token"]}
    with SessionLocal() as session:
        expected_id = uuid.UUID(demo["obligations"][0]["expected_id"])
        received = session.get(ExpectedReceipt, expected_id)
        assert received is not None, "Run the browser gate first"
        report_id = received.report_id
    with httpx.Client(
        base_url="http://localhost:8000", headers=headers, timeout=30
    ) as client:
        report = client.get("/api/reports/" + str(report_id))
        report.raise_for_status()
        current = report.json()["current_revision_id"]
        body = {"operation_id": str(uuid.uuid4()), "revision_id": current}
        first = client.post(f"/api/reports/workflow/{report_id}/review", json=body)
        first.raise_for_status()
        retry = client.post(f"/api/reports/workflow/{report_id}/review", json=body)
        assert retry.json() == first.json()
        confirmed = client.get("/api/reports/workflow/inbox?status=CONFIRMED").json()
        assert any(item["id"] == str(report_id) for item in confirmed)
    with SessionLocal() as session:
        review = session.scalar(
            select(ReportReview).where(
                ReportReview.revision_id == uuid.UUID(current),
                ReportReview.reviewer_id == uuid.UUID(demo["actors"]["reviewer"]["id"]),
            )
        )
        assert review is not None
        checks = [
            (
                "reporting_requirements",
                "id",
                demo["obligations"][0]["expected_id"],
                "deadline_hour",
            ),
            ("expected_reports", "id", str(expected_id), "expected_by"),
            (
                "expected_report_receipts",
                "expected_id",
                str(expected_id),
                "received_at",
            ),
            ("report_reviews", "id", str(review.id), "reviewed_at"),
        ]
        # The requirement key is different from its deterministic expected key.
        requirement_id = session.scalar(
            text("SELECT requirement_id FROM expected_reports WHERE id=:id"),
            {"id": expected_id},
        )
        checks[0] = (
            "reporting_requirements",
            "id",
            str(requirement_id),
            "deadline_hour",
        )
        for table, key, value, column in checks:
            rejected = False
            try:
                with session.begin_nested():
                    session.execute(
                        text(f"UPDATE {table} SET {column}={column} WHERE {key}=:id"),
                        {"id": uuid.UUID(value)},
                    )
            except DBAPIError as exc:
                assert "immutable" in str(exc).lower()
                rejected = True
            assert rejected, table
        session.rollback()
    print(
        "PostgreSQL: review retry preserved; four obligation/history mutation guards passed."
    )


if __name__ == "__main__":
    main()
