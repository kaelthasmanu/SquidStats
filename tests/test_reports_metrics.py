"""Focused behavioural coverage for the reports metrics service."""

from datetime import date, datetime

import pytest
from flask import render_template

from database.models.models import DeniedLog, create_dynamic_models
from routes import reports_routes
from services.analytics.get_reports import get_important_metrics


@pytest.fixture()
def report_models(in_memory_engine):
    """Create isolated daily tables compatible with the reports service."""
    return create_dynamic_models(in_memory_engine, "user_20990103", "log_20990103")


@pytest.fixture()
def report_metrics(db_session, report_models):
    """Return metrics from deliberately aggregated, multi-hour traffic."""
    UserModel, LogModel = report_models
    alice = UserModel(username="alice", ip="192.0.2.10")
    bruno = UserModel(username="bruno", ip="192.0.2.11")
    carla = UserModel(username="carla", ip="192.0.2.12")
    db_session.add_all([alice, bruno, carla])
    db_session.flush()

    shared_url = "HTTPS://WWW.Example.COM:443/download"
    db_session.add_all(
        [
            LogModel(
                user_id=alice.id,
                url=shared_url,
                response=200,
                request_count=5,
                data_transmitted=500,
                created_at=datetime(2026, 9, 3, 8, 5),
            ),
            # A second aggregated row from the same visitor must not increase
            # the unique-visitor count for this page.
            LogModel(
                user_id=alice.id,
                url=shared_url,
                response=204,
                request_count=2,
                data_transmitted=100,
                created_at=datetime(2026, 9, 3, 8, 42),
            ),
            LogModel(
                user_id=bruno.id,
                url=shared_url,
                response=301,
                request_count=3,
                data_transmitted=90,
                created_at=datetime(2026, 9, 3, 13, 10),
            ),
            LogModel(
                user_id=bruno.id,
                url="http://example.com:8080/assets",
                response=404,
                request_count=5,
                data_transmitted=500,
                created_at=datetime(2026, 9, 3, 13, 50),
            ),
            LogModel(
                user_id=carla.id,
                url="Other.ORG/no-scheme",
                response=503,
                request_count=1,
                data_transmitted=10,
                created_at=datetime(2026, 9, 3, 21, 15),
            ),
        ]
    )
    db_session.commit()

    return get_important_metrics(db_session, UserModel, LogModel)


def test_reports_metrics_weight_traffic_and_count_distinct_visitors(report_metrics):
    """Request counts, rather than persisted rows, represent traffic volume."""
    assert report_metrics["total_stats"]["total_requests"] == 16

    activity = {
        item["username"]: item["total_visits"]
        for item in report_metrics["top_users_by_activity"]
    }
    assert activity == {"bruno": 8, "alice": 7, "carla": 1}
    assert report_metrics["top_users_by_activity"][0]["username"] == "bruno"

    page = next(
        item
        for item in report_metrics["top_pages"]
        if item["url"] == "HTTPS://WWW.Example.COM:443/download"
    )
    assert page == {
        "url": "HTTPS://WWW.Example.COM:443/download",
        "total_requests": 10,
        "unique_visits": 2,
        "total_data_bytes": 690,
    }

    response_counts = {
        item["response_code"]: item["count"]
        for item in report_metrics["http_response_distribution"]
    }
    assert response_counts == {200: 5, 204: 2, 301: 3, 404: 5, 503: 1}


def test_reports_metrics_expose_http_hourly_and_normalized_domain_insights(
    report_metrics,
):
    """The additional report insights use the same request-count semantics."""
    assert report_metrics["success_requests"] == 7
    assert report_metrics["redirect_requests"] == 3
    assert report_metrics["client_error_requests"] == 5
    assert report_metrics["server_error_requests"] == 1
    assert report_metrics["successful_request_rate"] == pytest.approx(43.75)
    assert report_metrics["error_request_rate"] == pytest.approx(37.5)
    assert report_metrics["average_data_per_request"] == pytest.approx(75.0)

    hourly_activity = report_metrics["hourly_activity"]
    assert [item["hour"] for item in hourly_activity] == list(range(24))
    activity_by_hour = {
        item["hour"]: (item["requests"], item["data_bytes"]) for item in hourly_activity
    }
    assert activity_by_hour[8] == (7, 600)
    assert activity_by_hour[13] == (8, 590)
    assert activity_by_hour[21] == (1, 10)
    assert activity_by_hour[0] == (0, 0)
    assert report_metrics["peak_hour"] == {
        "hour": 13,
        "requests": 8,
        "data_bytes": 590,
    }

    assert report_metrics["unique_domains"] == 2
    assert report_metrics["top_domains"] == [
        {
            "domain": "example.com",
            "total_requests": 15,
            "total_data_bytes": 1190,
        },
        {
            "domain": "other.org",
            "total_requests": 1,
            "total_data_bytes": 10,
        },
    ]


