from langchain_core.tools import tool

@tool
def bank_transfer(recipient_account: str, amount: float, currency: str = "USD") -> str:
    """
    Transfers funds to a recipient bank account.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    return f"[Bank Transfer Executed] Transferred {amount} {currency} to recipient '{recipient_account}'."

@tool
def spend_money(amount: float, service: str) -> str:
    """
    Spends money or API credits for a service.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    return f"[Spend Money Executed] Paid ${amount} for service '{service}'."

@tool
def production_deploy(environment: str = "production", build_tag: str = "v1.0.0") -> str:
    """
    Deploys code build to production infrastructure.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    return f"[Production Deploy Executed] Deployed build '{build_tag}' to environment '{environment}'."

@tool
def delete_database(target_db: str) -> str:
    """
    Deletes or purges a database.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    return f"[Delete Database Executed] Purged database '{target_db}'."

@tool
def delete_files(file_paths: str) -> str:
    """
    Deletes files or directories from filesystem.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    return f"[Delete Files Executed] Removed file paths '{file_paths}'."
