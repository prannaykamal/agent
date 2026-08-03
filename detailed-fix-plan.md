# Detailed Fix Plan

This plan is based on the latest read-only project audit and verification run.

Current verification result:

```text
177 passed, 1 failed, 3 skipped, 1 warning
```

The project checklist marks all tasks complete, but the product is not verification-complete because one backend test currently fails and a few product-readiness gaps remain.

## 1. Fix the failing GitHub clone test

Affected file:

```text
src/mcp_gateway/sandboxes/code_sandbox.py
```

Current failing area:

```python
if res.returncode == 0 or "already exists" in res.stderr:
```

Problem:

This can incorrectly return `SUCCESS` when `git clone` actually failed. The current failing test proves that an invalid GitHub clone path can be reported as successful.

Fix steps:

1. Open `src/mcp_gateway/sandboxes/code_sandbox.py`.
2. Locate `github_clone`.
3. Stop treating `"already exists"` in `stderr` as success.
4. Use `res.returncode == 0` as the only success condition for a real clone.
5. Handle an existing destination directory before calling `git clone`.
6. Return structured `FAILED` JSON for invalid URLs, non-zero git exit codes, missing git executable, and invalid destination paths.

Recommended behavior:

- Empty `repo_url` returns `FAILED`.
- Invalid repo URL returns `FAILED`.
- Missing `git` executable returns `FAILED`.
- Destination exists and is not a Git repository returns `FAILED`.
- Destination exists and is already the requested Git repository may return `SUCCESS`.
- Clone command returns non-zero returns `FAILED`.

Suggested implementation shape:

```python
dest_dir = Path(target_dir).resolve() if target_dir else WORKSPACE_DIR / "repo"

if dest_dir.exists():
    if (dest_dir / ".git").exists():
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

    return json.dumps({
        "status": "FAILED",
        "exit_code": 1,
        "stdout": "",
        "stderr": f"Destination already exists and is not the requested cloned repository: {dest_dir}",
        "message": "[GitHub Error] Destination path already exists."
    })

dest_dir.parent.mkdir(parents=True, exist_ok=True)

res = subprocess.run(
    ["git", "clone", cleaned_url, str(dest_dir)],
    capture_output=True,
    text=True,
    timeout=20,
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
    "exit_code": res.returncode,
    "stdout": res.stdout,
    "stderr": res.stderr,
    "message": f"[GitHub Error - Exit Code {res.returncode}] Git clone failed: {res.stderr.strip() or res.stdout.strip()}"
})
```

## 2. Make the GitHub test deterministic

Affected file:

```text
tests/test_p1_integration_truthfulness.py
```

Current problem:

The test uses `target_dir=""`, which maps to the shared `.agent/workspace/repo` path. That makes the test stateful because previous clone attempts or existing files can change the behavior.

Fix steps:

1. Update the failing test to use pytest's `tmp_path`.
2. Pass a unique target directory into `github_clone`.
3. Keep the invalid URL assertion.

Suggested test shape:

```python
def test_github_tools_return_structured_failures(tmp_path):
    target_dir = tmp_path / "invalid_clone_target"

    res_clone_str = github_clone.invoke({
        "repo_url": "https://invalid.github.com/nonexistent_repo_12345.git",
        "target_dir": str(target_dir),
    })

    res_clone = json.loads(res_clone_str)
    assert res_clone["status"] == "FAILED"
    assert res_clone["exit_code"] != 0
    assert "stderr" in res_clone
    assert "stdout" in res_clone
    assert "GitHub Error" in res_clone["message"]
```

## 3. Add workspace boundary protection to GitHub clone

Affected file:

```text
src/mcp_gateway/sandboxes/code_sandbox.py
```

Current problem:

`target_dir` can be resolved to any filesystem path. For a sandbox tool, clone targets should stay inside the configured GitHub workspace directory.

Fix steps:

1. Resolve `dest_dir`.
2. Check that `dest_dir` is inside `WORKSPACE_DIR`.
3. If it is outside, return structured `FAILED` JSON.

Suggested guard:

