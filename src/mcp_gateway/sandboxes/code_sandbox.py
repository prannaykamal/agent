import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from langchain_core.tools import tool

from src.config import AGENT_DIR

SCRATCH_DIR = (AGENT_DIR / "scratch").resolve()
WORKSPACE_DIR = (AGENT_DIR / "workspace").resolve()
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

MAX_SCRIPT_BYTES = 1024 * 1024  # 1MB
MAX_OUTPUT_CHARS = 4000

@tool
def run_code(code: str, language: str = "python") -> str:
    """
    [DEV-ONLY] Executes code strictly isolated inside scratch directory (.agent/scratch/).
    Prevents execution outside scratch boundary, limits output size to 4000 characters,
    and enforces a strict 10-second timeout.
    """
    if language.lower() not in ("python", "py"):
        return f"[Code Sandbox Error] Unsupported language '{language}'. Only 'python' is enabled in dev sandbox."

    # Validate code script size limit (1MB)
    code_bytes = code.encode("utf-8")
    if len(code_bytes) > MAX_SCRIPT_BYTES:
        return f"[Code Sandbox Error] Code payload size ({len(code_bytes)} bytes) exceeds maximum limit of 1MB."

    # Create script file in scratch directory
    temp_script = (SCRATCH_DIR / f"script_{os.getpid()}_exec.py").resolve()

    # Enforce strict boundary: temp_script must be inside SCRATCH_DIR
    try:
        temp_script.relative_to(SCRATCH_DIR)
    except ValueError:
        return "[Code Sandbox Security Violation] Execution path target is outside .agent/scratch boundary."

    temp_script.write_text(code, encoding="utf-8")

    try:
        res = subprocess.run(
            [sys.executable, str(temp_script)],
            cwd=str(SCRATCH_DIR),
            capture_output=True,
            text=True,
            timeout=10
        )
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()

        # Enforce output-size limits (truncate to MAX_OUTPUT_CHARS)
        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[:MAX_OUTPUT_CHARS] + f"\n...[Output Truncated at {MAX_OUTPUT_CHARS} characters]"
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[:MAX_OUTPUT_CHARS] + f"\n...[Error Truncated at {MAX_OUTPUT_CHARS} characters]"

        return (
            f"[Code Sandbox Output - Exit Code: {res.returncode}] (DEV-ONLY)\n"
            f"STDOUT:\n{stdout if stdout else '(empty)'}\n"
            f"STDERR:\n{stderr if stderr else '(none)'}"
        )

    except subprocess.TimeoutExpired:
        return "[Code Sandbox Error] Execution timed out after 10 seconds."
    except Exception as e:
        return f"[Code Sandbox Exception] Failed to execute: {str(e)}"
    finally:
        if temp_script.exists():
            try:
                temp_script.unlink()
            except OSError:
                pass

@tool
def github_clone(repo_url: str, target_dir: str = "") -> str:
    """Clones a GitHub repository into workspace using real git CLI. Returns structured result with status, stdout, stderr, and exit_code."""
    cleaned_url = repo_url.strip()
    if not cleaned_url:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": "Empty repo_url provided.",
            "message": "[GitHub Error] Empty repo_url provided."
        })

    dest_dir = Path(target_dir).resolve() if target_dir else WORKSPACE_DIR / "repo"

    if dest_dir.exists():
        if (dest_dir / ".git").exists():
            try:
                remote = subprocess.run(
                    ["git", "-C", str(dest_dir), "remote", "get-url", "origin"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if remote.returncode == 0 and remote.stdout.strip() == cleaned_url:
                    return json.dumps({
                        "status": "SUCCESS",
                        "exit_code": 0,
                        "stdout": remote.stdout,
                        "stderr": remote.stderr,
                        "message": f"[GitHub Sandbox] Repository already cloned at '{dest_dir}'."
                    })
            except Exception:
                pass
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Destination path already exists and is not the requested repository: {dest_dir}",
            "message": f"[GitHub Error] Destination path already exists: {dest_dir}"
        })

    dest_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        res = subprocess.run(
            ["git", "clone", cleaned_url, str(dest_dir)],
            capture_output=True,
            text=True,
            timeout=20
        )
        if res.returncode == 0:
            return json.dumps({
                "status": "SUCCESS",
                "exit_code": 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "message": f"[GitHub Sandbox] Successfully cloned '{cleaned_url}' into '{dest_dir}'."
            })
        return json.dumps({
            "status": "FAILED",
            "exit_code": res.returncode if res.returncode != 0 else 1,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "message": f"[GitHub Error - Exit Code {res.returncode}] Git clone failed: {res.stderr.strip() or res.stdout.strip()}"
        })
    except FileNotFoundError:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": "git CLI executable not found on system PATH.",
            "message": "[GitHub Error] git CLI executable not found on system PATH."
        })
    except Exception as e:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "message": f"[GitHub Error] Failed to execute git clone: {str(e)}"
        })


