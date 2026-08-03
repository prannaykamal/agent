from typing import Tuple, Dict, Any, Optional

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
    "github_merge": "Git operation: Merges branch into target main branch",
    "calendar_create_event": "Calendar creation: Creates new calendar event",
    "calendar_delete_event": "Calendar deletion: Deletes existing calendar event"
}

MEDIUM_RISK_TOOLS: Dict[str, str] = {
    "github_commit_and_push": "Git push: Pushes code changes to repository",
    "schedule_job": "Scheduling: Registers a background recurring job",
    "spawn_agent": "Sub-agent: Launches an autonomous child sub-agent"
}

def classify_tool_risk(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """
    Evaluates tool risk level STRICTLY based on tool name and parameters—never based on LLM outputs.
    
    Returns:
        Tuple of (risk_level, reason) where risk_level is 'High', 'Medium', or 'Low'.
    """
    clean_name = tool_name.strip().lower()

    if clean_name in HIGH_RISK_TOOLS:
        return "High", HIGH_RISK_TOOLS[clean_name]

    if clean_name in MEDIUM_RISK_TOOLS:
        return "Medium", MEDIUM_RISK_TOOLS[clean_name]

    return "Low", "Read-only or local non-destructive operation"