```python
try:
    dest_dir.relative_to(WORKSPACE_DIR)
except ValueError:
    return json.dumps({
        "status": "FAILED",
        "exit_code": 1,
        "stdout": "",
        "stderr": "target_dir must stay inside the GitHub workspace sandbox.",
        "message": "[GitHub Security Error] target_dir is outside workspace boundary."
    })
```

Note:

If tests use `tmp_path`, either update the sandbox boundary rule to allow explicit test paths under pytest, or keep the production boundary rule and test it separately with a workspace-local target path.

## 4. Remove the duplicate backup route

Affected file:

```text
src/api/server.py
```

Current duplicate routes:

```text
POST /api/system/backup
```

The route appears twice:

```text
src/api/server.py:546
src/api/server.py:642
```

Fix steps:

1. Keep one implementation only.
2. Prefer keeping the later route in the "System Backup & Restore Endpoints" section because it sits next to restore logic.
3. Remove the earlier `api_trigger_backup` function.
4. Re-run API route tests.

Expected result:

- Only one `POST /api/system/backup` route exists.
- Backup behavior remains unchanged.
- API route discovery is less ambiguous.

## 5. Align Python dependencies

Affected files:

```text
pyproject.toml
requirements.txt
```

Current problem:

`requirements.txt` includes dependencies that are missing from `pyproject.toml`.

Confirmed missing dependencies:

```text
playwright>=1.40.0
duckduckgo-search>=4.0.0
```

Fix steps:

1. Add the missing dependencies to the `dependencies` list in `pyproject.toml`.
2. Keep versions aligned with `requirements.txt`.
3. Reinstall the package in editable mode if needed.

Command:

```powershell
python -m pip install -e .
```

Expected result:

- Fresh installs from `pyproject.toml` include browser and search dependencies.
- The project is less dependent on manually using `requirements.txt`.

## 6. Fix the stale README test claim

Affected file:

```text
README.md
```

Current problem:

The README claims:

```text
172 tests passed/skipped, 100% success rate
```

Current verified result:

```text
177 passed, 1 failed, 3 skipped, 1 warning
```

Fix steps:

1. Remove the hardcoded passing-test count until the suite is green.
2. Replace it with a neutral instruction to run the suite.
3. After the GitHub clone fix is complete and the full suite passes, update the README with the new exact result.

Suggested replacement:

```text
Run the complete verified test suite:
```

Expected result:

- README no longer overstates product readiness.
- Documentation matches verified behavior.

## 7. Re-run focused verification

After applying the GitHub fixes, run the targeted failing test first:

```powershell
python -m pytest tests/test_p1_integration_truthfulness.py -q
```

Expected result:

```text
passed
```

If this passes, continue to the full backend suite.

## 8. Re-run full backend verification

Command:

```powershell
python -m pytest -q -p no:cacheprovider
```

Completion gate:

- `0 failed`
- No unexpected errors
- Skips are intentional and documented
- Test count is recorded for README updates

## 9. Re-run frontend build verification

Command:

```powershell
cd frontend
npm run build
```

Expected result:

- Vite production build succeeds.
- `frontend/dist/index.html` is regenerated.
- No unresolved import or JSX build errors.

## 10. Re-check product completeness

After all fixes and verification commands pass, reassess product completeness using these gates:

1. Full Python test suite has `0 failed`.
2. Frontend production build succeeds.
3. README test claim matches the actual latest test result.
4. Only one `/api/system/backup` route exists.
5. GitHub tools return truthful structured failures.
6. Dependency files are aligned.
7. Provider limitations are documented honestly as real, local, fallback, or simulated.

Only after these gates pass should the project be called verification-complete.

## Current Product Completeness Assessment

Based on the latest audit:

```text
Local MVP/prototype completeness: about 88-90%
Production-ready product completeness: about 75-80%
```

Reason:

The frontend, backend, database, agent loop, HITL flow, memory system, and many integration surfaces are present. However, the product still has one failing test, stale documentation, duplicate route cleanup, dependency drift, and several provider paths that are local/fallback/simulated rather than fully proven live integrations.
