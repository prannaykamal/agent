from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.external_providers.telegram_bot_api import get_status as get_telegram_status
from src.external_providers.whatsapp_api import get_status as get_whatsapp_status

_DIRECT_PROVIDER_STATUS_LOADERS = {
    "whatsapp_api": get_whatsapp_status,
    "telegram_bot_api": get_telegram_status,
}


def target_external_provider_ids() -> List[str]:
    return list(_DIRECT_PROVIDER_STATUS_LOADERS.keys())


def get_external_provider_statuses() -> List[Dict[str, Any]]:
    statuses = []
    for provider_id in target_external_provider_ids():
        statuses.append(_DIRECT_PROVIDER_STATUS_LOADERS[provider_id]())
    return statuses


def get_external_provider_status(provider_id: str) -> Optional[Dict[str, Any]]:
    clean = str(provider_id or "").strip()
    loader = _DIRECT_PROVIDER_STATUS_LOADERS.get(clean)
    if not loader:
        return None
    return loader()
