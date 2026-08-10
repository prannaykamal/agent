from typing import Tuple, Dict, Any, Optional

from src.tools.removed_tools import is_removed_tool_name
from src.personal_os.policy import get_personal_os_policy

# Deterministic High-Risk Tool Registry & Justifications
HIGH_RISK_TOOLS: Dict[str, str] = {
    "bank_transfer": "Financial transaction: Initiates monetary transfer",
    "spend_money": "Financial action: Spends real money or API credits",
    "production_deploy": "Deployment: Deploys code to production environment",
    "delete_database": "Data destruction: Drops database or purges persistent tables",
    "send_email": "External message: Sends outbound email to external recipient",
    "email_send": "External message: Sends outbound email to external recipient",
    "whatsapp_send": "External message: Sends outbound WhatsApp message to recipient",
    "telegram_send": "External message: Sends outbound Telegram message",
    "delete_files": "Filesystem destruction: Deletes persistent files or directories",
    "calendar_create_event": "Calendar creation: Creates new calendar event",
    "calendar_delete_event": "Calendar deletion: Deletes existing calendar event"
}

MEDIUM_RISK_TOOLS: Dict[str, str] = {
    "schedule_job": "Scheduling: Registers a background recurring job",
    "spawn_agent": "Sub-agent: Launches an autonomous child sub-agent"
}

def classify_tool_risk(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """
    Evaluates tool risk level STRICTLY based on tool name and parameters—never based on LLM outputs.
    
    Returns:
        Tuple of (risk_level, reason) where risk_level is 'High', 'Medium', 'Low',
        or 'Blocked' for removed tools.
    """
    clean_name = tool_name.strip().lower()

    if is_removed_tool_name(clean_name):
        return "Blocked", "Removed tool: blocked by the tools architecture migration"

    personal_os_policy = get_personal_os_policy(clean_name)
    if personal_os_policy is not None:
        return personal_os_policy.risk_class.value, personal_os_policy.reason

    if clean_name in HIGH_RISK_TOOLS:
        return "High", HIGH_RISK_TOOLS[clean_name]

    if clean_name in MEDIUM_RISK_TOOLS:
        return "Medium", MEDIUM_RISK_TOOLS[clean_name]

    return "Low", "Read-only or local non-destructive operation"
