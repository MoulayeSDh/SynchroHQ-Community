# ruff: noqa: F811
import copy
import uuid
from datetime import UTC, datetime, timedelta

from test_hierarchy import obligation, setup
from test_reports import request_for
from test_sync import env  # noqa: F401

from app.modules.hierarchy.models import ExpectedReport
from app.modules.identity.security import get_current_user_id


def test_overview_counts_official_receipts_once_and_applies_scope(env):
    client, session, app, _, foreign, *_ = env
    draft, payload, _ = setup(env)
    expected = obligation(client, payload)
    identifier = expected["items"][0]["id"]
    today = datetime.now(UTC).date()
    path = f"/api/reports/analytics/overview?start={today}&end={today}"
    initial = client.get(path)
    assert initial.status_code == 200
    assert initial.json()["counts"] == {
        "EXPECTED": 1, "RECEIVED": 0, "LATE": 0, "MISSING": 0
    }
    grant = client.post(
        "/api/reports/contexts/" + draft["form_version_id"],
        params={"expected_report_id": identifier},
    ).json()
    second = copy.deepcopy(draft)
    second.update(draft_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4()))
    assert client.post("/api/sync/drafts", json=second).status_code == 200
    linked = {
        **payload,
        "report_id": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "draft_id": second["draft_id"],
        "snapshot": grant["snapshot"],
        "expected_report_id": identifier,
    }
    now = datetime.now(UTC).isoformat()
    linked.update(created_at=now, finalized_at=now, confirmed_at=now)
    result = client.post(
        "/api/reports/confirmations", json=request_for(linked, grant["context_token"])
    )
    assert result.status_code == 200, result.text
    current = client.get(path).json()
    assert current["total"] == 1
    assert current["counts"]["RECEIVED"] == 1
    assert sum(current["by_period"][0]["counts"].values()) == 1
    assert sum(current["by_territory"][0]["counts"].values()) == 1
    expected_row = session.get(ExpectedReport, uuid.UUID(identifier))
    expected_row.expected_by = datetime.now(UTC) - timedelta(days=1)
    session.commit()
    late = client.get(path).json()
    assert late["counts"]["LATE"] == 1
    assert late["counts"]["RECEIVED"] == 0
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    hidden = client.get(path).json()
    assert hidden["total"] == 0
    assert hidden["available_territories"] == []


def test_overview_reference_ten_obligations_eight_on_time_one_late_one_missing(env):
    client, session, *_ = env
    draft, payload, _ = setup(env)
    today = datetime.now(UTC).date()
    first = today - timedelta(days=9)
    result = obligation(client, payload, first, today)
    assert result["total"] == 10
    for index, item in enumerate(result["items"]):
        expected = session.get(ExpectedReport, uuid.UUID(item["id"]))
        expected.expected_by = datetime.now(UTC) + (
            timedelta(days=1) if index < 8 else -timedelta(days=1)
        )
    session.commit()
    for item in result["items"][:9]:
        grant = client.post(
            "/api/reports/contexts/" + draft["form_version_id"],
            params={"expected_report_id": item["id"]},
        )
        assert grant.status_code == 200, grant.text
        context = grant.json()
        synced = copy.deepcopy(draft)
        synced.update(draft_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4()))
        assert client.post("/api/sync/drafts", json=synced).status_code == 200
        linked = {
            **payload,
            "report_id": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "draft_id": synced["draft_id"],
            "snapshot": context["snapshot"],
            "expected_report_id": item["id"],
        }
        now = datetime.now(UTC).isoformat()
        linked.update(created_at=now, finalized_at=now, confirmed_at=now)
        received = client.post(
            "/api/reports/confirmations", json=request_for(linked, context["context_token"])
        )
        assert received.status_code == 200, received.text
    path = f"/api/reports/analytics/overview?start={first}&end={today}"
    overview = client.get(path)
    assert overview.status_code == 200, overview.text
    summary = overview.json()
    assert summary["total"] == 10
    assert summary["counts"] == {
        "EXPECTED": 0, "RECEIVED": 8, "LATE": 1, "MISSING": 1
    }
    assert sum(sum(row["counts"].values()) for row in summary["by_period"]) == 10
    assert sum(sum(row["counts"].values()) for row in summary["by_territory"]) == 10
