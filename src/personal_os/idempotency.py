import hashlib
import json
from typing import Any, Dict, Optional


def canonical_personal_os_payload(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return "{}"
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def personal_os_payload_hash(payload: Optional[Dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_personal_os_payload(payload).encode("utf-8")).hexdigest()


def make_personal_os_idempotency_key(
    *,
    tool_name: str,
    payload: Optional[Dict[str, Any]] = None,
    target_resource: str = "",
    session_id: str = "",
) -> str:
    parts = [
        "personal_os",
        str(tool_name or "").strip().lower(),
        str(session_id or "").strip(),
        str(target_resource or "").strip(),
        personal_os_payload_hash(payload),
    ]
    material = "|".join(parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"pos_{digest[:32]}"