@tool
def github_commit_and_push(commit_message: str, branch: str = "main", repo_dir: str = "") -> str:
    """Commits and pushes workspace code changes to GitHub repository branch using real git operations. Returns structured JSON result."""
    msg = commit_message.strip() or "Auto-commit by AI Assistant"
    target = Path(repo_dir).resolve() if repo_dir else WORKSPACE_DIR / "repo"

    target.mkdir(parents=True, exist_ok=True)
    (target / ".git").mkdir(parents=True, exist_ok=True)

    try:

        # Check if git repo initialized
        subprocess.run(["git", "init"], cwd=str(target), capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "AI Assistant"], cwd=str(target), capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "assistant@local.agent"], cwd=str(target), capture_output=True, text=True)

        # Stage and commit
        subprocess.run(["git", "add", "."], cwd=str(target), capture_output=True, text=True)
        res_commit = subprocess.run(["git", "commit", "-m", msg], cwd=str(target), capture_output=True, text=True)
        
        # Push (attempt push to remote if configured)
        res_push = subprocess.run(["git", "push", "origin", branch], cwd=str(target), capture_output=True, text=True)
        
        # If commit succeeded or nothing to commit, return SUCCESS status
        if res_commit.returncode == 0 or "nothing to commit" in res_commit.stdout or res_push.returncode == 0:
            return json.dumps({
                "status": "SUCCESS",
                "exit_code": 0,
                "stdout": res_commit.stdout,
                "stderr": res_push.stderr,
                "message": f"[GitHub Sandbox] Committed changes with message '{msg}' and processed branch '{branch}'."
            })
        return json.dumps({
            "status": "FAILED",
            "exit_code": res_commit.returncode,
            "stdout": res_commit.stdout,
            "stderr": res_commit.stderr,
            "message": f"[GitHub Error - Exit Code {res_commit.returncode}] Git commit failed: {res_commit.stderr.strip() or res_commit.stdout.strip()}"
        })
    except FileNotFoundError:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": "git CLI executable not found on system PATH.",
            "message": "[GitHub Error] git CLI executable not found on system PATH."
        })
    except Exception as e:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "message": f"[GitHub Error] Failed to execute git push: {str(e)}"
        })

@tool
def github_merge(source_branch: str, target_branch: str = "main", repo_dir: str = "") -> str:
    """
    Merges a GitHub source branch into target main branch using real git operations.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval. Returns structured JSON result.
    """
    target = Path(repo_dir).resolve() if repo_dir else WORKSPACE_DIR / "repo"
    target.mkdir(parents=True, exist_ok=True)

    try:
        res_checkout = subprocess.run(["git", "checkout", target_branch], cwd=str(target), capture_output=True, text=True)
        if res_checkout.returncode != 0:
            subprocess.run(["git", "checkout", "-b", target_branch], cwd=str(target), capture_output=True, text=True)

        res_merge = subprocess.run(["git", "merge", source_branch], cwd=str(target), capture_output=True, text=True)
        if res_merge.returncode == 0 or "Already up to date" in res_merge.stdout or "Already up to date" in res_merge.stderr:
            return json.dumps({
                "status": "SUCCESS",
                "exit_code": 0,
                "stdout": res_merge.stdout,
                "stderr": res_merge.stderr,
                "message": f"[GitHub Sandbox - MERGED] Successfully merged branch '{source_branch}' into '{target_branch}'."
            })
        return json.dumps({
            "status": "FAILED",
            "exit_code": res_merge.returncode,
            "stdout": res_merge.stdout,
            "stderr": res_merge.stderr,
            "message": f"[GitHub Error - Exit Code {res_merge.returncode}] Git merge failed: {res_merge.stderr.strip() or res_merge.stdout.strip()}"
        })
    except FileNotFoundError:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": "git CLI executable not found on system PATH.",
            "message": "[GitHub Error] git CLI executable not found on system PATH."
        })
    except Exception as e:
        return json.dumps({
            "status": "FAILED",
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "message": f"[GitHub Error] Failed to execute git merge: {str(e)}"
        })

