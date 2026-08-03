import json
import itertools
from typing import Dict, Any, Optional

_id_counter = itertools.count(1)

def next_request_id() -> int:
    """Generates an incremental JSON-RPC request ID."""
    return next(_id_counter)

def build_request(method: str, params: Optional[Dict[str, Any]] = None, request_id: Optional[int] = None) -> Dict[str, Any]:
    """Builds a JSON-RPC 2.0 request dictionary."""
    req_id = request_id if request_id is not None else next_request_id()
    msg = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method
    }
    if params is not None:
        msg["params"] = params
    return msg

def build_notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Builds a JSON-RPC 2.0 notification dictionary (no ID)."""
    msg = {
        "jsonrpc": "2.0",
        "method": method
    }
    if params is not None:
        msg["params"] = params
    return msg

def build_response(request_id: int, result: Optional[Any] = None, error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Builds a JSON-RPC 2.0 response dictionary."""
    msg: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id
    }
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg

def parse_json_rpc(message_str: str) -> Dict[str, Any]:
    """Parses a JSON-RPC 2.0 JSON string into a dictionary."""
    try:
        data = json.loads(message_str)
        if not isinstance(data, dict):
            raise ValueError("JSON-RPC message must be a JSON object.")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON string: {str(e)}")