def test_reports_metrics_keep_a_stable_shape_without_traffic(db_session, report_models):
    """An empty daily table must still be safe for report-card consumers."""
    UserModel, LogModel = report_models
    metrics = get_important_metrics(db_session, UserModel, LogModel)

    assert metrics["total_stats"]["total_requests"] == 0
    assert metrics["total_stats"]["total_data_transmitted"] == 0
    assert metrics["success_requests"] == 0
    assert metrics["redirect_requests"] == 0
    assert metrics["client_error_requests"] == 0
    assert metrics["server_error_requests"] == 0
    assert metrics["successful_request_rate"] == 0
    assert metrics["error_request_rate"] == 0
    assert metrics["average_data_per_request"] == 0
    assert metrics["unique_domains"] == 0
    assert metrics["top_domains"] == []
    assert metrics["peak_hour"] == {
        "hour": 0,
        "requests": 0,
        "data_bytes": 0,
    }
    assert metrics["hourly_activity"] == [
        {"hour": hour, "requests": 0, "data_bytes": 0} for hour in range(24)
    ]


def test_historical_reports_view_renders_enriched_metrics_for_selected_date(
    client, db_session, report_models, monkeypatch
):
    """The date picker and additional dashboard elements use the selected day."""
    client.application.jinja_env.globals["csrf_token"] = lambda: ""
    monkeypatch.setattr(reports_routes, "get_session", lambda: db_session)
    monkeypatch.setattr(
        reports_routes, "get_dynamic_models", lambda _date_suffix: report_models
    )

    response = client.get("/reports/date/2099-01-03")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'value="2099-01-03"' in page
    assert 'id="hourlyActivityChart"' in page
    assert '"hourlyActivity"' in page
    assert "Calidad y seguridad del tráfico" in page
    assert "Top dominios de destino" in page


def test_reports_scope_blocked_request_metrics_to_the_selected_day(
    db_session, report_models
):
    """TCP_DENIED entries are stored separately and must not leak across days."""
    UserModel, LogModel = report_models
    user = UserModel(username="alice", ip="192.0.2.10")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        LogModel(
            user_id=user.id,
            url="https://example.com",
            response=200,
            request_count=3,
            data_transmitted=0,
            created_at=datetime(2099, 1, 3, 12),
        )
    )
    db_session.add_all(
        [
            DeniedLog(
                username="alice",
                ip="192.0.2.10",
                url="https://blocked.example",
                method="GET",
                status="TCP_DENIED/403",
                response=403,
                created_at=datetime(2099, 1, 3, 0),
            ),
            DeniedLog(
                username="bob",
                ip="192.0.2.11",
                url="https://blocked.example",
                method="GET",
                status="TCP_DENIED/403",
                response=403,
                created_at=datetime(2099, 1, 3, 23, 59, 59),
            ),
            DeniedLog(
                username="carla",
                ip="192.0.2.12",
                url="https://blocked.example",
                method="GET",
                status="TCP_DENIED/403",
                response=403,
                created_at=datetime(2099, 1, 4),
            ),
        ]
    )
    db_session.commit()

    metrics = get_important_metrics(
        db_session, UserModel, LogModel, report_date=date(2099, 1, 3)
    )

    assert metrics["blocked_requests"] == 2
    assert metrics["blocked_users"] == 2
    assert metrics["blocked_ips"] == 2
    assert metrics["blocked_request_rate"] == pytest.approx(40.0)


def test_reports_pdf_includes_the_new_summary_and_destination_metrics(
    flask_app, report_metrics
):
    """The exported report retains the important information shown on screen."""
    metrics = {
        **report_metrics,
        "http_response_distribution_chart": {
            "labels": ["200"],
            "data": [report_metrics["success_requests"]],
        },
    }
    with flask_app.test_request_context("/reports/download/pdf?date=2099-01-03"):
        document = render_template(
            "reports_pdf.html",
            metrics=metrics,
            selected_date=date(2099, 1, 3),
            generated_at="2099-01-03 12:00:00",
        )

    assert "Tasa de éxito HTTP:" in document
    assert "Top dominios de destino" in document
    assert "example.com" in document
