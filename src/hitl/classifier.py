from typing import Any, Dict, Optional, Tuple

from src.tools.policy import legacy_risk_tuple


def classify_tool_risk(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """
    Compatibility wrapper for legacy callers.

    Phase T8 centralizes executable tool policy in src.tools.policy. This
    function preserves the historical (risk_level, reason) shape while avoiding
    a second independent risk map.
    """
    return legacy_risk_tuple(tool_name, tool_args)