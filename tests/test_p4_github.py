import os
import subprocess
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from src.db import init_db
from src.mcp_gateway.sandboxes.code_sandbox import (
    github_clone, github_commit_and_push, github_merge
)
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p4_github.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_github_sandbox_source_tools_remain_until_t3(temp_db, tmp_path):
    """T2 keeps GitHub sandbox source symbols on disk but blocks active execution."""
    assert github_clone.name == "github_clone"
    assert github_commit_and_push.name == "github_commit_and_push"
    assert github_merge.name == "github_merge"

def test_github_rest_api_endpoints(temp_db, tmp_path):
    """Verifies REST API endpoints POST /api/github/clone, /commit_and_push, and /merge."""
    repo_dir = str(tmp_path / "api_repo")

    # POST clone
    resp_clone = client.post("/api/github/clone", json={
        "repo_url": "https://github.com/example/demo.git",
        "target_dir": repo_dir
    })
    assert resp_clone.status_code == 200
    assert resp_clone.json()["status"] == "blocked"
    assert "removed or blocked" in resp_clone.json()["result"]

    # POST commit_and_push
    resp_commit = client.post("/api/github/commit_and_push", json={
        "commit_message": "API test commit",
        "branch": "main",
        "repo_dir": repo_dir
    })
    assert resp_commit.status_code == 200
    assert resp_commit.json()["status"] == "blocked"
    assert "removed or blocked" in resp_commit.json()["result"]

    # POST merge
    resp_merge = client.post("/api/github/merge", json={
        "source_branch": "feature_api",
        "target_branch": "main",
        "repo_dir": repo_dir
    })
    assert resp_merge.status_code == 200
    assert resp_merge.json()["status"] == "blocked"
    assert "removed or blocked" in resp_merge.json()["message"]


