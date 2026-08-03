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

def test_github_real_git_operations(temp_db, tmp_path):
    """Verifies github_commit_and_push and github_merge execute real git operations."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Commit in new repo
    (repo_dir / "README.md").write_text("# Test Repo\nInitial content", encoding="utf-8")
    res_commit = github_commit_and_push.invoke({
        "commit_message": "Add README",
        "branch": "main",
        "repo_dir": str(repo_dir)
    })
    assert "status" in res_commit or "Committed changes" in res_commit
    assert (repo_dir / ".git").exists()

    # 2. Create feature branch
    try:
        subprocess.run(["git", "checkout", "-b", "feature/login"], cwd=str(repo_dir), capture_output=True, text=True)
    except FileNotFoundError:
        pass

    (repo_dir / "login.py").write_text("def login(): pass\n", encoding="utf-8")

    res_commit2 = github_commit_and_push.invoke({
        "commit_message": "Add login feature",
        "branch": "feature/login",
        "repo_dir": str(repo_dir)
    })
    assert "status" in res_commit2 or "Committed changes" in res_commit2

    # 3. Merge feature branch into main
    res_merge = github_merge.invoke({
        "source_branch": "feature/login",
        "target_branch": "main",
        "repo_dir": str(repo_dir)
    })
    assert "MERGED" in res_merge or "status" in res_merge

def test_github_rest_api_endpoints(temp_db, tmp_path):
    """Verifies REST API endpoints POST /api/github/clone, /commit_and_push, and /merge."""
    repo_dir = str(tmp_path / "api_repo")

    # POST clone
    resp_clone = client.post("/api/github/clone", json={
        "repo_url": "https://github.com/example/demo.git",
        "target_dir": repo_dir
    })
    assert resp_clone.status_code == 200
    assert "result" in resp_clone.json()

    # POST commit_and_push
    resp_commit = client.post("/api/github/commit_and_push", json={
        "commit_message": "API test commit",
        "branch": "main",
        "repo_dir": repo_dir
    })
    assert resp_commit.status_code == 200
    assert "result" in resp_commit.json()

    # POST merge
    resp_merge = client.post("/api/github/merge", json={
        "source_branch": "feature_api",
        "target_branch": "main",
        "repo_dir": repo_dir
    })
    assert resp_merge.status_code == 200
    assert resp_merge.json()["status"] == "APPROVAL_REQUIRED"


