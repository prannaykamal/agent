from fastapi.testclient import TestClient

from src.api.server import app


client = TestClient(app)


def test_t7_search_api_shape_is_preserved_when_provider_unavailable():
    response = client.get("/api/search?q=Python&max_results=2")

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "Python"
    assert "results" in data
    assert "total_results" in data
    assert data["results"] == []


def test_t7_calendar_api_shape_is_preserved_as_mcp_wrapper():
    response = client.get("/api/calendar/events")

    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert "total_events" in data
    assert "result" in data
    assert isinstance(data["events"], list)


def test_t7_email_api_shape_is_preserved_as_gmail_mcp_wrapper():
    response = client.get("/api/email/messages")

    assert response.status_code == 200
    data = response.json()
    assert "messages" in data
    assert "total_messages" in data
    assert "result" in data
    assert isinstance(data["messages"], list)


def test_t7_create_send_routes_keep_approval_shapes():
    calendar_response = client.post(
        "/api/calendar/events",
        json={"title": "Planning", "start_time": "10:00", "end_time": "11:00"},
    )
    email_response = client.post(
        "/api/email/send",
        json={"to": "u@example.com", "subject": "s", "body": "b"},
    )

    assert calendar_response.status_code == 200
    assert calendar_response.json()["status"] == "APPROVAL_REQUIRED"
    assert email_response.status_code == 200
    assert email_response.json()["status"] == "APPROVAL_REQUIRED"


def test_t7_integrations_status_reports_provider_managed_mcp():
    response = client.get("/api/integrations/status")

    assert response.status_code == 200
    data = response.json()["integrations"]
    assert data["search"]["mode"] == "provider_managed_mcp"
    assert data["calendar"]["provider_id"] == "google_calendar"
    assert data["email_smtp"]["provider_id"] == "gmail"
