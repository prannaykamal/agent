import json

from fastapi.testclient import TestClient

from src.api.server import app
from src.mcp_gateway.protocol.oauth import finish_google_oauth, save_oauth_tokens, start_google_oauth
from src.tools.mcp_provider_config import load_target_mcp_provider_configs, redact_observability_text
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache


client = TestClient(app)


def _gmail_config(tmp_path):
    path = tmp_path / "mcp_config.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "enabled": True,
                        "transport": "http",
                        "url": "https://gmailmcp.googleapis.com/mcp/v1",
                        "oauth": {"clientId": "demo-client", "clientSecret": "demo-secret"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_t6_oauth_error_text_keeps_http_status():
    text = redact_observability_text(
        "MCP HTTP 401: Request is missing required authentication credential. Expected OAuth 2 access token.",
        extra_values=("demo-secret",),
    )
    assert text is not None
    assert "401" in text
    assert text != "[REDACTED]"
    assert "demo-secret" not in text


def test_t6_oauth_start_requires_google_client():
    clear_mcp_provider_discovery_cache()
    response = client.get("/api/tools/mcp/providers/gmail/oauth/start")
    assert response.status_code == 400
    assert "OAuth" in response.json()["detail"]


def test_t6_oauth_start_returns_google_authorization_url(tmp_path, monkeypatch):
    config = _gmail_config(tmp_path)
    pending = tmp_path / "oauth_pending.json"
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: config)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.PENDING_PATH", pending)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.mcp_config_path", lambda: config)
    result = start_google_oauth("gmail", config_path=config)
    assert result["provider_id"] == "gmail"
    assert result["redirect_uri"] == "http://127.0.0.1:8000/api/tools/mcp/oauth/callback"
    assert "accounts.google.com" in result["authorization_url"]
    assert "demo-client" in result["authorization_url"]
    assert "demo-secret" not in result["authorization_url"]
    assert pending.exists()


def test_t6_oauth_start_returns_google_authorization_url_for_stdio_gmail(tmp_path, monkeypatch):
    path = tmp_path / "mcp_config.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": "python",
                        "args": ["-m", "src.mcp_gateway.gmail_local_mcp"],
                        "oauth": {"clientId": "demo-client", "clientSecret": "demo-secret"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    pending = tmp_path / "oauth_pending.json"
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: path)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.PENDING_PATH", pending)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.mcp_config_path", lambda: path)
    result = start_google_oauth("gmail", config_path=path)
    assert result["provider_id"] == "gmail"
    assert "accounts.google.com" in result["authorization_url"]
    assert "gmail.compose" in result["authorization_url"]
    assert "gmail.send" in result["authorization_url"]


def test_t6_oauth_callback_persists_access_token(tmp_path, monkeypatch):
    config = _gmail_config(tmp_path)
    pending = tmp_path / "oauth_pending.json"
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: config)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.PENDING_PATH", pending)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.mcp_config_path", lambda: config)
    start_google_oauth("gmail", config_path=config)
    state = next(iter(json.loads(pending.read_text(encoding="utf-8"))))

    def fake_post(_url, fields):
        assert fields["grant_type"] == "authorization_code"
        assert fields["code"] == "auth-code"
        return {"access_token": "ya29-test-token", "refresh_token": "refresh-test", "expires_in": 3600}

    monkeypatch.setattr("src.mcp_gateway.protocol.oauth._post_form", fake_post)
    result = finish_google_oauth("auth-code", state)
    assert result["status"] == "signed_in"
    loaded = load_target_mcp_provider_configs(config)["gmail"]
    assert loaded.oauth["accessToken"] == "ya29-test-token"
    assert loaded.oauth["refreshToken"] == "refresh-test"
    status = loaded.to_status_dict()
    assert status["oauth_signed_in"] is True
    assert "ya29-test-token" not in json.dumps(status)


def test_t6_save_oauth_tokens_keeps_existing_client(tmp_path, monkeypatch):
    config = _gmail_config(tmp_path)
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: config)
    save_oauth_tokens("gmail", access_token="tok-1", refresh_token="ref-1", expires_in=60, config_path=config)
    raw = json.loads(config.read_text(encoding="utf-8"))
    oauth = raw["mcpServers"]["gmail"]["oauth"]
    assert oauth["clientId"] == "demo-client"
    assert oauth["accessToken"] == "tok-1"
    assert oauth["refreshToken"] == "ref-1"


def test_resolve_google_access_token_reads_mcp_oauth(tmp_path, monkeypatch):
    from src.mcp_gateway.protocol.oauth import resolve_google_access_token

    config = tmp_path / "mcp_config.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": "python",
                        "args": ["-m", "src.mcp_gateway.gmail_local_mcp"],
                        "oauth": {"accessToken": "ya29-from-config"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: config)
    monkeypatch.setattr("src.mcp_gateway.protocol.oauth.mcp_config_path", lambda: config)
    assert resolve_google_access_token("gmail", env={}) == "ya29-from-config"
    assert resolve_google_access_token("gmail", env={"GOOGLE_ACCESS_TOKEN": "env-token"}) == "env-token"
