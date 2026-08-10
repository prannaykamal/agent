from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class ToolErrorCode(str, Enum):
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    REMOVED_TOOL = "REMOVED_TOOL"
    INVOCATION_FAILED_RETRYABLE = "INVOCATION_FAILED_RETRYABLE"
    INVOCATION_FAILED_TERMINAL = "INVOCATION_FAILED_TERMINAL"


@dataclass(frozen=True)
class NormalizedToolError:
    code: ToolErrorCode
    message: str
    retryable: bool = False
    metadata: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "metadata": dict(self.metadata or {}),
        }


def normalize_tool_error(code: ToolErrorCode | str, message: str, *, retryable: bool = False, **metadata: Any) -> NormalizedToolError:
    return NormalizedToolError(
        code=ToolErrorCode(code),
        message=str(message or "")[:500],
        retryable=retryable,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )
