# ruff: noqa: F811
import copy
import uuid
from datetime import UTC, date, datetime, timedelta

from test_reports import prepare, request_for
from test_sync import env  # noqa: F401

from app.modules.authorization.models import Permission, RolePermission
from app.modules.hierarchy.models import ExpectedReport, ReportingRequirement
from app.modules.hierarchy.service import category, periods
from app.modules.identity.security import get_current_user_id


def setup(env):
    client, session, *_, role = env
    draft, payload, body = prepare(env)
    for code in ("reporting:manage", "reports:review"):
        p = Permission(code=code)
        session.add(p)
        session.flush()
        session.add(RolePermission(role_id=role.id, permission_id=p.id))
    session.commit()
    return draft, payload, body


def obligation(client, payload, start=None, end=None, cadence="DAILY"):
    start = start or datetime.now(UTC).date()
    end = end or start
    body = {
        "id": str(uuid.uuid4()),
        "form_id": payload["snapshot"]["form_id"],
        "organization_id": payload["snapshot"]["organization"]["id"],
        "territory_id": payload["snapshot"]["territory_id"],
        "cadence": cadence,
        "active_from": str(start),
        "active_until": str(end),
        "timezone": "Africa/Nouakchott",
        "deadline_hour": 18,
        "deadline_days": 1,
    }
    created = client.post("/api/reports/workflow/requirements", json=body)
    assert created.status_code == 200, created.text
    assert client.post("/api/reports/workflow/requirements", json=body).json() == created.json()
    url = f"/api/reports/workflow/requirements/materialize?start={start}&end={end}"
    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 200
    response = client.get(f"/api/reports/workflow/expected?start={start}&end={end}")
    assert response.status_code == 200
    return response.json()


def test_obligations_use_explicit_receipts_and_confirmation_binding(env):
    client, session, _, user, *_ = env
    draft, payload, body = setup(env)
    expected = obligation(client, payload)
    assert expected["total"] == 1
    assert expected["counts"]["EXPECTED"] == 1
    assert client.post("/api/reports/confirmations", json=body).status_code == 200
    # An ordinary report does not satisfy an obligation by resembling it.
    assert (
        client.get(
            f"/api/reports/workflow/expected?start={datetime.now(UTC).date()}&end={datetime.now(UTC).date()}"
        ).json()["counts"]["EXPECTED"]
        == 1
    )
    identifier = expected["items"][0]["id"]
    context = client.post(
        "/api/reports/contexts/" + draft["form_version_id"],
        params={"expected_report_id": identifier},
    )
    assert context.status_code == 200
    grant = context.json()
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
    received = client.post(
        "/api/reports/confirmations", json=request_for(linked, grant["context_token"])
    )
    assert received.status_code == 200, received.text
    rows = client.get(
        f"/api/reports/workflow/expected?start={datetime.now(UTC).date()}&end={datetime.now(UTC).date()}"
    ).json()
    assert rows["counts"]["RECEIVED"] == 1
    assert rows["items"][0]["report_id"] == linked["report_id"]
    assert (
        client.post(
            "/api/reports/contexts/" + draft["form_version_id"],
            params={"expected_report_id": identifier},
        ).status_code
        == 409
    )


def test_inbox_filters_never_bypass_authorization_and_reviews_are_revision_specific(env):
    client, session, app, user, foreign, _, other_area, *_ = env
    _, payload, body = setup(env)
    assert client.post("/api/reports/confirmations", json=body).status_code == 200
    assert (
        client.get("/api/reports/workflow/inbox?status=TO_REVIEW").json()[0]["id"]
        == payload["report_id"]
    )
    review = {"operation_id": str(uuid.uuid4()), "revision_id": payload["revision_id"]}
    path = "/api/reports/workflow/" + payload["report_id"] + "/review"
    first = client.post(path, json=review)
    assert first.status_code == 200
    assert client.post(path, json=review).json() == first.json()
    assert client.get("/api/reports/workflow/inbox?status=TO_REVIEW").json() == []
    assert len(client.get("/api/reports/workflow/inbox?status=CONFIRMED").json()) == 1
    assert (
        client.get(
            "/api/reports/workflow/inbox", params={"territory_id": str(other_area.id)}
        ).json()
        == []
    )
    assert (
        client.post(
            path,
            json={**review, "operation_id": str(uuid.uuid4()), "revision_id": str(uuid.uuid4())},
        ).status_code
        == 409
    )
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert (
        client.get(
            "/api/reports/workflow/inbox",
            params={"author_id": str(user.id), "territory_id": payload["snapshot"]["territory_id"]},
        ).json()
        == []
    )
    assert client.post(path, json={**review, "operation_id": str(uuid.uuid4())}).status_code == 404


def test_requirement_overlap_invalid_dates_and_invisible_expected_are_rejected(env):
    client, session, app, user, foreign, *_ = env
    draft, payload, _ = setup(env)
    result = obligation(client, payload)
    identifier = result["items"][0]["id"]
    assert (
        client.post(
            "/api/reports/workflow/requirements/materialize?start=2026-01-01&end=2028-01-01"
        ).status_code
        == 422
    )
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert client.post(
        "/api/reports/contexts/" + draft["form_version_id"],
        params={"expected_report_id": identifier},
    ).status_code in (403, 404)
    assert (
        client.get(
            f"/api/reports/workflow/expected?start={datetime.now(UTC).date()}&end={datetime.now(UTC).date()}"
        ).json()["total"]
        == 0
    )


def test_calendar_boundaries_and_missing_before_after_deadline(env):
    client, session, *_ = env
    _, payload, _ = setup(env)
    result = obligation(client, payload)
    item = session.get(ExpectedReport, uuid.UUID(result["items"][0]["id"]))
    requirement = session.get(ReportingRequirement, item.requirement_id)
    deadline = item.expected_by.replace(tzinfo=UTC)
    assert category(session, item, deadline)[0] == "EXPECTED"
    assert category(session, item, deadline + timedelta(microseconds=1))[0] == "MISSING"
    requirement.cadence = "MONTHLY"
    requirement.active_from = date(2028, 2, 1)
    requirement.active_until = date(2028, 2, 29)
    values = list(periods(requirement, date(2028, 2, 1), date(2028, 2, 29)))
    assert len(values) == 1 and values[0][1] == date(2028, 2, 29)
    assert values[0][2] == datetime(2028, 3, 1, 18, tzinfo=UTC)
    requirement.cadence = "WEEKLY"
    requirement.active_from = date(2026, 9, 28)
    requirement.active_until = date(2026, 10, 4)
    values = list(periods(requirement, requirement.active_from, requirement.active_until))
    assert len(values) == 1 and values[0][1] == date(2026, 10, 4)
