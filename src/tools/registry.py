from typing import Dict, List, Optional

from src.tools.registry_types import ToolMetadata
from src.tools.removed_tools import (
    get_removed_tool_metadata as _get_removed_tool_metadata,
    is_removed_tool_name,
)


def get_personal_os_tool_metadata() -> List[ToolMetadata]:
    from src.personal_os.registry import get_personal_os_tool_metadata as _get_metadata

    return _get_metadata()


def get_mcp_gateway_tool_metadata() -> List[ToolMetadata]:
    from src.mcp_gateway.registry import get_mcp_gateway_tool_metadata as _get_metadata

    return _get_metadata()


def get_removed_tool_metadata() -> List[ToolMetadata]:
    return _get_removed_tool_metadata()


def get_bindable_tool_metadata() -> List[ToolMetadata]:
    """Returns metadata for currently bindable active tools.

    T2 removes browser/code sandbox tools from active binding while preserving
    removed-target metadata for observability and T3 deletion tracking.
    """
    active = get_personal_os_tool_metadata() + get_mcp_gateway_tool_metadata()
    return [item for item in active if not is_removed_tool_name(item.legacy_name)]


def get_unified_tool_metadata() -> List[ToolMetadata]:
    """Returns active metadata plus T1 removed-target metadata."""
    return get_bindable_tool_metadata() + get_removed_tool_metadata()


def get_tool_metadata_by_id(tool_id: str) -> Optional[ToolMetadata]:
    clean_id = str(tool_id or "").strip()
    for item in get_unified_tool_metadata():
        if item.tool_id == clean_id:
            return item
    return None


def get_tool_metadata_by_legacy_name(legacy_name: str) -> Optional[ToolMetadata]:
    """
    Returns the active metadata for a legacy tool name when present.

    Removed-target metadata is returned for sandbox tools after T2 filtering.
    """
    clean_name = str(legacy_name or "").strip()
    for item in get_bindable_tool_metadata():
        if item.legacy_name == clean_name:
            return item
    for item in get_removed_tool_metadata():
        if item.legacy_name == clean_name:
            return item
    return None


def get_unified_tool_metadata_by_id() -> Dict[str, ToolMetadata]:
    return {item.tool_id: item for item in get_unified_tool_metadata()}

