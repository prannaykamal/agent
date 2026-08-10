import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DELETED_FILES = [
    REPO_ROOT / "src" / "mcp_gateway" / "sandboxes" / "browser_sandbox.py",
    REPO_ROOT / "src" / "mcp_gateway" / "sandboxes" / "code_sandbox.py",
]
DELETED_MODULES = [
    "src.mcp_gateway." + "sand" + "boxes.browser_" + "sandbox",
    "src.mcp_gateway." + "sand" + "boxes.code_" + "sandbox",
]


def test_t3_deleted_sandbox_source_files_are_absent():
    for path in DELETED_FILES:
        assert not path.exists(), f"Deleted sandbox file still exists: {path}"


def test_t3_deleted_sandbox_modules_are_not_importable():
    for module_name in DELETED_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)


def test_t3_api_import_succeeds_without_sandbox_modules():
    from src.api.server import app

    assert app.title == "24x7 Personal Assistant API"


def test_t3_registry_import_succeeds_without_sandbox_modules():
    from src.mcp_gateway.registry import get_all_mcp_tools

    names = {tool.name for tool in get_all_mcp_tools()}
    assert "search_web" in names
