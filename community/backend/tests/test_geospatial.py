# ruff: noqa: F811
from test_forms import env  # noqa: F401

from app.modules.geospatial.service import valid_points


def test_gps_projection_keeps_each_valid_activity_index():
    answers = {"activities": [
        {"location": {"latitude": 18.09, "longitude": -15.98}},
        {"location": None},
        {"location": {"latitude": 18.15, "longitude": -15.90}},
        {"location": {"latitude": True, "longitude": 1}},
        {"location": {"latitude": 91, "longitude": 1}},
    ]}
    assert valid_points(answers) == [(0, 18.09, -15.98), (2, 18.15, -15.90)]


def test_no_spatial_query_without_reports_read_permission(env):
    client, *_ = env
    response = client.get("/api/reports/geospatial/points?start=2026-09-28&end=2026-09-29")
    assert response.status_code == 200
    assert response.json() == {
        "start": "2026-09-28", "end": "2026-09-29", "total": 0,
        "truncated": False, "items": [], "available_forms": [],
    }
