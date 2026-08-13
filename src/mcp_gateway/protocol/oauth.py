"""Google OAuth for Gmail and Calendar MCP providers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from src.config import AGENT_DIR
from src.tools.mcp_provider_config import (
    TARGET_MCP_PROVIDER_ALIASES,
    load_target_mcp_provider_configs,
    mcp_config_path,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8000/api/tools/mcp/oauth/callback"
PENDING_PATH = AGENT_DIR / "oauth_pending.json"
OAUTH_HTTP_PROVIDERS = {"gmail", "google_calendar"}
OAUTH_GOOGLE_PROVIDERS = OAUTH_HTTP_PROVIDERS
DEFAULT_SCOPES = {
    "gmail": (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.send",
    ),
    "google_calendar": (
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    ),
}


def oauth_access_token(oauth: Optional[Mapping[str, Any]]) -> str:
    data = dict(oauth or {})
    return str(data.get("accessToken") or data.get("access_token") or "").strip()


def resolve_google_access_token(provider_id: str, env: Optional[Mapping[str, str]] = None) -> str:
    """Return a Google token from process env, then MCP OAuth / provider env."""
    source = env if env is not None else os.environ
    token = str(
        source.get("GOOGLE_ACCESS_TOKEN")
        or source.get("GMAIL_ACCESS_TOKEN")
        or source.get("CALENDAR_ACCESS_TOKEN")
        or ""
    ).strip()
    if token:
        return token
    try:
        configs = load_target_mcp_provider_configs()
        provider = configs.get(provider_id)
        if provider is None:
            return ""
        provider = ensure_fresh_access_token(provider)
        token = oauth_access_token(getattr(provider, "oauth", None))
        if token:
            return token
        merged = stdio_env_with_oauth(getattr(provider, "env", None), getattr(provider, "oauth", None))
        return str(
            merged.get("GOOGLE_ACCESS_TOKEN")
            or merged.get("GMAIL_ACCESS_TOKEN")
            or merged.get("CALENDAR_ACCESS_TOKEN")
            or ""
        ).strip()
    except Exception:
        return ""


def stdio_env_with_oauth(
    env: Optional[Mapping[str, str]] = None,
    oauth: Optional[Mapping[str, Any]] = None,
    *,
    project_root: Optional[Path] = None,
) -> Dict[str, str]:
    """Copy provider env and inject a fresh Google access token for stdio MCP servers."""
    merged = {str(key): str(value) for key, value in dict(env or {}).items() if value is not None}
    token = oauth_access_token(oauth)
    if token:
        merged.setdefault("GMAIL_ACCESS_TOKEN", token)
        merged.setdefault("CALENDAR_ACCESS_TOKEN", token)
        merged.setdefault("GOOGLE_ACCESS_TOKEN", token)
    merged.setdefault("PYTHONUNBUFFERED", "1")
    if project_root is not None:
        root = str(project_root)
        existing = merged.get("PYTHONPATH") or ""
        merged["PYTHONPATH"] = os.pathsep.join(part for part in (root, existing) if part)
    return merged


def _pending_store() -> Dict[str, Any]:
    if not PENDING_PATH.exists():
        return {}
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_pending(data: Dict[str, Any]) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _post_form(url: str, fields: Dict[str, str]) -> Dict[str, Any]:
    encoded = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Google OAuth token exchange failed ({exc.code}).") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Google OAuth token exchange returned non-JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Google OAuth token exchange returned an invalid payload.")
    if payload.get("error"):
        raise ValueError("Google OAuth token exchange was rejected.")
    return payload


def _server_key_for_provider(raw: Dict[str, Any], provider_id: str) -> Optional[str]:
    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    aliases = {provider_id, *TARGET_MCP_PROVIDER_ALIASES.get(provider_id, [])}
    for name in servers:
        if str(name).strip().lower() in aliases:
            return str(name)
    return None


def save_oauth_tokens(
    provider_id: str,
    *,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: Optional[int] = None,
    config_path: Optional[Path] = None,
) -> None:
    path = Path(config_path) if config_path else mcp_config_path()
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(raw, dict):
        raw = {}
    key = _server_key_for_provider(raw, provider_id)
    if key is None:
        raise ValueError(f"Provider '{provider_id}' is missing from MCP config.")
    servers = raw.setdefault("mcpServers", {})
    server = servers.setdefault(key, {})
    if not isinstance(server, dict):
        raise ValueError(f"Provider '{provider_id}' MCP config is invalid.")
    oauth = dict(server.get("oauth") or {})
    oauth["accessToken"] = access_token
    if refresh_token:
        oauth["refreshToken"] = refresh_token
    if expires_in:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=max(int(expires_in) - 60, 30))
        oauth["expiresAt"] = expiry.replace(microsecond=0).isoformat()
    server["oauth"] = oauth
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

    clear_mcp_provider_discovery_cache()


def start_google_oauth(
    provider_id: str,
    *,
    config_path: Optional[Path] = None,
    redirect_uri: Optional[str] = None,
) -> Dict[str, str]:
    clean_id = str(provider_id or "").strip()
    if clean_id not in OAUTH_HTTP_PROVIDERS:
        raise ValueError(f"Provider '{clean_id}' does not use Google OAuth.")
    config = load_target_mcp_provider_configs(config_path)[clean_id]
    client_id = str((config.oauth or {}).get("clientId") or "").strip()
    if not config.enabled or not client_id:
        raise ValueError(f"Provider '{clean_id}' is missing a Google OAuth client ID.")
    scopes = list(config.scopes or DEFAULT_SCOPES.get(clean_id, ()))
    if not scopes:
        scopes = list(DEFAULT_SCOPES.get(clean_id, ()))
    redirect = str(redirect_uri or (config.oauth or {}).get("redirectUri") or DEFAULT_REDIRECT_URI).strip()
    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    pending = _pending_store()
    pending[state] = {
        "provider_id": clean_id,
        "code_verifier": verifier,
        "redirect_uri": redirect,
        "config_path": str(config_path) if config_path else "",
        "created_at": time.time(),
    }
    _write_pending(pending)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {
        "provider_id": clean_id,
        "authorization_url": f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}",
        "redirect_uri": redirect,
    }


def finish_google_oauth(code: str, state: str) -> Dict[str, str]:
    clean_code = str(code or "").strip()
    clean_state = str(state or "").strip()
    if not clean_code or not clean_state:
        raise ValueError("Google OAuth callback is missing code or state.")
    pending = _pending_store()
    record = pending.pop(clean_state, None)
    _write_pending(pending)
    if not isinstance(record, dict):
        raise ValueError("Google OAuth state is invalid or expired. Start sign-in again.")
    if time.time() - float(record.get("created_at") or 0) > 900:
        raise ValueError("Google OAuth state expired. Start sign-in again.")
    provider_id = str(record.get("provider_id") or "")
    config_path = Path(record["config_path"]) if record.get("config_path") else None
    config = load_target_mcp_provider_configs(config_path)[provider_id]
    payload = _post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": str((config.oauth or {}).get("clientId") or ""),
            "client_secret": str((config.oauth or {}).get("clientSecret") or ""),
            "code": clean_code,
            "code_verifier": str(record.get("code_verifier") or ""),
            "grant_type": "authorization_code",
            "redirect_uri": str(record.get("redirect_uri") or DEFAULT_REDIRECT_URI),
        },
    )
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Google OAuth did not return an access token.")
    save_oauth_tokens(
        provider_id,
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or "").strip() or None,
        expires_in=int(payload.get("expires_in") or 3600),
        config_path=config_path,
    )
    return {"provider_id": provider_id, "status": "signed_in"}


def _token_expired(oauth: Dict[str, str]) -> bool:
    raw = str(oauth.get("expiresAt") or "").strip()
    if not raw:
        return False
    try:
        expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expiry


def ensure_fresh_access_token(provider: Any, *, config_path: Optional[Path] = None) -> Any:
    oauth = dict(getattr(provider, "oauth", None) or {})
    access = str(oauth.get("accessToken") or oauth.get("access_token") or "").strip()
    refresh = str(oauth.get("refreshToken") or oauth.get("refresh_token") or "").strip()
    if access and not _token_expired(oauth):
        return provider
    if not refresh:
        return provider
    client_id = str(oauth.get("clientId") or "").strip()
    client_secret = str(oauth.get("clientSecret") or "").strip()
    if not client_id or not client_secret:
        return provider
    try:
        payload = _post_form(
            GOOGLE_TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
        )
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            return provider
        save_oauth_tokens(
            provider.provider_id,
            access_token=access_token,
            refresh_token=str(payload.get("refresh_token") or "").strip() or refresh,
            expires_in=int(payload.get("expires_in") or 3600),
            config_path=config_path,
        )
        oauth["accessToken"] = access_token
        from dataclasses import replace

        return replace(provider, oauth=oauth)
    except Exception:
        return provider
